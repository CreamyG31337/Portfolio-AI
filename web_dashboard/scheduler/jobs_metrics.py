"""
Metrics Jobs
============

Jobs for refreshing benchmark data, exchange rates, and performance metrics.
"""

import logging
import time
from datetime import datetime, timezone, timedelta, date, time as dt_time
from decimal import Decimal
from collections import defaultdict
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

def benchmark_refresh_job() -> None:
    """Refresh benchmark data cache for chart performance.
    
    This job:
    1. Fetches latest benchmark data from Yahoo Finance
    2. Caches it in the benchmark_data table
    3. Ensures charts always have up-to-date market index data
    
    Benchmarks refreshed:
    - S&P 500 (^GSPC)
    - Nasdaq-100 (QQQ)
    - Russell 2000 (^RUT)
    - Total Market (VTI)
    """
    job_id = 'benchmark_refresh'
    start_time = time.time()
    target_date = datetime.now(timezone.utc).date()
    
    try:
        # Import job tracking
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        
        logger.info("Starting benchmark refresh job...")
        
        # Mark job as started in database
        mark_job_started('benchmark_refresh', target_date)
        
        # Import dependencies
        try:
            import yfinance as yf
            from supabase_client import SupabaseClient
        except ImportError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Missing dependency: {e}"
            try:
                log_job_execution(job_id, False, message, duration_ms)
            except Exception as log_error:
                logger.warning(f"Failed to log job execution: {log_error}")
            logger.error(f"❌ {message}")
            return
        
        # Initialize Supabase client (use service role for writing)
        client = SupabaseClient(use_service_role=True)
        
        # Define benchmarks to refresh
        benchmarks = [
            {"ticker": "^GSPC", "name": "S&P 500"},
            {"ticker": "QQQ", "name": "Nasdaq-100"},
            {"ticker": "^RUT", "name": "Russell 2000"},
            {"ticker": "VTI", "name": "Total Market"}
        ]
        
        # Fetch data for the last 30 days to ensure we have recent data
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        
        benchmarks_updated = 0
        benchmarks_failed = 0
        total_rows_cached = 0
        
        for benchmark in benchmarks:
            ticker = benchmark["ticker"]
            name = benchmark["name"]
            
            try:
                logger.info(f"Fetching {name} ({ticker})...")
                
                # Fetch data from Yahoo Finance
                data = yf.download(
                    ticker,
                    start=start_date,
                    end=end_date,
                    progress=False,
                    auto_adjust=False
                )
                
                if data.empty:
                    logger.warning(f"No data available for {name} ({ticker})")
                    benchmarks_failed += 1
                    continue
                
                # Reset index to get Date as a column
                data = data.reset_index()
                
                # Handle MultiIndex columns from yfinance
                if hasattr(data.columns, 'levels'):
                    data.columns = data.columns.get_level_values(0)
                
                # Convert to list of dicts for caching
                rows = data.to_dict('records')
                
                # Cache in database
                if client.cache_benchmark_data(ticker, rows):
                    total_rows_cached += len(rows)
                    benchmarks_updated += 1
                    logger.info(f"✅ Cached {len(rows)} rows for {name} ({ticker})")
                else:
                    benchmarks_failed += 1
                    logger.warning(f"Failed to cache data for {name} ({ticker})")
                
            except Exception as e:
                logger.error(f"Error fetching {name} ({ticker}): {e}")
                benchmarks_failed += 1
        
        # Clear cache to ensure fresh data is used in charts
        try:
            from cache_version import bump_cache_version
            bump_cache_version()
            logger.info("🔄 Cache version bumped - charts will use fresh benchmark data")
        except Exception as cache_error:
            logger.warning(f"⚠️  Failed to bump cache version: {cache_error}")
        
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Updated {benchmarks_updated} benchmarks ({total_rows_cached} rows), {benchmarks_failed} failed"
        try:
            log_job_execution(job_id, True, message, duration_ms)
        except Exception as log_error:
            logger.warning(f"Failed to log job execution: {log_error}")
        mark_job_completed('benchmark_refresh', target_date, None, [], duration_ms=duration_ms)
        logger.info(f"✅ {message}")
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Error: {str(e)}"
        try:
            log_job_execution(job_id, False, message, duration_ms)
        except Exception as log_error:
            logger.warning(f"Failed to log job execution error: {log_error}")
        try:
            mark_job_failed('benchmark_refresh', target_date, None, message, duration_ms=duration_ms)
        except Exception:
            pass  # Don't fail if tracking fails
        logger.error(f"❌ Benchmark refresh job failed: {e}", exc_info=True)



