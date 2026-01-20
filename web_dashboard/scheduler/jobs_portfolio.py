"""
Portfolio Price Update Jobs
============================

Jobs for updating portfolio positions with current market prices.
"""

import logging
import time
import threading
from datetime import datetime, timedelta, date, time as dt_time
from typing import Optional
from decimal import Decimal
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

# Add parent directory to path if needed (standard boilerplate for these jobs)
import sys
from pathlib import Path

# Add project root to path for utils imports
current_dir = Path(__file__).resolve().parent
if current_dir.name == 'scheduler':
    project_root = current_dir.parent.parent
else:
    project_root = current_dir.parent.parent

# Also ensure web_dashboard is in path for supabase_client imports
web_dashboard_path = str(Path(__file__).resolve().parent.parent)
if web_dashboard_path not in sys.path:
    sys.path.insert(0, web_dashboard_path)

# CRITICAL: Project root must be inserted LAST (at index 0) to ensure it comes
# BEFORE web_dashboard in sys.path. This prevents web_dashboard/utils from
# shadowing the project root's utils package.
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
elif sys.path[0] != str(project_root):
    # If it is in path but not first, move it to front
    sys.path.remove(str(project_root))
    sys.path.insert(0, str(project_root))

from scheduler.scheduler_core import log_job_execution

# Initialize logger
logger = logging.getLogger(__name__)

# Lazy import helper for exchange rates (imported inside functions to avoid scheduler crashes)
def _get_exchange_rate_for_date(date_obj, from_curr, to_curr):
    """Lazy import wrapper for exchange rate function."""
    try:
        from exchange_rates_utils import get_exchange_rate_for_date_from_db
        return get_exchange_rate_for_date_from_db(date_obj, from_curr, to_curr)
    except ImportError as e:
        logger.error(f"Failed to import exchange_rates_utils: {e}")
        return None

# Thread-safe lock to prevent concurrent execution
# A simple boolean was causing race conditions when backfill and scheduled jobs ran simultaneously
_update_prices_lock = threading.Lock()


def _log_portfolio_job_progress(fund_name: str, message: str, success: bool = True):
    """Log portfolio job progress to both scheduler logs and Application Logs.
    
    This ensures visibility in both:
    - Scheduler execution logs (in-memory, for recent job history)
    - Application Logs (file-based, visible in Admin → System → Application Logs)
    
    Args:
        fund_name: Fund being processed
        message: Progress message
        success: Whether this is a success (INFO) or failure (ERROR) message
    """
    # Log to scheduler execution logs
    try:
        job_id = f'portfolio_update_{fund_name.replace(" ", "_")}'
        log_job_execution(job_id, success, message, 0)
    except Exception:
        pass  # Silently ignore if not available
    
    # Log to Application Logs (file-based, visible in web UI)
    try:
        from log_handler import log_message
        level = 'ERROR' if not success else 'INFO'
        log_message(f"[Portfolio Update - {fund_name}] {message}", level=level)
    except Exception:
        pass  # Silently ignore if not available


