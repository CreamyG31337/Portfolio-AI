"""
Job Execution Tracking Utilities
=================================

Centralized functions for tracking job execution status across web dashboard
and console app. Enables detection of incomplete runs when Docker crashes.

Usage:
    from utils.job_tracking import mark_job_started, mark_job_completed
    
    mark_job_started('update_portfolio_prices', target_date)
    try:
        # ... process data ...
        mark_job_completed('update_portfolio_prices', target_date, None, funds_completed)
    except Exception as e:
        mark_job_failed('update_portfolio_prices', target_date, None, str(e))
        raise
"""

import logging
from datetime import date, datetime, timezone
from typing import List, Optional, Dict, Any
import sys
import os
from pathlib import Path

# Add web_dashboard to path for supabase_client imports
# This ensures job_tracking can import supabase_client regardless of execution context
# IMPORTANT: Insert web_dashboard AFTER project root to avoid shadowing utils package
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent
web_dashboard_dir = project_root / 'web_dashboard'
if str(web_dashboard_dir) not in sys.path:
    # Insert at index 1 (after project root) if project root is at index 0
    if sys.path and sys.path[0] == str(project_root):
        sys.path.insert(1, str(web_dashboard_dir))
    else:
        sys.path.insert(0, str(web_dashboard_dir))

logger = logging.getLogger(__name__)

AI_JOB_NAMES = {
    # Research/news ingestion jobs (high AI usage, can overlap on same URLs)
    'market_research',
    'ticker_research',
    'opportunity_discovery',
    'alpha_research',
    'ticker_analysis',
    'etf_group_analysis',
    'analyze_congress_trades',
    'rescore_congress_sessions',
    'social_sentiment',
    'social_sentiment_ai',
    'signal_scan',
    'ticker_meta_analysis',
    'sector_meta_analysis',
    'market_daily_brief',
    'action_queue_ai_review',
    'insights_thesis_evaluation',
    'ui_ai_summaries',
}

AI_JOB_MAX_AGE_HOURS: Dict[str, int] = {
    # Longer-running heavy jobs.
    'ticker_analysis': 3,
    'etf_group_analysis': 2,
    'sector_meta_analysis': 2,
    'ticker_research': 2,
    'market_research': 2,
    # Most other AI jobs should finish well within an hour.
}


# ---------------------------------------------------------------------------
# Queue-managed job detection (Q3, 2026-05-23)
# ---------------------------------------------------------------------------
#
# `is_queue_managed_job(job_id)` is the single source of truth for "does this
# job route through the AI task queue?". Scheduler-side callers use it to skip
# the global AI mutex check (`get_running_ai_job`) for jobs whose work is
# actually executed by the embedded worker pool in
# ``web_dashboard/scheduler/ai_task_workers.py``.
#
# The parsing here MUST stay byte-for-byte equivalent to
# ``AIQueueConfig.from_env`` in ``ai_task_workers.py`` so that a single env
# var (`AI_QUEUE_JOBS`) controls both worker activation and global-lock
# bypass. ``tests/test_job_tracking_queue_managed.py`` asserts that the two
# implementations agree across whitespace / casing / boolean variants.
_QUEUE_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def _parse_ai_queue_enabled(value: str | None) -> bool:
    """Mirror ``AIQueueConfig.from_env`` boolean parsing for AI_QUEUE_ENABLED."""
    if value is None:
        return False
    return value.strip().lower() in _QUEUE_TRUE_VALUES


def _parse_ai_queue_jobs(value: str | None) -> tuple[str, ...]:
    """Mirror ``AIQueueConfig.from_env`` CSV parsing for AI_QUEUE_JOBS."""
    if not value:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def is_queue_managed_job(job_id: str | None) -> bool:
    """Return True when ``job_id`` opted into the AI task queue.

    A job is "queue-managed" when both:

    - ``AI_QUEUE_ENABLED`` is truthy ("1"/"true"/"yes"/"on", case-insensitive)
    - ``job_id`` (after stripping) appears in the ``AI_QUEUE_JOBS`` CSV list

    Queue-managed jobs do not respect the global AI mutex
    (``get_running_ai_job``) because their actual LLM work runs in the
    backend-bound worker pool, which leases tasks atomically.

    Returns False on empty/None ``job_id``.
    """
    if not job_id:
        return False
    normalized = job_id.strip()
    if not normalized:
        return False
    if not _parse_ai_queue_enabled(os.environ.get("AI_QUEUE_ENABLED")):
        return False
    return normalized in _parse_ai_queue_jobs(os.environ.get("AI_QUEUE_JOBS"))