def refresh_exchange_rates_job() -> None:
    """Fetch and store the latest exchange rate and fill gaps in historical data.
    
    This ensures the dashboard always has up-to-date rates for currency conversion.
    It checks for gaps in the last 30 days and fills them from BoC API.
    """
    job_id = 'exchange_rates'
    start_time = time.time()
    target_date = datetime.now(timezone.utc).date()
    
    try:
        # Import job tracking
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        
        logger.info("Starting exchange rates refresh job...")
        
        # Mark job as started in database
        mark_job_started('exchange_rates', target_date)
        
        # Import here to avoid circular imports
        from exchange_rates_utils import reload_exchange_rate_for_date, reload_exchange_rates_for_range, get_supabase_client
        
        # 1. Fetch today's rate
        today = datetime.now(timezone.utc)
        rate = reload_exchange_rate_for_date(today, 'USD', 'CAD')
        
        # 2. Check for gaps in the last 30 days
        client = get_supabase_client()
        filled_count = 0
        if client:
            end_lookback = today
            start_lookback = end_lookback - timedelta(days=30)
            
            # Get existing rates in range
            existing_rates = client.get_exchange_rates(start_lookback, end_lookback, 'USD', 'CAD')
            existing_dates = set()
            for r in existing_rates:
                try:
                    dt = datetime.fromisoformat(r['timestamp'].replace('Z', '+00:00'))
                    existing_dates.add(dt.date())
                except:
                    continue
            
            # Check for missing dates (excluding weekends where BoC might not have data)
            missing_range_start = None
            missing_range_end = None
            
            current = start_lookback
            while current <= end_lookback:
                # Is this date missing and not a weekend? (0=Mon, 5=Sat, 6=Sun)
                # Actually BoC has data for weekdays. 
                # If it's missing, let's just try to fetch the whole range from BoC
                # since the range API is efficient and handles its own logic.
                current += timedelta(days=1)
            
            # More efficient: just always refresh the last 30 days from BoC
            # or detect the first missing date.
            # Let's find the most recent date in DB and fill from there to today.
            latest_db_rate = client.supabase.table("exchange_rates") \
                .select("timestamp") \
                .eq("from_currency", "USD") \
                .eq("to_currency", "CAD") \
                .order("timestamp", desc=True) \
                .limit(1) \
                .execute()
                
            if latest_db_rate.data:
                last_dt = datetime.fromisoformat(latest_db_rate.data[0]['timestamp'].replace('Z', '+00:00'))
                if (today - last_dt).days > 1:
                    logger.info(f"Detected gap in exchange rates since {last_dt.date()}. Filling gaps...")
                    filled_count = reload_exchange_rates_for_range(last_dt, today, 'USD', 'CAD')
            else:
                # No data at all? Fetch last 90 days.
                logger.info("No exchange rate data found. Backfilling last 90 days...")
                filled_count = reload_exchange_rates_for_range(today - timedelta(days=90), today, 'USD', 'CAD')
        
        if rate is not None:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Updated USD/CAD rate: {rate}"
            if filled_count > 0:
                message += f" (filled {filled_count} historical gaps)"
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            mark_job_completed('exchange_rates', target_date, None, [], duration_ms=duration_ms)
            logger.info(f"✅ {message}")
        else:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "Failed to fetch today's exchange rate from API"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            mark_job_failed('exchange_rates', target_date, None, message, duration_ms=duration_ms)
            logger.warning(f"⚠️ {message}")
            
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Error: {str(e)}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        try:
            from utils.job_tracking import mark_job_failed
            mark_job_failed('exchange_rates', target_date, None, message, duration_ms=duration_ms)
        except Exception:
            pass  # Don't fail if tracking fails
        logger.error(f"❌ Exchange rates job failed: {e}", exc_info=True)



