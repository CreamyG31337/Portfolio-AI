"""
Insider Trades Jobs
===================

Jobs for fetching corporate insider trading data from an external source.
Uses FlareSolverr to bypass Cloudflare protection.
"""

import ast
import logging
import time
import requests
import os
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

from web_fetch_client import fetch_page_via_flaresolverr, get_web_fetch_client

_INSIDER_DATA_VAR_NAMES = (
    "recentInsiderTransactionsData",
    "topMonthlyInsiderTransactionsData",
)


def _get_insider_source_url() -> str:
    url = os.getenv("INSIDER_TRADES_BASE_URL", "").strip()
    if url:
        return url
    try:
        return base64.b64decode(
            os.getenv("INSIDER_TRADES_SOURCE_ENCODED", "aHR0cHM6Ly93d3cucXVpdmVycXVhbnQuY29tL2luc2lkZXJzLw==")
        ).decode("utf-8")
    except Exception:
        return ""


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


def _extract_bracketed_array(script_content: str, var_name: str) -> Optional[str]:
    """Extract a bracket-balanced array literal assigned to ``var_name``."""
    marker = f"{var_name} ="
    idx = script_content.find(marker)
    if idx < 0:
        return None
    start = script_content.find("[", idx)
    if start < 0:
        return None
    depth = 0
    for pos in range(start, len(script_content)):
        char = script_content[pos]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return script_content[start : pos + 1]
    return None


def _parse_insider_trades_from_html(html_content: str) -> List[Dict[str, Any]]:
    """Parse embedded insider trade rows from the source page HTML."""
    soup = BeautifulSoup(html_content, "html.parser")
    for script in soup.find_all("script", src=False):
        if not script.string:
            continue
        script_content = script.string
        for var_name in _INSIDER_DATA_VAR_NAMES:
            if var_name not in script_content:
                continue
            array_literal = _extract_bracketed_array(script_content, var_name)
            if not array_literal:
                logger.debug("Could not extract array for %s", var_name)
                continue
            try:
                trades_data = ast.literal_eval(array_literal)
            except (ValueError, SyntaxError) as parse_error:
                logger.warning("Failed to parse %s: %s", var_name, parse_error)
                continue
            if isinstance(trades_data, list) and trades_data:
                logger.info("Found %d trades in %s", len(trades_data), var_name)
                return trades_data
    return []