def mark_job_started(
    job_name: str,
    target_date: date,
    fund_name: Optional[str] = None
) -> None:
    """
    Mark a job as started (status='running').
    
    Args:
        job_name: Name of the job (e.g., 'update_portfolio_prices')
        target_date: Date the job is processing
        fund_name: Specific fund being processed, None if all funds
    """
    try:
        from supabase_client import SupabaseClient
    except ImportError:
        # Try relative import from web_dashboard
        import sys
        from pathlib import Path
        current_file = Path(__file__).resolve()
        web_dashboard_dir = current_file.parent.parent / 'web_dashboard'
        if str(web_dashboard_dir) not in sys.path:
            sys.path.insert(0, str(web_dashboard_dir))
        from supabase_client import SupabaseClient
    
    try:
        client = SupabaseClient(use_service_role=True)
        # Use empty string instead of None for fund_name to avoid PostgreSQL NULL uniqueness issue
        # PostgreSQL treats NULL != NULL, so UNIQUE constraint doesn't prevent duplicates with NULLs
        effective_fund_name = fund_name if fund_name is not None else ''
        client.supabase.table("job_executions").upsert({
            'job_name': job_name,
            'target_date': target_date.isoformat(),
            'fund_name': effective_fund_name,
            'status': 'running',
            'started_at': datetime.now(timezone.utc).isoformat(),
            'completed_at': None,
            'error_message': None,
        }, on_conflict='job_name,target_date,fund_name').execute()
        
        logger.debug(f"Marked job '{job_name}' as started for {target_date}")
    except Exception as e:
        # Don't fail the job if tracking fails
        logger.warning(f"Failed to mark job started: {e}")


def mark_job_completed(
    job_name: str,
    target_date: date,
    fund_name: Optional[str],
    funds_processed: List[str],
    duration_ms: Optional[int] = None,
    message: Optional[str] = None
) -> None:
    """
    Mark a job as successfully completed.
    
    Args:
        job_name: Name of the job
        target_date: Date the job processed
        fund_name: Specific fund processed, None if all funds
        funds_processed: List of fund names that completed successfully
        duration_ms: Execution duration in milliseconds (optional)
        message: Optional success message to display (stored in error_message field for display)
    """
    try:
        from supabase_client import SupabaseClient
    except ImportError:
        # Try relative import from web_dashboard
        import sys
        from pathlib import Path
        current_file = Path(__file__).resolve()
        web_dashboard_dir = current_file.parent.parent / 'web_dashboard'
        if str(web_dashboard_dir) not in sys.path:
            sys.path.insert(0, str(web_dashboard_dir))
        from supabase_client import SupabaseClient
    
    try:
        client = SupabaseClient(use_service_role=True)
        
        # Use empty string instead of None for fund_name (PostgreSQL NULL uniqueness issue)
        effective_fund_name = fund_name if fund_name is not None else ''
        
        # First check if there's an existing entry
        result = client.supabase.table("job_executions")\
            .select("id")\
            .eq("job_name", job_name)\
            .eq("target_date", target_date.isoformat())\
            .eq("fund_name", effective_fund_name)\
            .execute()
        
        # Update existing or insert new
        data = {
            'job_name': job_name,
            'target_date': target_date.isoformat(),
            'fund_name': effective_fund_name,
            'status': 'success',
            'completed_at': datetime.now(timezone.utc).isoformat(),
            'funds_processed': funds_processed
        }
        
        # Add duration_ms if provided
        if duration_ms is not None:
            data['duration_ms'] = duration_ms
        
        # Store message in error_message field (used for display even for successful jobs)
        if message:
            data['error_message'] = message[:500]  # Truncate to prevent huge strings
        
        client.supabase.table("job_executions").upsert(
            data,
            on_conflict='job_name,target_date,fund_name'
        ).execute()
        
        logger.debug(f"Marked job '{job_name}' as completed for {target_date}")
    except Exception as e:
        logger.warning(f"Failed to mark job completed: {e}")