def _process_performance_metrics_for_date(
    client,
    target_date: date,
    fund_filter: Optional[str] = None,
    skip_existing: bool = False
) -> tuple[int, int, list[str]]:
    """Process performance metrics for a single date.
    
    Args:
        client: SupabaseClient instance
        target_date: Date to process
        fund_filter: Optional fund name to filter by
        skip_existing: If True, skip dates that already have metrics
    
    Returns:
        Tuple of (rows_inserted, rows_skipped, list of fund names processed)
    """
    # Get all funds that have data for target_date
    positions_query = client.supabase.table("portfolio_positions")\
        .select("fund, total_value, cost_basis, pnl, currency, date")\
        .gte("date", f"{target_date}T00:00:00")\
        .lt("date", f"{target_date}T23:59:59.999999")
    
    if fund_filter:
        positions_query = positions_query.eq("fund", fund_filter)
    
    positions_result = positions_query.execute()
    
    if not positions_result.data:
        return (0, 0, [])
    
    # Group by fund and aggregate
    fund_totals = defaultdict(lambda: {
        'total_value': Decimal('0'),
        'cost_basis': Decimal('0'),
        'unrealized_pnl': Decimal('0'),
        'total_trades': 0
    })
    
    # Load exchange rates if needed for USD conversion
    from exchange_rates_utils import get_exchange_rate_for_date_from_db
    
    for pos in positions_result.data:
        fund = pos['fund']
        original_currency = pos.get('currency', 'CAD')
        currency = original_currency
        # Validate currency: treat 'nan', None, or empty strings as 'CAD'
        if not currency or not isinstance(currency, str):
            currency = 'CAD'
            logger.warning(f"⚠️ Position in fund '{fund}' has invalid currency (None/non-string). Defaulting to CAD.")
        else:
            currency = currency.strip().upper()
            if currency in ('NAN', 'NONE', 'NULL', ''):
                logger.warning(f"⚠️ Position in fund '{fund}' ticker '{pos.get('ticker', 'unknown')}' has invalid currency '{original_currency}'. Defaulting to CAD.")
                currency = 'CAD'
        
        # Convert to Decimal for precision
        total_value = Decimal(str(pos.get('total_value', 0) or 0))
        cost_basis = Decimal(str(pos.get('cost_basis', 0) or 0))
        pnl = Decimal(str(pos.get('pnl', 0) or 0))
        
        # Convert USD to CAD if needed
        if currency == 'USD':
            rate = get_exchange_rate_for_date_from_db(
                datetime.combine(target_date, dt_time(0, 0, 0)),
                'USD',
                'CAD'
            )
            if rate:
                rate_decimal = Decimal(str(rate))
                total_value *= rate_decimal
                cost_basis *= rate_decimal
                pnl *= rate_decimal
        
        fund_totals[fund]['total_value'] += total_value
        fund_totals[fund]['cost_basis'] += cost_basis
        fund_totals[fund]['unrealized_pnl'] += pnl
        fund_totals[fund]['total_trades'] += 1
    
    # Insert/update performance_metrics for each fund
    rows_inserted = 0
    rows_skipped = 0
    for fund, totals in fund_totals.items():
        # Check if we should skip existing entries
        if skip_existing:
            existing = client.supabase.table("performance_metrics")\
                .select("id")\
                .eq("fund", fund)\
                .eq("date", str(target_date))\
                .execute()
            
            if existing.data:
                rows_skipped += 1
                continue  # This fund+date already exists, skip
        
        performance_pct = (
            (float(totals['unrealized_pnl']) / float(totals['cost_basis']) * 100)
            if totals['cost_basis'] > 0 else 0.0
        )
        
        # Upsert into performance_metrics
        client.supabase.table("performance_metrics").upsert({
            'fund': fund,
            'date': str(target_date),
            'total_value': float(totals['total_value']),
            'cost_basis': float(totals['cost_basis']),
            'unrealized_pnl': float(totals['unrealized_pnl']),
            'performance_pct': round(performance_pct, 2),
            'total_trades': totals['total_trades'],
            'winning_trades': 0,  # Not calculated in this version
            'losing_trades': 0     # Not calculated in this version
        }, on_conflict='fund,date').execute()
        
        rows_inserted += 1
    
    return (rows_inserted, rows_skipped, list(fund_totals.keys()))


