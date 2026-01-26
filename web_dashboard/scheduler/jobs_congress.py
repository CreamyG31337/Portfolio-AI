"""
Congress Trades Jobs
===================

Jobs for fetching and analyzing congressional stock trades.
"""

import base64
import logging
import time
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# Add parent directory to path if needed (standard boilerplate for these jobs)
import sys

# Add project root to path for utils imports
current_dir = Path(__file__).resolve().parent
if current_dir.name == "scheduler":
    project_root = current_dir.parent.parent
else:
    project_root = current_dir.parent.parent

# CRITICAL: Project root must be inserted FIRST (at index 0) to ensure it comes
# BEFORE web_dashboard in sys.path. This prevents web_dashboard/utils from
# shadowing the project root's utils package.
project_root_str = str(project_root)
if project_root_str in sys.path:
    sys.path.remove(project_root_str)
sys.path.insert(0, project_root_str)

# Also ensure web_dashboard is in path for supabase_client imports
# (but AFTER project root so it doesn't shadow utils)
web_dashboard_path = str(Path(__file__).resolve().parent.parent)
if web_dashboard_path in sys.path:
    sys.path.remove(web_dashboard_path)
# Insert at index 1, after project_root
if len(sys.path) > 1:
    sys.path.insert(1, web_dashboard_path)
else:
    sys.path.append(web_dashboard_path)

from scheduler.scheduler_core import log_job_execution

# Initialize logger
logger = logging.getLogger(__name__)

