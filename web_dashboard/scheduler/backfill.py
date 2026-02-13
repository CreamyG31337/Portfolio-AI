"""
Smart Backfill System for Portfolio Positions
==============================================

Automatically fills gaps in portfolio_positions data between first trade and today.
Runs on scheduler startup to catch downtime/reboots.

USES JOB COMPLETION TRACKING: Checks job_executions table instead of portfolio data
to detect incomplete runs where Docker was stopped mid-job.
"""

import logging
from datetime import datetime, timedelta, date, time as dt_time
from typing import Optional
import pandas as pd

logger = logging.getLogger(__name__)


def startup_backfill_check() -> None:
    """
    Smart backfill: Checks job completion status for each trading day.
    Much faster than per-fund checks and detects crashed/failed jobs.
    
    Edge cases handled:
    - New installation (no trades) → Returns immediately
    - Crashed jobs → Detected by status='running' for old dates  
    - Failed jobs → Detected by status='failed'
    - Missing jobs → No record in job_executions
    """
    try:
        # Add project root to path for imports (same pattern as jobs.py)
        import sys
        from pathlib import Path
        
        # Get absolute paths
        project_root = Path(__file__).resolve().parent.parent.parent
        project_root_str = str(project_root)
        
        if project_root_str not in sys.path:
            sys.path.insert(0, project_root_str)
        
        # Also add web_dashboard to path
        web_dashboard_path = str(Path(__file__).resolve().parent.parent)
        if web_dashboard_path not in sys.path:
            sys.path.insert(0, web_dashboard_path)
        
        from supabase_client import SupabaseClient
        
        # Defensive imports with retry logic
        try:
            from utils.market_holidays import MarketHolidays
        except ModuleNotFoundError:
            if project_root_str not in sys.path:
                sys.path.insert(0, project_root_str)
            from utils.market_holidays import MarketHolidays
        
        try:
            from scheduler.jobs import update_portfolio_prices_job
        except ModuleNotFoundError:
            if web_dashboard_path not in sys.path:
                sys.path.insert(0, web_dashboard_path)
            from scheduler.jobs import update_portfolio_prices_job
        
        try:
            from utils.job_tracking import is_job_completed
        except ModuleNotFoundError:
            if project_root_str not in sys.path:
                sys.path.insert(0, project_root_str)
            from utils.job_tracking import is_job_completed
        
        # Use service role key to bypass RLS (background job needs full access)
        client = SupabaseClient(use_service_role=True)
        market_holidays = MarketHolidays()

        
        logger.info("🔍 Starting smart backfill check (job completion validation)...")
        
        # 1. Get all production funds to find earliest trade
        funds_result = client.supabase.table("funds")\
            .select("name")\
            .eq("is_production", True)\
            .execute()
            
        if not funds_result.data:
            logger.info("✅ No production funds found - skipping backfill")
            return
        
        fund_names = [f['name'] for f in funds_result.data]
        logger.info(f"   Checking {len(fund_names)} production funds: {fund_names}")
        
        # 2. Find earliest trade across ALL production funds
        earliest_trade_date = None
        for fund_name in fund_names:
            trades_result = client.supabase.table("trade_log")\
                .select("date")\
                .eq("fund", fund_name)\
                .order("date")\
                .limit(1)\
                .execute()
            
            if trades_result.data:
                fund_earliest = pd.to_datetime(trades_result.data[0]['date']).date()
                if earliest_trade_date is None or fund_earliest < earliest_trade_date:
                    earliest_trade_date = fund_earliest
        
        if earliest_trade_date is None:
            logger.info("✅ No trades found - skipping backfill (new installation)")
            return
        
        logger.info(f"   Earliest trade across all funds: {earliest_trade_date}")
        
        # 3. Find the most recent date where DATA EXISTS (our checkpoint)
        #    We only need to process dates AFTER this checkpoint
        #    Note: We check data existence only, not job completion, because job tracking is newer
        
        # CRITICAL: Use ET timezone for 'today' to match market hours
        # Using server time (UTC) causes wrong date selection on cloud servers
        import pytz
        et = pytz.timezone('America/New_York')
        today = datetime.now(et).date()
        
        checkpoint_date = None
        
        # Start from today and work backwards to find last date with data
        check_date = today
        while check_date >= earliest_trade_date:
            if market_holidays.is_trading_day(check_date, market="any"):
                # Check if portfolio data exists for this date
                try:
                    start_of_day = datetime.combine(check_date, dt_time(0, 0, 0)).isoformat()
                    end_of_day = datetime.combine(check_date, dt_time(23, 59, 59, 999999)).isoformat()
                    
                    result = client.supabase.table("portfolio_positions")\
                        .select("id", count='exact')\
                        .gte("date", start_of_day)\
                        .lt("date", end_of_day)\
                        .in_("fund", fund_names)\
                        .limit(1)\
                        .execute()
                    
                    data_exists = (result.count and result.count > 0)
                except:
                    data_exists = False
                
                # Found our checkpoint - last date with data!
                if data_exists:
                    checkpoint_date = check_date
                    logger.info(f"   Found checkpoint: {checkpoint_date} (data exists)")
                    break
            
            check_date -= timedelta(days=1)
            
            # Don't search more than 30 days back (performance)
            if (today - check_date).days > 30:
                logger.info("   No data found in last 30 days - will process from earliest trade")
                checkpoint_date = earliest_trade_date - timedelta(days=1)
                break
        
        if checkpoint_date is None:
            # No checkpoint found at all
            checkpoint_date = earliest_trade_date - timedelta(days=1)
            logger.info("   No checkpoint found - will process all dates from earliest trade")
        
        # 4. Now collect all dates AFTER checkpoint that need processing
        missing_days = []
        current = checkpoint_date + timedelta(days=1)  # Start day after checkpoint
        
        # Import market hours for market open check (defensive)
        try:
            from market_data.market_hours import MarketHours
        except ModuleNotFoundError:
            if project_root_str not in sys.path:
                sys.path.insert(0, project_root_str)
            from market_data.market_hours import MarketHours
        
        market_hours = MarketHours()
        
        while current <= today:
            if market_holidays.is_trading_day(current, market="any"):
                # CRITICAL: Skip TODAY if market hasn't opened yet
                # We should NOT create data for a date until the market has opened for that day
                if current == today:
                    now_et = datetime.now(et)
                    market_open_time = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
                    
                    # If it's before 9:30 AM ET, market hasn't opened yet - skip today
                    if now_et < market_open_time:
                        logger.info(f"   {current}: Market hasn't opened yet (current: {now_et.strftime('%I:%M %p ET')}, opens: 9:30 AM ET) - skipping")
                        # Don't add today to missing_days - we'll process it after market opens
                        current += timedelta(days=1)
                        continue
                
                # Check if this date needs processing
                job_completed = is_job_completed('update_portfolio_prices', current)
                
                # Check data existence
                data_exists = False
                try:
                    start_of_day = datetime.combine(current, dt_time(0, 0, 0)).isoformat()
                    end_of_day = datetime.combine(current, dt_time(23, 59, 59, 999999)).isoformat()
                    
                    result = client.supabase.table("portfolio_positions")\
                        .select("id", count='exact')\
                        .gte("date", start_of_day)\
                        .lt("date", end_of_day)\
                        .in_("fund", fund_names)\
                        .limit(1)\
                        .execute()
                    
                    data_exists = (result.count and result.count > 0)
                except Exception as e:
                    logger.warning(f"Could not check data existence for {current}: {e}")
                    data_exists = False
                
                # Re-run if job incomplete OR data missing
                if not job_completed or not data_exists:
                    missing_days.append(current)
                    if job_completed and not data_exists:
                        logger.info(f"   {current}: Job completed but data missing - will re-run")
                    elif not job_completed and data_exists:
                        logger.info(f"   {current}: Data exists but job incomplete - will re-run")
                    elif not job_completed and not data_exists:
                        logger.info(f"   {current}: Both job and data missing - will re-run")
            
            current += timedelta(days=1)
        
        if not missing_days:
            logger.info("✅ All trading days have completed jobs AND data - no backfill needed")
            return
        
        logger.warning(f"⚠️  Found {len(missing_days)} days with incomplete/missing jobs")
        logger.info(f"   Date range: {missing_days[0]} to {missing_days[-1]}")
        
        # 4. OPTIMIZATION: Group consecutive days into ranges for batch processing
        # This reduces API calls from O(Days * Tickers) to O(Tickers)
        date_ranges = []
        if missing_days:
            range_start = missing_days[0]
            range_end = missing_days[0]
            
            for i in range(1, len(missing_days)):
                current_day = missing_days[i]
                # Check if current day is consecutive (next day after range_end)
                if (current_day - range_end).days == 1:
                    # Extend current range
                    range_end = current_day
                else:
                    # Save current range and start new one
                    date_ranges.append((range_start, range_end))
                    range_start = current_day
                    range_end = current_day
            
            # Don't forget the last range
            date_ranges.append((range_start, range_end))
        
        logger.info(f"   Grouped into {len(date_ranges)} date range(s) for batch processing")
        
        # 5. Process each range using batch backfill
        success_count = 0
        fail_count = 0
        
        for range_start, range_end in date_ranges:
            try:
                if range_start == range_end:
                    logger.info(f"   Backfilling single day: {range_start}...")
                else:
                    logger.info(f"   Backfilling date range: {range_start} to {range_end}...")
                
                from scheduler.jobs import backfill_portfolio_prices_range
                backfill_portfolio_prices_range(range_start, range_end)
                
                # Count days in this range
                days_in_range = (range_end - range_start).days + 1
                success_count += days_in_range
            except Exception as e:
                logger.error(f"   ❌ Failed to backfill range {range_start} to {range_end}: {e}")
                days_in_range = (range_end - range_start).days + 1
                fail_count += days_in_range
                # Continue with next range even if one fails
        
        logger.info(f"✅ Backfill complete: {success_count} days succeeded, {fail_count} days failed")
        
    except Exception as e:
        logger.error(f"❌ Backfill check failed: {e}", exc_info=True)
        # Don't crash the scheduler if backfill fails