def mark_job_failed(
    job_name: str,
    target_date: date,
    fund_name: Optional[str],
    error: str,
    duration_ms: Optional[int] = None
) -> None:
    """
    Mark a job as failed with error message.
    
    Args:
        job_name: Name of the job
        target_date: Date the job was processing
        fund_name: Specific fund being processed, None if all funds
        error: Error message
        duration_ms: Execution duration in milliseconds (optional)
    """
    try:
        from supabase_client import SupabaseClient
    except ImportError:
        # Try relative import from web_dashboard
        import sys
        from pathlib import Path
        current_file = Path(__file__).resolve()
        web_dashboard_dir = current_file.parent.parent / 'web_dashboard'
        if str(web_dashboard_dir) not in sys.path:
            sys.path.insert(0, str(web_dashboard_dir))
        from supabase_client import SupabaseClient
    
    try:
        client = SupabaseClient(use_service_role=True)
        # Use empty string instead of None for fund_name (PostgreSQL NULL uniqueness issue)
        effective_fund_name = fund_name if fund_name is not None else ''
        data = {
            'job_name': job_name,
            'target_date': target_date.isoformat(),
            'fund_name': effective_fund_name,
            'status': 'failed',
            'completed_at': datetime.now(timezone.utc).isoformat(),
            'error_message': error[:500]  # Truncate to prevent huge error strings
        }
        
        # Add duration_ms if provided
        if duration_ms is not None:
            data['duration_ms'] = duration_ms
        
        client.supabase.table("job_executions").upsert(
            data,
            on_conflict='job_name,target_date,fund_name'
        ).execute()
        
        logger.debug(f"Marked job '{job_name}' as failed for {target_date}")
    except Exception as e:
        logger.warning(f"Failed to mark job as failed: {e}")


def is_job_completed(
    job_name: str,
    target_date: date,
    fund_name: Optional[str] = None
) -> bool:
    """
    Check if a job completed successfully for a specific date.
    
    Args:
        job_name: Name of the job
        target_date: Date to check
        fund_name: Specific fund to check, None if checking all-funds job
        
    Returns:
        True if job completed successfully, False otherwise
    """
    try:
        from supabase_client import SupabaseClient
    except ImportError:
        # Try relative import from web_dashboard
        import sys
        from pathlib import Path
        current_file = Path(__file__).resolve()
        web_dashboard_dir = current_file.parent.parent / 'web_dashboard'
        if str(web_dashboard_dir) not in sys.path:
            sys.path.insert(0, str(web_dashboard_dir))
        from supabase_client import SupabaseClient
    
    try:
        client = SupabaseClient(use_service_role=True)
        result = client.supabase.table("job_executions")\
            .select("status")\
            .eq("job_name", job_name)\
            .eq("target_date", target_date.isoformat())\
            .eq("status", "success")
        
        if fund_name is not None:
            result = result.eq("fund_name", fund_name)
        else:
            # BUG FIX: mark_job_completed uses empty string '' instead of NULL
            # to avoid PostgreSQL NULL uniqueness issues. Check for BOTH.
            # Use or_() to check for NULL OR empty string
            result = result.or_(
                "fund_name.is.null,fund_name.eq."
            )
        
        result = result.execute()
        
        return bool(result.data)
    except Exception as e:
        logger.warning(f"Failed to check job completion: {e}")
        # If tracking check fails, assume not completed (safe default)
        return False


def get_incomplete_jobs(
    job_name: str,
    since_date: date
) -> List[Dict[str, Any]]:
    """
    Get all jobs with status='running' or 'failed' since a given date.
    
    Used to detect crashed jobs (status still 'running' for old dates).
    
    Args:
        job_name: Name of the job to check
        since_date: Only return jobs from this date onwards
        
    Returns:
        List of job execution records that are incomplete
    """
    try:
        from supabase_client import SupabaseClient
    except ImportError:
        # Try relative import from web_dashboard
        import sys
        from pathlib import Path
        current_file = Path(__file__).resolve()
        web_dashboard_dir = current_file.parent.parent / 'web_dashboard'
        if str(web_dashboard_dir) not in sys.path:
            sys.path.insert(0, str(web_dashboard_dir))
        from supabase_client import SupabaseClient
    
    try:
        client = SupabaseClient(use_service_role=True)
        result = client.supabase.table("job_executions")\
            .select("*")\
            .eq("job_name", job_name)\
            .gte("target_date", since_date.isoformat())\
            .in_("status", ["running", "failed"])\
            .execute()
        
        return result.data if result.data else []
    except Exception as e:
        logger.warning(f"Failed to get incomplete jobs: {e}")
        return []


