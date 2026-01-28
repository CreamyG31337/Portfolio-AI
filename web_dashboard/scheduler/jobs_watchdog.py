"""
Job Retry Watchdog
==================

Periodic watchdog job that:
1. Detects stale running jobs (container restart)
2. Detects recent failed jobs
3. Processes retry queue
4. Validates data for critical jobs
"""

import logging
import time
from datetime import datetime, timedelta, date, time as dt_time
from typing import Optional, Dict, Any, List
import sys
from pathlib import Path

# Add project root to path for utils imports
current_dir = Path(__file__).resolve().parent
if current_dir.name == 'scheduler':
    project_root = current_dir.parent.parent
else:
    project_root = current_dir.parent.parent

# CRITICAL: Project root must be FIRST in sys.path to ensure utils.job_tracking
# is found from the project root, not from web_dashboard/utils
# Force project root to be at index 0, removing it first if it exists elsewhere
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

# Import job_tracking - path should be set up correctly now
# Clear any cached import failures for utils.job_tracking
if 'utils.job_tracking' in sys.modules:
    del sys.modules['utils.job_tracking']
if 'utils' in sys.modules:
    # Only remove utils if it's from the wrong location (web_dashboard/utils)
    utils_module = sys.modules.get('utils')
    if utils_module and hasattr(utils_module, '__file__'):
        utils_file = Path(utils_module.__file__).resolve() if utils_module.__file__ else None
        if utils_file and 'web_dashboard' in str(utils_file):
            del sys.modules['utils']

try:
    from utils.job_tracking import (
        add_to_retry_queue,
        get_pending_retries,
        mark_retrying,
        mark_resolved,
        mark_abandoned,
        is_calculation_job,
        mark_job_failed
    )
except ImportError as e:
    # Last resort: try to fix path and import again
    # Remove any existing project_root and web_dashboard from path
    project_root_str = str(project_root)
    web_dashboard_str = str(web_dashboard_path)
    if project_root_str in sys.path:
        sys.path.remove(project_root_str)
    if web_dashboard_str in sys.path:
        sys.path.remove(web_dashboard_str)
    # Insert in correct order
    sys.path.insert(0, project_root_str)
    if len(sys.path) > 1:
        sys.path.insert(1, web_dashboard_str)
    else:
        sys.path.append(web_dashboard_str)
    
    # Clear module cache again
    if 'utils.job_tracking' in sys.modules:
        del sys.modules['utils.job_tracking']
    if 'utils' in sys.modules:
        utils_module = sys.modules.get('utils')
        if utils_module and hasattr(utils_module, '__file__'):
            utils_file = Path(utils_module.__file__).resolve() if utils_module.__file__ else None
            if utils_file and 'web_dashboard' in str(utils_file):
                del sys.modules['utils']
    
    # Try import one more time
    from utils.job_tracking import (
        add_to_retry_queue,
        get_pending_retries,
        mark_retrying,
        mark_resolved,
        mark_abandoned,
        is_calculation_job,
        mark_job_failed
    )
from utils.market_holidays import MarketHolidays

logger = logging.getLogger(__name__)


def watchdog_job() -> None:
    """
    Periodic watchdog that checks for missed/failed jobs and retries them.
    Runs every 30-60 minutes to catch failures quickly.
    """
    job_id = 'watchdog'
    start_time = time.time()
    
    # Import job tracking at the start
    from datetime import timezone
    target_date = datetime.now(timezone.utc).date()
    
    try:
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed as tracking_mark_failed
        mark_job_started(job_id, target_date)
    except Exception as e:
        logger.warning(f"Could not mark job started: {e}")
    
    try:
        logger.info("🔍 Starting watchdog job check...")
        
        # 1. Detect stale running jobs (container restart)
        detect_stale_running_jobs()
        
        # 2. Detect recent failed jobs
        detect_recent_failed_jobs()
        
        # 3. Process retry queue
        process_retry_queue()
        
        # 4. Validate critical jobs (data exists check)
        validate_critical_jobs()
        
        duration_ms = int((time.time() - start_time) * 1000)
        message = "Watchdog check complete"
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        try:
            mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms)
        except:
            pass
        logger.info(f"✅ {message} in {duration_ms}ms")
        
    except Exception as error:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Watchdog job failed: {str(error)}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        try:
            tracking_mark_failed(job_id, target_date, None, message, duration_ms=duration_ms)
        except:
            pass
        logger.error(f"❌ {message}", exc_info=True)