def startup_performance_metrics_backfill() -> None:
    """
    Detect and fill gaps in performance_metrics by comparing against portfolio_positions.
    
    Runs on startup (with delay) to ensure performance_metrics has data for every date
    that portfolio_positions has data for. This prevents the dashboard chart from showing
    gaps when the optimized metrics path is used.
    
    Only checks the last 90 days to keep startup fast.
    """
    try:
        import sys
        from pathlib import Path
        
        project_root = Path(__file__).resolve().parent.parent.parent
        project_root_str = str(project_root)
        if project_root_str not in sys.path:
            sys.path.insert(0, project_root_str)
        
        web_dashboard_path = str(Path(__file__).resolve().parent.parent)
        if web_dashboard_path not in sys.path:
            sys.path.insert(0, web_dashboard_path)
        
        from supabase_client import SupabaseClient
        
        logger.info("🔍 Starting performance_metrics gap detection...")
        
        client = SupabaseClient(use_service_role=True)
        
        # Get production funds
        funds_result = client.supabase.table("funds")\
            .select("name")\
            .eq("is_production", True)\
            .execute()
        
        if not funds_result.data:
            logger.info("✅ No production funds - skipping performance metrics backfill")
            return
        
        fund_names = [f['name'] for f in funds_result.data]
        
        # Only check last 90 days
        import pytz
        et = pytz.timezone('America/New_York')
        cutoff_date = (datetime.now(et) - timedelta(days=90)).date()
        
        # Get all dates from portfolio_positions (after cutoff)
        pp_dates_by_fund: dict[str, set] = {}
        for fund_name in fund_names:
            result = client.supabase.table("portfolio_positions")\
                .select("date")\
                .eq("fund", fund_name)\
                .gte("date", cutoff_date.isoformat())\
                .execute()
            
            if result.data:
                dates = set()
                for row in result.data:
                    dt = pd.to_datetime(row['date']).date()
                    dates.add(dt)
                pp_dates_by_fund[fund_name] = dates
        
        if not pp_dates_by_fund:
            logger.info("✅ No portfolio_positions data in last 90 days - skipping")
            return
        
        # Get all dates from performance_metrics (after cutoff)
        pm_dates_by_fund: dict[str, set] = {}
        for fund_name in fund_names:
            result = client.supabase.table("performance_metrics")\
                .select("date")\
                .eq("fund", fund_name)\
                .gte("date", cutoff_date.isoformat())\
                .execute()
            
            if result.data:
                dates = set()
                for row in result.data:
                    dt = pd.to_datetime(row['date']).date()
                    dates.add(dt)
                pm_dates_by_fund[fund_name] = dates
        
        # Find missing dates (in portfolio_positions but not in performance_metrics)
        all_missing_dates: set = set()
        for fund_name in fund_names:
            pp_dates = pp_dates_by_fund.get(fund_name, set())
            pm_dates = pm_dates_by_fund.get(fund_name, set())
            missing = pp_dates - pm_dates
            
            if missing:
                logger.info(f"   {fund_name}: {len(missing)} dates missing from performance_metrics")
                all_missing_dates.update(missing)
        
        if not all_missing_dates:
            logger.info("✅ performance_metrics is complete - no gaps found")
            return
        
        logger.warning(f"⚠️  Found {len(all_missing_dates)} unique dates with missing performance_metrics")
        
        # Import the backfill function
        try:
            from scheduler.jobs_metrics import populate_performance_metrics_job
        except ModuleNotFoundError:
            if web_dashboard_path not in sys.path:
                sys.path.insert(0, web_dashboard_path)
            from scheduler.jobs_metrics import populate_performance_metrics_job
        
        # Process each missing date
        success_count = 0
        fail_count = 0
        
        for target_date in sorted(all_missing_dates):
            try:
                populate_performance_metrics_job(
                    target_date=target_date,
                    skip_existing=True
                )
                success_count += 1
            except Exception as e:
                logger.error(f"   ❌ Failed to backfill performance_metrics for {target_date}: {e}")
                fail_count += 1
        
        logger.info(
            f"✅ Performance metrics backfill complete: "
            f"{success_count} dates succeeded, {fail_count} dates failed"
        )
        
    except Exception as e:
        logger.error(f"❌ Performance metrics backfill check failed: {e}", exc_info=True)