def fetch_congress_trades_job() -> None:
    """Fetch and analyze congressional stock trades from Financial Modeling Prep API.
    
    This job:
    1. Fetches House and Senate trading disclosures from FMP API
    2. Processes up to 10 records per chamber per run (API docs claim 0-25 but actual limit is 10)
    3. Cleans and normalizes the data
    4. Checks for duplicates before processing
    5. Analyzes each new trade with AI (Ollama Granite 3.3) for conflict of interest
    6. Saves trades to Supabase congress_trades table
    
    Note: FMP API documentation lies - they claim limit can be 0-25, but only 10 actually works.
    """
    import os
    import requests
    import json
    import re
    
    job_id = 'congress_trades'
    start_time = time.time()
    
    try:
        # Ensure path is set up correctly before importing
        import sys
        from pathlib import Path
        
        # Re-ensure project root is first in path
        current_dir = Path(__file__).resolve().parent
        if current_dir.name == "scheduler":
            project_root = current_dir.parent.parent
        else:
            project_root = current_dir.parent.parent
        
        project_root_str = str(project_root)
        if project_root_str in sys.path:
            sys.path.remove(project_root_str)
        sys.path.insert(0, project_root_str)
        
        # Import job tracking
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        
        logger.info("Starting congress trades job...")
        
        # Mark job as started
        target_date = datetime.now(timezone.utc).date()
        mark_job_started('congress_trades', target_date)
        
        # Import dependencies (lazy imports)
        try:
            from supabase_client import SupabaseClient
            from ollama_client import get_ollama_client
            from web_dashboard.utils.politician_mapping import lookup_politician_metadata, resolve_politician_name
            from settings import get_summarizing_model
        except ImportError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Missing dependency: {e}"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            return
        
        # Get FMP API key
        fmp_api_key = os.getenv("FMP_API_KEY")
        if not fmp_api_key:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "FMP_API_KEY not found in environment"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            return
        
        # Initialize clients
        supabase_client = SupabaseClient(use_service_role=True)
        ollama_client = get_ollama_client()
        
        if not ollama_client:
            logger.warning("⚠️  Ollama unavailable - trades will be saved without conflict analysis")
        
        # Calculate cutoff date (7 days ago)
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=7)
        
        # Base URL for FMP API (obfuscated)
        _FMP_BASE_ENCODED = "aHR0cHM6Ly9maW5hbmNpYWxtb2RlbGluZ3ByZXAuY29tL3N0YWJsZQ=="
        base_url = base64.b64decode(_FMP_BASE_ENCODED).decode('utf-8')
        
        # Track statistics
        total_trades_found = 0
        new_trades = 0
        skipped_duplicates = 0
        skipped_no_ticker = 0
        ai_analyzed = 0
        errors = 0
        
        # Process both House and Senate
        for chamber in ['House', 'Senate']:
            logger.info(f"Fetching {chamber} trades...")
            
            # Use stable API endpoints
            if chamber == 'House':
                endpoint = f"{base_url}/house-latest"
            else:  # Senate
                endpoint = f"{base_url}/senate-latest"
            
            # Note: FMP API is locked to page 0 only
            # API docs claim limit can be 0-25, but they're liars - only 10 actually works (as of 2025-12-27)
            page = 0
            limit = 10  # Actual API limit: 10 responses per call (docs falsely claim 0-25)
            
            try:
                # Fetch page 0 only (other pages are locked)
                params = {
                    'page': page,
                    'limit': limit,
                    'apikey': fmp_api_key
                }
                
                logger.info(f"Fetching {chamber} page {page} (limit {limit} records)...")
                response = requests.get(endpoint, params=params, timeout=30)
                response.raise_for_status()
                
                # Parse JSON response
                try:
                    data = response.json()
                    # Response is a list of trades
                    trades = data if isinstance(data, list) else []
                except json.JSONDecodeError as json_error:
                    logger.error(f"Failed to parse {chamber} response as JSON: {json_error}")
                    logger.debug(f"Response content: {response.text[:500]}")
                    continue  # Skip this chamber, try next
                
                if not trades:
                    logger.info(f"No trades found for {chamber}")
                    continue  # Skip this chamber, try next
                
                logger.info(f"Found {len(trades)} trades for {chamber}")
                
                # Process each trade
                for trade_data in trades:
                        total_trades_found += 1
                        
                        try:
                            # Extract and clean data
                            # FMP API uses 'symbol' for ticker
                            ticker = trade_data.get('symbol') or trade_data.get('ticker') or ''
                            if not ticker or ticker.strip() == '':
                                skipped_no_ticker += 1
                                continue
                            
                            ticker = ticker.strip().upper()
                            
                            # Get politician name (FMP uses firstName and lastName)
                            first_name = trade_data.get('firstName') or trade_data.get('first_name') or ''
                            last_name = trade_data.get('lastName') or trade_data.get('last_name') or ''
                            politician = f"{first_name} {last_name}".strip()
                            
                            # Fallback to other fields if firstName/lastName not available
                            if not politician:
                                politician = trade_data.get('politician') or trade_data.get('name') or ''
                            
                            if not politician:
                                logger.warning(f"Missing politician name for trade: {trade_data}")
                                continue
                            
                            politician = politician.strip()
                            
                            # Look up politician in database for canonical name + metadata
                            politician_meta = lookup_politician_metadata(supabase_client, politician)
                            politician_id = None
                            
                            if politician_meta:
                                # Use canonical name and metadata from database
                                politician = politician_meta['name']
                                politician_id = politician_meta['politician_id']
                                party = politician_meta['party']
                                state = politician_meta['state']
                                # Override chamber if DB has it
                                if politician_meta['chamber']:
                                    chamber = politician_meta['chamber']
                            else:
                                # Politician not in database - resolve name but mark for manual review
                                canonical_name, _ = resolve_politician_name(politician)
                                politician = canonical_name
                                party = None
                                state = None
                                logger.warning(f"Politician not in database: {politician}")
                            
                            # Parse dates (FMP uses disclosureDate and transactionDate)
                            disclosure_date_str = trade_data.get('disclosureDate') or trade_data.get('disclosure_date') or trade_data.get('date')
                            transaction_date_str = trade_data.get('transactionDate') or trade_data.get('transaction_date') or trade_data.get('trade_date')
                            
                            if not disclosure_date_str:
                                logger.warning(f"Missing disclosure date for trade: {trade_data}")
                                continue
                            
                            try:
                                # Parse dates (FMP may return in various formats)
                                # Try common date formats
                                date_formats = [
                                    '%Y-%m-%d',
                                    '%Y-%m-%dT%H:%M:%S',
                                    '%Y-%m-%dT%H:%M:%SZ',
                                    '%m/%d/%Y',
                                    '%d/%m/%Y',
                                    '%Y/%m/%d'
                                ]
                                
                                disclosure_date = None
                                for fmt in date_formats:
                                    try:
                                        disclosure_date = datetime.strptime(disclosure_date_str.split('T')[0], fmt).date()
                                        break
                                    except (ValueError, AttributeError):
                                        continue
                                
                                if not disclosure_date:
                                    # Try ISO format
                                    try:
                                        disclosure_date = datetime.fromisoformat(disclosure_date_str.replace('Z', '+00:00')).date()
                                    except (ValueError, AttributeError):
                                        logger.warning(f"Failed to parse disclosure date: {disclosure_date_str}")
                                        continue
                                
                                if transaction_date_str:
                                    transaction_date = None
                                    for fmt in date_formats:
                                        try:
                                            transaction_date = datetime.strptime(transaction_date_str.split('T')[0], fmt).date()
                                            break
                                        except (ValueError, AttributeError):
                                            continue
                                    
                                    if not transaction_date:
                                        try:
                                            transaction_date = datetime.fromisoformat(transaction_date_str.replace('Z', '+00:00')).date()
                                        except (ValueError, AttributeError):
                                            transaction_date = disclosure_date  # Fallback to disclosure date
                                else:
                                    transaction_date = disclosure_date  # Fallback to disclosure date
                            except Exception as date_error:
                                logger.warning(f"Failed to parse dates: {date_error}, data: {trade_data}")
                                continue
                            
                            # Check if disclosure date is too old
                            # Note: Since we only get 10 records per chamber, we'll process all of them
                            # and let the 7-day cutoff be handled by the duplicate check
                            if disclosure_date < cutoff_date.date():
                                # Skip old trades (older than 7 days)
                                # But continue processing other trades since we only get 10 total per chamber
                                continue
                            
                            # Get transaction type (FMP may use 'type' or 'transactionType')
                            trade_type = trade_data.get('type') or trade_data.get('transactionType') or trade_data.get('transaction_type') or ''
                            if not trade_type:
                                # Try to infer from other fields
                                description = str(trade_data.get('description', '') or trade_data.get('transaction', '') or '').lower()
                                if 'purchase' in description or 'buy' in description:
                                    trade_type = 'Purchase'
                                elif 'sale' in description or 'sell' in description:
                                    trade_type = 'Sale'
                                else:
                                    trade_type = 'Purchase'  # Default
                            
                            # Normalize to Purchase or Sale
                            trade_type_lower = trade_type.lower()
                            if 'purchase' in trade_type_lower or 'buy' in trade_type_lower:
                                trade_type = 'Purchase'
                            else:
                                trade_type = 'Sale'
                            
                            # Get amount (keep as string - FMP may use 'amount' or 'value')
                            amount = trade_data.get('amount') or trade_data.get('value') or trade_data.get('range') or ''
                            if amount:
                                amount = str(amount).strip()
                            
                            # Get asset type (default to Stock)
                            asset_type = trade_data.get('assetType') or trade_data.get('asset_type') or 'Stock'
                            asset_type_lower = str(asset_type).lower()
                            if 'crypto' in asset_type_lower:
                                asset_type = 'Crypto'
                            else:
                                asset_type = 'Stock'
                            
                            # Extract additional fields if available
                            price_per_share = trade_data.get('pricePerShare') or trade_data.get('price_per_share') or trade_data.get('price')
                            
                            # Extract office field (may contain party/state as fallback)
                            office = trade_data.get('office') or ''
                            
                            # party and state already set from politician lookup above
                            # Only extract from office field if not found in database
                            if not party and not state:
                                if office:
                                    # Look for patterns like (D-CA), (R-TX), (I-VT)
                                    import re
                                    match = re.search(r'\(([DIR])-([A-Z]{2})\)', office)
                                    if match:
                                        party_code = match.group(1)
                                        state = match.group(2)
                                        if party_code == 'D':
                                            party = 'Democratic'
                                        elif party_code == 'R':
                                            party = 'Republican'
                                        elif party_code == 'I':
                                            party = 'Independent'
                            
                            # Extract owner (Self/Spouse/Dependent)
                            owner = trade_data.get('owner') or trade_data.get('assetOwner') or trade_data.get('ownerType')
                            if owner:
                                owner = str(owner).strip().title()
                            else:
                                owner = 'Unknown'  # Default matches migration 36
                            
                            # Extract disclosure link
                            disclosure_link = trade_data.get('link') or trade_data.get('disclosureUrl') or trade_data.get('url')
                            
                            # Extract capital gains flag
                            capital_gains = trade_data.get('capitalGains') or trade_data.get('capital_gains')
                            
                            # Extract any notes/description fields
                            notes = None
                            for field in ['description', 'comment', 'notes', 'memo']:
                                if field in trade_data and trade_data[field]:
                                    notes = str(trade_data[field]).strip()
                                    break
                            
                            # Build notes from available info
                            notes_parts = []
                            if notes:
                                notes_parts.append(notes)
                            if capital_gains:
                                notes_parts.append(f"Capital Gains: {capital_gains}")
                            if disclosure_link:
                                notes_parts.append(f"Disclosure: {disclosure_link}")
                            
                            final_notes = " | ".join(notes_parts) if notes_parts else None
                            
                            # Check for duplicate before processing
                            # Note: We use upsert with on_conflict, so duplicate check is optional
                            # Skip duplicate check if amount has special characters that cause URL encoding issues
                            try:
                                # Only check if amount is simple (no special chars that cause encoding issues)
                                if amount and politician_id and not any(char in amount for char in ['$', ',', '-', ' ']):
                                    existing = supabase_client.supabase.table("congress_trades")\
                                        .select("id")\
                                        .eq("politician_id", politician_id)\
                                        .eq("ticker", ticker)\
                                        .eq("transaction_date", transaction_date.isoformat())\
                                        .eq("amount", amount)\
                                        .maybe_single()\
                                        .execute()
                                    
                                    if existing and existing.data:
                                        skipped_duplicates += 1
                                        continue
                            except Exception as dup_check_error:
                                # Skip duplicate check if it fails - upsert will handle duplicates anyway
                                logger.debug(f"Duplicate check skipped (will use upsert): {dup_check_error}")
                                pass
                            
                            # This is a new trade - analyze with AI
                            conflict_score = None
                            notes = None
                            model_name = None  # Will be set if AI analysis runs
                            
                            # Note: Ollama errors (e.g., 404 if service not running) are handled gracefully
                            # Trades will still be saved without AI analysis if Ollama is unavailable
                            if ollama_client:
                                try:
                                    # Build prompt for AI analysis
                                    prompt = f"Analyze this trade: {politician} {'bought' if trade_type == 'Purchase' else 'sold'} {ticker} on {transaction_date}. Asset: {asset_type}. Amount: {amount}. Is this suspicious given current events? Return JSON: {{'conflict_score': 0.0-1.0, 'reasoning': '...'}}"
                                    
                                    # Query Ollama (non-streaming for structured response)
                                    # Get model from settings (defaults to granite3.3:8b from model_config.json)
                                    model_name = get_summarizing_model()
                                    full_response = ""
                                    for chunk in ollama_client.query_ollama(
                                        prompt=prompt,
                                        model=model_name,
                                        stream=True,
                                        temperature=0.3  # Lower temperature for more consistent analysis
                                    ):
                                        full_response += chunk
                                    
                                    # Parse JSON response
                                    json_match = re.search(r'\{[^{}]*"conflict_score"[^{}]*\}', full_response, re.DOTALL)
                                    if json_match:
                                        json_str = json_match.group(0)
                                    else:
                                        json_str = full_response.strip()
                                    
                                    # Remove markdown code blocks if present
                                    json_str = re.sub(r'```json\s*', '', json_str)
                                    json_str = re.sub(r'```\s*', '', json_str)
                                    json_str = json_str.strip()
                                    
                                    parsed = json.loads(json_str)
                                    
                                    conflict_score = float(parsed.get("conflict_score", 0.0))
                                    # Clamp to 0.0-1.0 range
                                    conflict_score = max(0.0, min(1.0, conflict_score))
                                    notes = parsed.get("reasoning", "AI analysis completed")
                                    
                                    ai_analyzed += 1
                                    
                                except json.JSONDecodeError as e:
                                    logger.warning(f"Failed to parse AI response for {politician} {ticker}: {e}")
                                    logger.debug(f"Response was: {full_response[:500]}")
                                    conflict_score = None
                                    notes = "Failed to parse AI response"
                                except Exception as ai_error:
                                    logger.warning(f"AI analysis failed for {politician} {ticker}: {ai_error}")
                                    conflict_score = None
                                    notes = "AI analysis error"
                            
                            # Skip trades without politician_id (can't enforce uniqueness without it)
                            if not politician_id:
                                logger.warning(f"Skipping trade for {politician} {ticker}: politician_id is None (politician not in database)")
                                errors += 1
                                continue
                            
                            # Prepare trade record with ALL available fields
                            # Note: 'politician' column was dropped in migration 27 - use politician_id only
                            trade_record = {
                                'ticker': ticker,
                                'politician_id': politician_id,  # FK to politicians table (required)
                                'chamber': chamber,
                                'party': party,  # From politicians table lookup
                                'state': state,  # From politicians table lookup
                                'owner': owner,  # Self/Spouse/Dependent if available, defaults to 'Unknown'
                                'transaction_date': transaction_date.isoformat(),
                                'disclosure_date': disclosure_date.isoformat(),
                                'type': trade_type,
                                'amount': amount,
                                'price': price_per_share,  # Price per share if available
                                'asset_type': asset_type,
                                'conflict_score': conflict_score,
                                'notes': final_notes  # Includes description, capital gains, disclosure link
                            }
                            
                            # Insert to Supabase (use upsert to handle duplicates)
                            # Migration 36 created a proper unique constraint that supports ON CONFLICT
                            try:
                                result = supabase_client.supabase.table("congress_trades")\
                                    .upsert(
                                        trade_record,
                                        on_conflict="politician_id,ticker,transaction_date,amount,type,owner"
                                    )\
                                    .execute()
                                
                                if result.data:
                                    new_trades += 1
                                    logger.debug(f"✅ Saved trade: {politician} {trade_type} {ticker} on {transaction_date}")
                                    
                                    # If AI analysis was successful, also save to PostgreSQL analysis table
                                    # (UI reads from PostgreSQL, not Supabase conflict_score column)
                                    if conflict_score is not None and result.data:
                                        try:
                                            from postgres_client import PostgresClient
                                            postgres = PostgresClient()
                                            
                                            # Get the trade ID from the inserted/updated record
                                            trade_id = result.data[0].get('id') if isinstance(result.data, list) and result.data else None
                                            if not trade_id and isinstance(result.data, dict):
                                                trade_id = result.data.get('id')
                                            
                                            if trade_id:
                                                # Save analysis to PostgreSQL (same as analyze_congress_trades_job)
                                                postgres.execute_update(
                                                    """
                                                    INSERT INTO congress_trades_analysis 
                                                        (trade_id, conflict_score, confidence_score, reasoning, model_used, analysis_version)
                                                    VALUES (%s, %s, %s, %s, %s, %s)
                                                    ON CONFLICT (trade_id, model_used, analysis_version) 
                                                    DO UPDATE SET 
                                                        conflict_score = EXCLUDED.conflict_score,
                                                        confidence_score = EXCLUDED.confidence_score,
                                                        reasoning = EXCLUDED.reasoning,
                                                        analyzed_at = NOW()
                                                    """,
                                                    (trade_id, conflict_score, 0.75, notes or "AI analysis completed", model_name or get_summarizing_model(), 1)
                                                )
                                                logger.debug(f"   💾 Saved analysis to PostgreSQL for trade {trade_id}")
                                        except ImportError:
                                            logger.debug("PostgreSQL client not available - skipping analysis save")
                                        except Exception as pg_error:
                                            logger.warning(f"Failed to save analysis to PostgreSQL: {pg_error}")
                                            # Don't fail the whole job if PostgreSQL save fails
                                else:
                                    skipped_duplicates += 1
                                    
                            except Exception as insert_error:
                                errors += 1
                                logger.error(f"Failed to insert trade for {politician} {ticker}: {insert_error}")
                                continue
                        
                        except Exception as trade_error:
                            errors += 1
                            logger.warning(f"Error processing trade: {trade_error}, data: {trade_data}")
                            continue
                    
                # Note: API is locked to page 0 only, so we don't paginate
                # We only get the 10 most recent trades per chamber per run
                # API docs claim 0-25 limit, but they're liars - only 10 works (as of 2025-12-27)
                
            except requests.exceptions.HTTPError as http_error:
                logger.error(f"HTTP error for {chamber}: {http_error}")
            except requests.exceptions.RequestException as req_error:
                logger.error(f"Request error for {chamber}: {req_error}")
            except Exception as e:
                logger.error(f"Unexpected error processing {chamber}: {e}", exc_info=True)
        
        # Log completion
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Found {total_trades_found} trades: {new_trades} new, {skipped_duplicates} duplicates, {skipped_no_ticker} no ticker, {ai_analyzed} AI analyzed, {errors} errors"
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        mark_job_completed('congress_trades', target_date, None, [], duration_ms=duration_ms)
        logger.info(f"✅ Congress trades job completed: {message} in {duration_ms/1000:.2f}s")
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Error: {str(e)}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        try:
            mark_job_failed('congress_trades', target_date, None, str(e), duration_ms=duration_ms)
        except Exception:
            pass
        logger.error(f"❌ Congress trades job failed: {e}", exc_info=True)


