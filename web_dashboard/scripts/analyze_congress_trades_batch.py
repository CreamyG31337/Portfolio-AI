#!/usr/bin/env python3
"""
Analyze Congress Trades Batch Script
====================================

This script analyzes congress trades using the local LLM to detect potential
conflicts of interest. It processes trades that haven't been scored yet.

Features:
- Batched processing (newest to oldest)
- Resumable (skips already scored trades)
- Fixes "failed" 0.0 scores to NULL so they can be retried
- Enriches data with company sector from securities table

Usage:
    python scripts/analyze_congress_trades_batch.py [--batch-size 10] [--model granite3.3:8b]
"""

import re
import sys
import os
import json
import time
import argparse
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime, timedelta
import pandas as pd

# Fix Windows console encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
from dotenv import load_dotenv
env_path = project_root / 'web_dashboard' / '.env'
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()

from supabase_client import SupabaseClient
from ollama_client import OllamaClient
from postgres_client import PostgresClient
from data.committee_jurisdictions import get_committee_context

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("congress_analysis.log")
    ]
)
logger = logging.getLogger(__name__)

# Module-level caches for performance
_politician_cache = {}  # {politician_name: {'id': int, 'committees_str': str}}
_sector_cache = {}      # {ticker: {'company_name': str, 'sector': str, 'description': str}}

# Known ETF tickers (major ones that appear frequently in congressional trades)
KNOWN_ETF_TICKERS = {
    'SPY', 'QQQ', 'VOO', 'IVV', 'DIA', 'IWM', 'EFA', 'VEA', 'VTI', 
    'AGG', 'BND', 'GLD', 'SLV', 'VNQ', 'XLF', 'XLE', 'XLK', 'XLV'
}

# Helper to extract JSON from text (handles models that return extra text)
def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract first JSON block found in text using regex."""
    try:
        # First, try direct parse
        return json.loads(text.strip())
    except json.JSONDecodeError:
        try:
            # Find the first { and last }
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except:
            pass
    return None

def is_low_risk_asset(context: Dict[str, Any]) -> Tuple[bool, str]:
    """Check if an asset is low-risk and doesn't require AI analysis.
    
    Low-risk assets include:
    - Non-purchase/sale transactions (Exchange, Received, etc.)
    - ETFs and Mutual Funds
    - Bonds, Treasuries, and other fixed-income securities
    
    Args:
        context: Trade context dictionary with enriched data
        
    Returns:
        Tuple of (is_low_risk: bool, reason: str)
    """
    # Check 1: Transaction type - only analyze Purchase/Sale
    txn_type = context.get('type', '').strip()
    if txn_type not in ['Purchase', 'Sale']:
        return True, f"Non-investment transaction type: {txn_type}"
    
    # Check 2: Known ETF tickers
    ticker = context.get('ticker', '').strip().upper()
    if ticker in KNOWN_ETF_TICKERS:
        return True, f"Known ETF ticker: {ticker}"
    
    # Check 3: Company name indicators (ETF, Fund, Index)
    company_name = (context.get('company_name') or '').lower()
    for indicator in [' etf', ' fund', ' index', 'ishares', 'vanguard', 'spdr']:
        if indicator in company_name:
            return True, f"Asset name indicates fund/ETF: {company_name}"
    
    # Check 4: Sector/Asset type indicators (Bonds, Treasuries)
    sector = (context.get('sector') or '').lower()
    for indicator in ['bond', 'treasury', 'municipal', 'note', 'bill']:
        if indicator in sector:
            return True, f"Fixed-income security: {sector}"
    
    # Not a low-risk asset - requires AI analysis
    return False, ""

# Prompt template for SESSION-BASED analysis with Intent Classification
SESSION_PROMPT_TEMPLATE = """
Role: Forensic Financial Analyst
Mission: Classify the **INTENT** behind Congressional trading sessions.

--- INPUT DATA ---
**Subject:** {politician} ({party} - {state})
**Chamber:** {chamber}

**Committee Powers & Jurisdictions:**
{committee_descriptions}
*(Use these definitions to determine regulatory reach.)*

**Session Activity ({trade_count} trades):**
{trades_table}

--- ANALYSIS LOGIC (Follow Step-by-Step) ---

STEP 1: REGULATORY LINK?
- Does the Committee Definition above explicitly cover the stock's industry?
  - *YES:* Proceed to Step 2.
  - *NO:* Mark as "NO_RELATIONSHIP" (Score 0.0).

STEP 2: DIRECTION OF TRADE?
- **BUYING:** This is an active bet on the sector.
  - *Verdict:* If Link is YES -> "CONFLICT_BUY" (Score 0.9).
- **SELLING:** This is ambiguous. Proceed to Step 3.

STEP 3: SELLING CONTEXT (The "Deborah Ross" Rule)
- **Small Sell ($1k - $15k):** This is likely "Divestment" or "Housekeeping."
  - *Verdict:* "ROUTINE_DIVESTMENT" (Score 0.1 - Safe).