def _fetch_insider_trades_from_source(url: str) -> tuple[List[Dict[str, Any]], str]:
    """Fetch source HTML and parse trades. Retries with direct HTTP if FlareSolverr HTML is unusable."""
    html_content = fetch_page_via_flaresolverr(url)
    if html_content:
        trades_data = _parse_insider_trades_from_html(html_content)
        if trades_data:
            return trades_data, "flaresolverr"
        logger.warning(
            "FlareSolverr returned HTML but no insider trades data; trying direct fetch..."
        )

    try:
        html_content = get_web_fetch_client().fetch_direct_html(url)
    except requests.exceptions.RequestException as direct_error:
        logger.warning("Direct fetch failed for insider source: %s", direct_error)
        return [], "none"

    trades_data = _parse_insider_trades_from_html(html_content)
    if trades_data:
        return trades_data, "direct"
    return [], "none"


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
        source_url = _get_insider_source_url()
        if not source_url:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "INSIDER_TRADES_BASE_URL (or INSIDER_TRADES_SOURCE_ENCODED) not set"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            return
        try:
            from robots_utils import is_robots_enforced, check_or_raise
            if is_robots_enforced():
                check_or_raise(job_id, [source_url])
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
            try:
                mark_job_failed('insider_trades', target_date, None, message, duration_ms=duration_ms)
            except Exception:
                pass
            return

        # Initialize client
        supabase_client = SupabaseClient(use_service_role=True)

        # Date filter: 0 = no filter (backfill all from page); otherwise only trades within last N days
        try:
            days_filter = int(os.getenv("INSIDER_TRADES_DAYS", "7"))
        except ValueError:
            days_filter = 7
        if days_filter <= 0:
            cutoff_date = None  # no date filter: process all trades from source (backfill)
            logger.info("INSIDER_TRADES_DAYS=0: backfill mode, ingesting all trades from page (no date filter)")
        else:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_filter)
            logger.info(f"Only ingesting trades from last {days_filter} days (set INSIDER_TRADES_DAYS=0 for one-time backfill)")

        # Track statistics
        total_trades_found = 0
        new_trades = 0
        skipped_duplicates = 0
        skipped_old = 0
        errors = 0

        url = source_url
        try:
            logger.info("Fetching insider trades from source...")
            trades_data, fetch_method = _fetch_insider_trades_from_source(url)
            if trades_data:
                logger.info("Loaded insider trades via %s", fetch_method)

            if not trades_data:
                logger.warning("No embedded insider trades data found on page")
                duration_ms = int((time.time() - start_time) * 1000)
                message = "No insider trades data found on source page"
                log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
                mark_job_failed('insider_trades', target_date, None, message, duration_ms=duration_ms)
                return

            # Polite scraping: when up to date, only process first N rows (source is newest-first).
            # When behind (newest in DB older than catch-up threshold), process all to catch up.
            default_recent_rows = 300
            try:
                catch_up_days = int(os.getenv("INSIDER_TRADES_CATCH_UP_DAYS", "7"))
            except ValueError:
                catch_up_days = 7
            try:
                max_rows_env = os.getenv("INSIDER_TRADES_MAX_ROWS", "").strip()
                max_rows_override = int(max_rows_env) if max_rows_env else None
            except ValueError:
                max_rows_override = None

            newest_in_db = None
            try:
                r = (
                    supabase_client.supabase.table("insider_trades")
                    .select("transaction_date")
                    .order("transaction_date", desc=True)
                    .limit(1)
                    .execute()
                )
                if r.data and r.data[0].get("transaction_date"):
                    newest_in_db = r.data[0]["transaction_date"]
                    if hasattr(newest_in_db, "date"):
                        newest_in_db = newest_in_db.date()
                    elif isinstance(newest_in_db, str):
                        newest_in_db = datetime.strptime(newest_in_db[:10], "%Y-%m-%d").date()
            except Exception as e:
                logger.debug(f"Could not get newest transaction_date: {e}")

            now_date = datetime.now(timezone.utc).date()
            days_since_newest = (
                (now_date - newest_in_db).days if newest_in_db else 999
            )
            if max_rows_override == 0:
                logger.info("INSIDER_TRADES_MAX_ROWS=0: processing all trades from source")
            elif days_since_newest >= catch_up_days:
                logger.info(
                    f"Newest trade in DB is {days_since_newest} days old (threshold={catch_up_days}): "
                    f"processing all {len(trades_data)} trades (catch-up)"
                )
            elif len(trades_data) > default_recent_rows:
                n = max_rows_override if max_rows_override and max_rows_override > 0 else default_recent_rows
                trades_data = trades_data[:n]
                logger.info(
                    f"Up to date (newest {days_since_newest}d ago): processing first {n} trades only"
                )

            # Process the extracted trades data
            # Data structure from the source page (expected keys):
            # rptOwnerName, officerTitle, issuerTradingSymbol, transactionCode, transactionShares,
            # transactionPricePerShare, transactionDate, fileDate, rptOwnerCik, transactionValue
            # Log first trade keys so we can verify source shape when names are missing
            if trades_data:
                first_keys = list(trades_data[0].keys()) if isinstance(trades_data[0], dict) else []
                logger.info(f"First raw trade keys from source: {first_keys}")

            logger.info(f"Processing {len(trades_data)} insider trades...")

            trades_to_upsert = []
            for trade_data in trades_data:
                try:
                    total_trades_found += 1

                    # Extract data from trade object
                    ticker = trade_data.get('issuerTradingSymbol', '').strip().upper()
                    if not ticker:
                        continue

                    # Insider name: try primary and fallback keys (source may use different names)
                    insider_name = (
                        trade_data.get('rptOwnerName') or
                        trade_data.get('reportingOwnerName') or
                        trade_data.get('ownerName') or
                        trade_data.get('name') or
                        ''
                    )
                    if isinstance(insider_name, str):
                        insider_name = insider_name.strip()
                    else:
                        insider_name = str(insider_name).strip() if insider_name is not None else ''
                    if not insider_name:
                        logger.warning(
                            f"Insider name missing for ticker {ticker}, raw keys: {list(trade_data.keys()) if isinstance(trade_data, dict) else 'n/a'}"
                        )
                        insider_name = "Unknown"

                    # Title: source uses '-' when missing; store '' so DB never has NULL (every trade has a person)
                    insider_title = trade_data.get('officerTitle', '-') or '-'
                    if isinstance(insider_title, str):
                        insider_title = insider_title.strip()
                    else:
                        insider_title = str(insider_title).strip() if insider_title is not None else ''
                    if insider_title == '-' or not insider_title:
                        insider_title = ''

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

                    # Skip trades older than cutoff (when date filter is enabled)
                    if cutoff_date is not None and transaction_date < cutoff_date.date():
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
                        'source': 'sec_form4',
                    }

                    # ⚡ Bolt: Accumulate trades to perform a batched upsert, avoiding per-row queries
                    trades_to_upsert.append(trade_record)

                except Exception as trade_error:
                    errors += 1
                    logger.warning(f"Error processing trade: {trade_error}")
                    continue

            # ⚡ Bolt: Perform batched upsert after loop finishes for this chunk
            if trades_to_upsert:
                try:
                    result = supabase_client.supabase.table("insider_trades")\
                        .upsert(
                            trades_to_upsert,
                            on_conflict="ticker,insider_name,transaction_date,type,shares,price_per_share"
                        )\
                        .execute()

                    if result.data:
                        new_trades += len(result.data)
                        logger.debug(f"✅ Saved {len(result.data)} insider trades in batch")
                except Exception as insert_error:
                    errors += 1
                    logger.error(f"Failed to batched insert insider trades: {insert_error}")

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
        mark_job_completed('insider_trades', target_date, None, [], duration_ms=duration_ms, message=message)
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