def cleanup_stale_running_jobs(max_age_hours: int = 24) -> int:
    """
    Mark old 'running' jobs as 'failed' (assume they crashed).
    
    Jobs that have been 'running' for more than max_age_hours are
    assumed to have crashed and are marked as failed.
    
    Args:
        max_age_hours: Consider jobs older than this as crashed
        
    Returns:
        Number of jobs cleaned up
    """
    from supabase_client import SupabaseClient
    
    try:
        client = SupabaseClient()
        cutoff_time = datetime.now(timezone.utc).timestamp() - (max_age_hours * 3600)
        cutoff_dt = datetime.fromtimestamp(cutoff_time, tz=timezone.utc)
        
        # Find stale running jobs
        result = client.supabase.table("job_executions")\
            .select("id")\
            .eq("status", "running")\
            .lt("started_at", cutoff_dt.isoformat())\
            .execute()
        
        if not result.data:
            return 0
        
        # Mark them as failed
        for job in result.data:
            client.supabase.table("job_executions")\
                .update({
                    'status': 'failed',
                    'completed_at': datetime.now(timezone.utc).isoformat(),
                    'error_message': f'Job stale (running > {max_age_hours}h)'
                })\
                .eq("id", job['id'])\
                .execute()
        
        count = len(result.data)
        logger.info(f"Cleaned up {count} stale running jobs")
        return count
    except Exception as e:
        logger.warning(f"Failed to cleanup stale jobs: {e}")
        return 0


def get_running_ai_job(
    exclude_job_name: Optional[str] = None,
    max_age_hours: int = 1,
    *,
    ignore_for_queue_managed: bool = True,
) -> Optional[str]:
    """
    Check if any AI job is currently running (global lock).

    Args:
        exclude_job_name: Job name to ignore (typically current job)
        max_age_hours: Ignore running jobs older than this window
        ignore_for_queue_managed: When True (default), return None immediately
            if ``exclude_job_name`` is a queue-managed job (per
            ``AI_QUEUE_ENABLED`` + ``AI_QUEUE_JOBS``). This implements Q3 of
            the AI task queue roadmap: queue-managed jobs no longer block on
            unrelated long-running AI jobs because their LLM work is leased
            atomically by the embedded worker pool, not gated by the global
            mutex. Set to False to inspect raw lock state (e.g. for admin UI).

    Returns:
        Running job name if lock is active, otherwise None
    """
    # Q3 (2026-05-23): queue-managed jobs bypass the global AI mutex entirely.
    # The cron-side body still writes `job_executions` (audit trail), but it
    # no longer waits on `alpha_research`/etc. to release the lock before
    # enqueueing per-task work.
    if (
        ignore_for_queue_managed
        and exclude_job_name
        and is_queue_managed_job(exclude_job_name)
    ):
        logger.debug(
            "Bypassing global AI lock for queue-managed job '%s'",
            exclude_job_name,
        )
        return None

    try:
        from supabase_client import SupabaseClient
        client = SupabaseClient(use_service_role=True)
        result = client.supabase.table("job_executions") \
            .select("id, job_name, started_at, completed_at") \
            .eq("status", "running") \
            .in_("job_name", list(AI_JOB_NAMES)) \
            .execute()

        if not result.data:
            return None

        now_utc = datetime.now(timezone.utc)
        # Newest first gives most accurate lock owner when multiple rows are running.
        sorted_rows = sorted(
            result.data,
            key=lambda r: (r.get("started_at") or ""),
            reverse=True,
        )

        for row in sorted_rows:
            job_name = row.get("job_name")
            if not job_name or job_name == exclude_job_name:
                continue

            stale_after_hours = AI_JOB_MAX_AGE_HOURS.get(job_name, max_age_hours)
            started_at = row.get("started_at")
            completed_at = row.get("completed_at")
            row_id = row.get("id")

            # Zombie: terminal timestamp set but status never flipped (blocks all AI jobs).
            if completed_at and row_id:
                try:
                    client.supabase.table("job_executions") \
                        .update({
                            "status": "success",
                            "completed_at": completed_at,
                            "error_message": "Auto-cleared zombie AI lock (completed_at set while running)",
                        }) \
                        .eq("id", row_id) \
                        .eq("status", "running") \
                        .execute()
                    logger.warning(
                        "Auto-cleared zombie AI lock id=%s job=%s (had completed_at)",
                        row_id,
                        job_name,
                    )
                except Exception as clear_err:
                    logger.warning(
                        "Failed to clear zombie AI lock id=%s (%s): %s",
                        row_id,
                        job_name,
                        clear_err,
                    )
                continue

            if not started_at:
                return job_name

            try:
                started = datetime.fromisoformat(
                    started_at.replace("Z", "+00:00") if isinstance(started_at, str) else str(started_at)
                )
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                age_seconds = (now_utc - started).total_seconds()

                # Self-heal stale lock rows by id to avoid fund_name NULL/'' key mismatches.
                if age_seconds >= (stale_after_hours * 3600):
                    row_id = row.get("id")
                    if row_id:
                        try:
                            client.supabase.table("job_executions") \
                                .update({
                                    "status": "failed",
                                    "completed_at": now_utc.isoformat(),
                                    "error_message": (
                                        f"Auto-cleared stale AI lock "
                                        f"(running > {stale_after_hours}h)"
                                    )[:500],
                                }) \
                                .eq("id", row_id) \
                                .eq("status", "running") \
                                .execute()
                            logger.warning(
                                "Auto-cleared stale AI lock row id=%s job=%s age=%.1fm",
                                row_id,
                                job_name,
                                age_seconds / 60.0,
                            )
                        except Exception as clear_err:
                            logger.warning(
                                "Failed to auto-clear stale AI lock id=%s (%s): %s",
                                row_id,
                                job_name,
                                clear_err,
                            )
                    continue
            except Exception:
                # If parse fails, treat as active to be safe.
                return job_name

            return job_name

        return None
    except Exception as e:
        logger.warning(f"Failed to check AI job lock: {e}")
        return None