def _ensure_sys_path_setup() -> None:
    """Ensure project root and web_dashboard are in sys.path for imports.
    
    This must be called at the start of any function that imports utils modules.
    Safe to call multiple times - idempotent.
    """
    try:
        # Use print as fallback - always works even if logging is broken
        print(f"[{__name__}] _ensure_sys_path_setup() called")
        try:
            logger.debug("_ensure_sys_path_setup() called")
        except:
            pass  # Logger might not be ready
        
        import sys
        from pathlib import Path
        
        # Safely get __file__ - it might not be available in all contexts
        try:
            current_file = __file__
            print(f"[{__name__}] Using __file__: {current_file}")
        except NameError:
            # __file__ not available - use module location as fallback
            print(f"[{__name__}] WARNING: __file__ not available")
            try:
                logger.warning("Warning: __file__ not available, using module path")
            except:
                pass
            import os
            current_file = os.path.abspath(__file__ if '__file__' in globals() else 'jobs_portfolio.py')
        
        # Get absolute path to project root
        # __file__ is scheduler/jobs_portfolio.py
        # parent is scheduler/, parent.parent is web_dashboard/, parent.parent.parent is project root
        try:
            project_root = Path(current_file).resolve().parent.parent.parent
            project_root_str = str(project_root)
            print(f"[{__name__}] Project root: {project_root_str}")
        except Exception as path_error:
            print(f"[{__name__}] ERROR: Failed to resolve project root: {path_error}")
            try:
                logger.warning(f"Warning: Failed to resolve project root path: {path_error}")
            except:
                pass
            return  # Can't proceed without valid path
        
        # CRITICAL: Project root must be FIRST in sys.path to ensure utils.job_tracking
        # is found from the project root, not from web_dashboard/utils
        if project_root_str not in sys.path:
            sys.path.insert(0, project_root_str)
            print(f"[{__name__}] Added project root to sys.path[0]")
        elif sys.path[0] != project_root_str:
            # If it is in path but not first, move it to front
            try:
                sys.path.remove(project_root_str)
            except ValueError:
                # Item not in list - shouldn't happen but handle gracefully
                pass
            sys.path.insert(0, project_root_str)
            print(f"[{__name__}] Moved project root to sys.path[0]")
        
        # Also ensure web_dashboard is in path for supabase_client imports
        # (but AFTER project root so it doesn't shadow utils)
        try:
            web_dashboard_path = str(Path(current_file).resolve().parent.parent)
            if web_dashboard_path not in sys.path:
                # Insert at index 1, after project_root (or at 0 if project_root wasn't added)
                insert_index = 1 if project_root_str in sys.path and sys.path[0] == project_root_str else 0
                sys.path.insert(insert_index, web_dashboard_path)
                print(f"[{__name__}] Added web_dashboard to sys.path[{insert_index}]")
        except Exception as path_error:
            print(f"[{__name__}] WARNING: Failed to resolve web_dashboard path: {path_error}")
            try:
                logger.warning(f"Warning: Failed to resolve web_dashboard path: {path_error}")
            except:
                pass
            # Continue - project_root is more important
    except Exception as e:
        # Don't let path setup failures crash the job - log and continue
        # The top-level path setup should have already handled this
        print(f"[{__name__}] CRITICAL ERROR in _ensure_sys_path_setup: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        try:
            logger.warning(f"Warning: Failed to ensure sys.path setup: {e}", exc_info=True)
        except:
            pass  # Even logging failed


def update_portfolio_prices_job(
    target_date: Optional[date] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    use_date_range: bool = False
) -> None:
    """Update portfolio positions with current market prices for a specific date or date range.
    
    Args:
        target_date: Single date to update. If None, auto-determines (today or last trading day).
        from_date: Start date for range (only used if use_date_range is True).
        to_date: End date for range (only used if use_date_range is True).
        use_date_range: If True, process date range from from_date to to_date instead of single target_date.
    
    This job:
    1. Gets current positions from the latest snapshot (or rebuilds from trade log)
    2. Fetches current market prices for all positions
    3. Updates only the target date's snapshot
    4. Does NOT delete any historical data
    
    Based on logic from debug/rebuild_portfolio_complete.py but modified to:
    - Only update current/last day (or specified date)
    - Not wipe historical data
    - Work with Supabase directly
    
    Safety Features:
    - Prevents concurrent execution (thread-safe lock + APScheduler max_instances=1)
    - Atomic delete+insert per fund (all or nothing)
    - Skips failed tickers but continues with successful ones
    - Handles partial failures gracefully
    """
    # IMMEDIATE logging - use print() as fallback since it always works
    import sys
    print(f"[{__name__}] update_portfolio_prices_job() STARTED", file=sys.stderr, flush=True)
    try:
        logger.info("update_portfolio_prices_job() started")
    except:
        pass  # Logger might not be ready yet
    
    # Initialize variables that finally block needs (before any try blocks)
    is_date_range_mode = use_date_range and from_date and to_date if (use_date_range and from_date and to_date) else False
    lock_acquired = False  # Track if we actually acquired the lock
    
    # Wrap everything in try/except to prevent scheduler crashes
    try:
        print(f"[{__name__}] Setting up sys.path...", file=sys.stderr, flush=True)
        # CRITICAL: Ensure sys.path is set up FIRST, before any imports
        _ensure_sys_path_setup()
        print(f"[{__name__}] sys.path setup complete", file=sys.stderr, flush=True)
        
        # Initialize job tracking first (before lock check so we can log lock failures)
        job_id = 'update_portfolio_prices'
        start_time = time.time()
        print(f"[{__name__}] Job ID: {job_id}, start_time: {start_time}", file=sys.stderr, flush=True)
        
        # Check if this is date range mode - if so, we'll handle it differently (backfill function has its own lock)
        is_date_range_mode = use_date_range and from_date and to_date
        
        # Acquire lock with non-blocking check - if another thread is already running, skip
        # Skip lock for date range mode since backfill_portfolio_prices_range has its own lock
        if not is_date_range_mode:
            acquired = _update_prices_lock.acquire(blocking=False)
            lock_acquired = acquired
            if not acquired:
                duration_ms = int((time.time() - start_time) * 1000)
                message = "Job already running - skipped (lock not acquired)"
                # Log as failed to indicate this was a skipped execution, not a successful run
                log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
                # Also mark in database as failed with clear skipped message
                try:
                    from utils.job_tracking import mark_job_failed
                    fallback_date = date.today() if target_date is None else target_date
                    mark_job_failed('update_portfolio_prices', fallback_date, None, message, duration_ms=duration_ms)
                except Exception:
                    pass  # Don't fail if tracking fails
                logger.warning(f"⚠️ {message}")
                return
        
        try:
            # Import dependencies (after sys.path is set up)
            from market_data.data_fetcher import MarketDataFetcher
            from market_data.price_cache import PriceCache
            from market_data.market_hours import MarketHours
            from utils.market_holidays import MarketHolidays
            from supabase_client import SupabaseClient
            from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
            
            # Initialize components
            market_fetcher = MarketDataFetcher()
            
            # Create Settings with data_dir to avoid "No data directory" error
            from config.settings import Settings
            cache_settings = Settings()
            # Set data directory explicitly in config
            cache_settings.set('repository.csv.data_directory', str(Path.home() / '.trading_bot_cache'))
            price_cache = PriceCache(settings=cache_settings)
            
            market_hours = MarketHours()
            market_holidays = MarketHolidays()
            # Use service role key to bypass RLS (background job needs full access)
            client = SupabaseClient(use_service_role=True)
            
            # Handle date range mode
            if use_date_range and from_date and to_date:
                # Date range mode - use optimized backfill function
                if from_date > to_date:
                    duration_ms = int((time.time() - start_time) * 1000)
                    message = f"Invalid date range: from_date ({from_date}) must be <= to_date ({to_date})"
                    log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
                    try:
                        mark_job_failed('update_portfolio_prices', from_date, None, message, duration_ms=duration_ms)
                    except Exception:
                        pass
                    logger.error(f"❌ {message}")
                    return
                
                # Warn if range is large
                days_in_range = (to_date - from_date).days + 1
                if days_in_range > 30:
                    logger.warning(f"⚠️ Processing large date range: {days_in_range} days ({from_date} to {to_date}). This may take a while.")
                
                logger.info(f"Starting portfolio price update job in date range mode: {from_date} to {to_date}")
                
                # Use the optimized backfill function for date ranges
                try:
                    backfill_portfolio_prices_range(from_date, to_date)
                    duration_ms = int((time.time() - start_time) * 1000)
                    message = f"Updated prices for date range {from_date} to {to_date} ({days_in_range} day(s))"
                    log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
                    mark_job_completed('update_portfolio_prices', to_date, None, [], duration_ms=duration_ms, message=message)
                    logger.info(f"✅ {message}")
                except Exception as e:
                    duration_ms = int((time.time() - start_time) * 1000)
                    message = f"Error processing date range: {str(e)}"
                    log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
                    try:
                        mark_job_failed('update_portfolio_prices', from_date, None, message, duration_ms=duration_ms)
                    except Exception:
                        pass
                    logger.error(f"❌ {message}", exc_info=True)
                # Note: backfill_portfolio_prices_range manages its own lock, so we don't release here
                return
            
            # Single date mode (existing logic)
            # Determine if this is a manual or automatic execution
            execution_mode = "manual" if target_date is not None else "automatic"
            logger.info(f"Starting portfolio price update job... (mode: {execution_mode}, target_date: {target_date})")
            
            # Determine target date if not specified
            if target_date is None:
                # Auto-detect based on time of day and market hours
                # This matches the logic in utils/portfolio_update_logic.py from console app
                # Key principle: 
                # - Before 9:30 AM ET: Use yesterday (market hasn't opened yet)
                # - After 4:00 PM ET: Use today (market has closed)
                # - Between 9:30 AM - 4:00 PM: Use today if trading day (for live prices)
                pass

            # CRITICAL: Get current time in ET FIRST, then derive 'today' from ET time
            # Using server time (UTC) for 'today' causes wrong date selection
            from datetime import datetime as dt
            import pytz
            
            et = pytz.timezone('America/New_York')
            now_et = dt.now(et)
            today = now_et.date()  # Use ET date, not server/UTC date
            
            # Market hours: 9:30 AM - 4:00 PM ET
            market_open_hour = 9
            market_open_minute = 30
            market_close_hour = 16
            
            # Determine time of day status
            current_time = now_et.time()
            is_before_open = current_time < dt_time(market_open_hour, market_open_minute)
            is_after_close = current_time >= dt_time(market_close_hour, 0)
            
            use_today = False
            if market_holidays.is_trading_day(today, market="any"):
                if is_before_open:
                    # Before 9:30 AM - market hasn't opened yet, use yesterday
                    logger.info(f"Current time is {now_et.strftime('%I:%M %p ET')} - before market open (9:30 AM ET) - will use last trading day")
                elif is_after_close:
                    # After 4:00 PM - market has closed, use today
                    use_today = True
                else:
                    # During market hours (9:30 AM - 4:00 PM) - use today for live prices
                    use_today = True
            
            if use_today:
                target_date = today
                logger.info(f"Auto-detected target_date: {target_date} (today - market {'closed' if is_after_close else 'open'})")
            else:
                # Use last trading day
                target_date = None
                logger.info(f"Searching for last trading day (today {today} is before market open or not a trading day)")
                for i in range(1, 8):
                    check_date = today - timedelta(days=i)
                    if market_holidays.is_trading_day(check_date, market="any"):
                        target_date = check_date
                        logger.info(f"Found last trading day: {target_date} ({i} day(s) ago)")
                        break
                
                if target_date is None:
                    duration_ms = int((time.time() - start_time) * 1000)
                    message = f"No trading day found in last 7 days - skipping update"
                    # Log as failed to indicate this was a skipped execution
                    log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
                    # Also mark in database as failed with clear skipped message
                    try:
                        from utils.job_tracking import mark_job_failed
                        mark_job_failed('update_portfolio_prices', date.today(), None, message, duration_ms=duration_ms)
                    except Exception:
                        pass  # Don't fail if tracking fails
                    logger.warning(f"⚠️ {message}")
                    return
        
            # CRITICAL: Double-check that target_date is actually a trading day
            # This prevents the job from running on holidays/weekends even if cron triggers it
            if not market_holidays.is_trading_day(target_date, market="any"):
                duration_ms = int((time.time() - start_time) * 1000)
                message = f"Target date {target_date} is not a trading day - skipping update"
                # Log as failed to indicate this was a skipped execution
                log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
                # Also mark in database as failed with clear skipped message
                try:
                    from utils.job_tracking import mark_job_failed
                    mark_job_failed('update_portfolio_prices', target_date, None, message, duration_ms=duration_ms)
                except Exception:
                    pass  # Don't fail if tracking fails
                logger.warning(f"⚠️ {message}")
                return
            
            # Get all production funds from database (skip test/dev funds)
            funds_result = client.supabase.table("funds")\
                .select("name, base_currency")\
                .eq("is_production", True)\
                .execute()
                
            if not funds_result.data:
                duration_ms = int((time.time() - start_time) * 1000)
                message = "No production funds found in database - skipping update"
                # Log as failed to indicate this was a skipped execution
                log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
                # Also mark in database as failed with clear skipped message
                try:
                    from utils.job_tracking import mark_job_failed
                    mark_job_failed('update_portfolio_prices', target_date, None, message, duration_ms=duration_ms)
                except Exception:
                    pass  # Don't fail if tracking fails
                logger.warning(f"⚠️ {message}")
                return
            
            # Build list of production funds with their base currency settings
            funds = [(f['name'], f.get('base_currency', 'CAD')) for f in funds_result.data]
            logger.info(f"Processing {len(funds)} production funds")
            
            # AUTO-BACKFILL: Check for missing dates per fund and backfill if needed
            # This ensures we don't have gaps in the data
            logger.info("Checking for missing dates that need backfill...")
            try:
                # Check each fund individually for missing dates
                funds_needing_backfill = []
                
                for fund_name, _ in funds:
                    # Find the latest date with data for THIS fund
                    latest_date_result = client.supabase.table("portfolio_positions")\
                        .select("date")\
                        .eq("fund", fund_name)\
                        .order("date", desc=True)\
                        .limit(1)\
                        .execute()
                
                    if latest_date_result.data:
                        latest_date_str = latest_date_result.data[0]['date']
                        if 'T' in latest_date_str:
                            latest_date = datetime.fromisoformat(latest_date_str.replace('Z', '+00:00')).date()
                        else:
                            latest_date = datetime.strptime(latest_date_str, '%Y-%m-%d').date()
                        
                        # Check if there are missing trading days between latest_date and target_date
                        missing_days = []
                        check_date = latest_date + timedelta(days=1)
                        while check_date < target_date:
                            if market_holidays.is_trading_day(check_date, market="any"):
                                # Verify data doesn't exist for this date for THIS fund
                                start_of_day = datetime.combine(check_date, dt_time(0, 0, 0)).isoformat()
                                end_of_day = datetime.combine(check_date, dt_time(23, 59, 59, 999999)).isoformat()
                                
                                data_check = client.supabase.table("portfolio_positions")\
                                    .select("id", count='exact')\
                                    .eq("fund", fund_name)\
                                    .gte("date", start_of_day)\
                                    .lt("date", end_of_day)\
                                    .limit(1)\
                                    .execute()
                                
                                if not (data_check.count and data_check.count > 0):
                                    missing_days.append(check_date)
                            check_date += timedelta(days=1)
                        
                        if missing_days:
                            funds_needing_backfill.append((fund_name, latest_date, missing_days))
                    else:
                        # No data for this fund - find earliest trade and backfill from there
                        trades_result = client.supabase.table("trade_log")\
                            .select("date")\
                            .eq("fund", fund_name)\
                            .order("date")\
                            .limit(1)\
                            .execute()
                        
                        if trades_result.data:
                            earliest_trade_str = trades_result.data[0]['date']
                            if 'T' in earliest_trade_str:
                                earliest_trade = datetime.fromisoformat(earliest_trade_str.replace('Z', '+00:00')).date()
                            else:
                                earliest_trade = datetime.strptime(earliest_trade_str, '%Y-%m-%d').date()
                            
                            # Find all missing trading days from earliest trade to target_date
                            missing_days = []
                            check_date = earliest_trade
                            while check_date < target_date:
                                if market_holidays.is_trading_day(check_date, market="any"):
                                    start_of_day = datetime.combine(check_date, dt_time(0, 0, 0)).isoformat()
                                    end_of_day = datetime.combine(check_date, dt_time(23, 59, 59, 999999)).isoformat()
                                    
                                    data_check = client.supabase.table("portfolio_positions")\
                                        .select("id", count='exact')\
                                        .eq("fund", fund_name)\
                                        .gte("date", start_of_day)\
                                        .lt("date", end_of_day)\
                                        .limit(1)\
                                        .execute()
                                    
                                    if not (data_check.count and data_check.count > 0):
                                        missing_days.append(check_date)
                                check_date += timedelta(days=1)
                            
                            if missing_days:
                                funds_needing_backfill.append((fund_name, earliest_trade, missing_days))
            
                # If any funds need backfill, do it now
                if funds_needing_backfill:
                    # Collect all unique missing days across all funds
                    all_missing_days = set()
                    for _, _, missing in funds_needing_backfill:
                        all_missing_days.update(missing)
                
                    if all_missing_days:
                        sorted_missing = sorted(all_missing_days)
                        backfill_start = sorted_missing[0]
                        backfill_end = sorted_missing[-1]
                        
                        logger.warning(f"Found missing trading days for {len(funds_needing_backfill)} fund(s): {backfill_start} to {backfill_end}")
                        logger.info(f"Total missing days: {len(sorted_missing)}")
                        logger.info("Auto-backfilling missing dates...")
                        
                        # Release lock temporarily to allow backfill to acquire it
                        _update_prices_lock.release()
                        
                        try:
                            # Call backfill for the missing date range
                            backfill_portfolio_prices_range(backfill_start, backfill_end)
                            logger.info(f"Auto-backfill completed for {len(sorted_missing)} days")
                        except Exception as backfill_error:
                            logger.error(f"Auto-backfill failed: {backfill_error}", exc_info=True)
                            # Continue with regular update anyway
                    
                        # Re-acquire lock for the regular update
                        acquired = _update_prices_lock.acquire(blocking=False)
                        if not acquired:
                            # Another process got the lock - that's okay, we already backfilled
                            duration_ms = int((time.time() - start_time) * 1000)
                            message = "Lock not available after backfill - another process may be updating"
                            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
                            try:
                                from utils.job_tracking import mark_job_failed
                                mark_job_failed('update_portfolio_prices', target_date, None, message, duration_ms=duration_ms)
                            except Exception:
                                pass
                            logger.warning(f"⚠️ {message}")
                            return
                    else:
                        logger.info("No missing dates found - data is continuous")
                else:
                    logger.info("No missing dates found for any fund")
            except Exception as backfill_check_error:
                logger.warning(f"Could not check for missing dates: {backfill_check_error}")
                import traceback
                logger.debug(traceback.format_exc())
                # Continue with regular update anyway
        
            # Mark job as started (for completion tracking)
            mark_job_started('update_portfolio_prices', target_date)

            total_positions_updated = 0
            total_funds_processed = 0
            funds_completed = []  # Track which funds completed successfully

            for fund_name, base_currency in funds:
                try:
                    logger.info(f"Processing fund: {fund_name} (base_currency: {base_currency})")
                
                    # Rebuild current positions from trade log (source of truth)
                    # This ensures we have accurate positions even if database is stale
                    
                    # Get all trades for this fund
                    trades_result = client.supabase.table("trade_log")\
                        .select("*")\
                        .eq("fund", fund_name)\
                        .order("date")\
                        .execute()
                
                    if not trades_result.data:
                        logger.info(f"  No trades found for {fund_name}")
                        continue
                    
                    # Build running positions from trade log (same logic as rebuild script)
                    running_positions = defaultdict(lambda: {
                        'shares': Decimal('0'),
                        'cost': Decimal('0'),
                        'currency': 'USD'
                    })
                    
                    for trade in trades_result.data:
                        ticker = trade['ticker']
                        shares = Decimal(str(trade.get('shares', 0) or 0))
                        price = Decimal(str(trade.get('price', 0) or 0))
                        cost = shares * price
                        reason = str(trade.get('reason', '')).upper()
                        
                        if 'SELL' in reason:
                            # Simple FIFO: reduce shares and cost proportionally
                            if running_positions[ticker]['shares'] > 0:
                                cost_per_share = running_positions[ticker]['cost'] / running_positions[ticker]['shares']
                                running_positions[ticker]['shares'] -= shares
                                running_positions[ticker]['cost'] -= shares * cost_per_share
                                # Ensure we don't go negative
                                if running_positions[ticker]['shares'] < 0:
                                    running_positions[ticker]['shares'] = Decimal('0')
                                if running_positions[ticker]['cost'] < 0:
                                    running_positions[ticker]['cost'] = Decimal('0')
                        else:
                            # Default to BUY
                            running_positions[ticker]['shares'] += shares
                            running_positions[ticker]['cost'] += cost
                            currency = trade.get('currency', 'USD')
                            # Validate currency: must be a non-empty string and not 'nan'
                            if currency and isinstance(currency, str):
                                currency_upper = currency.strip().upper()
                                if currency_upper and currency_upper not in ('NAN', 'NONE', 'NULL', ''):
                                    running_positions[ticker]['currency'] = currency_upper
                                else:
                                    # Invalid currency string - keep default 'USD'
                                    logger.warning(f"⚠️ Trade for '{ticker}' in fund '{fund_name}' has invalid currency '{currency}'. Defaulting to USD.")
                            else:
                                # If currency is None or not a string, keep default 'USD'
                                logger.warning(f"⚠️ Trade for '{ticker}' in fund '{fund_name}' has missing currency. Defaulting to USD.")
                    
                    # Filter to only positions with shares > 0
                    current_holdings = {
                        ticker: pos for ticker, pos in running_positions.items()
                        if pos['shares'] > 0
                    }
                    
                    if not current_holdings:
                        logger.info(f"  No active positions for {fund_name}")
                        continue
                
                    logger.info(f"  Found {len(current_holdings)} active positions")
                    
                    # Populate currency cache from current holdings before fetching
                    # This ensures we know which tickers are USD vs CAD to avoid wrong Canadian fallbacks
                    for ticker, holding in current_holdings.items():
                        currency = holding.get('currency', 'USD')
                        if currency:
                            market_fetcher._portfolio_currency_cache[ticker.upper()] = currency.upper()
                    
                    # CRITICAL: Check which markets are actually open on target_date
                    # This prevents fetching stale/bad data when one market is closed but the other is open
                    us_market_open = not market_holidays.is_us_market_closed(target_date)
                    canadian_market_open = not market_holidays.is_canadian_market_closed(target_date)
                    
                    logger.info(f"  Market status for {target_date}: US={'OPEN' if us_market_open else 'CLOSED'}, Canada={'OPEN' if canadian_market_open else 'CLOSED'}")
                    
                    # Helper to detect market from ticker suffix (more reliable than currency)
                    def is_canadian_ticker(ticker: str) -> bool:
                        return ticker.endswith(('.TO', '.V', '.CN'))
                    
                    # Categorize tickers by market status - but DON'T remove closed-market tickers!
                    # We'll fetch prices for open-market tickers and use cached/previous prices for closed ones
                    tickers_to_fetch = []  # Tickers whose market is open - fetch fresh prices
                    tickers_to_carry_forward = []  # Tickers whose market is closed - use previous close
                    
                    for ticker, holding in current_holdings.items():
                        is_canadian = is_canadian_ticker(ticker)
                        ticker_market_open = (canadian_market_open if is_canadian else us_market_open)
                        
                        if ticker_market_open:
                            tickers_to_fetch.append(ticker)
                        else:
                            tickers_to_carry_forward.append(ticker)
                    
                    if tickers_to_carry_forward:
                        market_status = []
                        if not us_market_open:
                            market_status.append("US closed")
                        if not canadian_market_open:
                            market_status.append("Canada closed")
                        logger.info(f"  📋 {len(tickers_to_carry_forward)} ticker(s) will use previous close ({', '.join(market_status)})")
                        for ticker in tickers_to_carry_forward[:5]:  # Show first 5
                            logger.debug(f"    {ticker} (will use cached/previous price)")
                        if len(tickers_to_carry_forward) > 5:
                            logger.debug(f"    ... and {len(tickers_to_carry_forward) - 5} more")
                    
                    if not tickers_to_fetch and not tickers_to_carry_forward:
                        logger.warning(f"  ⏭️  No positions for {fund_name} - skipping")
                        continue
                    
                    logger.info(f"  Will fetch fresh prices for {len(tickers_to_fetch)}/{len(current_holdings)} ticker(s)")
                    
                    # Get exchange rate for target date (for USD→base_currency conversion)
                    exchange_rate = Decimal('1.0')  # Default for same currency or no conversion needed
                    if base_currency != 'USD':  # Only fetch rate if converting TO non-USD currency
                        rate = _get_exchange_rate_for_date(
                            datetime.combine(target_date, dt_time(0, 0, 0)),
                            'USD',
                            base_currency
                        )
                        if rate is not None:
                            exchange_rate = Decimal(str(rate))
                            logger.info(f"  Using exchange rate USD→{base_currency}: {exchange_rate}")
                        else:
                            # Fallback rate if no data available
                            exchange_rate = Decimal('1.35')
                            logger.warning(f"  Missing exchange rate for {target_date}, using fallback {exchange_rate}")
                    
                    # OPTIMIZATION: Fetch current prices for open-market tickers in parallel
                    # For closed-market tickers, we'll use cached/previous prices
                    current_prices = {}
                    failed_tickers = []
                    rate_limit_errors = 0
                    
                    # Helper function to fetch price for a single ticker
                    def fetch_ticker_price(ticker: str) -> tuple[str, Optional[Decimal], Optional[str]]:
                        """Fetch price for a single ticker. Returns (ticker, price, error_type)."""
                        try:
                            # Fetch price data for target date
                            start_dt = datetime.combine(target_date, dt_time(0, 0, 0))
                            end_dt = datetime.combine(target_date, dt_time(23, 59, 59, 999999))
                            result = market_fetcher.fetch_price_data(ticker, start=start_dt, end=end_dt)
                            
                            if result and result.df is not None and not result.df.empty:
                                # Get the most recent close price
                                latest_price = Decimal(str(result.df['Close'].iloc[-1]))
                                return (ticker, latest_price, None)
                            else:
                                # Try to get from cache or previous day
                                cached_data = price_cache.get_cached_price(ticker)
                                if cached_data is not None and not cached_data.empty:
                                    latest_price = Decimal(str(cached_data['Close'].iloc[-1]))
                                    return (ticker, latest_price, 'cached')
                                else:
                                    return (ticker, None, 'no_data')
                        except Exception as e:
                            error_str = str(e).lower()
                            # Check for rate limiting errors (429, too many requests, etc.)
                            if '429' in error_str or 'rate limit' in error_str or 'too many requests' in error_str:
                                return (ticker, None, 'rate_limit')
                            else:
                                return (ticker, None, 'error')
                    
                    # Helper to get cached/previous close for closed-market tickers
                    def get_cached_price(ticker: str) -> tuple[str, Optional[Decimal], Optional[str]]:
                        """Get cached price for a ticker whose market is closed. Returns (ticker, price, source)."""
                        try:
                            cached_data = price_cache.get_cached_price(ticker)
                            if cached_data is not None and not cached_data.empty:
                                latest_price = Decimal(str(cached_data['Close'].iloc[-1]))
                                return (ticker, latest_price, 'carried_forward')
                            else:
                                return (ticker, None, 'no_cache')
                        except Exception:
                            return (ticker, None, 'cache_error')
                    
                    # Step 1: Get prices for closed-market tickers from cache (previous close)
                    if tickers_to_carry_forward:
                        logger.info(f"  Getting previous close for {len(tickers_to_carry_forward)} closed-market tickers...")
                        carried_forward_count = 0
                        for ticker in tickers_to_carry_forward:
                            ticker, price, source = get_cached_price(ticker)
                            if price is not None:
                                current_prices[ticker] = price
                                carried_forward_count += 1
                                logger.debug(f"    {ticker}: ${price} (previous close)")
                            else:
                                # If no cache available, we'll still try to include the position
                                # using the last known price from the holding if available
                                holding = current_holdings.get(ticker, {})
                                last_known_price = holding.get('last_price') or holding.get('price')
                                if last_known_price:
                                    current_prices[ticker] = Decimal(str(last_known_price))
                                    carried_forward_count += 1
                                    logger.debug(f"    {ticker}: ${last_known_price} (from holding)")
                                else:
                                    logger.warning(f"    {ticker}: No cached or holding price available")
                                    failed_tickers.append(ticker)
                        logger.info(f"  Carried forward {carried_forward_count}/{len(tickers_to_carry_forward)} closed-market prices")
                    
                    # Step 2: Fetch prices for open-market tickers in parallel
                    max_workers = min(5, len(tickers_to_fetch)) if tickers_to_fetch else 1
                    
                    if tickers_to_fetch:
                        logger.info(f"  Fetching fresh prices for {len(tickers_to_fetch)} open-market tickers (max_workers={max_workers})...")
                        price_fetch_start = time.time()
                        
                        with ThreadPoolExecutor(max_workers=max_workers) as executor:
                            # Submit tasks only for open-market tickers
                            future_to_ticker = {executor.submit(fetch_ticker_price, ticker): ticker for ticker in tickers_to_fetch}
                            
                            # Process completed tasks
                            for future in as_completed(future_to_ticker):
                                ticker, price, error_type = future.result()
                                
                                if price is not None:
                                    current_prices[ticker] = price
                                    if error_type == 'cached':
                                        logger.debug(f"    {ticker}: ${price} (cached fallback)")
                                    else:
                                        logger.debug(f"    {ticker}: ${price}")
                                else:
                                    if error_type == 'rate_limit':
                                        rate_limit_errors += 1
                                        if rate_limit_errors == 1:
                                            logger.warning(f"  ⚠️  Rate limiting detected for {ticker}")
                                        failed_tickers.append(ticker)
                                    elif error_type == 'no_data':
                                        logger.warning(f"    {ticker}: Could not fetch price (no data)")
                                        failed_tickers.append(ticker)
                                    else:
                                        logger.warning(f"    {ticker}: Error fetching price")
                                        failed_tickers.append(ticker)
                        
                        price_fetch_time = time.time() - price_fetch_start
                        fetched_count = len([t for t in tickers_to_fetch if t in current_prices])
                        avg_time_per_ticker = price_fetch_time / len(tickers_to_fetch) if tickers_to_fetch else 0
                        logger.info(f"  Parallel fetch complete: {fetched_count}/{len(tickers_to_fetch)} succeeded ({price_fetch_time:.2f}s, ~{avg_time_per_ticker:.2f}s per ticker)")
                        
                        if rate_limit_errors > 0:
                            logger.warning(f"  ⚠️  Rate limiting detected: {rate_limit_errors} tickers hit 429 errors")
                            logger.warning(f"     Consider: reducing max_workers, adding delays, or using API keys")
                    
                    # Summary of all prices (fetched + carried forward)
                    logger.info(f"  Total prices available: {len(current_prices)}/{len(current_holdings)} tickers")
                    
                    if failed_tickers:
                        logger.warning(f"  Failed to get prices for {len(failed_tickers)} tickers: {failed_tickers}")
                        # If ALL tickers failed, skip this fund (don't create empty snapshot)
                        if len(failed_tickers) == len(current_holdings):
                            logger.warning(f"  All tickers failed for {fund_name} - skipping update")
                            continue
                    
                    # Create updated positions for target date
                    # Only include positions where we successfully fetched prices
                    updated_positions = []
                    successful_tickers = []
                    for ticker, holding in current_holdings.items():
                        if ticker in failed_tickers:
                            logger.warning(f"  Skipping {ticker} - price fetch failed")
                            continue
                        
                        current_price = current_prices.get(ticker)
                        if current_price is None:
                            continue
                        
                        shares = holding['shares']
                        cost_basis = holding['cost']
                        avg_price = cost_basis / shares if shares > 0 else Decimal('0')
                        market_value = shares * current_price
                        unrealized_pnl = market_value - cost_basis
                        
                        # Convert to base currency if needed
                        position_currency = holding['currency']
                        if position_currency == 'USD' and base_currency != 'USD':
                            # Convert USD position to base currency (e.g., CAD)
                            market_value_base = market_value * exchange_rate
                            cost_basis_base = cost_basis * exchange_rate
                            pnl_base = unrealized_pnl * exchange_rate
                            conversion_rate = exchange_rate
                        elif position_currency == base_currency:
                            # Already in base currency - no conversion
                            market_value_base = market_value
                            cost_basis_base = cost_basis
                            pnl_base = unrealized_pnl
                            conversion_rate = Decimal('1.0')
                        else:
                            # Other currency combinations not yet supported - store as-is
                            logger.warning(f"  Unsupported currency conversion: {position_currency} → {base_currency}")
                            market_value_base = market_value
                            cost_basis_base = cost_basis
                            pnl_base = unrealized_pnl
                            conversion_rate = Decimal('1.0')
                        
                        # CRITICAL: Create datetime with ET timezone, then convert to UTC for storage
                        # This ensures the timestamp is correctly interpreted regardless of server timezone
                        from datetime import datetime as dt
                        import pytz
                        et_tz = pytz.timezone('America/New_York')
                        # Create datetime at 4 PM ET (market close) for the target date
                        et_datetime = et_tz.localize(dt.combine(target_date, dt_time(16, 0)))
                        # Convert to UTC for storage (Supabase stores timestamps in UTC)
                        utc_datetime = et_datetime.astimezone(pytz.UTC)
                        # Calculate date_only for unique constraint (fund, ticker, date_only)
                        date_only = utc_datetime.date()
                        
                        updated_positions.append({
                            'fund': fund_name,
                            'ticker': ticker,
                            'shares': float(shares),
                            'price': float(current_price),
                            'cost_basis': float(cost_basis),
                            # 'total_value': float(market_value),  # REMOVED: Generated column - DB calculates automatically
                            'pnl': float(unrealized_pnl),
                            'currency': holding['currency'],
                            'date': utc_datetime.isoformat(),
                            'date_only': date_only.isoformat(),  # Include for unique constraint upsert
                            # New: Pre-converted values in base currency
                            'base_currency': base_currency,
                            'total_value_base': float(market_value_base),
                            'cost_basis_base': float(cost_basis_base),
                            'pnl_base': float(pnl_base),
                            'exchange_rate': float(conversion_rate)
                        })
                        successful_tickers.append(ticker)
                    
                    if not updated_positions:
                        logger.warning(f"  No positions to update for {fund_name} (all tickers failed or no active positions)")
                        continue
                    
                    # Log summary
                    logger.info(f"  Successfully fetched prices for {len(successful_tickers)}/{len(current_holdings)} tickers")
                    
                    # CRITICAL: Delete ALL existing positions for target date BEFORE inserting
                    # This prevents duplicates - there should only be one snapshot per day
                    # Use a more comprehensive delete query to ensure we catch all records
                    start_of_day = datetime.combine(target_date, dt_time(0, 0, 0)).isoformat()
                    end_of_day = datetime.combine(target_date, dt_time(23, 59, 59, 999999)).isoformat()
                    
                    # Delete in batches to handle large datasets
                    deleted_total = 0
                    while True:
                        # Get IDs of positions to delete (limit to avoid timeout)
                        existing_result = client.supabase.table("portfolio_positions")\
                            .select("id")\
                            .eq("fund", fund_name)\
                            .gte("date", start_of_day)\
                            .lte("date", end_of_day)\
                            .limit(1000)\
                            .execute()
                        
                        if not existing_result.data:
                            break
                        
                        # Delete by IDs
                        ids_to_delete = [row['id'] for row in existing_result.data]
                        delete_result = client.supabase.table("portfolio_positions")\
                            .delete()\
                            .in_("id", ids_to_delete)\
                            .execute()
                        
                        deleted_count = len(delete_result.data) if delete_result.data else len(ids_to_delete)
                        deleted_total += deleted_count
                        
                        # If we got fewer than 1000, we're done
                        if len(existing_result.data) < 1000:
                            break
                    
                    if deleted_total > 0:
                        logger.info(f"  Deleted {deleted_total} existing positions for {target_date} (preventing duplicates)")
                    
                    # ATOMIC UPDATE: Upsert updated positions (insert or update on conflict)
                    # Using upsert instead of insert to handle race conditions gracefully
                    # The unique constraint on (fund, date, ticker) prevents duplicates
                    # If delete+insert pattern fails due to race condition, upsert will handle it
                    if updated_positions:
                        try:
                            # Ensure all tickers exist in securities table before inserting (required for FK constraint)
                            try:
                                from supabase_client import SupabaseClient as SupabaseClientType
                                supabase_client = SupabaseClientType(use_service_role=True)
                                
                                unique_tickers = set(pos['ticker'] for pos in updated_positions)
                                for ticker in unique_tickers:
                                    # Get currency for this ticker from positions
                                    ticker_positions = [p for p in updated_positions if p['ticker'] == ticker]
                                    currency = ticker_positions[0].get('currency', 'USD') if ticker_positions else 'USD'
                                    try:
                                        supabase_client.ensure_ticker_in_securities(ticker, currency)
                                    except Exception as e:
                                        logger.warning(f"  Could not ensure ticker {ticker} in securities: {e}")
                            except Exception as ensure_error:
                                logger.warning(f"  Failed to ensure tickers exist: {ensure_error}")
                                # Continue anyway - the insert will fail with FK error if ticker doesn't exist
                            
                            # Use upsert with on_conflict to handle duplicates from race conditions
                            # This is safer than insert alone - if the job runs twice concurrently,
                            # or if delete+insert fails, upsert will update existing records instead of erroring
                            # The unique constraint is on (fund, ticker, date_only) - date_only is auto-populated by trigger
                            upsert_result = client.supabase.table("portfolio_positions")\
                                .upsert(
                                    updated_positions,
                                    on_conflict="fund,ticker,date_only"
                                )\
                                .execute()
                        
                            upserted_count = len(upsert_result.data) if upsert_result.data else len(updated_positions)
                            total_positions_updated += upserted_count
                            total_funds_processed += 1
                            funds_completed.append(fund_name)  # Track successful completion
                            
                            logger.info(f"  ✅ Upserted {upserted_count} positions for {fund_name}")
                        except Exception as upsert_error:
                            # Upsert failed - log error but don't fail entire job
                            # The delete already happened, but upsert failure is less likely than insert failure
                            # This is acceptable because:
                            # 1. Next run (15 min) will fix it
                            # 2. Historical data is preserved
                            # 3. We continue processing other funds
                            logger.error(f"  ❌ Failed to upsert positions for {fund_name}: {upsert_error}")
                            logger.warning(f"  ⚠️  {fund_name} has no positions for {target_date} until next run")
                            # Don't increment counters for failed upsert
                    else:
                        logger.warning(f"  No positions to insert for {fund_name} (all tickers failed price fetch)")
            
                except Exception as e:
                    logger.error(f"  ❌ Error processing fund {fund_name}: {e}", exc_info=True)
                    continue
        
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Updated {total_positions_updated} positions across {total_funds_processed} fund(s) for {target_date}"
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            logger.info(f"✅ {message}")

            # Mark job as completed successfully
            mark_job_completed('update_portfolio_prices', target_date, None, funds_completed, duration_ms=duration_ms, message=message)
        
            # Clear cache to ensure fresh data is used in charts
            try:
                from cache_version import bump_cache_version
                bump_cache_version()
                logger.info("🔄 Cache version bumped - charts will use fresh portfolio data")
            except Exception as cache_error:
                logger.warning(f"⚠️  Failed to bump cache version: {cache_error}")
        
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Error: {str(e)}"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ Portfolio price update job failed: {e}", exc_info=True)
            
            # Mark job as failed in database
            # If target_date not defined (early crash), use today as fallback
            try:
                fallback_date = date.today() if 'target_date' not in locals() or target_date is None else target_date
                mark_job_failed('update_portfolio_prices', fallback_date, None, str(e), duration_ms=duration_ms)
            except Exception as tracking_error:
                logger.error(f"Failed to mark job as failed in database: {tracking_error}", exc_info=True)
        finally:
            # Always release the lock, even if job fails (only if we actually acquired it)
            try:
                # Only release if we actually acquired the lock (not date range mode, and lock was acquired)
                if not is_date_range_mode and lock_acquired and _update_prices_lock.locked():
                    _update_prices_lock.release()
                    print(f"[{__name__}] Lock released", file=sys.stderr, flush=True)
            except Exception as lock_error:
                # Don't let lock release errors crash the scheduler
                print(f"[{__name__}] WARNING: Error releasing lock: {lock_error}", file=sys.stderr, flush=True)
                try:
                    logger.warning(f"Error releasing lock: {lock_error}")
                except:
                    pass
    
    except Exception as outer_error:
        # Catch any errors that happen before the inner try block (path setup, etc.)
        # This prevents the scheduler from crashing
        import traceback
        error_msg = f"❌ CRITICAL: Portfolio price update job crashed before main execution: {outer_error}"
        print(f"[{__name__}] {error_msg}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        try:
            logger.error(error_msg, exc_info=True)
        except:
            pass  # Logger might not work
        try:
            log_job_execution('update_portfolio_prices', success=False, message=f"Critical error: {str(outer_error)}", duration_ms=0)
        except Exception as log_err:
            print(f"[{__name__}] Failed to log job execution: {log_err}", file=sys.stderr, flush=True)


def backfill_portfolio_prices_range(start_date: date, end_date: date) -> None:
    """Backfill portfolio positions for a date range efficiently.
    
    This is a batch-optimized version of update_portfolio_prices_job that:
    1. Fetches price data for ALL tickers for the ENTIRE date range at once (1 API call per ticker)
    2. Correctly filters trades by date for each historical snapshot
    3. Processes all dates in the range with a single batch delete/insert
    
    Args:
        start_date: First date to backfill (inclusive)
        end_date: Last date to backfill (inclusive)
    
    Performance: O(Tickers) API calls instead of O(Days * Tickers)
    Correctness: Only includes trades up to each snapshot date
    """
    # IMMEDIATE logging - use print() as fallback since it always works
    import sys
    print(f"[{__name__}] backfill_portfolio_prices_range() STARTED", file=sys.stderr, flush=True)
    try:
        logger.info(f"backfill_portfolio_prices_range() started: {start_date} to {end_date}")
    except:
        pass  # Logger might not be ready yet
    
    # Wrap everything in try/except to prevent scheduler crashes
    try:
        print(f"[{__name__}] Setting up sys.path...", file=sys.stderr, flush=True)
        # CRITICAL: Ensure sys.path is set up FIRST, before any imports
        _ensure_sys_path_setup()
        print(f"[{__name__}] sys.path setup complete", file=sys.stderr, flush=True)
        
        job_id = 'backfill_portfolio_prices_range'
        start_time = time.time()
        print(f"[{__name__}] Job ID: {job_id}, start_time: {start_time}", file=sys.stderr, flush=True)
        
        # Acquire lock with non-blocking check - if another thread is already running, skip
        # This prevents backfill from running effectively concurrently with scheduled updates
        acquired = _update_prices_lock.acquire(blocking=False)
        if not acquired:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "Job already running - skipped (lock not acquired)"
            # Log as failed to indicate this was a skipped execution
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.warning(f"⚠️ {message}")
            return

        try:
            logger.info(f"Starting batch backfill for date range: {start_date} to {end_date}")
            
            # Import dependencies
            from market_data.data_fetcher import MarketDataFetcher
            from utils.market_holidays import MarketHolidays
            from supabase_client import SupabaseClient
            from utils.job_tracking import mark_job_completed, add_to_retry_queue
            from cache_version import bump_cache_version
            import pytz
            
            # Initialize components
            market_fetcher = MarketDataFetcher()
            market_holidays = MarketHolidays()
            client = SupabaseClient(use_service_role=True)
            
            # Get all production funds
            funds_result = client.supabase.table("funds")\
                .select("name, base_currency")\
                .eq("is_production", True)\
                .execute()
            
            if not funds_result.data:
                logger.info("No production funds found")
                return
            
            funds = [(f['name'], f.get('base_currency', 'CAD')) for f in funds_result.data]
            logger.info(f"Processing {len(funds)} production funds")
            
            # Build list of trading days in the range
            trading_days = []
            current = start_date
            while current <= end_date:
                if market_holidays.is_trading_day(current, market="any"):
                    trading_days.append(current)
                current += timedelta(days=1)
            
            if not trading_days:
                logger.info(f"No trading days in range {start_date} to {end_date}")
                return
            
            print(f"Backfilling {len(trading_days)} trading days: {trading_days[0]} to {trading_days[-1]}", flush=True)
            logger.info(f"Backfilling {len(trading_days)} trading days: {trading_days[0]} to {trading_days[-1]}")
            
            total_positions_created = 0
            successful_funds = []  # Track which funds completed successfully
            # ISSUE #1 FIX: Track per-day, per-fund success to detect partial failures
            from collections import defaultdict
            days_funds_complete = defaultdict(set)  # {date: {fund1, fund2, ...}}
            all_production_funds = set(f[0] for f in funds)  # All funds we're processing
        
            for fund_idx, (fund_name, base_currency) in enumerate(funds, 1):
                try:
                    fund_start_time = time.time()  # Track timing per fund
                    print(f"[{fund_idx}/{len(funds)}] Processing fund: {fund_name} (base_currency: {base_currency})", flush=True)
                    logger.info(f"[{fund_idx}/{len(funds)}] Processing fund: {fund_name} (base_currency: {base_currency})")
                    _log_portfolio_job_progress(fund_name, f"Starting backfill for {len(trading_days)} trading days")
                    
                    # Get ALL trades for this fund (we'll filter by date later)
                    trades_load_start = time.time()
                    logger.info(f"  Fetching trades from database...")
                    trades_result = client.supabase.table("trade_log")\
                        .select("*")\
                        .eq("fund", fund_name)\
                        .order("date")\
                        .execute()
                    
                    if not trades_result.data:
                        logger.info(f"  No trades found for {fund_name} - skipping")
                        _log_portfolio_job_progress(fund_name, "No trades found - skipping")
                        continue
                    
                    trades_load_time = time.time() - trades_load_start
                    logger.info(f"  Loaded {len(trades_result.data)} trades in {trades_load_time:.2f}s")
                
                    # Convert trade dates to date objects for comparison
                    trades_with_dates = []
                    parse_errors = 0
                    for trade in trades_result.data:
                        trade_date_str = trade.get('date')
                        if trade_date_str:
                            # Parse the date - handle both date and datetime formats
                            try:
                                if 'T' in trade_date_str:
                                    trade_date = datetime.fromisoformat(trade_date_str.replace('Z', '+00:00')).date()
                                else:
                                    trade_date = datetime.strptime(trade_date_str, '%Y-%m-%d').date()
                                trades_with_dates.append({**trade, '_parsed_date': trade_date})
                            except Exception as e:
                                parse_errors += 1
                                logger.warning(f"  Could not parse trade date {trade_date_str}: {e}")
                                continue
                    
                    if parse_errors > 0:
                        logger.warning(f"  Skipped {parse_errors} trades with unparseable dates")
                    
                    if not trades_with_dates:
                        logger.info(f"  No valid trades with parseable dates for {fund_name} - skipping")
                        continue
                    
                    logger.info(f"  Successfully parsed {len(trades_with_dates)} trades")
                    
                    # Identify all unique tickers across ALL trades
                    all_tickers = set()
                    ticker_currencies = {}  # Track currency for each ticker (for reference, not market detection)
                    for trade in trades_with_dates:
                        ticker = trade['ticker']
                        all_tickers.add(ticker)
                        # Store currency for reference (used for base currency conversion, not market detection)
                        currency = trade.get('currency', 'USD')
                        if currency and isinstance(currency, str):
                            currency_upper = currency.strip().upper()
                            if currency_upper and currency_upper not in ('NAN', 'NONE', 'NULL', ''):
                                ticker_currencies[ticker] = currency_upper
                            else:
                                ticker_currencies[ticker] = 'USD'  # Default
                        else:
                            ticker_currencies[ticker] = 'USD'  # Default
                    
                    logger.info(f"  Found {len(all_tickers)} unique tickers across all trades")
                    
                    # Populate currency cache from trades before fetching
                    # This ensures we know which tickers are USD vs CAD to avoid wrong Canadian fallbacks
                    for ticker, currency in ticker_currencies.items():
                        market_fetcher._portfolio_currency_cache[ticker.upper()] = currency.upper()
                    
                    # Helper to detect market from ticker suffix (more reliable than currency)
                    def is_canadian_ticker(ticker: str) -> bool:
                        return ticker.endswith(('.TO', '.V', '.CN'))
                    
                    # CRITICAL: Build per-day market-aware ticker list using TICKER SUFFIX (not currency)
                    # For each trading day, only fetch prices for tickers whose market is open
                    # Closed-market tickers will get forward-filled prices later
                    tickers_per_day = {}  # {date: [tickers]} - tickers whose market is open that day
                    skipped_per_day = defaultdict(list)  # {date: [tickers]} - for logging
                    
                    for day in trading_days:
                        us_open = not market_holidays.is_us_market_closed(day)
                        canada_open = not market_holidays.is_canadian_market_closed(day)
                        
                        day_tickers = []
                        for ticker in all_tickers:
                            is_canadian = is_canadian_ticker(ticker)
                            ticker_market_open = canada_open if is_canadian else us_open
                            
                            if ticker_market_open:
                                day_tickers.append(ticker)
                            else:
                                skipped_per_day[day].append(ticker)
                        
                        tickers_per_day[day] = day_tickers
                    
                    # Log market-aware filtering results
                    total_skipped = sum(len(v) for v in skipped_per_day.values())
                    if total_skipped > 0:
                        logger.info(f"  📋 {total_skipped} ticker-day combinations will use forward-fill (market closed)")
                        # Show a few examples
                        for day in sorted(skipped_per_day.keys())[:3]:  # First 3 days with skips
                            skipped = skipped_per_day[day]
                            us_open = not market_holidays.is_us_market_closed(day)
                            canada_open = not market_holidays.is_canadian_market_closed(day)
                            market_status = f"US={'OPEN' if us_open else 'CLOSED'}, CA={'OPEN' if canada_open else 'CLOSED'}"
                            logger.info(f"      {day}: {len(skipped)} ticker(s) ({market_status})")
                    
                    # OPTIMIZATION: Fetch price data for ALL tickers for the ENTIRE date range at once
                    # This is 1 API call per ticker instead of 1 API call per ticker per day
                    ticker_price_data = {}
                    failed_tickers = []
                    
                    logger.info(f"  Fetching price data for {len(all_tickers)} tickers in parallel...")
                    fetch_start = time.time()
                    
                    # OPTIMIZATION: Parallel price fetching with vectorized pandas extraction
                    # This replaces sequential fetching (O(n)) with parallel (O(n/workers))
                    ticker_list = list(all_tickers)
                    price_cache_dict = {}  # {(ticker, date): price} for O(1) lookups
                    rate_limit_errors = 0
                    successful_fetches = 0
                    
                    # Helper function to fetch and extract prices for a single ticker
                    def fetch_ticker_prices(ticker: str) -> tuple[str, dict, bool, Optional[str]]:
                        """Fetch price data for a single ticker with vectorized extraction.
                        
                        Returns: (ticker, {date: price}, success, error_type)
                        """
                        try:
                            # Fetch all historical data for this ticker at once
                            range_start = datetime.combine(trading_days[0], dt_time(0, 0, 0))
                            range_end = datetime.combine(trading_days[-1], dt_time(23, 59, 59, 999999))
                            result = market_fetcher.fetch_price_data(ticker, start=range_start, end=range_end)
                            
                            if result and result.df is not None and not result.df.empty:
                                # OPTIMIZATION: Vectorized price extraction using pandas
                                # Extract all prices at once instead of iterating per-day lookups
                                ticker_prices = {}
                                df = result.df
                                
                                if 'Close' in df.columns and not df.empty:
                                    # Create date column from index for fast filtering
                                    df_with_dates = df.copy()
                                    if hasattr(df.index, 'date'):
                                        df_with_dates['_date'] = [d.date() for d in df.index]
                                    else:
                                        df_with_dates['_date'] = pd.to_datetime(df.index).date
                                    
                                    # Filter to only days where THIS ticker's market was open
                                    # This prevents using stale prices on market holidays
                                    valid_days_for_ticker = set()
                                    for day in trading_days:
                                        if ticker in tickers_per_day.get(day, []):
                                            valid_days_for_ticker.add(day)
                                    
                                    mask = df_with_dates['_date'].isin(valid_days_for_ticker)
                                    filtered = df_with_dates.loc[mask]
                                    
                                    # Extract prices (already filtered, fast iteration)
                                    for _, row in filtered.iterrows():
                                        day = row['_date']
                                        if day in valid_days_for_ticker:
                                            ticker_prices[day] = Decimal(str(row['Close']))
                                
                                return (ticker, ticker_prices, True, None)
                            else:
                                return (ticker, {}, False, 'no_data')
                        
                        except Exception as e:
                            error_str = str(e).lower()
                            # Check for rate limiting
                            if '429' in error_str or 'rate limit' in error_str or 'too many requests' in error_str:
                                return (ticker, {}, False, 'rate_limit')
                            else:
                                return (ticker, {}, False, 'error')
                    
                    # PARALLEL EXECUTION: Fetch all tickers concurrently
                    max_workers = min(5, len(ticker_list))  # Conservative for free-tier APIs
                    logger.info(f"  Using {max_workers} parallel workers...")
                    
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        # Submit all tasks
                        future_to_ticker = {executor.submit(fetch_ticker_prices, ticker): ticker for ticker in ticker_list}
                        
                        # Process completed tasks
                        completed = 0
                        for future in as_completed(future_to_ticker):
                            completed += 1
                            ticker, ticker_prices, success, error_type = future.result()
                            
                            if success:
                                # Store all prices for this ticker
                                for day, price in ticker_prices.items():
                                    price_cache_dict[(ticker, day)] = price
                                ticker_price_data[ticker] = ticker_prices  # Also store dict for later
                                successful_fetches += 1
                                
                                # Progress every 10 tickers
                                if completed % 10 == 0:
                                    logger.info(f"    Progress: {completed}/{len(ticker_list)} tickers fetched...")
                            else:
                                failed_tickers.append(ticker)
                                if error_type == 'rate_limit':
                                    rate_limit_errors += 1
                                    if rate_limit_errors == 1:
                                        logger.warning(f"  ⚠️  Rate limiting detected for {ticker}")
                                elif error_type == 'no_data':
                                    logger.warning(f"      {ticker}: No price data available")
                                else:
                                    logger.warning(f"      {ticker}: Error fetching price data")
                    
                    fetch_duration = time.time() - fetch_start
                    avg_time_per_ticker = fetch_duration / len(ticker_list) if ticker_list else 0
                    logger.info(f"  Parallel fetch complete: {successful_fetches}/{len(all_tickers)} succeeded in {fetch_duration:.2f}s (~{avg_time_per_ticker:.2f}s per ticker)")
                    
                    if rate_limit_errors > 0:
                        logger.warning(f"  ⚠️  Rate limiting detected: {rate_limit_errors} tickers hit 429 errors")
                        logger.warning(f"     Consider: reducing max_workers, adding delays, or using API keys")
                    
                    if failed_tickers:
                        logger.warning(f"  Failed to fetch prices for {len(failed_tickers)} tickers: {failed_tickers}")
                    
                    # CRITICAL: Build forward-fill lookup table for closed-market days
                    # This ensures positions aren't dropped when their market is closed
                    # For each ticker, if a day is missing, carry forward the last known price
                    logger.info(f"  Building forward-fill price lookup for {len(all_tickers)} tickers...")
                    forward_fill_count = 0
                    
                    for ticker in all_tickers:
                        if ticker in failed_tickers:
                            continue  # Skip tickers that completely failed
                        
                        last_known_price = None
                        for day in trading_days:  # trading_days is already sorted ascending
                            cache_key = (ticker, day)
                            if cache_key in price_cache_dict:
                                # We have a price for this day - update last known
                                last_known_price = price_cache_dict[cache_key]
                            elif last_known_price is not None:
                                # No price for this day (market closed) - use forward-fill
                                price_cache_dict[cache_key] = last_known_price
                                forward_fill_count += 1
                    
                    if forward_fill_count > 0:
                        logger.info(f"  Forward-filled {forward_fill_count} ticker-day prices for closed-market days")
                    
                    # Now process each trading day
                    all_positions = []  # Collect all position records for batch insert
                    # ISSUE #2 CLARITY: Track positions count per day FOR THIS FUND
                    positions_per_day = {}  # Per-fund tracking: {date: count}
                    
                    # OPTIMIZATION: Cache exchange rates to avoid redundant DB lookups
                    exchange_rate_cache = {}  # {(date, from_curr, to_curr): rate}
                    
                    def get_cached_exchange_rate(date_obj, from_curr, to_curr):
                        """Get exchange rate with caching to minimize database lookups."""
                        cache_key = (date_obj if isinstance(date_obj, date) else date_obj.date(), from_curr, to_curr)
                        if cache_key in exchange_rate_cache:
                            return exchange_rate_cache[cache_key]
                        
                        # Fetch from database and cache
                        rate = _get_exchange_rate_for_date(
                            datetime.combine(cache_key[0], dt_time(0, 0, 0)),
                            from_curr,
                            to_curr
                        )
                        if rate is not None:
                            exchange_rate_cache[cache_key] = Decimal(str(rate))
                            return exchange_rate_cache[cache_key]
                        
                        # Fallback rates
                        if from_curr == 'USD' and to_curr == 'CAD':
                            fallback = Decimal('1.35')
                        elif from_curr == 'CAD' and to_curr == 'USD':
                            fallback = Decimal('1.0') / Decimal('1.35')
                        else:
                            fallback = Decimal('1.0')
                        
                        exchange_rate_cache[cache_key] = fallback
                        return fallback
                    
                    logger.info(f"  Processing {len(trading_days)} trading days to build position snapshots...")
                    process_start = time.time()
                    
                    for day_idx, target_date in enumerate(trading_days, 1):
                        # Progress update every 10 days or on last day
                        if day_idx % 10 == 0 or day_idx == len(trading_days):
                            logger.info(f"    Processing day {day_idx}/{len(trading_days)}: {target_date}...")
                        # CORRECTNESS FIX: Filter trades to only those on or before target_date
                        trades_up_to_date = [t for t in trades_with_dates if t['_parsed_date'] <= target_date]
                        
                        # Build running positions from filtered trades
                        running_positions = defaultdict(lambda: {
                            'shares': Decimal('0'),
                            'cost': Decimal('0'),
                            'currency': 'USD'
                        })
                        
                        for trade in trades_up_to_date:
                            ticker = trade['ticker']
                            shares = Decimal(str(trade.get('shares', 0) or 0))
                            price = Decimal(str(trade.get('price', 0) or 0))
                            cost = shares * price
                            reason = str(trade.get('reason', '')).upper()
                            
                            if 'SELL' in reason:
                                if running_positions[ticker]['shares'] > 0:
                                    cost_per_share = running_positions[ticker]['cost'] / running_positions[ticker]['shares']
                                    running_positions[ticker]['shares'] -= shares
                                    running_positions[ticker]['cost'] -= shares * cost_per_share
                                    if running_positions[ticker]['shares'] < 0:
                                        running_positions[ticker]['shares'] = Decimal('0')
                                    if running_positions[ticker]['cost'] < 0:
                                        running_positions[ticker]['cost'] = Decimal('0')
                            else:
                                running_positions[ticker]['shares'] += shares
                                running_positions[ticker]['cost'] += cost
                                currency = trade.get('currency', 'USD')
                                if currency and isinstance(currency, str):
                                    currency_upper = currency.strip().upper()
                                    if currency_upper and currency_upper not in ('NAN', 'NONE', 'NULL', ''):
                                        running_positions[ticker]['currency'] = currency_upper
                        
                        # Filter to only positions with shares > 0
                        current_holdings = {
                            ticker: pos for ticker, pos in running_positions.items()
                            if pos['shares'] > 0
                        }
                        
                        if not current_holdings:
                            # ISSUE #3: Better logging for edge cases
                            logger.debug(f"  {target_date}: No active positions for {fund_name} (no trades yet or all sold)")
                            continue
                        
                        # OPTIMIZATION: Use cached exchange rate lookup
                        exchange_rate = Decimal('1.0')
                        if base_currency != 'USD':
                            exchange_rate = get_cached_exchange_rate(target_date, 'USD', base_currency)
                        
                        # Create position records for this date
                        et_tz = pytz.timezone('America/New_York')
                        et_datetime = et_tz.localize(datetime.combine(target_date, dt_time(16, 0)))
                        utc_datetime = et_datetime.astimezone(pytz.UTC)
                        
                        for ticker, holding in current_holdings.items():
                            if ticker in failed_tickers:
                                continue  # Skip tickers with no price data
                            
                            # OPTIMIZATION: O(1) dict lookup instead of DataFrame operations
                            current_price = price_cache_dict.get((ticker, target_date))
                            if current_price is None:
                                # ISSUE #3: Better logging - track why day was skipped
                                logger.debug(f"  {target_date} {ticker}: No price data available in cache (skipping)")
                                continue
                            
                            shares = holding['shares']
                            cost_basis = holding['cost']
                            market_value = shares * current_price
                            unrealized_pnl = market_value - cost_basis
                            
                            # Convert to base currency
                            position_currency = holding['currency']
                            if position_currency == 'USD' and base_currency != 'USD':
                                market_value_base = market_value * exchange_rate
                                cost_basis_base = cost_basis * exchange_rate
                                pnl_base = unrealized_pnl * exchange_rate
                                conversion_rate = exchange_rate
                            elif position_currency == base_currency:
                                market_value_base = market_value
                                cost_basis_base = cost_basis
                                pnl_base = unrealized_pnl
                                conversion_rate = Decimal('1.0')
                            else:
                                market_value_base = market_value
                                cost_basis_base = cost_basis
                                pnl_base = unrealized_pnl
                                conversion_rate = Decimal('1.0')
                            
                            all_positions.append({
                                'fund': fund_name,
                                'ticker': ticker,
                                'shares': float(shares),
                                'price': float(current_price),
                                'cost_basis': float(cost_basis),
                                # 'total_value': float(market_value),  # REMOVED: Generated column - DB calculates automatically
                                'pnl': float(unrealized_pnl),
                                'currency': holding['currency'],
                                'date': utc_datetime.isoformat(),
                                'base_currency': base_currency,
                                'total_value_base': float(market_value_base),
                                'cost_basis_base': float(cost_basis_base),
                                'pnl_base': float(pnl_base),
                                'exchange_rate': float(conversion_rate)
                            })
                            # BUG FIX: Track that this day has positions
                            positions_per_day[target_date] = positions_per_day.get(target_date, 0) + 1
                    
                    process_duration = time.time() - process_start
                    logger.info(f"  Finished processing {len(trading_days)} days in {process_duration:.2f}s")
                
                    if not all_positions:
                        logger.info(f"  No positions to backfill for {fund_name} - skipping")
                        continue
                    
                    logger.info(f"  Created {len(all_positions)} position records across {len(trading_days)} days")
                    
                    # BATCH DELETE: Remove all existing positions for this fund in the date range
                    # Use smaller batch sizes to avoid Supabase "Bad Request" errors with large IN clauses
                    logger.info(f"  Deleting existing positions for date range {trading_days[0]} to {trading_days[-1]}...")
                    start_of_range = datetime.combine(trading_days[0], dt_time(0, 0, 0)).isoformat()
                    end_of_range = datetime.combine(trading_days[-1], dt_time(23, 59, 59, 999999)).isoformat()
                    
                    # Use smaller batch size for deletes to avoid JSON/Bad Request errors
                    DELETE_BATCH_SIZE = 200  # Reduced from 1000 to avoid Supabase limits
                    DELETE_CHUNK_SIZE = 100  # Size for retry chunks if batch fails
                    
                    deleted_total = 0
                    delete_batch_num = 0
                    max_delete_iterations = 100  # Safety limit to prevent infinite loops
                    delete_iteration = 0
                    
                    while delete_iteration < max_delete_iterations:
                        delete_iteration += 1
                        delete_batch_num += 1
                        existing_result = client.supabase.table("portfolio_positions")\
                            .select("id")\
                            .eq("fund", fund_name)\
                            .gte("date", start_of_range)\
                            .lte("date", end_of_range)\
                            .limit(DELETE_BATCH_SIZE)\
                            .execute()
                        
                        if not existing_result.data:
                            break
                        
                        # Filter out any None or invalid IDs
                        ids_to_delete = [row['id'] for row in existing_result.data if row.get('id') is not None]
                        
                        if not ids_to_delete:
                            logger.warning(f"    Delete batch {delete_batch_num}: No valid IDs found")
                            break
                        
                        logger.info(f"    Delete batch {delete_batch_num}: Found {len(ids_to_delete)} positions to delete")
                        
                        # Delete in smaller chunks to avoid Supabase limits
                        chunk_deleted = 0
                        for chunk_idx in range(0, len(ids_to_delete), DELETE_CHUNK_SIZE):
                            chunk_ids = ids_to_delete[chunk_idx:chunk_idx + DELETE_CHUNK_SIZE]
                            try:
                                delete_result = client.supabase.table("portfolio_positions")\
                                    .delete()\
                                    .in_("id", chunk_ids)\
                                    .execute()
                                
                                chunk_count = len(delete_result.data) if delete_result.data else len(chunk_ids)
                                chunk_deleted += chunk_count
                                logger.debug(f"      Deleted chunk {chunk_idx//DELETE_CHUNK_SIZE + 1} ({chunk_count} positions)")
                            except Exception as chunk_error:
                                error_msg = str(chunk_error)
                                logger.error(f"      Error deleting chunk {chunk_idx//DELETE_CHUNK_SIZE + 1}: {chunk_error}")
                                logger.error(f"        Error type: {type(chunk_error).__name__}")
                                logger.error(f"        Error details: {error_msg[:500]}")
                                
                                # If it's a JSON/Bad Request error, try even smaller chunks
                                if 'Bad Request' in error_msg or 'JSON' in error_msg or '400' in error_msg:
                                    logger.warning(f"        Bad Request detected - trying individual deletes for this chunk")
                                    # Try deleting one at a time as last resort
                                    for single_id in chunk_ids:
                                        try:
                                            single_delete = client.supabase.table("portfolio_positions")\
                                                .delete()\
                                                .eq("id", single_id)\
                                                .execute()
                                            chunk_deleted += 1
                                        except Exception as single_error:
                                            logger.error(f"          Failed to delete ID {single_id}: {single_error}")
                                else:
                                    # Re-raise if it's not a known issue we can handle
                                    raise
                        
                        deleted_total += chunk_deleted
                        logger.info(f"    Delete batch {delete_batch_num}: Deleted {chunk_deleted} positions (total: {deleted_total})")
                        
                        if len(existing_result.data) < DELETE_BATCH_SIZE:
                            break
                    
                    if delete_iteration >= max_delete_iterations:
                        logger.warning(f"  Delete loop reached maximum iterations ({max_delete_iterations}) - may not have deleted all records")
                    
                    # VERIFICATION: Check if any records still exist after delete - retry if needed
                    max_verify_attempts = 3
                    for verify_attempt in range(1, max_verify_attempts + 1):
                        verify_result = client.supabase.table("portfolio_positions")\
                            .select("id", count='exact')\
                            .eq("fund", fund_name)\
                            .gte("date", start_of_range)\
                            .lte("date", end_of_range)\
                            .limit(1)\
                            .execute()
                        
                        remaining_count = verify_result.count if verify_result.count is not None else 0
                        if remaining_count == 0:
                            logger.info(f"  Verified: All existing positions deleted (0 remaining)")
                            break
                        else:
                            logger.warning(f"  Verification attempt {verify_attempt}: {remaining_count} positions still exist")
                            if verify_attempt < max_verify_attempts:
                                logger.info(f"    Retrying delete for remaining {remaining_count} positions...")
                                # Try one more delete pass
                                retry_result = client.supabase.table("portfolio_positions")\
                                    .select("id")\
                                    .eq("fund", fund_name)\
                                    .gte("date", start_of_range)\
                                    .lte("date", end_of_range)\
                                    .limit(remaining_count)\
                                    .execute()
                                
                                if retry_result.data:
                                    retry_ids = [row['id'] for row in retry_result.data if row.get('id') is not None]
                                    # Delete in small chunks
                                    for i in range(0, len(retry_ids), DELETE_CHUNK_SIZE):
                                        retry_chunk = retry_ids[i:i + DELETE_CHUNK_SIZE]
                                        try:
                                            client.supabase.table("portfolio_positions")\
                                                .delete()\
                                                .in_("id", retry_chunk)\
                                                .execute()
                                            deleted_total += len(retry_chunk)
                                        except Exception as retry_error:
                                            logger.error(f"    Retry delete failed: {retry_error}")
                            else:
                                logger.error(f"  ERROR: {remaining_count} positions still exist after {max_verify_attempts} delete attempts")
                                logger.error(f"    This may cause duplicate records. Consider manual cleanup.")
                    
                    if deleted_total > 0:
                        logger.info(f"  Deleted {deleted_total} existing positions in {delete_batch_num} batch(es)")
                    else:
                        logger.info(f"  No existing positions to delete")
                
                    # CHUNKED BATCH INSERT: Process in chunks to avoid Supabase 1000-row limit
                    # FIX: Chunking, validation, and per-chunk tracking
                    # Reduced chunk size to avoid "Bad Request" errors with large position counts
                    CHUNK_SIZE = 200  # Reduced from 500 to avoid JSON/Bad Request errors
                    RETRY_CHUNK_SIZE = 50  # Smaller size for retry if Bad Request occurs
                    total_inserted = 0
                    days_inserted_for_fund = set()  # Days that actually got inserted for this fund
                    failed_chunks = []  # Track failed chunks for retry
                    
                    # Validate positions before inserting (remove any with None or invalid values)
                    validated_positions = []
                    invalid_count = 0
                    import math
                    for pos in all_positions:
                        # Check for required fields and valid types
                        if (pos.get('fund') and pos.get('ticker') and pos.get('date') and
                            pos.get('shares') is not None and pos.get('price') is not None):
                            # Ensure numeric fields are valid (not NaN, inf, etc.)
                            try:
                                shares = float(pos['shares'])
                                price = float(pos['price'])
                                # Check for valid numbers (not NaN, not inf)
                                if (isinstance(shares, (int, float)) and isinstance(price, (int, float)) and
                                    not (math.isnan(shares) or math.isnan(price) or 
                                         math.isinf(shares) or math.isinf(price))):
                                    validated_positions.append(pos)
                                else:
                                    invalid_count += 1
                            except (ValueError, TypeError):
                                invalid_count += 1
                        else:
                            invalid_count += 1
                    
                    if invalid_count > 0:
                        logger.warning(f"  Filtered out {invalid_count} invalid positions (missing fields or NaN values)")
                    
                    if not validated_positions:
                        logger.warning(f"  No valid positions to insert for {fund_name}")
                        continue
                    
                    # Ensure all tickers exist in securities table before inserting (required for FK constraint)
                    try:
                        from supabase_client import SupabaseClient as SupabaseClientType
                        supabase_client = SupabaseClientType(use_service_role=True)
                        
                        unique_tickers = set(pos['ticker'] for pos in validated_positions)
                        logger.info(f"  Ensuring {len(unique_tickers)} unique tickers exist in securities table...")
                        for ticker in unique_tickers:
                            # Get currency for this ticker from positions
                            ticker_positions = [p for p in validated_positions if p['ticker'] == ticker]
                            currency = ticker_positions[0].get('currency', 'USD') if ticker_positions else 'USD'
                            try:
                                supabase_client.ensure_ticker_in_securities(ticker, currency)
                            except Exception as e:
                                logger.warning(f"  Could not ensure ticker {ticker} in securities: {e}")
                    except Exception as ensure_error:
                        logger.warning(f"  Failed to ensure tickers exist: {ensure_error}")
                        # Continue anyway - the insert will fail with FK error if ticker doesn't exist
                    
                    # Split positions into chunks
                    num_chunks = (len(validated_positions) + CHUNK_SIZE - 1) // CHUNK_SIZE
                    print(f"  Inserting {len(validated_positions)} positions in {num_chunks} chunk(s) of {CHUNK_SIZE}...", flush=True)
                    logger.info(f"  Inserting {len(validated_positions)} positions in {num_chunks} chunk(s) of {CHUNK_SIZE}...")
                    
                    for chunk_idx in range(num_chunks):
                        start_idx = chunk_idx * CHUNK_SIZE
                        end_idx = min(start_idx + CHUNK_SIZE, len(validated_positions))
                        chunk = validated_positions[start_idx:end_idx]
                        
                        logger.info(f"    Inserting chunk {chunk_idx + 1}/{num_chunks} ({len(chunk)} positions)...")
                        
                        try:
                            # Insert this chunk
                            chunk_result = client.supabase.table("portfolio_positions")\
                                .insert(chunk)\
                                .execute()
                            
                            chunk_inserted = len(chunk_result.data) if chunk_result.data else len(chunk)
                            total_inserted += chunk_inserted
                            
                            # Track which days are in this chunk (for validation)
                            chunk_dates = set()
                            for pos in chunk:
                                # Extract date from ISO string (e.g., "2025-12-19T21:00:00+00:00")
                                pos_date_str = pos['date']
                                if 'T' in pos_date_str:
                                    pos_date = datetime.fromisoformat(pos_date_str.replace('Z', '+00:00')).date()
                                else:
                                    pos_date = datetime.strptime(pos_date_str, '%Y-%m-%d').date()
                                chunk_dates.add(pos_date)
                            
                            logger.info(f"    Chunk {chunk_idx + 1}/{num_chunks}: Inserted {chunk_inserted} positions for {len(chunk_dates)} days")
                            
                            # VALIDATION: Verify data actually exists in database for this chunk
                            logger.debug(f"    Validating {len(chunk_dates)} days in chunk {chunk_idx + 1}...")
                            for day in chunk_dates:
                                try:
                                    start_of_day = datetime.combine(day, dt_time(0, 0, 0)).isoformat()
                                    end_of_day = datetime.combine(day, dt_time(23, 59, 59, 999999)).isoformat()
                                    
                                    verify_result = client.supabase.table("portfolio_positions")\
                                        .select("id", count='exact')\
                                        .eq("fund", fund_name)\
                                        .gte("date", start_of_day)\
                                        .lte("date", end_of_day)\
                                        .limit(1)\
                                        .execute()
                                    
                                    count = verify_result.count if verify_result.count is not None else 0
                                    if count > 0:
                                        days_inserted_for_fund.add(day)
                                        logger.debug(f"      {day}: Validation passed ({count} positions found)")
                                    else:
                                        logger.warning(f"    WARNING: {day}: Insert succeeded but validation found no data (count={count})")
                                        logger.warning(f"      This means insert appeared to succeed but data is missing from database")
                                        # Add to retry queue - insert appeared to succeed but data missing
                                        try:
                                            add_to_retry_queue(
                                                job_name='update_portfolio_prices',
                                                target_date=day,
                                                entity_id=fund_name,
                                                entity_type='fund',
                                                failure_reason='validation_failed',
                                                error_message='Insert succeeded but validation found no data in database',
                                                context={
                                                    'chunk_number': chunk_idx + 1,
                                                    'batch_range': f"{start_date} to {end_date}"
                                                }
                                            )
                                            logger.info(f"    📝 Added {day} to retry queue for {fund_name} (validation failed)")
                                        except Exception as retry_error:
                                            logger.error(f"    ❌ Failed to add {day} to retry queue: {retry_error}")
                                except Exception as validation_error:
                                    logger.warning(f"    ⚠️  {day}: Validation query failed: {validation_error}")
                        
                        except Exception as chunk_error:
                            error_msg = str(chunk_error)
                            is_bad_request = ('Bad Request' in error_msg or 'JSON' in error_msg or 
                                             '400' in error_msg or 'could not be generated' in error_msg)
                            
                            # Chunk insert failed - track which days were in this chunk
                            chunk_dates = set()
                            for pos in chunk:
                                pos_date_str = pos['date']
                                if 'T' in pos_date_str:
                                    pos_date = datetime.fromisoformat(pos_date_str.replace('Z', '+00:00')).date()
                                else:
                                    pos_date = datetime.strptime(pos_date_str, '%Y-%m-%d').date()
                                chunk_dates.add(pos_date)
                            
                            failed_chunks.append({
                                'chunk_number': chunk_idx + 1,
                                'dates': sorted(list(chunk_dates)),
                                'error': error_msg,
                                'position_count': len(chunk),
                                'is_bad_request': is_bad_request
                            })
                            
                            logger.error(f"    ERROR: Chunk {chunk_idx + 1}/{num_chunks} failed: {chunk_error}")
                            logger.error(f"      Error type: {type(chunk_error).__name__}")
                            logger.error(f"      Error details: {error_msg[:500]}")
                            logger.warning(f"      Days in failed chunk: {sorted(list(chunk_dates))}")
                            
                            # If it's a Bad Request/JSON error, try smaller chunks
                            if is_bad_request and len(chunk) > RETRY_CHUNK_SIZE:
                                logger.warning(f"      Bad Request detected - retrying with smaller chunks ({RETRY_CHUNK_SIZE} positions)...")
                                retry_inserted = 0
                                for retry_idx in range(0, len(chunk), RETRY_CHUNK_SIZE):
                                    retry_chunk = chunk[retry_idx:retry_idx + RETRY_CHUNK_SIZE]
                                    try:
                                        retry_result = client.supabase.table("portfolio_positions")\
                                            .insert(retry_chunk)\
                                            .execute()
                                        retry_count = len(retry_result.data) if retry_result.data else len(retry_chunk)
                                        retry_inserted += retry_count
                                        logger.info(f"        Retry chunk {retry_idx//RETRY_CHUNK_SIZE + 1}: Inserted {retry_count} positions")
                                    except Exception as retry_error:
                                        logger.error(f"        Retry chunk {retry_idx//RETRY_CHUNK_SIZE + 1} also failed: {retry_error}")
                                        # Add to failed chunks for retry queue
                                        for pos in retry_chunk:
                                            try:
                                                pos_date_str = pos['date']
                                                if 'T' in pos_date_str:
                                                    retry_date = datetime.fromisoformat(pos_date_str.replace('Z', '+00:00')).date()
                                                else:
                                                    retry_date = datetime.strptime(pos_date_str, '%Y-%m-%d').date()
                                                chunk_dates.add(retry_date)
                                            except:
                                                pass
                                
                                if retry_inserted > 0:
                                    total_inserted += retry_inserted
                                    logger.info(f"      Retry succeeded for {retry_inserted} positions")
                                    # Remove successfully retried days from failed list
                                    chunk_dates = set()  # Will be recalculated below for remaining failures
                            
                            # Try to get more details about the error
                            if hasattr(chunk_error, 'args') and chunk_error.args:
                                logger.error(f"      Error args: {chunk_error.args}")
                            if hasattr(chunk_error, 'message'):
                                logger.error(f"      Error message: {chunk_error.message}")
                            
                            # Add each failed day to retry queue
                            for failed_day in chunk_dates:
                                try:
                                    add_to_retry_queue(
                                        job_name='update_portfolio_prices',
                                        target_date=failed_day,
                                        entity_id=fund_name,
                                        entity_type='fund',
                                        failure_reason='chunk_failed',
                                        error_message=f"Chunk {chunk_idx + 1} insert failed: {str(chunk_error)[:200]}",
                                        context={
                                            'chunk_number': chunk_idx + 1,
                                            'position_count': len(chunk),
                                            'batch_range': f"{start_date} to {end_date}"
                                        }
                                    )
                                    logger.info(f"    📝 Added {failed_day} to retry queue for {fund_name}")
                                except Exception as retry_error:
                                    logger.error(f"    ❌ Failed to add {failed_day} to retry queue: {retry_error}")
                            
                            # Continue with next chunk - don't fail entire batch
                            continue
                
                    # Summary
                    print(f"  Insert summary for {fund_name}:", flush=True)
                    print(f"    Total positions created: {len(all_positions)}", flush=True)
                    print(f"    Total positions inserted: {total_inserted}", flush=True)
                    print(f"    Days validated: {len(days_inserted_for_fund)}", flush=True)
                    print(f"    Failed chunks: {len(failed_chunks)}", flush=True)
                    logger.info(f"  Insert summary for {fund_name}:")
                    logger.info(f"    Total positions created: {len(all_positions)}")
                    logger.info(f"    Total positions inserted: {total_inserted}")
                    logger.info(f"    Days validated: {len(days_inserted_for_fund)}")
                    logger.info(f"    Failed chunks: {len(failed_chunks)}")
                    
                    if total_inserted > 0:
                        logger.info(f"  Inserted {total_inserted}/{len(all_positions)} positions for {fund_name}")
                        if fund_name not in successful_funds:
                            successful_funds.append(fund_name)
                        total_positions_created += total_inserted
                        
                        # Log completion summary with timing
                        fund_duration = time.time() - fund_start_time
                        _log_portfolio_job_progress(
                            fund_name,
                            f"Completed: {total_inserted} positions across {len(days_inserted_for_fund)} days ({fund_duration:.1f}s)"
                        )
                    else:
                        logger.warning(f"  WARNING: No positions were inserted for {fund_name}")
                        logger.warning(f"    This could mean:")
                        logger.warning(f"      1. All chunks failed")
                        logger.warning(f"      2. All positions were invalid")
                        logger.warning(f"      3. Insert operations all failed")
                    
                    if failed_chunks:
                        logger.error(f"  ERROR: {len(failed_chunks)} chunk(s) failed for {fund_name}")
                        for fail in failed_chunks[:5]:  # Only show first 5 to avoid spam
                            logger.error(f"    Chunk {fail['chunk_number']}: {fail['position_count']} positions")
                            logger.error(f"      Days: {fail['dates'][:5]}{'...' if len(fail['dates']) > 5 else ''}")
                            logger.error(f"      Error: {fail['error'][:200]}")
                            logger.error(f"      Bad Request: {fail.get('is_bad_request', False)}")
                        if len(failed_chunks) > 5:
                            logger.error(f"    ... and {len(failed_chunks) - 5} more failed chunks")
                    
                    # Track which days succeeded for THIS fund (only validated days)
                    if days_inserted_for_fund:
                        logger.info(f"  Validated {len(days_inserted_for_fund)} days with data for {fund_name}")
                        logger.debug(f"    Validated days: {sorted(list(days_inserted_for_fund))[:10]}{'...' if len(days_inserted_for_fund) > 10 else ''}")
                        for day_with_data in days_inserted_for_fund:
                            days_funds_complete[day_with_data].add(fund_name)
                            logger.debug(f"    Added {day_with_data} to days_funds_complete for {fund_name}")
                    else:
                        logger.warning(f"  WARNING: No days validated for {fund_name} - will NOT be marked complete")
                        logger.warning(f"    This means either:")
                        logger.warning(f"      1. No positions were created (no active holdings)")
                        logger.warning(f"      2. All inserts failed")
                        logger.warning(f"      3. Validation queries are failing")
                
                except Exception as e:
                    logger.error(f"  ERROR: Failed to process fund {fund_name}")
                    logger.error(f"    Error type: {type(e).__name__}")
                    logger.error(f"    Error message: {str(e)[:500]}")
                    logger.error(f"    Full traceback:", exc_info=True)
                    
                    # Add all remaining days to retry queue
                    # Find which days haven't been processed yet
                    # BUGFIX: days_inserted_for_fund might not exist if error occurred before chunking
                    processed_days = locals().get('days_inserted_for_fund', set())
                    remaining_days = set(trading_days) - processed_days
                    
                    if remaining_days:
                        logger.warning(f"  Adding {len(remaining_days)} unprocessed days to retry queue for {fund_name}")
                        retry_added = 0
                        retry_failed = 0
                        for unprocessed_day in remaining_days:
                            try:
                                add_to_retry_queue(
                                    job_name='update_portfolio_prices',
                                    target_date=unprocessed_day,
                                    entity_id=fund_name,
                                    entity_type='fund',
                                    failure_reason='fund_processing_failed',
                                    error_message=f"Fund processing exception: {str(e)[:200]}",
                                    context={
                                        'batch_range': f"{start_date} to {end_date}",
                                        'processed_days': sorted(list(processed_days))
                                    }
                                )
                                retry_added += 1
                            except Exception as retry_error:
                                retry_failed += 1
                                if retry_failed <= 5:  # Only log first 5 failures to avoid spam
                                    logger.error(f"    Failed to add {unprocessed_day} to retry queue: {retry_error}")
                        
                        if retry_failed > 5:
                            logger.error(f"    ... and {retry_failed - 5} more retry queue failures (duplicate entries likely)")
                        logger.info(f"  Added {retry_added} days to retry queue, {retry_failed} failed")
                    
                    continue
        
            # ISSUE #1 FIX: Only mark days as completed if ALL production funds succeeded
            # This prevents partial failures from being marked as complete
            print(f"Checking which days have all funds complete...", flush=True)
            print(f"  All production funds: {sorted(list(all_production_funds))}", flush=True)
            print(f"  Days with some funds complete: {len(days_funds_complete)} days", flush=True)
            logger.info(f"Checking which days have all funds complete...")
            logger.debug(f"  All production funds: {sorted(list(all_production_funds))}")
            logger.debug(f"  Days with some funds complete: {len(days_funds_complete)} days")
            
            days_all_funds_complete = []
            for day, funds_for_day in days_funds_complete.items():
                if funds_for_day == all_production_funds:
                    days_all_funds_complete.append(day)
                else:
                    missing_funds = all_production_funds - funds_for_day
                    logger.debug(f"  {day}: Missing funds {missing_funds} (has: {sorted(list(funds_for_day))})")
            
            print(f"Found {len(days_all_funds_complete)} days with all funds complete (out of {len(trading_days)} trading days)", flush=True)
            logger.info(f"Found {len(days_all_funds_complete)} days with all funds complete (out of {len(trading_days)} trading days)")
            
            # ISSUE #4: Validate data exists in database before marking complete
            days_validated = []
            print(f"Validating {len(days_all_funds_complete)} days in database...", flush=True)
            logger.info(f"Validating {len(days_all_funds_complete)} days in database...")
            for day in days_all_funds_complete:
                try:
                    # Quick validation: verify positions exist for this day
                    start_of_day = datetime.combine(day, dt_time(0, 0, 0)).isoformat()
                    end_of_day = datetime.combine(day, dt_time(23, 59, 59, 999999)).isoformat()
                    
                    verify_result = client.supabase.table("portfolio_positions")\
                        .select("id", count='exact')\
                        .gte("date", start_of_day)\
                        .lte("date", end_of_day)\
                        .in_("fund", list(all_production_funds))\
                        .limit(1)\
                        .execute()
                    
                    count = verify_result.count if verify_result.count is not None else 0
                    if count > 0:
                        days_validated.append(day)
                        logger.debug(f"  {day}: Database validation passed ({count} positions found)")
                    else:
                        logger.warning(f"  WARNING: {day}: Data validation failed - no positions found in DB (count={count})")
                        logger.warning(f"    This means positions were inserted but are now missing from database")
                except Exception as e:
                    logger.warning(f"  WARNING: {day}: Could not validate data existence: {e}")
                    logger.warning(f"    Validation query failed - skipping this day")
            
            if days_validated:
                logger.info(f"Marking {len(days_validated)} fully complete days (out of {len(trading_days)} trading days)...")
                marked_count = 0
                failed_mark_count = 0
                for day in days_validated:
                    try:
                        mark_job_completed('update_portfolio_prices', day, None, successful_funds, duration_ms=None)
                        marked_count += 1
                        if marked_count <= 5 or marked_count % 50 == 0:
                            logger.debug(f"  Marked {day} as completed ({marked_count}/{len(days_validated)})")
                    except Exception as e:
                        failed_mark_count += 1
                        logger.error(f"  ERROR: Failed to mark {day} as completed: {e}")
                        logger.error(f"    Error type: {type(e).__name__}")
                        logger.error(f"    Error details: {str(e)[:300]}")
                
                logger.info(f"  Successfully marked {marked_count} days as completed")
                if failed_mark_count > 0:
                    logger.error(f"  Failed to mark {failed_mark_count} days as completed")
                
                # ISSUE #3: Better logging for skipped days with reasons
                skipped_days = set(trading_days) - set(days_validated)
                if skipped_days:
                    logger.warning(f"  {len(skipped_days)} days NOT marked complete")
                    logger.warning(f"    First 20 skipped days: {sorted(list(skipped_days))[:20]}")
                    
                    # Categorize why days were skipped
                    no_positions_count = 0
                    partial_failure_count = 0
                    validation_failed_count = 0
                    
                    for day in sorted(skipped_days):
                        funds_for_day = days_funds_complete.get(day, set())
                        if not funds_for_day:
                            no_positions_count += 1
                            if no_positions_count <= 5:
                                logger.debug(f"   {day}: No positions created (no active holdings or all tickers failed)")
                        elif funds_for_day != all_production_funds:
                            partial_failure_count += 1
                            missing_funds = all_production_funds - funds_for_day
                            if partial_failure_count <= 5:
                                logger.warning(f"   {day}: Partial failure - missing data for funds: {missing_funds}")
                        else:
                            validation_failed_count += 1
                            if validation_failed_count <= 5:
                                logger.warning(f"   {day}: Validation failed - data missing from database")
                    
                    logger.info(f"    Skipped day breakdown:")
                    logger.info(f"      No positions created: {no_positions_count} days")
                    logger.info(f"      Partial failures: {partial_failure_count} days")
                    logger.info(f"      Validation failed: {validation_failed_count} days")
            else:
                logger.warning(f"  WARNING: No days fully completed - nothing marked as completed")
                logger.warning(f"    This means either:")
                logger.warning(f"      1. No positions were created for any day")
                logger.warning(f"      2. All inserts failed")
                logger.warning(f"      3. Validation failed for all days")
                logger.warning(f"      4. Not all funds completed for any day")
        
            # Bump cache version to force UI refresh
            try:
                bump_cache_version()
                logger.info("Cache version bumped - Streamlit will show fresh data")
            except Exception as e:
                logger.warning(f"Failed to bump cache version: {e}")
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Final summary
            logger.info("=" * 80)
            logger.info("BACKFILL SUMMARY")
            logger.info("=" * 80)
            logger.info(f"Date range: {start_date} to {end_date}")
            logger.info(f"Trading days processed: {len(trading_days)}")
            logger.info(f"Funds processed: {len(funds)}")
            logger.info(f"Successful funds: {len(successful_funds)}/{len(funds)}")
            if successful_funds:
                logger.info(f"  Successful: {', '.join(successful_funds)}")
            failed_funds = [f[0] for f in funds if f[0] not in successful_funds]
            if failed_funds:
                logger.warning(f"  Failed: {', '.join(failed_funds)}")
            logger.info(f"Total positions created: {total_positions_created}")
            logger.info(f"Days fully completed: {len(days_validated)}/{len(trading_days)}")
            if days_validated:
                logger.info(f"  Completed dates: {sorted(days_validated)[:10]}{'...' if len(days_validated) > 10 else ''}")
            skipped_days = set(trading_days) - set(days_validated)
            if skipped_days:
                logger.warning(f"  Skipped dates: {len(skipped_days)} days (see details above)")
            logger.info(f"Total duration: {duration_ms/1000:.2f}s")
            logger.info("=" * 80)
            
            message = f"Backfilled {total_positions_created} positions for date range {start_date} to {end_date}"
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            logger.info(f"Backfill job completed: {message} in {duration_ms/1000:.2f}s")
        
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Error: {str(e)}"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error("=" * 80)
            logger.error("BACKFILL FAILED")
            logger.error("=" * 80)
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error message: {str(e)[:500]}")
            logger.error(f"Duration before failure: {duration_ms/1000:.2f}s")
            logger.error("Full traceback:", exc_info=True)
            logger.error("=" * 80)
            
            # Mark job as failed in database
            try:
                from utils.job_tracking import mark_job_failed
                mark_job_failed('backfill_portfolio_prices_range', start_date, None, str(e), duration_ms=duration_ms)
            except Exception as tracking_error:
                logger.error(f"Failed to mark backfill job as failed in database: {tracking_error}", exc_info=True)
            finally:
                # Always release the lock (only if we acquired it)
                if _update_prices_lock.locked():
                    _update_prices_lock.release()
    
    except Exception as outer_error:
        # Catch any errors that happen before the inner try block (path setup, etc.)
        # This prevents the scheduler from crashing
        import traceback
        error_msg = f"❌ CRITICAL: Backfill job crashed before main execution: {outer_error}"
        print(f"[{__name__}] {error_msg}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        try:
            logger.error(error_msg, exc_info=True)
        except:
            pass  # Logger might not work
        try:
            log_job_execution('backfill_portfolio_prices_range', success=False, message=f"Critical error: {str(outer_error)}", duration_ms=0)
        except Exception as log_err:
            print(f"[{__name__}] Failed to log job execution: {log_err}", file=sys.stderr, flush=True)