def detect_stale_running_jobs() -> None:
    """
    Find jobs with status='running' older than 1 hour (likely container restart).
    Mark as failed and add to retry queue if calculation job.
    """
    try:
        from supabase_client import SupabaseClient
        client = SupabaseClient(use_service_role=True)
        
        # Find stale running jobs (older than 1 hour)
        from datetime import timezone
        cutoff_time = datetime.now(timezone.utc).timestamp() - (1 * 3600)  # 1 hour ago
        cutoff_dt = datetime.fromtimestamp(cutoff_time, tz=timezone.utc)
        
        result = client.supabase.table("job_executions")\
            .select("id, job_name, target_date, fund_name, started_at")\
            .eq("status", "running")\
            .lt("started_at", cutoff_dt.isoformat())\
            .execute()
        
        if not result.data:
            return
        
        logger.warning(f"Found {len(result.data)} stale running job(s)")
        
        for job in result.data:
            job_name = job['job_name']
            target_date_str = job.get('target_date')
            fund_name = job.get('fund_name') or None
            started_at_str = job.get('started_at')
            
            if not target_date_str:
                logger.warning(f"  Skipping {job_name} - no target_date")
                continue
            
            try:
                target_date = datetime.fromisoformat(target_date_str).date()
            except Exception:
                logger.warning(f"  Skipping {job_name} - invalid target_date: {target_date_str}")
                continue
            
            # Calculate duration if started_at is available
            duration_info = ""
            if started_at_str:
                try:
                    if isinstance(started_at_str, str):
                        started_dt = datetime.fromisoformat(started_at_str.replace('Z', '+00:00'))
                    else:
                        started_dt = started_at_str
                    
                    if started_dt.tzinfo is None:
                        started_dt = started_dt.replace(tzinfo=timezone.utc)
                    else:
                        started_dt = started_dt.astimezone(timezone.utc)
                    
                    now = datetime.now(timezone.utc)
                    duration_seconds = (now - started_dt).total_seconds()
                    duration_minutes = duration_seconds / 60
                    duration_hours = duration_minutes / 60
                    
                    if duration_hours >= 1:
                        duration_info = f" (ran for {duration_hours:.1f} hours)"
                    elif duration_minutes >= 1:
                        duration_info = f" (ran for {duration_minutes:.1f} minutes)"
                    else:
                        duration_info = f" (ran for {duration_seconds:.0f} seconds)"
                except Exception as e:
                    logger.debug(f"Could not calculate duration for {job_name}: {e}")
            
            # Mark as failed in job_executions
            error_message = f"Container restarted - job interrupted{duration_info}"
            try:
                mark_job_failed(
                    job_name=job_name,
                    target_date=target_date,
                    fund_name=fund_name,
                    error=error_message
                )
            except Exception as e:
                logger.warning(f"  Failed to mark {job_name} as failed: {e}")
            
            # Add to retry queue if calculation job
            if is_calculation_job(job_name):
                try:
                    entity_id = fund_name if fund_name else None
                    entity_type = 'fund' if fund_name else 'all_funds'
                    
                    add_to_retry_queue(
                        job_name=job_name,
                        target_date=target_date,
                        entity_id=entity_id,
                        entity_type=entity_type,
                        failure_reason='container_restart',
                        error_message='Job interrupted by container restart'
                    )
                    logger.info(f"  📝 Added {job_name} {target_date} to retry queue")
                except Exception as e:
                    logger.error(f"  ❌ Failed to add {job_name} to retry queue: {e}")
        
    except Exception as e:
        logger.warning(f"Failed to detect stale running jobs: {e}")


