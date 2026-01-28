"""
Insider Trades Jobs
===================

Jobs for fetching corporate insider trading data from an external source.
Uses FlareSolverr to bypass Cloudflare protection.
"""

import logging
import time
import requests
import os
import json
import base64
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup
import re

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

# FlareSolverr URL (for bypassing Cloudflare)
FLARESOLVERR_URL = os.getenv("FLARESOLVERR_URL", "http://localhost:8191")

# Insider trades source URL 
_INSIDER_SOURCE_URL_ENCODED = "aHR0cHM6Ly93d3cucXVpdmVycXVhbnQuY29tL2luc2lkZXJzLw=="
_INSIDER_SOURCE_URL = base64.b64decode(_INSIDER_SOURCE_URL_ENCODED).decode('utf-8')


def fetch_page_via_flaresolverr(url: str) -> Optional[str]:
    """Fetch a page using FlareSolverr to bypass Cloudflare protection."""
    try:
        flaresolverr_endpoint = f"{FLARESOLVERR_URL}/v1"
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": 60000
        }

        logger.debug(f"Requesting via FlareSolverr: {url}")
        response = requests.post(
            flaresolverr_endpoint,
            json=payload,
            timeout=90
        )
        response.raise_for_status()

        data = response.json()

        if data.get("status") != "ok":
            error_msg = data.get("message", "Unknown error")
            logger.warning(f"FlareSolverr returned error: {error_msg}")
            return None

        solution = data.get("solution", {})
        if not solution:
            logger.warning("FlareSolverr response missing solution")
            return None

        return solution.get("response")

    except requests.exceptions.ConnectionError:
        logger.warning(f"FlareSolverr unavailable at {FLARESOLVERR_URL}")
        return None
    except requests.exceptions.Timeout:
        logger.warning("FlareSolverr request timed out")
        return None
    except Exception as e:
        logger.warning(f"FlareSolverr request failed: {e}")
        return None


def parse_value(value_str: str) -> Optional[float]:
    """Parse monetary value from string like '$1.2M' or '$500K'.

    Args:
        value_str: String representation of value (e.g., '$1.2M', '$500K', '$1,234')

    Returns:
        Float value in dollars, or None if parsing fails
    """
    if not value_str:
        return None

    try:
        # Remove $ and commas
        clean_str = value_str.replace('$', '').replace(',', '').strip()

        # Handle K (thousands) and M (millions)
        multiplier = 1
        if clean_str.endswith('K'):
            multiplier = 1000
            clean_str = clean_str[:-1]
        elif clean_str.endswith('M'):
            multiplier = 1000000
            clean_str = clean_str[:-1]
        elif clean_str.endswith('B'):
            multiplier = 1000000000
            clean_str = clean_str[:-1]

        return float(clean_str) * multiplier
    except (ValueError, AttributeError):
        return None


def parse_shares(shares_str: str) -> Optional[int]:
    """Parse number of shares from string.

    Args:
        shares_str: String representation of shares (e.g., '1,000' or '500K')

    Returns:
        Integer number of shares, or None if parsing fails
    """
    if not shares_str:
        return None

    try:
        # Remove commas
        clean_str = shares_str.replace(',', '').strip()

        # Handle K (thousands) and M (millions)
        multiplier = 1
        if clean_str.endswith('K'):
            multiplier = 1000
            clean_str = clean_str[:-1]
        elif clean_str.endswith('M'):
            multiplier = 1000000
            clean_str = clean_str[:-1]

        return int(float(clean_str) * multiplier)
    except (ValueError, AttributeError):
        return None