def populate_performance_metrics_job(
    target_date: Optional[date] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    fund_filter: Optional[str] = None,
    skip_existing: bool = False
) -> None:
    """Aggregate daily portfolio performance into performance_metrics table.
    
    This pre-calculates daily metrics to speed up chart queries (90 rows vs 1338 rows).
    By default runs yesterday's data to ensure market close prices are final.
    
    Args:
        target_date: Single date to process. If None, defaults to yesterday.
        from_date: Start of date range (optional). If provided with to_date, processes range.
        to_date: End of date range (optional). If provided with from_date, processes range.
        fund_filter: Optional fund name to filter by. If None, processes all funds.
        skip_existing: If True, skip dates that already have metrics. If False, always upsert.
    """
    job_id = 'performance_metrics'
    start_time = time.time()
    
    try:
        # Import job tracking
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        
        logger.info("Starting performance metrics population job...")
        
        # Import here to avoid circular imports
        from supabase_client import SupabaseClient
        
        # Use service role key to bypass RLS (background job needs full access)
        client = SupabaseClient(use_service_role=True)
        
        # Determine which dates to process
        dates_to_process = []
        
        if from_date and to_date:
            # Date range mode
            if from_date > to_date:
                raise ValueError(f"from_date ({from_date}) must be <= to_date ({to_date})")
            
            # Warn if range is large
            days_in_range = (to_date - from_date).days + 1
            if days_in_range > 30:
                logger.warning(f"⚠️ Processing large date range: {days_in_range} days ({from_date} to {to_date}). This may take a while.")
            
            # Generate list of dates in range
            current_date = from_date
            while current_date <= to_date:
                dates_to_process.append(current_date)
                current_date += timedelta(days=1)
        elif target_date:
            # Single date mode
            dates_to_process = [target_date]
        else:
            # Default: yesterday
            dates_to_process = [(datetime.now(timezone.utc) - timedelta(days=1)).date()]
        
        # Process each date
        total_rows_inserted = 0
        total_rows_skipped = 0
        total_dates_processed = 0
        total_dates_failed = 0
        all_funds_processed = set()
        
        for process_date in dates_to_process:
            try:
                # Mark job as started in database
                mark_job_started('performance_metrics', process_date)
                
                # Process this date
                rows_inserted, rows_skipped, funds = _process_performance_metrics_for_date(
                    client, process_date, fund_filter, skip_existing
                )
                
                if rows_inserted == 0 and rows_skipped == 0:
                    # No data for this date
                    logger.info(f"ℹ️ No position data found for {process_date}")
                    continue
                
                total_rows_inserted += rows_inserted
                total_rows_skipped += rows_skipped
                all_funds_processed.update(funds)
                total_dates_processed += 1
                
                # Log progress for date ranges
                if len(dates_to_process) > 1:
                    logger.info(f"✅ Processed {process_date}: {rows_inserted} inserted, {rows_skipped} skipped")
                
            except Exception as date_error:
                total_dates_failed += 1
                logger.error(f"❌ Error processing {process_date}: {date_error}")
                # Continue with next date even if one fails
                try:
                    mark_job_failed('performance_metrics', process_date, None, str(date_error), 0)
                except Exception:
                    pass
        
        # Final summary
        duration_ms = int((time.time() - start_time) * 1000)
        
        if len(dates_to_process) > 1:
            # Date range summary
            message = f"Processed {total_dates_processed}/{len(dates_to_process)} dates: {total_rows_inserted} fund(s) inserted, {total_rows_skipped} skipped"
            if total_dates_failed > 0:
                message += f", {total_dates_failed} failed"
        else:
            # Single date summary
            process_date = dates_to_process[0]
            if total_rows_skipped > 0:
                message = f"Populated {total_rows_inserted} fund(s) for {process_date} (skipped {total_rows_skipped} existing)"
            else:
                message = f"Populated {total_rows_inserted} fund(s) for {process_date}"
        
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        
        # Mark completion for the last date processed (or first if none processed)
        if dates_to_process:
            mark_job_completed('performance_metrics', dates_to_process[-1], None, list(all_funds_processed), duration_ms=duration_ms)
        
        logger.info(f"✅ {message}")
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Error: {str(e)}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        try:
            from utils.job_tracking import mark_job_failed
            error_date = target_date if target_date else (datetime.now(timezone.utc) - timedelta(days=1)).date()
            mark_job_failed('performance_metrics', error_date, None, message, duration_ms=duration_ms)
        except Exception:
            pass  # Don't fail if tracking fails
        logger.error(f"❌ Performance metrics job failed: {e}", exc_info=True)

