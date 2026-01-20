"""
Job Retry Processor
===================

Processes entries from the job_retry_queue table and retries failed jobs.

This job runs every 15 minutes to:
1. Find pending retries from the queue
2. Re-execute the failed job/date/entity
3. Mark as resolved on success or abandoned after max retries
"""

import logging
from datetime import date, datetime, timedelta
from typing import Optional

# Import log_job_execution at module level so it's always available
from scheduler.scheduler_core import log_job_execution

logger = logging.getLogger(__name__)


def process_retry_queue_job() -> None:
    """
    Process pending retries from the job_retry_queue.
    
    Finds entries with status='pending' and retry_count < max_retries,
    then re-runs the specific job for that date/entity.
    """
    import time
    start_time = time.time()
    job_id = 'process_retry_queue'
    
    try:
        # Add project root to path
        import sys
        from pathlib import Path
        
        project_root = Path(__file__).resolve().parent.parent.parent
        project_root_str = str(project_root)
        
        if project_root_str not in sys.path:
            sys.path.insert(0, project_root_str)
        
        web_dashboard_path = str(Path(__file__).resolve().parent.parent)
        if web_dashboard_path not in sys.path:
            sys.path.insert(0, web_dashboard_path)
        
        from utils.job_tracking import (
            get_pending_retries, mark_retrying, 
            mark_resolved, mark_abandoned
        )
        from scheduler.jobs_portfolio import backfill_portfolio_prices_range
        from supabase_client import SupabaseClient
        
        logger.info("🔄 Starting retry queue processor...")
        
        # OLLAMA CONTENTION CHECK: Skip if any Ollama-using job is currently running
        # These jobs use Ollama and should never run concurrently
        OLLAMA_JOBS = [
            'social_sentiment_ai',
            'analyze_congress_trades', 
            'rescore_congress_sessions',
            'signal_scan'
        ]
        
        try:
            client = SupabaseClient(use_service_role=True)
            running_jobs = client.supabase.table("job_executions")\
                .select("job_name")\
                .eq("status", "running")\
                .in_("job_name", OLLAMA_JOBS)\
                .execute()
            
            if running_jobs.data:
                running_names = [j['job_name'] for j in running_jobs.data]
                duration_ms = int((time.time() - start_time) * 1000)
                message = f"Skipped: Ollama job(s) running: {running_names}"
                log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
                logger.info(f"⏸️  {message}")
                return
        except Exception as check_error:
            logger.warning(f"Could not check for running Ollama jobs: {check_error}")
            # Continue anyway - better to retry than to skip indefinitely
        
        # Get pending retries (max 3 retries, within last 7 days)
        # BATCH LIMIT: Only process 5 items at a time to prevent resource exhaustion
        BATCH_LIMIT = 5
        retries = get_pending_retries(max_retries=3, max_age_days=7, limit=BATCH_LIMIT)

        
        if not retries:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "No pending retries found"
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            logger.info(f"✅ {message}")
            return
        
        logger.info(f"Found {len(retries)} pending retry entries (limit: {BATCH_LIMIT})")
        
        # Track results
        resolved_count = 0
        failed_count = 0
        abandoned_count = 0
        
        # Process each retry
        for retry in retries:
            job_name = retry['job_name']
            target_date_str = retry.get('target_date')
            entity_id = retry.get('entity_id')
            entity_type = retry.get('entity_type', 'fund')
            retry_count = retry.get('retry_count', 0)
            failure_reason = retry.get('failure_reason', 'unknown')
            
            # Convert empty string to None for entity_id
            if entity_id == '':
                entity_id = None
            
            # Parse target_date
            if target_date_str:
                target_date = datetime.fromisoformat(target_date_str).date()
            else:
                logger.warning(f"⚠️  Skipping retry with no target_date: {retry}")
                continue
            
            logger.info(f"  Retrying: {job_name} {target_date} {entity_id or 'all_funds'} (attempt #{retry_count + 1}, reason: {failure_reason})")
            
            # Mark as retrying
            mark_retrying(job_name, target_date, entity_id, entity_type)
            
            try:
                # Re-run the specific job for this date/entity
                if job_name == 'update_portfolio_prices':
                    # Retry the backfill for this specific date
                    backfill_portfolio_prices_range(target_date, target_date)
                    
                    # Success - mark as resolved
                    mark_resolved(job_name, target_date, entity_id, entity_type)
                    resolved_count += 1
                    logger.info(f"  ✅ Retry succeeded: {job_name} {target_date} {entity_id or 'all_funds'}")
                    
                else:
                    # Unknown job type - mark as abandoned
                    logger.warning(f"  ⚠️  Unknown job type: {job_name} - marking as abandoned")
                    mark_abandoned(job_name, target_date, entity_id, entity_type)
                    abandoned_count += 1
                    
            except Exception as e:
                logger.error(f"  ❌ Retry failed: {job_name} {target_date} {entity_id or 'all_funds'}: {e}")
                
                # Check if max retries exceeded
                if retry_count + 1 >= 3:
                    mark_abandoned(job_name, target_date, entity_id, entity_type)
                    abandoned_count += 1
                    logger.warning(f"  ⚠️  Abandoned after {retry_count + 1} retries: {job_name} {target_date} {entity_id or 'all_funds'}")
                else:
                    failed_count += 1
                    # Status reverts to 'pending' automatically for next retry
        
        # Summary
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Processed {len(retries)} retries: {resolved_count} resolved, {failed_count} failed, {abandoned_count} abandoned"
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        logger.info(f"✅ {message} in {duration_ms/1000:.2f}s")
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Error: {str(e)}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        logger.error(f"❌ Retry queue processor failed: {e}", exc_info=True)