def fetch_insider_trades_job() -> None:
    """Fetch corporate insider trades from an external source.

    This job:
    1. Scrapes insider trading data from the source website
    2. Parses transaction details (name, title, ticker, shares, value, etc.)
    3. Checks for duplicates before processing
    4. Saves trades to Supabase insider_trades table

    Note: The source site displays insider trades from SEC disclosures (Form 4).
    Corporate insiders are required to disclose trades within two business days.
    
    Robots.txt enforcement: Controlled by ENABLE_ROBOTS_TXT_CHECKS environment variable.
    When enabled, checks robots.txt before accessing the insider trades source website.
    """
    job_id = 'insider_trades'
    start_time = time.time()

    try:
        # Check robots.txt compliance (if enabled)
        try:
            from robots_utils import is_robots_enforced, check_or_raise
            if is_robots_enforced():
                # Check representative domain for insider trades source
                # Note: Actual URL is obfuscated using base64 encoding
                representative_urls = [
                    _INSIDER_SOURCE_URL,  # Insider trades source
                ]
                check_or_raise(job_id, representative_urls)
        except ImportError:
            # robots_utils not available, skip check
            pass
        
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

        logger.info("Starting insider trades job...")

        # Mark job as started
        target_date = datetime.now(timezone.utc).date()
        mark_job_started('insider_trades', target_date)

        # Import dependencies (lazy imports)
        try:
            from supabase_client import SupabaseClient
        except ImportError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Missing dependency: {e}"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            return

        # Initialize client
        supabase_client = SupabaseClient(use_service_role=True)

        # Calculate cutoff date (7 days ago)
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=7)

        # Track statistics
        total_trades_found = 0
        new_trades = 0
        skipped_duplicates = 0
        skipped_old = 0
        errors = 0

        # Scrape insider trades page
        url = _INSIDER_SOURCE_URL

        try:
            logger.info(f"Fetching insider trades from {url}...")

            # Try FlareSolverr first
            html_content = fetch_page_via_flaresolverr(url)

            if not html_content:
                logger.warning("FlareSolverr failed or unavailable, trying direct request...")
                # Fallback to direct request
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Connection': 'keep-alive',
                }
                response = requests.get(url, headers=headers, timeout=30)
                response.raise_for_status()
                html_content = response.text

            # Parse HTML with BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')

            # Look for embedded data in script tags
            # The source page embeds insider trades as JavaScript variables
            inline_scripts = soup.find_all('script', src=False)
            trades_data = []

            for script in inline_scripts:
                if not script.string:
                    continue

                script_content = script.string

                # Look for recentInsiderTransactionsData variable
                if 'recentInsiderTransactionsData' in script_content or 'topMonthlyInsiderTransactionsData' in script_content:
                    logger.debug("Found insider transactions data in script")

                    # Extract the JavaScript array
                    # Pattern: let recentInsiderTransactionsData = [{...}, {...}];
                    match = re.search(r'(?:recentInsiderTransactionsData|topMonthlyInsiderTransactionsData)\s*=\s*(\[.+?\]);', script_content, re.DOTALL)

                    if match:
                        json_str = match.group(1)
                        try:
                            # Convert JavaScript to valid JSON (replace single quotes with double quotes if needed)
                            # The source uses Python dict notation which is valid JS but not JSON
                            json_str_fixed = json_str.replace("'", '"').replace('True', 'true').replace('False', 'false').replace('None', 'null')
                            trades_data = json.loads(json_str_fixed)
                            logger.info(f"Found {len(trades_data)} trades in embedded data")
                            break
                        except json.JSONDecodeError as e:
                            logger.warning(f"Failed to parse embedded data: {e}")
                            # Try eval as fallback (safe since it's from the source page)
                            try:
                                trades_data = eval(json_str)
                                logger.info(f"Found {len(trades_data)} trades using eval")
                                break
                            except Exception as eval_error:
                                logger.warning(f"eval also failed: {eval_error}")
                                continue

            if not trades_data:
                logger.warning("No embedded insider trades data found on page")
                duration_ms = int((time.time() - start_time) * 1000)
                message = "No insider trades data found on source page"
                log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
                mark_job_failed('insider_trades', target_date, None, message, duration_ms=duration_ms)
                return

            # Process the extracted trades data
            # Data structure from the source page:
            # {'rptOwnerName': 'NAME', 'officerTitle': 'TITLE', 'issuerTradingSymbol': 'TICKER',
            #  'transactionCode': 'Purchase/Sale', 'transactionShares': 123, 'transactionPricePerShare': 1.23,
            #  'transactionDate': 'Jan 21, 2026', 'fileDate': 'Jan 23, 2026 (10:52 PM)',
            #  'rptOwnerCik': 1234567, 'transactionValue': 1234.56}

            logger.info(f"Processing {len(trades_data)} insider trades...")

            for trade_data in trades_data:
                try:
                    total_trades_found += 1

                    # Extract data from trade object
                    ticker = trade_data.get('issuerTradingSymbol', '').strip().upper()
                    if not ticker:
                        continue

                    insider_name = trade_data.get('rptOwnerName', '').strip()
                    insider_title = trade_data.get('officerTitle', '-').strip()
                    if insider_title == '-':
                        insider_title = None

                    # Get transaction type
                    trade_type = trade_data.get('transactionCode', '').strip()
                    if 'purchase' in trade_type.lower() or 'buy' in trade_type.lower():
                        trade_type = 'Purchase'
                    elif 'sale' in trade_type.lower() or 'sell' in trade_type.lower():
                        trade_type = 'Sale'
                    else:
                        trade_type = trade_type.title() if trade_type else 'Unknown'

                    # Get numeric values (already in correct format from the source page)
                    value = trade_data.get('transactionValue')
                    shares = trade_data.get('transactionShares')
                    price_per_share = trade_data.get('transactionPricePerShare')

                    # Get dates
                    date_str = trade_data.get('transactionDate', '')
                    disclosed_str = trade_data.get('fileDate', '')

                    # Parse transaction date (format: "Jan 21, 2026")
                    transaction_date = None
                    if date_str:
                        try:
                            transaction_date = datetime.strptime(date_str, '%b %d, %Y').date()
                        except ValueError:
                            # Try other formats
                            for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%B %d, %Y']:
                                try:
                                    transaction_date = datetime.strptime(date_str, fmt).date()
                                    break
                                except ValueError:
                                    continue

                    if not transaction_date:
                        logger.debug(f"Could not parse transaction date: {date_str}")
                        continue

                    # Check if transaction is too old
                    if transaction_date < cutoff_date.date():
                        skipped_old += 1
                        continue

                    # Parse disclosure date (format: "Jan 23, 2026 (10:52 PM)")
                    disclosure_date = None
                    if disclosed_str:
                        try:
                            # Remove time portion in parentheses
                            disclosed_clean = re.sub(r'\s*\([^)]+\)', '', disclosed_str)
                            disclosure_date = datetime.strptime(disclosed_clean.strip(), '%b %d, %Y')
                        except ValueError:
                            # Try other formats
                            for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%B %d, %Y']:
                                try:
                                    disclosure_date = datetime.strptime(disclosed_clean, fmt)
                                    break
                                except (ValueError, NameError):
                                    continue

                    # Default to transaction date if disclosure date not available
                    if not disclosure_date:
                        disclosure_date = datetime.combine(transaction_date, datetime.min.time())

                    # Check for duplicate
                    try:
                        existing = supabase_client.supabase.table("insider_trades")\
                            .select("id")\
                            .eq("ticker", ticker)\
                            .eq("insider_name", insider_name)\
                            .eq("transaction_date", transaction_date.isoformat())\
                            .eq("type", trade_type)\
                            .maybe_single()\
                            .execute()

                        if existing and existing.data:
                            skipped_duplicates += 1
                            continue
                    except Exception as dup_check_error:
                        # Skip duplicate check if it fails - upsert will handle duplicates
                        logger.debug(f"Duplicate check skipped (will use upsert): {dup_check_error}")
                        pass

                    # Prepare trade record
                    trade_record = {
                        'ticker': ticker,
                        'insider_name': insider_name,
                        'insider_title': insider_title,
                        'transaction_date': transaction_date.isoformat(),
                        'disclosure_date': disclosure_date.isoformat(),
                        'type': trade_type,
                        'shares': shares,
                        'price_per_share': float(price_per_share) if price_per_share else None,
                        'value': float(value) if value else None,
                    }

                    # Insert to Supabase (use upsert to handle duplicates)
                    try:
                        result = supabase_client.supabase.table("insider_trades")\
                            .upsert(
                                trade_record,
                                on_conflict="ticker,insider_name,transaction_date,type,shares,price_per_share"
                            )\
                            .execute()

                        if result.data:
                            new_trades += 1
                            logger.debug(f"✅ Saved trade: {insider_name} {trade_type} {shares} shares of {ticker} @ ${price_per_share}")
                        else:
                            skipped_duplicates += 1
                    except Exception as insert_error:
                        errors += 1
                        logger.error(f"Failed to insert trade for {insider_name} {ticker}: {insert_error}")
                        continue

                except Exception as trade_error:
                    errors += 1
                    logger.warning(f"Error processing trade: {trade_error}")
                    continue

        except requests.exceptions.HTTPError as http_error:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"HTTP error: {http_error}"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            mark_job_failed('insider_trades', target_date, None, message, duration_ms=duration_ms)
            return
        except requests.exceptions.RequestException as req_error:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Request error: {req_error}"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            mark_job_failed('insider_trades', target_date, None, message, duration_ms=duration_ms)
            return

        # Log completion
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Found {total_trades_found} trades: {new_trades} new, {skipped_duplicates} duplicates, {skipped_old} old, {errors} errors"
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        mark_job_completed('insider_trades', target_date, None, [], duration_ms=duration_ms)
        logger.info(f"✅ Insider trades job completed: {message} in {duration_ms/1000:.2f}s")

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Error: {str(e)}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        try:
            mark_job_failed('insider_trades', target_date, None, str(e), duration_ms=duration_ms)
        except Exception:
            pass
        logger.error(f"❌ Insider trades job failed: {e}", exc_info=True)