def analyze_congress_trades_job() -> None:
    """Analyze unscored congress trades using committee data to calculate conflict scores.
    
    This job:
    1. Finds trades where conflict_score IS NULL
    2. Enriches with committee assignments and sector data
    3. Uses Granite AI to calculate conflict scores
    4. Updates conflict_score and notes fields
    
    Note: This is a wrapper around analyze_congress_trades_batch.py logic.
    Processes in batches to avoid overwhelming Ollama.
    """
    job_id = 'analyze_congress_trades'
    start_time = time.time()
    
    try:
        # Ensure path is set up correctly before importing
        import sys
        from pathlib import Path
        
        # Re-ensure project root is first in path
        current_dir = Path(__file__).resolve().parent
        if current_dir.name == "scheduler":
            project_root = current_dir.parent.parent
        else:
            project_root = current_dir.parent.parent
        
        project_root_str = str(project_root)
        if project_root_str in sys.path:
            sys.path.remove(project_root_str)
        sys.path.insert(0, project_root_str)
        
        # Import job tracking
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        
        logger.info("Starting congress trades analysis job...")
        
        # Mark job as started
        target_date = datetime.now(timezone.utc).date()
        mark_job_started('analyze_congress_trades', target_date)
        
        # Import dependencies (lazy imports)
        try:
            from supabase_client import SupabaseClient
            from ollama_client import OllamaClient
        except ImportError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Missing dependency: {e}"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            mark_job_failed('analyze_congress_trades', target_date, None, message, duration_ms=duration_ms)
            return
        
        # Import analysis functions from batch script
        # We'll import the functions directly to reuse the logic
        import sys
        from pathlib import Path
        project_root = Path(__file__).parent.parent.parent
        sys.path.insert(0, str(project_root))
        sys.path.insert(0, str(project_root / 'web_dashboard'))
        
        # Import the analysis functions
        # Note: fix_failed_scores is NOT imported - it should only be run manually via --fix-only flag
        from scripts.analyze_congress_trades_batch import (
            get_trade_context,
            analyze_trade,
            is_low_risk_asset
        )
        from settings import get_summarizing_model
        
        # Initialize clients
        client = SupabaseClient(use_service_role=True)
        ollama = OllamaClient()
        
        # Get model from settings (defaults to granite3.3:8b from model_config.json)
        model_name = get_summarizing_model()
        
        # Check Ollama health
        if not ollama or not ollama.check_health():
            duration_ms = int((time.time() - start_time) * 1000)
            message = "Ollama is not accessible - skipping analysis"
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            logger.warning(f"⚠️  {message}")
            mark_job_completed('analyze_congress_trades', target_date, None, [], duration_ms=duration_ms)
            return
        
        # Note: fix_failed_scores() is NOT called here automatically
        # It should only be run manually via the batch script with --fix-only flag
        # This is because 0.0 might be a legitimate score in the future
        
        # Process unscored trades in batches
        batch_size = 10  # Process 10 trades per run to avoid overwhelming Ollama
        total_processed = 0
        total_errors = 0
        
        try:
            # Fetch unscored trades (newest first)
            response = client.supabase.table("congress_trades_enriched")\
                .select("*")\
                .is_("conflict_score", "null")\
                .order("transaction_date", desc=True)\
                .limit(batch_size)\
                .execute()
            
            trades = response.data
            
            if not trades:
                duration_ms = int((time.time() - start_time) * 1000)
                message = "No unscored trades found"
                log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
                logger.info(f"✅ {message}")
                mark_job_completed('analyze_congress_trades', target_date, None, [], duration_ms=duration_ms)
                return
            
            logger.info(f"Processing {len(trades)} unscored trades...")
            
            # Process each trade
            for trade in trades:
                try:
                    # Enrich with committee data and sector info
                    context = get_trade_context(client, trade)
                    
                    # Check if this is a low-risk asset that doesn't need AI analysis
                    is_low_risk, filter_reason = is_low_risk_asset(context)
                    
                    if is_low_risk:
                        # Automatically assign low conflict score without AI analysis
                        analysis = {
                            'conflict_score': 0.0,
                            'confidence_score': 1.0,
                            'reasoning': f"Auto-filtered: {filter_reason}"
                        }
                        logger.info(f"   [FILTERED] {context['politician']} - {context['ticker']}: {filter_reason}")
                    else:
                        # Analyze with AI (using model from settings)
                        analysis = analyze_trade(ollama, context, model=model_name)
                    
                    if analysis and 'conflict_score' in analysis:
                        score = float(analysis['conflict_score'])
                        confidence = float(analysis.get('confidence_score', 0.75))  # Default to 0.75 if missing
                        reasoning = analysis.get('reasoning', 'No reasoning provided')
                        
                        # Save to PostgreSQL (separate database to save Supabase costs)
                        try:
                            from postgres_client import PostgresClient
                            postgres = PostgresClient()
                            
                            postgres.execute_update(
                                """
                                INSERT INTO congress_trades_analysis 
                                    (trade_id, conflict_score, confidence_score, reasoning, model_used, analysis_version)
                                VALUES (%s, %s, %s, %s, %s, %s)
                                ON CONFLICT (trade_id, model_used, analysis_version) 
                                DO UPDATE SET 
                                    conflict_score = EXCLUDED.conflict_score,
                                    confidence_score = EXCLUDED.confidence_score,
                                    reasoning = EXCLUDED.reasoning,
                                    analyzed_at = NOW()
                                """,
                                (trade['id'], score, confidence, reasoning, model_name, 1)
                            )
                            
                            logger.info(f"   [SCORED] {context['politician']} - {context['ticker']}: conflict={score:.2f}, confidence={confidence:.2f}")
                            total_processed += 1
                        except Exception as db_error:
                            logger.error(f"   [ERROR] Failed to save analysis to Postgres: {db_error}")
                            total_errors += 1
                    else:
                        logger.warning(f"   [WARN] Failed to parse AI response for trade ID {trade['id']}")
                        total_errors += 1
                        # Don't update - leave as NULL so it can be retried
                        
                except Exception as e:
                    logger.error(f"Error processing trade {trade.get('id', 'unknown')}: {e}", exc_info=True)
                    total_errors += 1
                    # Continue processing other trades
            
            # Log completion
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Processed {total_processed} trades, {total_errors} errors"
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            logger.info(f"✅ Congress trades analysis job completed: {message} in {duration_ms/1000:.2f}s")
            mark_job_completed('analyze_congress_trades', target_date, None, [], duration_ms=duration_ms)
            
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Error during analysis: {e}"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}", exc_info=True)
            mark_job_failed('analyze_congress_trades', target_date, None, str(e), duration_ms=duration_ms)
            
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Critical error: {e}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        logger.error(f"❌ Congress trades analysis job failed: {e}", exc_info=True)
        try:
            from utils.job_tracking import mark_job_failed
            target_date = datetime.now(timezone.utc).date()
            mark_job_failed('analyze_congress_trades', target_date, None, str(e), duration_ms=duration_ms)
        except:
            pass