- **Large Sell ($50k+) or Full Exit:** This is "Dumping."
  - *Verdict:* If Link is YES -> "SUSPICIOUS_SELL" (Score 0.8 - Danger).
- **Options/Shorts:** Betting against the market.
  - *Verdict:* "AGGRESSIVE_BET" (Score 1.0 - Critical).

--- OUTPUT REQUIREMENT ---
Return valid JSON only. "risk_pattern" MUST be one of the enums below.

Enums for "risk_pattern":
- "CONFLICT_BUY" (Buying regulated stock)
- "SUSPICIOUS_SELL" (Large dump of regulated stock)
- "AGGRESSIVE_BET" (Options/Shorts)
- "ROUTINE_DIVESTMENT" (Small sales of regulated stock)
- "NO_RELATIONSHIP" (No committee link)

{{
  "conflict_score": 0.1,
  "confidence_score": 0.95,
  "risk_pattern": "ROUTINE_DIVESTMENT",
  "reasoning": "Subject sits on Science Committee (Nuclear AI Regulation), which links to Microsoft. HOWEVER, the trade is a small sale (<$15k). This fits the pattern of ethical divestment rather than insider profit-taking."
}}

The confidence_score (0.0-1.0) indicates how certain you are.
"""

# Legacy prompt for single-trade analysis (kept for backward compatibility if needed)
PROMPT_TEMPLATE = """
Analyze this trade for potential Insider Trading/Conflict of Interest.
Data:
- Politician: {politician} ({party} - {state})
- Chamber: {chamber}
- Asset Owner: {owner}
- Committee Assignments: {committees}
- Ticker: {ticker}
- Company: {company_name}
- Sector: {sector}
{description_section}- Date: {date}
- Type: {type}
- Amount: {amount}

Task:
Calculate a 'conflict_score' from 0.0 to 1.0 based on these rules:
1. HIGH SCORE (0.8-1.0): Direct overlap (e.g., Armed Services member buying Defense stock, spouse trades, timing near votes).
2. MEDIUM SCORE (0.4-0.7): Sector overlap or related industries.
3. LOW SCORE (0.0-0.3): Broad index funds or clearly unrelated industries.

Consider:
- Committee jurisdiction over company's sector
- Asset owner (Self vs Spouse/Dependent) - spouse trades can still be concerning
- Political party relevance to industry
- State interests (e.g., CA rep + tech stocks, TX rep + energy)

Return JSON with TWO fields:
{{
  "conflict_score": 0.95,
  "confidence_score": 0.88,
  "reasoning": "Rep. Smith (R-TX) sits on House Armed Services and bought $50k RTX. High overlap between committee jurisdiction and defense contractor."
}}