def add_to_retry_queue(
    job_name: str,
    target_date: date,
    entity_id: Optional[str],
    entity_type: str = 'fund',
    failure_reason: str = 'job_failed',
    error_message: str = '',
    context: Optional[Dict[str, Any]] = None
) -> None:
    """
    Add a failed job/day to the retry queue.
    
    Args:
        job_name: Name of the job
        target_date: Date that needs retry
        entity_id: Specific entity (fund_name, ticker, etc.) or None
        entity_type: Type of entity ('fund', 'ticker', 'all_funds', etc.)
        failure_reason: Why it failed ('chunk_failed', 'insert_failed', etc.)
        error_message: Error details
        context: Optional JSONB context (batch ranges, chunk numbers, etc.)
    """
    try:
        from supabase_client import SupabaseClient
        client = SupabaseClient(use_service_role=True)
        
        # Use empty string instead of None for entity_id (PostgreSQL NULL uniqueness issue)
        effective_entity_id = entity_id if entity_id is not None else ''
        
        # Check if already in queue (avoid duplicates)
        existing = client.supabase.table("job_retry_queue")\
            .select("id")\
            .eq("job_name", job_name)\
            .eq("target_date", target_date.isoformat())\
            .eq("entity_id", effective_entity_id)\
            .eq("entity_type", entity_type)\
            .in_("status", ["pending", "retrying"])\
            .execute()
        
        if existing.data:
            logger.debug(f"Retry entry already exists for {job_name} {target_date} {entity_id}")
            return
        
        # Insert new retry entry
        data = {
            'job_name': job_name,
            'target_date': target_date.isoformat(),
            'entity_id': effective_entity_id,
            'entity_type': entity_type,
            'failure_reason': failure_reason,
            'error_message': error_message[:1000],  # Truncate long errors
            'status': 'pending',
            'retry_count': 0,
        }
        
        if context is not None:
            data['context'] = context
        
        client.supabase.table("job_retry_queue")\
            .insert(data)\
            .execute()
        
        logger.debug(f"Added {job_name} {target_date} {entity_id} to retry queue")
        
    except Exception as e:
        logger.warning(f"Failed to add to retry queue: {e}")
        # Don't raise - retry queue failure shouldn't break the job