def rescore_congress_sessions_job(limit: int = 1000, batch_size: int = 10, model: Optional[str] = None) -> None:
    """Manual job: Rescore congress trades sessions using updated AI logic.
    
    This is a ONE-TIME job for backfilling the entire database with the new:
    - Intent Classification logic
    - Leadership jurisdiction fix
    - Batch prefetching optimization
    
    Args:
        limit: Max sessions to process (default 1000)
        batch_size: Number of sessions per batch (default 10)
        model: Model to use (defaults to get_summarizing_model() from settings)
    """
    job_id = 'rescore_congress_sessions'
    start_time = time.time()
    
    try:
        # Ensure path is set up correctly before importing
        import sys
        from pathlib import Path
        
        # Re-ensure project root is first in path
        current_dir = Path(__file__).resolve().parent
        if current_dir.name == "scheduler":
            project_root = current_dir.parent.parent
        else:
            project_root = current_dir.parent.parent
        
        project_root_str = str(project_root)
        if project_root_str in sys.path:
            sys.path.remove(project_root_str)
        sys.path.insert(0, project_root_str)
        
        # Import job tracking
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        from settings import get_summarizing_model
        
        # Use provided model or get from settings
        if model is None:
            model = get_summarizing_model()
        
        logger.info(f"Starting congress sessions rescore job (Limit: {limit}, Batch: {batch_size}, Model: {model})...")
        
        # Mark job as started
        target_date = datetime.now(timezone.utc).date()
        mark_job_started('rescore_congress_sessions', target_date)
        
        # Import dependencies
        try:
            import subprocess
            from pathlib import Path
        except ImportError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Missing dependency: {e}"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            mark_job_failed('rescore_congress_sessions', target_date, None, message, duration_ms=duration_ms)
            return
        
        # Build script path
        project_root = Path(__file__).parent.parent.parent
        script_path = project_root / 'web_dashboard' / 'scripts' / 'analyze_congress_trades_batch.py'
        
        if not script_path.exists():
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Analysis script not found: {script_path}"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            mark_job_failed('rescore_congress_sessions', target_date, None, message, duration_ms=duration_ms)
            return
        
        # Run the batch analysis script with rescore parameters
        # Cast to int to handle float values from Streamlit number_input
        limit = int(limit)
        batch_size = int(batch_size)
        
        cmd = [
            'python', '-u', str(script_path),
            '--sessions',
            '--rescore',
            '--batch-size', str(batch_size),
            '--model', str(model),
            '--limit', str(limit)
        ]
        logger.info(f"Executing command: {' '.join(cmd)}")
        logger.info(f"Working Directory: {str(project_root)}")

        
        # Use Popen to stream output line-by-line
        process = subprocess.Popen(
            cmd,
            cwd=str(project_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Merge stderr into stdout
            text=True,
            bufsize=1,  # Line buffered
            encoding='utf-8'
        )

        # Stream output
        full_output = []
        last_log_time = time.time()
        
        # Read stdout line by line
        for line in iter(process.stdout.readline, ''):
            clean_line = line.strip()
            full_output.append(clean_line)
            
            # Log significant lines to main logger immediately
            # This makes them visible in the console/logs in real-time
            if clean_line:
                if any(x in clean_line for x in ["SESSION ANALYZED", "Completed processing", "Starting AI Analysis", "Traceback", "Error"]):
                    logger.info(f"   [Script] {clean_line}")
                # Log progress every 60 seconds regardless of content
                elif time.time() - last_log_time > 60:
                    logger.info(f"   [Script] {clean_line}")
                    last_log_time = time.time()
        
        process.stdout.close()
        return_code = process.wait()
        
        if return_code == 0:
            duration_ms = int((time.time() - start_time) * 1000)
            # Find completion message
            completed_lines = [line for line in full_output if 'Completed processing' in line]
            
            if completed_lines:
                # Remove timestamp/level prefix if present to keep it clean
                msg_text = completed_lines[-1]
                if "INFO -" in msg_text:
                    message = msg_text.split('INFO -')[-1].strip()
                else:
                    message = msg_text
            else:
                message = f"Rescore completed ({limit} sessions)"
            
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            mark_job_completed('rescore_congress_sessions', target_date, None, [], duration_ms=duration_ms)
            logger.info(f"✅ {message}")
        else:
            duration_ms = int((time.time() - start_time) * 1000)
            # Use last 10 lines as error snippet
            error_snippet = "\n".join(full_output[-10:])
            message = f"Script failed with exit code {return_code}. Last output:\n{error_snippet}"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            mark_job_failed('rescore_congress_sessions', target_date, None, message, duration_ms=duration_ms)
            logger.error(f"❌ Script failed: {message}")
        
    except subprocess.TimeoutExpired:
        duration_ms = int((time.time() - start_time) * 1000)
        message = "Job timed out after 2 hours"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        try:
            mark_job_failed('rescore_congress_sessions', target_date, None, message, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error(f"❌ {message}")
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Error: {str(e)}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        try:
            mark_job_failed('rescore_congress_sessions', target_date, None, message, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error(f"❌ Congress sessions rescore job failed: {e}", exc_info=True)


def scrape_congress_trades_job(months_back: Optional[int] = None, page_size: int = 100, max_pages: Optional[int] = None, start_page: int = 1, skip_recent: bool = False) -> None:
    """Manual job: Scrape congressional trades from external source.

    This job scrapes historical congressional trading data
    using BeautifulSoup and FlareSolverr (if available) to bypass Cloudflare.
    
    Args:
        months_back: Number of months back to scrape (None = all available)
        page_size: Number of trades per page (default: 100)
        max_pages: Maximum number of pages to process (None = unlimited)
        start_page: Page number to start from (default: 1)
        skip_recent: Skip trades on or after most recent trade date (default: False)
    """
    job_id = 'scrape_congress_trades'
    start_time = time.time()
    
    try:
        # Ensure path is set up correctly before importing
        import sys
        from pathlib import Path
        
        # Re-ensure project root is first in path
        current_dir = Path(__file__).resolve().parent
        if current_dir.name == "scheduler":
            project_root = current_dir.parent.parent
        else:
            project_root = current_dir.parent.parent
        
        project_root_str = str(project_root)
        if project_root_str in sys.path:
            sys.path.remove(project_root_str)
        sys.path.insert(0, project_root_str)
        
        # Import job tracking
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        
        logger.info(f"Starting congress trades scraping job (months_back={months_back}, page_size={page_size}, max_pages={max_pages}, start_page={start_page}, skip_recent={skip_recent})...")
        
        # Mark job as started
        target_date = datetime.now(timezone.utc).date()
        mark_job_started('scrape_congress_trades', target_date)
        
        # Import dependencies
        try:
            import subprocess
            from pathlib import Path
        except ImportError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Missing dependency: {e}"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            mark_job_failed('scrape_congress_trades', target_date, None, message, duration_ms=duration_ms)
            return
        
        # Build script path
        project_root = Path(__file__).parent.parent.parent
        script_path = project_root / 'web_dashboard' / 'scripts' / 'seed_congress_trades.py'
        
        if not script_path.exists():
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Scraping script not found: {script_path}"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            mark_job_failed('scrape_congress_trades', target_date, None, message, duration_ms=duration_ms)
            return
        
        # Build command with parameters
        cmd = ['python', '-u', str(script_path)]
        
        if months_back is not None:
            cmd.extend(['--months-back', str(int(months_back))])
        if page_size != 100:
            cmd.extend(['--page-size', str(int(page_size))])
        if max_pages is not None:
            cmd.extend(['--max-pages', str(int(max_pages))])
        if start_page != 1:
            cmd.extend(['--start-page', str(int(start_page))])
        if skip_recent:
            cmd.append('--skip-recent')
        
        logger.info(f"Executing command: {' '.join(cmd)}")
        logger.info(f"Working Directory: {str(project_root)}")
        
        # Use Popen to stream output line-by-line
        process = subprocess.Popen(
            cmd,
            cwd=str(project_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Merge stderr into stdout
            text=True,
            bufsize=1,  # Line buffered
            encoding='utf-8'
        )
        
        # Stream output
        full_output = []
        last_log_time = time.time()
        
        # Read stdout line by line
        for line in iter(process.stdout.readline, ''):
            clean_line = line.strip()
            full_output.append(clean_line)
            
            # Log significant lines to main logger immediately
            if clean_line:
                if any(x in clean_line for x in ["✅", "❌", "⚠️", "Total added", "Total skipped", "Total errors", "Completed", "Traceback", "Error"]):
                    logger.info(f"   [Script] {clean_line}")
                # Log progress every 60 seconds regardless of content
                elif time.time() - last_log_time > 60:
                    logger.info(f"   [Script] {clean_line}")
                    last_log_time = time.time()
        
        process.stdout.close()
        return_code = process.wait()
        
        if return_code == 0:
            duration_ms = int((time.time() - start_time) * 1000)
            # Find completion message
            completed_lines = [line for line in full_output if 'Total added' in line or 'Total skipped' in line]
            
            if completed_lines:
                # Get the summary line
                summary = completed_lines[-1] if completed_lines else "Scraping completed"
                message = summary
            else:
                message = "Congress trades scraping completed"
            
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            mark_job_completed('scrape_congress_trades', target_date, None, [], duration_ms=duration_ms)
            logger.info(f"✅ {message}")
        else:
            duration_ms = int((time.time() - start_time) * 1000)
            # Use last 10 lines as error snippet
            error_snippet = "\n".join(full_output[-10:])
            message = f"Script failed with exit code {return_code}. Last output:\n{error_snippet}"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            mark_job_failed('scrape_congress_trades', target_date, None, message, duration_ms=duration_ms)
            logger.error(f"❌ Script failed: {message}")
        
    except subprocess.TimeoutExpired:
        duration_ms = int((time.time() - start_time) * 1000)
        message = "Job timed out"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        try:
            mark_job_failed('scrape_congress_trades', target_date, None, message, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error(f"❌ {message}")
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Error: {str(e)}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        try:
            mark_job_failed('scrape_congress_trades', target_date, None, message, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error(f"❌ Congress trades scraping job failed: {e}", exc_info=True)