The confidence_score (0.0-1.0) indicates how certain you are about the conflict_score. Use high confidence (>0.8) for clear-cut cases, medium (0.5-0.8) for typical cases, and low (<0.5) for ambiguous situations.
"""

def fix_failed_scores(client: SupabaseClient):
    """Reset trades with 0.0 score and failure notes to NULL so they can be retried.
    
    WARNING: This should ONLY be run manually via --fix-only flag.
    Do NOT call this automatically in scheduled jobs, as 0.0 might be a legitimate score.
    This function is only for fixing buggy scores from previous versions.
    """
    logger.info("Checking for failed scores (0.0 with error notes)...")
    
    try:
        # Find records with 0 score and "Error" or "Failed" in notes
        # Supabase filtering limitations might require fetching and filtering in python if logic is complex
        # But we can try a simple query first.
        
        # Note: We can't easily do LIKE query for multiple conditions in one go via simple client methods sometimes
        # So we fetch 0 scores and check notes in Python for safety
        
        response = client.supabase.table("congress_trades")\
            .select("id, notes")\
            .eq("conflict_score", 0.0)\
            .execute()
            
        to_fix = []
        for row in response.data:
            notes = str(row.get('notes', '')).lower()
            if 'error' in notes or 'fail' in notes or 'optimization failed' in notes:
                to_fix.append(row['id'])
        
        if to_fix:
            logger.info(f"Found {len(to_fix)} failed records to reset.")
            # Update in batches
            batch_size = 50
            for i in range(0, len(to_fix), batch_size):
                batch_ids = to_fix[i:i+batch_size]
                client.supabase.table("congress_trades")\
                    .update({"conflict_score": None})\
                    .in_("id", batch_ids)\
                    .execute()
            logger.info("   [FIXED] Reset failed scores to NULL.")
        else:
            logger.info("No failed scores found.")
            
    except Exception as e:
        logger.error(f"Error fixing failed scores: {e}")

# ===== BATCH PREFETCH FUNCTIONS (Optimization) =====

def prefetch_securities_batch(client: SupabaseClient, tickers: List[str]) -> None:
    """Prefetch securities data for multiple tickers in a single query.
    
    This populates the module-level _sector_cache to avoid per-trade queries.
    """
    # Filter out already cached tickers
    uncached_tickers = [t for t in tickers if t not in _sector_cache]
    
    if not uncached_tickers:
        return
    
    # Chunk tickers to avoid "URL too long" error
    chunk_size = 50
    for i in range(0, len(uncached_tickers), chunk_size):
        chunk = uncached_tickers[i:i + chunk_size]
        try:
            response = client.supabase.table("securities")\
                .select("ticker, company_name, sector, description")\
                .in_("ticker", chunk)\
                .execute()
            
            for sec in response.data:
                ticker = sec.get('ticker')
                if ticker:
                    _sector_cache[ticker] = {
                        'company_name': sec.get('company_name', 'Unknown'),
                        'sector': sec.get('sector', 'Unknown'),
                        'description': sec.get('description') or None
                    }
        except Exception as e:
            logger.warning(f"Failed to prefetch securities chunk {i}: {e}")
            
    logger.debug(f"Prefetched securities for {len(uncached_tickers)} tickers")


def prefetch_politician_committees(client: SupabaseClient, politician_name: str) -> None:
    """Prefetch politician and committee data for a single politician in optimized queries.
    
    This populates the module-level _politician_cache.
    """
    if politician_name in _politician_cache:
        return
    
    try:
        # Find the politician
        politician_result = client.supabase.table("politicians")\
            .select("id, name")\
            .ilike("name", f"%{politician_name}%")\
            .limit(1)\
            .execute()
        
        if not politician_result.data:
            _politician_cache[politician_name] = {
                'id': None,
                'committees_str': f'Unknown (politician "{politician_name}" not found in database)'
            }
            return
        
        politician_id = politician_result.data[0]['id']
        
        # Get all committee assignments
        assignments_result = client.supabase.table("committee_assignments")\
            .select("""
                committee_id,
                rank,
                title,
                committees (
                    name,
                    target_sectors
                )
            """)\
            .eq("politician_id", politician_id)\
            .execute()
        
        if assignments_result.data:
            committees_list = []
            for assignment in assignments_result.data:
                committee = assignment.get('committees', {})
                committee_name = committee.get('name', 'Unknown')
                target_sectors = committee.get('target_sectors', [])
                title = assignment.get('title', 'Member')
                
                sectors_str = ', '.join(target_sectors) if target_sectors else 'None'
                title_str = f" ({title})" if title else ""
                committees_list.append(f"{committee_name}{title_str} - Sectors: {sectors_str}")
            
            committees_str = '; '.join(committees_list)
        else:
            committees_str = 'None'
        
        # Leadership Fix
        leadership_names = ["Pelosi", "Mike Johnson", "Speaker Johnson"]
        if any(ln.lower() in politician_name.lower() for ln in leadership_names):
            if committees_str == 'None':
                committees_str = "Leadership"
            else:
                committees_str = f"Leadership; {committees_str}"
        
        _politician_cache[politician_name] = {
            'id': politician_id,
            'committees_str': committees_str
        }
        
        logger.debug(f"Prefetched committees for {politician_name}")
        
    except Exception as e:
        logger.warning(f"Failed to prefetch politician data for {politician_name}: {e}")
        _politician_cache[politician_name] = {
            'id': None,
            'committees_str': 'Error fetching committee data'
        }

def get_trade_context(client: SupabaseClient, trade: Dict[str, Any], use_cache: bool = True) -> Dict[str, Any]:
    """Enrich trade data with sector, company info, and committee assignments.
    
    Args:
        client: Supabase client instance
        trade: Trade data dictionary
        use_cache: Whether to use module-level caches for performance
    """
    ticker = trade.get('ticker')
    politician_name = trade.get('politician', 'Unknown')
    
    context = {
        'politician': politician_name,
        'party': trade.get('party') or 'Unknown',
        'state': trade.get('state') or 'Unknown',
        'chamber': trade.get('chamber') or 'Unknown',
        'owner': trade.get('owner') or 'Self',  # Default to Self if not specified
        'committees': 'Unknown',
        'ticker': ticker,
        'company_name': 'Unknown',
        'sector': 'Unknown',
        'description': None,
        'date': trade.get('transaction_date'),
        'type': trade.get('type'),
        'amount': trade.get('amount')
    }
    
    # Fetch metadata from securities table (with caching)
    try:
        if use_cache and ticker in _sector_cache:
            # Use cached data
            cached = _sector_cache[ticker]
            context['company_name'] = cached.get('company_name', 'Unknown')
            context['sector'] = cached.get('sector', 'Unknown')
            context['description'] = cached.get('description')
        else:
            # Fetch from database
            response = client.supabase.table("securities")\
                .select("company_name, sector, description")\
                .eq("ticker", ticker)\
                .execute()
                
            if response.data:
                sec = response.data[0]
                company_name = sec.get('company_name', 'Unknown')
                sector = sec.get('sector', 'Unknown')
                description = sec.get('description')
                
                context['company_name'] = company_name
                context['sector'] = sector
                context['description'] = description
                
                # Cache for future use
                if use_cache:
                    _sector_cache[ticker] = {
                        'company_name': company_name,
                        'sector': sector,
                        'description': description
                    }
                    
    except Exception as e:
        logger.warning(f"Failed to fetch security metadata for {ticker}: {e}")
    
    # Fetch committee assignments for this politician (with caching)
    try:
        if use_cache and politician_name in _politician_cache:
            # Use cached committees string
            context['committees'] = _politician_cache[politician_name]['committees_str']
        else:
            # First, find the politician by name (fuzzy match - try exact first, then partial)
            politician_result = client.supabase.table("politicians")\
                .select("id, name")\
                .ilike("name", f"%{politician_name}%")\
                .limit(1)\
                .execute()
            
            if politician_result.data:
                politician_id = politician_result.data[0]['id']
                
                # Get all committee assignments for this politician
                assignments_result = client.supabase.table("committee_assignments")\
                    .select("""
                        committee_id,
                        rank,
                        title,
                        committees (
                            name,
                            target_sectors
                        )
                    """)\
                    .eq("politician_id", politician_id)\
                    .execute()
                
                if assignments_result.data:
                    committees_list = []
                    for assignment in assignments_result.data:
                        committee = assignment.get('committees', {})
                        committee_name = committee.get('name', 'Unknown')
                        target_sectors = committee.get('target_sectors', [])
                        rank = assignment.get('rank')
                        title = assignment.get('title', 'Member')
                        
                        # Format: "House Committee on Armed Services (Chairman) - Defense, Aerospace"
                        sectors_str = ', '.join(target_sectors) if target_sectors else 'None'
                        title_str = f" ({title})" if title else ""
                        committees_list.append(f"{committee_name}{title_str} - Sectors: {sectors_str}")
                    
                    committees_str = '; '.join(committees_list)
                else:
                    committees_str = 'None'
                
                # Leadership Fix: Explicitly add Leadership context for known high-profile members
                # (Nancy Pelosi, Mike Johnson often show up with no committees)
                leadership_names = ["Pelosi", "Mike Johnson", "Speaker Johnson"]
                if any(ln.lower() in politician_name.lower() for ln in leadership_names):
                    if committees_str == 'None':
                        committees_str = "Leadership"
                    else:
                        committees_str = f"Leadership; {committees_str}"
                    
                context['committees'] = committees_str
                
                # Cache for future use
                if use_cache:
                    _politician_cache[politician_name] = {
                        'id': politician_id,
                        'committees_str': committees_str
                    }
                else:
                    context['committees'] = 'None (no committee assignments found)'
            else:
                context['committees'] = f'Unknown (politician "{politician_name}" not found in database)'
                
    except Exception as e:
        logger.warning(f"Failed to fetch committee data for {politician_name}: {e}")
        context['committees'] = 'Error fetching committee data'
        
    return context

def analyze_trade(ollama: OllamaClient, context: Dict[str, Any], model: str, verbose: bool = False, max_retries: int = 2) -> Dict[str, Any]:
    """Run AI analysis on a single trade with structured JSON output.
    
    Args:
        ollama: Ollama client instance
        context: Trade context dictionary
        model: Model name to use
        verbose: Whether to print streaming output
        max_retries: Maximum number of retry attempts for transient failures
    
    Returns:
        Dictionary with conflict_score, confidence_score, and reasoning, or None on failure
    """
    # Format description section if available
    description_section = ""
    if context.get('description'):
        description_section = f"- Description: {context['description']}\n"
    
    # Create context copy with formatted description
    formatted_context = context.copy()
    formatted_context['description_section'] = description_section
    
    prompt = PROMPT_TEMPLATE.format(**formatted_context)
    
    logger.info(f"Analyzing {context['politician']} - {context['ticker']}...")
    
    if verbose:
        print(f"\n{'='*80}")
        print(f"🤖 Granite Analysis: {context['politician']} ({context['party']}-{context['state']}) - {context['ticker']}")
        print(f"{'='*80}")
    
    # System prompt to enforce JSON
    system_prompt = "You are a financial ethics analyzer. Return ONLY valid JSON with the exact fields specified."
    
    for attempt in range(max_retries + 1):
        try:
            # Use structured system prompt to encourage JSON output
            full_response = ""
            for chunk in ollama.query_ollama(
                prompt=prompt,
                model=model,
                stream=True,
                system_prompt=system_prompt,
                temperature=0.1  # Low temp for consistent JSON
            ):
                full_response += chunk
                if verbose:
                    print(chunk, end='', flush=True)
            
            if verbose:
                print(f"\n{'='*80}\n")
            
            # Parse JSON directly (no regex needed with format="json")
            result = extract_json(full_response)
            
            if not result:
                raise ValueError("Could not extract JSON from response")
            
            # Validate required fields with fallbacks
            if 'conflict_score' not in result:
                if 'score' in result:
                    result['conflict_score'] = result['score']
                else:
                    raise ValueError("Response missing 'conflict_score' or 'score' field")
            
            # confidence_score is optional for backward compatibility
            if 'confidence_score' not in result:
                logger.warning(f"Response missing 'confidence_score', defaulting to 0.75")
                result['confidence_score'] = 0.75
            
            if 'reasoning' not in result:
                result['reasoning'] = 'No reasoning provided'
            
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"AI Analysis JSON parse error (attempt {attempt + 1}/{max_retries + 1}): {e}")
            if attempt < max_retries:
                logger.info(f"Retrying in 1 second...")
                time.sleep(1)
            else:
                logger.error(f"Failed after {max_retries + 1} attempts")
                return None
                
        except Exception as e:
            logger.error(f"AI Analysis failed (attempt {attempt + 1}/{max_retries +1}): {e}")
            if attempt < max_retries:
                logger.info(f"Retrying in 1 second...")
                time.sleep(1)
            else:
                logger.error(f"Failed after {max_retries + 1} attempts")
                return None
    
    return None

def format_trades_table(trades: List[Dict[str, Any]]) -> str:
    """Format a list of trades into a readable table for the AI prompt.
    
    Args:
        trades: List of trade context dictionaries
        
    Returns:
        Formatted string table of trades
    """
    if not trades:
        return "No trades in session"
    
    lines = []
    lines.append("Date       | Type     | Ticker | Company                | Amount    | Owner")
    lines.append("-" * 80)
    
    for trade in trades:
        date = str(trade.get('date', 'Unknown'))[:10]
        txn_type = (trade.get('type', 'Unknown') or 'Unknown')[:8]
        ticker = (trade.get('ticker', '???') or '???')[:6]
        company = (trade.get('company_name', 'Unknown') or 'Unknown')[:22]
        amount = (trade.get('amount', 'Unknown') or 'Unknown')[:9]
        owner = (trade.get('owner', 'Self') or 'Self')[:10]
        
        lines.append(f"{date:10} | {txn_type:8} | {ticker:6} | {company:22} | {amount:9} | {owner}")
    
    return "\n".join(lines)


def analyze_session(
    ollama: OllamaClient,
    postgres: PostgresClient,
    supabase: SupabaseClient,
    session_id: int,
    model: str,
    verbose: bool = False
) -> bool:
    """Analyze an entire trading session.
    
    Args:
        ollama: Ollama client instance
        postgres: Postgres client instance
        supabase: Supabase client instance
        session_id: Session ID to analyze
        model: Model name to use
        verbose: Whether to print detailed output
        
    Returns:
        True if successful, False otherwise
    """
    from utils.session_manager import (
        should_skip_session,
        mark_session_analyzed
    )
    
    logger.info(f"Analyzing session {session_id}...")
    
    try:
        # Get session metadata
        session_result = postgres.execute_query(
            """
            SELECT politician_name, start_date, end_date, trade_count
            FROM congress_trade_sessions
            WHERE id = %s
            """,
            (session_id,)
        )
        
        if not session_result:
            logger.error(f"Session {session_id} not found")
            return False
        
        session = session_result[0]
        politician_name = session['politician_name']
        start_date = session['start_date']
        end_date = session['end_date']
        trade_count = session['trade_count']
        
        # Get trades for this session from postgres analysis table
        trades_result = postgres.execute_query(
            """
            SELECT trade_id
            FROM congress_trades_analysis
            WHERE session_id = %s
            """,
            (session_id,)
        )
        
        if not trades_result:
            logger.warning(f"No trades found for session {session_id}")
            return False
        
        trade_ids = [row['trade_id'] for row in trades_result]
        
        # Fetch full trade data from Supabase (chunked)
        trades = []
        chunk_size = 50
        for i in range(0, len(trade_ids), chunk_size):
            chunk = trade_ids[i:i + chunk_size]
            try:
                response = supabase.supabase.table("congress_trades_enriched")\
                    .select("*")\
                    .in_("id", chunk)\
                    .execute()
                trades.extend(response.data)
            except Exception as e:
                logger.error(f"Failed to fetch trades chunk {i}: {e}")
                return False
        
        if not trades:
            logger.warning(f"No trade data found in Supabase for session {session_id}")
            return False
        
        # === BATCH PREFETCH (Optimization) ===
        # Prefetch all securities data in one query
        tickers = list(set(t.get('ticker') for t in trades if t.get('ticker')))
        prefetch_securities_batch(supabase, tickers)
        
        # Prefetch politician committee data (one call for the session's politician)
        prefetch_politician_committees(supabase, politician_name)
        
        # Enrich each trade with context (now uses cache, no Supabase calls)
        enriched_trades = []
        for trade in trades:
            context = get_trade_context(supabase, trade)
            enriched_trades.append(context)
        
        # Check if we should skip this session (only low-risk trades)
        should_skip, skip_reason = should_skip_session(enriched_trades)
        
        if should_skip:
            # Auto-mark session as low-risk
            logger.info(f"   [FILTERED SESSION] {skip_reason}")
            mark_session_analyzed(
                postgres,
                session_id,
                conflict_score=0.0,
                confidence_score=1.0,
                ai_summary=f"Auto-filtered: {skip_reason}",
                risk_pattern="ROUTINE",  # Auto-filtered are always routine
                model_used=model
            )
            
            # Also save to each trade's analysis record
            for trade in trades:
                try:
                    postgres.execute_update(
                        """
                        INSERT INTO congress_trades_analysis 
                            (trade_id, session_id, conflict_score, confidence_score, reasoning, risk_pattern, model_used, analysis_version)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (trade_id, model_used, analysis_version) 
                        DO UPDATE SET 
                            session_id = EXCLUDED.session_id,
                            conflict_score = EXCLUDED.conflict_score,
                            confidence_score = EXCLUDED.confidence_score,
                            reasoning = EXCLUDED.reasoning,
                            risk_pattern = EXCLUDED.risk_pattern,
                            analyzed_at = NOW()
                        """,
                        (trade['id'], session_id, 0.0, 1.0, f"Auto-filtered: {skip_reason}", "ROUTINE", model, 1)
                    )
                except Exception as e:
                    logger.error(f"Failed to save filtered analysis for trade {trade['id']}: {e}")
            
            return True
        
        # Build context for prompt
        # Get politician context from first trade
        first_context = enriched_trades[0]
        politician_context = {
            'politician': politician_name,
            'party': first_context.get('party', 'Unknown'),
            'state': first_context.get('state', 'Unknown'),
            'chamber': first_context.get('chamber', 'Unknown'),
            'committees': first_context.get('committees', 'Unknown')
        }
        
        # Format trades table
        trades_table = format_trades_table(enriched_trades)
        
        # Generate committee context descriptions for injection
        committee_descriptions = get_committee_context(politician_context['committees'])
        
        # Build prompt with injected context
        prompt = SESSION_PROMPT_TEMPLATE.format(
            trade_count=trade_count,
            politician=politician_context['politician'],
            party=politician_context['party'],
            state=politician_context['state'],
            chamber=politician_context['chamber'],
            committee_descriptions=committee_descriptions,
            start_date=start_date,
            end_date=end_date,
            trades_table=trades_table
        )
        
        
        if verbose:
            try:
                print(f"\n{'='*80}")
                print(f"Session Analysis: {politician_name} ({trade_count} trades)")
                print(f"{'='*80}")
            except:
                pass  # Ignore print errors
        
        # Call AI with session prompt
        system_prompt = "You are a financial ethics analyzer. Return ONLY valid JSON with the exact fields specified."
        
        full_response = ""
        for chunk in ollama.query_ollama(
            prompt=prompt,
            model=model,
            stream=True,
            system_prompt=system_prompt,
            temperature=0.1
        ):
            full_response += chunk
            if verbose:
                try:
                    print(chunk, end='', flush=True)
                except:
                    pass  # Ignore print errors
        
        if verbose:
            try:
                print(f"\n{'='*80}\n")
            except:
                pass  # Ignore print errors

        
        # Parse response
        result = extract_json(full_response)
        
        if not result:
            logger.error(f"AI Response was not valid JSON for session {session_id}")
            logger.debug(f"Full response: {full_response}")
            return False
            
        if 'conflict_score' not in result:
            if 'score' in result:
                result['conflict_score'] = result['score']
            else:
                raise ValueError("Response missing 'conflict_score' or 'score' field")
        
        conflict_score = float(result['conflict_score'])
        confidence_score = float(result.get('confidence_score', 0.75))
        reasoning = result.get('reasoning', 'No reasoning provided')
        risk_pattern = result.get('risk_pattern', 'ROUTINE')  # Default to ROUTINE if not provided
        
        # Save to session table
        mark_session_analyzed(
            postgres,
            session_id,
            conflict_score=conflict_score,
            confidence_score=confidence_score,
            ai_summary=reasoning,
            risk_pattern=risk_pattern,
            model_used=model
        )
        
        # Save to each trade's analysis record
        for trade in trades:
            try:
                postgres.execute_update(
                    """
                    INSERT INTO congress_trades_analysis 
                        (trade_id, session_id, conflict_score, confidence_score, reasoning, risk_pattern, model_used, analysis_version)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (trade_id, model_used, analysis_version) 
                    DO UPDATE SET 
                        session_id = EXCLUDED.session_id,
                        conflict_score = EXCLUDED.conflict_score,
                        confidence_score = EXCLUDED.confidence_score,
                        reasoning = EXCLUDED.reasoning,
                        risk_pattern = EXCLUDED.risk_pattern,
                        analyzed_at = NOW()
                    """,
                    (trade['id'], session_id, conflict_score, confidence_score, reasoning, risk_pattern, model, 1)
                )
            except Exception as e:
                logger.error(f"Failed to save analysis for trade {trade['id']}: {e}")
        
        logger.info(f"   [SESSION ANALYZED] Score: {conflict_score:.2f}, Confidence: {confidence_score:.2f}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error analyzing session {session_id}: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description='Analyze Congress Trades')
    parser.add_argument('--batch-size', type=int, default=10, help='Number of trades/sessions to process per batch')
    parser.add_argument('--model', type=str, default='granite3.3:8b', help='Ollama model to use')
    parser.add_argument('--limit', type=int, default=0, help='Total limit of trades/sessions to process (0 for infinite)')
    parser.add_argument('--fix-only', action='store_true', help='Only fix failed scores and exit')
    parser.add_argument('--rescore', action='store_true', help='Re-analyze trades that already have conflict scores')
    parser.add_argument('--verbose', action='store_true', help='Show Granite\'s streaming output in real-time')
    parser.add_argument('--skip-nulls', action='store_true', help='Skip trades with null party or state metadata')
    parser.add_argument('--sessions', action='store_true', help='Use session-based analysis (analyze groups of trades together)')
    args = parser.parse_args()

    
    logger.info("Starting AI Analysis Job")
    
    try:
        client = SupabaseClient(use_service_role=True)
        ollama = OllamaClient()
        postgres = PostgresClient()  # For storing analysis results
        
        if not ollama.check_health():
            logger.error("   [ERROR] Ollama is not accessible. Is it running?")
            sys.exit(1)
            
        # Step 1: Fix failed scores
        fix_failed_scores(client)
        
        if args.fix_only:
            logger.info("Fix-only mode enabled. Exiting.")
            sys.exit(0)
        
        total_processed = 0
        
        # Session-based analysis mode
        if args.sessions:
            from utils.session_manager import get_sessions_needing_analysis
            
            logger.info("SESSION MODE: Analyzing trade sessions (groups of related trades)")
            
            while True:
                # Use current total_processed as offset when rescoring to paginate through database
                offset = total_processed if args.rescore else 0
                sessions = get_sessions_needing_analysis(
                    postgres, 
                    limit=args.batch_size,
                    rescore=args.rescore,
                    offset=offset
                )
                
                if not sessions:
                    logger.info("   [DONE] No more sessions to analyze.")
                    break
                
                logger.info(f"Processing {len(sessions)} sessions...")
                
                for session in sessions:
                    # Increment before processing to ensure offset advances even on failure
                    total_processed += 1
                    
                    success = analyze_session(
                        ollama, postgres, client, 
                        session['id'], 
                        args.model,
                        verbose=args.verbose
                    )
                    
                    # Check limit
                    if args.limit > 0 and total_processed >= args.limit:
                        logger.info(f"Reached limit of {args.limit} sessions.")
                        break
                
                # Check limit (outer loop)
                if args.limit > 0 and total_processed >= args.limit:
                    break
            
            logger.info(f"Completed processing {total_processed} sessions.")
            return
        
        # Individual trade analysis mode (legacy)
        # Determine mode
        if args.rescore:
            logger.info("RESCORE MODE: Re-analyzing trades (allows multiple analyses)")
        else:
            logger.info("NORMAL MODE: Analyzing trades without analysis in current version")
        
        if args.skip_nulls:
            logger.info("SKIP NULLS: Only processing trades with complete metadata (party, state)")
        
        # Cursor-based pagination for rescore mode
        # Track the last processed (transaction_date, id) tuple to enable proper pagination
        last_cursor_date = None
        last_cursor_id = None
        
        while True:

            # Fetch trades based on mode
            if args.rescore:
                # Rescore mode: analyze ALL trades with cursor-based pagination
                # Use composite cursor (transaction_date, id) for deterministic ordering
                query = client.supabase.table("congress_trades_enriched").select("*")
                
                # Apply cursor filter if we have a previous cursor
                # For DESC ordering, we want trades that come AFTER the cursor
                # We fetch a larger batch to account for filtering, then take batch_size
                if last_cursor_date is not None:
                    # Convert to string format if it's a date/datetime object
                    if hasattr(last_cursor_date, 'isoformat'):
                        cursor_date_str = last_cursor_date.isoformat()
                    elif isinstance(last_cursor_date, str):
                        cursor_date_str = last_cursor_date
                    else:
                        cursor_date_str = str(last_cursor_date)
                    
                    # Fetch trades with date <= cursor date (we'll filter to get only those after cursor)
                    # Fetch 2x batch_size to ensure we have enough after filtering
                    query = query.lte("transaction_date", cursor_date_str)
                
            else:
                # Normal mode: only analyze trades not yet analyzed with this version
                # Get trade IDs that have been analyzed (from Postgres)
                analyzed_result = postgres.execute_query(
                    "SELECT trade_id FROM congress_trades_analysis WHERE model_used = %s AND analysis_version = %s",
                    (args.model, 1)
                )
                
                analyzed_ids = [row['trade_id'] for row in analyzed_result] if analyzed_result else []
                
                # Fetch trades NOT in the analyzed list
                query = client.supabase.table("congress_trades_enriched").select("*")
                if analyzed_ids:
                    query = query.not_.in_("id", analyzed_ids)
            
            # Skip trades with null metadata if requested
            if args.skip_nulls:
                query = query.not_.is_("party", "null").not_.is_("state", "null")
            
            # Order by transaction_date DESC, then id DESC for deterministic ordering
            # This ensures consistent pagination even when multiple trades have the same date
            # Fetch larger batch in rescore mode to account for cursor filtering
            fetch_limit = args.batch_size * 2 if args.rescore and last_cursor_date is not None else args.batch_size
            response = query\
                .order("transaction_date", desc=True)\
                .order("id", desc=True)\
                .limit(fetch_limit)\
                .execute()
            
            trades = response.data
            
            # Apply cursor filtering in Python for rescore mode
            # Filter out trades that come before or equal to the cursor
            if args.rescore and last_cursor_date is not None and last_cursor_id is not None and trades:
                from datetime import datetime
                # Parse cursor date for comparison
                if isinstance(last_cursor_date, str):
                    try:
                        cursor_date = datetime.fromisoformat(last_cursor_date.replace('Z', '+00:00'))
                    except:
                        cursor_date = None
                else:
                    cursor_date = last_cursor_date
                
                filtered_trades = []
                for trade in trades:
                    trade_date = trade.get('transaction_date')
                    trade_id = trade.get('id')
                    
                    # Parse trade date for comparison
                    if isinstance(trade_date, str):
                        try:
                            trade_date_parsed = datetime.fromisoformat(trade_date.replace('Z', '+00:00'))
                        except:
                            trade_date_parsed = None
                    else:
                        trade_date_parsed = trade_date
                    
                    # Include trade if:
                    # 1. transaction_date < cursor_date, OR
                    # 2. transaction_date == cursor_date AND id < cursor_id
                    if trade_date_parsed and cursor_date:
                        if trade_date_parsed < cursor_date:
                            filtered_trades.append(trade)
                        elif trade_date_parsed == cursor_date and trade_id and trade_id < last_cursor_id:
                            filtered_trades.append(trade)
                    elif not trade_date_parsed:
                        # Include trades with null dates (shouldn't happen, but be safe)
                        filtered_trades.append(trade)
                
                trades = filtered_trades[:args.batch_size]  # Take only batch_size after filtering
            
            if not trades:
                logger.info("   [DONE] No more trades found.")
                break
                
            logger.info(f"Processing batch of {len(trades)} trades...")
            
            # Update cursor for next iteration (use the last trade in the batch)
            if args.rescore and trades:
                last_trade = trades[-1]
                last_cursor_date = last_trade.get('transaction_date')
                last_cursor_id = last_trade.get('id')
                last_cursor_id = last_trade.get('id')
                logger.info(f"   [CURSOR] Updated to: date={last_cursor_date}, id={last_cursor_id} (processed {len(trades)} trades in this batch)")
            
            for trade in trades:
                try:
                    # Enrich
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
                        # Analyze with AI
                        analysis = analyze_trade(ollama, context, args.model, verbose=args.verbose)
                    
                    if analysis and 'conflict_score' in analysis:
                        score = float(analysis['conflict_score'])
                        confidence = float(analysis.get('confidence_score', 0.75))  # Default to 0.75 if missing
                        reasoning = analysis.get('reasoning', 'No reasoning provided')
                        
                        # Save to postgres analysis table (separate database to save Supabase costs)
                        try:
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
                                (trade['id'], score, confidence, reasoning, args.model, 1)
                            )
                            logger.info(f"   [SCORED] conflict={score:.2f}, confidence={confidence:.2f}")
                            total_processed += 1
                        except Exception as db_error:
                            logger.error(f"   [ERROR] Failed to save analysis to Postgres: {db_error}")
                            
                    else:
                        logger.warning(f"   [WARN] Failed to parse AI response for ID {trade['id']}")
                        # We do NOT update the record, so it stays NULL and can be retried.
                        # Optionally, we could set a "failed_attempts" counter if we had one.
                        
                except Exception as e:
                    logger.error(f"Error processing trade {trade['id']}: {e}")
            
            # Clear caches after batch to avoid stale data
            _politician_cache.clear()
            _sector_cache.clear()
            logger.info(f"Cleared caches after batch (processed {total_processed} total)")
            
            # Check limit
            if args.limit > 0 and total_processed >= args.limit:
                logger.info(f"Reached limit of {args.limit} trades.")
                break
            
            # Small delay between batches
            time.sleep(1)
            
        logger.info(f"Job complete. Processed {total_processed} trades.")
        
    except Exception as e:
        logger.error(f"Critical error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