def detect_recent_failed_jobs() -> None:
    """
    Find jobs with status='failed' in last 24 hours.
    Add to retry queue if calculation job and not already queued.
    """
    try:
        from supabase_client import SupabaseClient
        client = SupabaseClient(use_service_role=True)
        
        # Find failed jobs in last 24 hours
        from datetime import timezone
        cutoff_time = datetime.now(timezone.utc).timestamp() - (24 * 3600)  # 24 hours ago
        cutoff_dt = datetime.fromtimestamp(cutoff_time, tz=timezone.utc)
        
        result = client.supabase.table("job_executions")\
            .select("job_name, target_date, fund_name, error_message")\
            .eq("status", "failed")\
            .gte("completed_at", cutoff_dt.isoformat())\
            .execute()
        
        if not result.data:
            return
        
        logger.info(f"Found {len(result.data)} recent failed job(s)")
        
        for job in result.data:
            job_name = job['job_name']
            
            # Only retry calculation jobs
            if not is_calculation_job(job_name):
                continue
            
            target_date_str = job.get('target_date')
            if not target_date_str:
                continue
            
            try:
                target_date = datetime.fromisoformat(target_date_str).date()
            except Exception:
                continue
            
            fund_name = job.get('fund_name') or None
            error_message = job.get('error_message', 'Job failed')
            
            # Check if already in retry queue
            entity_id = fund_name if fund_name else None
            entity_type = 'fund' if fund_name else 'all_funds'
            
            try:
                # Check if already pending/retrying
                check_result = client.supabase.table("job_retry_queue")\
                    .select("id")\
                    .eq("job_name", job_name)\
                    .eq("target_date", target_date.isoformat())\
                    .eq("entity_id", entity_id if entity_id else '')\
                    .eq("entity_type", entity_type)\
                    .in_("status", ["pending", "retrying"])\
                    .execute()
                
                if check_result.data:
                    continue  # Already in queue
                
                # Add to retry queue
                add_to_retry_queue(
                    job_name=job_name,
                    target_date=target_date,
                    entity_id=entity_id,
                    entity_type=entity_type,
                    failure_reason='job_failed',
                    error_message=error_message[:200]
                )
                logger.info(f"  📝 Added {job_name} {target_date} to retry queue")
            except Exception as e:
                logger.error(f"  ❌ Failed to add {job_name} to retry queue: {e}")
        
    except Exception as e:
        logger.warning(f"Failed to detect recent failed jobs: {e}")