def get_pending_retries(
    max_retries: int = 3,
    max_age_days: int = 7,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Get pending retries from the retry queue.
    
    Args:
        max_retries: Only return retries with retry_count < max_retries
        max_age_days: Only return retries created within max_age_days
        limit: Max number of retries to return (prevent overloading)
        
    Returns:
        List of retry queue records
    """
    try:
        from supabase_client import SupabaseClient
        from datetime import timedelta
        
        client = SupabaseClient(use_service_role=True)
        
        # Calculate cutoff date
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).date()
        
        result = client.supabase.table("job_retry_queue")\
            .select("*")\
            .eq("status", "pending")\
            .lt("retry_count", max_retries)\
            .gte("target_date", cutoff_date.isoformat())\
            .order("target_date", desc=False)\
            .order("created_at", desc=False)\
            .limit(limit)\
            .execute()
        
        return result.data if result.data else []
    except Exception as e:
        logger.warning(f"Failed to get pending retries: {e}")
        return []


def mark_retrying(
    job_name: str,
    target_date: date,
    entity_id: Optional[str],
    entity_type: str = 'fund'
) -> None:
    """
    Mark a retry entry as 'retrying'.
    
    Args:
        job_name: Name of the job
        target_date: Date being retried
        entity_id: Specific entity or None
        entity_type: Type of entity
    """
    try:
        from supabase_client import SupabaseClient
        client = SupabaseClient(use_service_role=True)
        
        effective_entity_id = entity_id if entity_id is not None else ''
        
        # Get current retry_count
        result = client.supabase.table("job_retry_queue")\
            .select("retry_count")\
            .eq("job_name", job_name)\
            .eq("target_date", target_date.isoformat())\
            .eq("entity_id", effective_entity_id)\
            .eq("entity_type", entity_type)\
            .eq("status", "pending")\
            .execute()
        
        if not result.data:
            logger.warning(f"Retry entry not found for {job_name} {target_date} {entity_id}")
            return
        
        current_count = result.data[0].get('retry_count', 0)
        
        # Update status and increment retry_count
        client.supabase.table("job_retry_queue")\
            .update({
                'status': 'retrying',
                'last_retry_at': datetime.now(timezone.utc).isoformat(),
                'retry_count': current_count + 1
            })\
            .eq("job_name", job_name)\
            .eq("target_date", target_date.isoformat())\
            .eq("entity_id", effective_entity_id)\
            .eq("entity_type", entity_type)\
            .execute()
        
        logger.debug(f"Marked {job_name} {target_date} {entity_id} as retrying")
        
    except Exception as e:
        logger.warning(f"Failed to mark retrying: {e}")


def mark_resolved(
    job_name: str,
    target_date: date,
    entity_id: Optional[str],
    entity_type: str = 'fund'
) -> None:
    """
    Mark a retry entry as 'resolved' (successful).
    
    Args:
        job_name: Name of the job
        target_date: Date that was retried
        entity_id: Specific entity or None
        entity_type: Type of entity
    """
    try:
        from supabase_client import SupabaseClient
        client = SupabaseClient(use_service_role=True)
        
        effective_entity_id = entity_id if entity_id is not None else ''
        
        client.supabase.table("job_retry_queue")\
            .update({
                'status': 'resolved',
                'resolved_at': datetime.now(timezone.utc).isoformat()
            })\
            .eq("job_name", job_name)\
            .eq("target_date", target_date.isoformat())\
            .eq("entity_id", effective_entity_id)\
            .eq("entity_type", entity_type)\
            .in_("status", ["retrying", "pending"])\
            .execute()
        
        logger.debug(f"Marked {job_name} {target_date} {entity_id} as resolved")
        
    except Exception as e:
        logger.warning(f"Failed to mark resolved: {e}")


def mark_abandoned(
    job_name: str,
    target_date: date,
    entity_id: Optional[str],
    entity_type: str = 'fund'
) -> None:
    """
    Mark a retry entry as 'abandoned' (max retries exceeded).
    
    Args:
        job_name: Name of the job
        target_date: Date that failed
        entity_id: Specific entity or None
        entity_type: Type of entity
    """
    try:
        from supabase_client import SupabaseClient
        client = SupabaseClient(use_service_role=True)
        
        effective_entity_id = entity_id if entity_id is not None else ''
        
        client.supabase.table("job_retry_queue")\
            .update({
                'status': 'abandoned',
                'resolved_at': datetime.now(timezone.utc).isoformat()
            })\
            .eq("job_name", job_name)\
            .eq("target_date", target_date.isoformat())\
            .eq("entity_id", effective_entity_id)\
            .eq("entity_type", entity_type)\
            .in_("status", ["retrying", "pending"])\
            .execute()
        
        logger.warning(f"Marked {job_name} {target_date} {entity_id} as abandoned (max retries exceeded)")
        
    except Exception as e:
        logger.warning(f"Failed to mark abandoned: {e}")


def mark_pending_retry(
    job_name: str,
    target_date: date,
    entity_id: Optional[str],
    entity_type: str = "fund",
    error_message: str = "",
) -> None:
    """
    Return a retry entry back to 'pending' after a failed retry attempt.

    This keeps non-terminal failures eligible for the next retry cycle instead
    of leaving entries stuck in 'retrying'.
    """
    try:
        from supabase_client import SupabaseClient

        client = SupabaseClient(use_service_role=True)
        effective_entity_id = entity_id if entity_id is not None else ""

        payload: Dict[str, Any] = {"status": "pending"}
        if error_message:
            payload["error_message"] = error_message[:1000]

        client.supabase.table("job_retry_queue")\
            .update(payload)\
            .eq("job_name", job_name)\
            .eq("target_date", target_date.isoformat())\
            .eq("entity_id", effective_entity_id)\
            .eq("entity_type", entity_type)\
            .eq("status", "retrying")\
            .execute()
    except Exception as e:
        logger.warning(f"Failed to mark retry pending: {e}")


def log_job_step(
    job_name: str,
    step_name: str,
    message: str,
    status: str = 'running',
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """
    Log a step in a running job's pipeline. Append-only, fire-and-forget.

    Args:
        job_name: Name of the job (e.g., 'alpha_research')
        step_name: Short step identifier (e.g., 'searxng_check', 'ai_summary')
        message: Human-readable progress message
        status: Step status - 'running', 'success', 'failed', 'skipped'
        metadata: Optional dict with extra context (article_url, ticker, error)
    """
    try:
        from supabase_client import SupabaseClient
        client = SupabaseClient(use_service_role=True)
        row: Dict[str, Any] = {
            'job_name': job_name,
            'run_date': date.today().isoformat(),
            'step_name': step_name,
            'message': message[:500],
            'status': status,
        }
        if metadata:
            row['metadata'] = metadata
        client.supabase.table("job_steps").insert(row).execute()
    except Exception as e:
        # Fire-and-forget: never let step logging break the job
        logger.debug(f"Step log failed (non-fatal): {e}")


def get_job_steps(
    job_name: str,
    run_date: Optional[date] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Get recent steps for a job run.

    Args:
        job_name: Name of the job
        run_date: Date to filter (defaults to today)
        limit: Max rows to return

    Returns:
        List of step dicts ordered by created_at desc
    """
    try:
        from supabase_client import SupabaseClient
        client = SupabaseClient(use_service_role=True)
        effective_date = (run_date or date.today()).isoformat()
        result = client.supabase.table("job_steps") \
            .select("step_name, message, status, metadata, created_at") \
            .eq("job_name", job_name) \
            .eq("run_date", effective_date) \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()
        return result.data if result.data else []
    except Exception as e:
        logger.debug(f"Failed to get job steps: {e}")
        return []


def cleanup_old_job_steps(retention_days: int = 7) -> int:
    """
    Delete job_steps rows older than retention_days.

    Returns:
        Number of rows deleted (approximate)
    """
    try:
        from supabase_client import SupabaseClient
        from datetime import timedelta
        client = SupabaseClient(use_service_role=True)
        cutoff = (date.today() - timedelta(days=retention_days)).isoformat()
        result = client.supabase.table("job_steps") \
            .delete() \
            .lt("run_date", cutoff) \
            .execute()
        count = len(result.data) if result.data else 0
        if count:
            logger.info(f"Cleaned up {count} old job_steps rows (older than {retention_days}d)")
        return count
    except Exception as e:
        logger.warning(f"Failed to cleanup job steps: {e}")
        return 0


def is_calculation_job(job_name: str) -> bool:
    """
    Determine if a job is a calculation job that needs retry tracking.
    
    Args:
        job_name: Name of the job
        
    Returns:
        True if calculation job, False if data collection job
    """
    calculation_jobs = {
        'update_portfolio_prices',
        'performance_metrics',
        'dividend_processing'
    }
    return job_name in calculation_jobs