def process_retry_queue() -> None:
    """
    Process pending retries from job_retry_queue table.
    Routes to appropriate job function based on job_name.
    """
    pending = get_pending_retries(max_retries=3, max_age_days=7)
    
    if not pending:
        return
    
    logger.info(f"Processing {len(pending)} pending retry(ies)...")
    
    for retry in pending:
        job_name = retry['job_name']
        target_date_str = retry.get('target_date')
        entity_id = retry.get('entity_id') or None
        entity_type = retry.get('entity_type', 'fund')
        
        if not target_date_str:
            logger.warning(f"  Skipping {job_name} - no target_date")
            continue
        
        try:
            target_date = datetime.fromisoformat(target_date_str).date()
        except Exception:
            logger.warning(f"  Skipping {job_name} - invalid target_date: {target_date_str}")
            continue
        
        # Mark as retrying
        try:
            mark_retrying(job_name, target_date, entity_id, entity_type)
        except Exception as e:
            logger.error(f"  ❌ Failed to mark {job_name} {target_date} as retrying: {e}")
            continue
        
        # Route to appropriate job function
        try:
            success = False
            
            if job_name == 'update_portfolio_prices':
                from scheduler.jobs_portfolio import update_portfolio_prices_job
                update_portfolio_prices_job(target_date=target_date)
                success = True
                
            elif job_name == 'performance_metrics':
                from scheduler.jobs_metrics import populate_performance_metrics_job
                populate_performance_metrics_job(target_date=target_date)
                success = True
                
            elif job_name == 'dividend_processing':
                from scheduler.jobs_dividends import process_dividends_job
                process_dividends_job(lookback_days=7)
                success = True
                
            else:
                logger.warning(f"  ⚠️  Unknown job type: {job_name}")
                continue
            
            if success:
                # Mark as resolved
                mark_resolved(job_name, target_date, entity_id, entity_type)
                logger.info(f"  ✅ Retry succeeded for {job_name} {target_date}")
            else:
                # Increment retry count (will be handled by mark_retrying on next attempt)
                logger.warning(f"  ⚠️  Retry returned False for {job_name} {target_date}")
                
        except Exception as retry_error:
            # Check retry count
            retry_count = retry.get('retry_count', 0) + 1  # Already incremented by mark_retrying
            
            if retry_count >= 3:
                mark_abandoned(job_name, target_date, entity_id, entity_type)
                logger.error(f"  ❌ Abandoned {job_name} {target_date} after 3 retries: {retry_error}")
            else:
                # Reset to pending for next retry
                try:
                    from supabase_client import SupabaseClient
                    client = SupabaseClient(use_service_role=True)
                    effective_entity_id = entity_id if entity_id is not None else ''
                    client.supabase.table("job_retry_queue")\
                        .update({'status': 'pending'})\
                        .eq("job_name", job_name)\
                        .eq("target_date", target_date.isoformat())\
                        .eq("entity_id", effective_entity_id)\
                        .eq("entity_type", entity_type)\
                        .execute()
                except Exception as e:
                    logger.error(f"  ❌ Failed to reset status: {e}")
                
                logger.warning(f"  ⚠️  Retry failed for {job_name} {target_date} (attempt {retry_count}/3): {retry_error}")


def validate_critical_jobs() -> None:
    """
    Validate that completed jobs actually have data.
    Catches cases where job was marked complete but data insert failed.
    """
    try:
        from supabase_client import SupabaseClient
        client = SupabaseClient(use_service_role=True)
        market_holidays = MarketHolidays()
        
        # For update_portfolio_prices: check last 7 trading days
        today = datetime.now().date()
        recent_dates = []
        check_date = today
        days_checked = 0
        
        while days_checked < 7 and check_date >= today - timedelta(days=14):
            if market_holidays.is_trading_day(check_date, market="any"):
                recent_dates.append(check_date)
                days_checked += 1
            check_date -= timedelta(days=1)
        
        if not recent_dates:
            return
        
        logger.info(f"Validating {len(recent_dates)} recent trading days...")
        
        # Get all production funds
        funds_result = client.supabase.table("funds")\
            .select("name")\
            .eq("is_production", True)\
            .execute()
        
        if not funds_result.data:
            return
        
        fund_names = [f['name'] for f in funds_result.data]
        
        for check_date in recent_dates:
            # Check if job marked as completed
            from utils.job_tracking import is_job_completed
            if not is_job_completed('update_portfolio_prices', check_date):
                continue
            
            # Verify data actually exists
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
                
                if not data_exists:
                    # Job marked complete but data missing - add to retry queue
                    logger.warning(f"  ⚠️  {check_date}: Job completed but data missing")
                    add_to_retry_queue(
                        job_name='update_portfolio_prices',
                        target_date=check_date,
                        entity_id=None,
                        entity_type='all_funds',
                        failure_reason='validation_failed',
                        error_message='Job completed but data missing from database'
                    )
                    logger.info(f"  📝 Added {check_date} to retry queue (validation failed)")
                    
            except Exception as e:
                logger.warning(f"  ⚠️  {check_date}: Could not validate data existence: {e}")
        
    except Exception as e:
        logger.warning(f"Failed to validate critical jobs: {e}")

