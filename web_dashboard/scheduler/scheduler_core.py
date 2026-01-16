"""
Scheduler Core - APScheduler Configuration and Management
==========================================================

Provides the background scheduler instance and management functions.
"""

import logging
import os
import sys
import threading
import time
from pathlib import Path
from datetime import datetime, timezone, date, timedelta
from typing import Dict, List, Optional, Any
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor

# Add project root to path for utils imports
current_dir = Path(__file__).resolve().parent
if current_dir.name == 'scheduler':
    project_root = current_dir.parent.parent
else:
    project_root = current_dir.parent.parent

# CRITICAL: Project root must be FIRST in sys.path to ensure utils.job_tracking
# is found from the project root, not from web_dashboard/utils
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
elif sys.path[0] != str(project_root):
    # If it is in path but not first, move it to front
    if str(project_root) in sys.path:
        sys.path.remove(str(project_root))
    sys.path.insert(0, str(project_root))

# Also ensure web_dashboard is in path for supabase_client imports
# (but AFTER project root so it doesn't shadow utils)
web_dashboard_path = str(current_dir.parent)
if web_dashboard_path not in sys.path:
    sys.path.insert(1, web_dashboard_path)  # Insert at index 1, after project_root

logger = logging.getLogger(__name__)
# Separate logger for heartbeat to allow filtering
heartbeat_logger = logging.getLogger(f"{__name__}.heartbeat")

# Global scheduler instance
_scheduler: Optional[BackgroundScheduler] = None

# Thread lock to prevent race conditions during scheduler creation/startup
# IMPORTANT: Use RLock (reentrant) because start_scheduler() acquires lock 
# then calls get_scheduler() which also needs the lock
_scheduler_lock = threading.RLock()

# Job execution log (in-memory, last N executions)
_job_logs: Dict[str, List[Dict[str, Any]]] = {}
MAX_LOG_ENTRIES = 50

# Track scheduler health
_scheduler_last_health_check: Optional[datetime] = None
_scheduler_restart_count = 0
_scheduler_intentional_shutdown = False
MAX_RESTART_ATTEMPTS = 5

# Heartbeat file to detect scheduler status across processes
# This allows Streamlit workers to check if scheduler is running without creating a new one
_HEARTBEAT_FILE = Path(__file__).parent.parent / 'logs' / '.scheduler_heartbeat'
_HEARTBEAT_INTERVAL = 20  # seconds between heartbeat updates
_HEARTBEAT_TIMEOUT = 60  # seconds before considering scheduler dead

# Lock file to prevent multiple processes from starting scheduler simultaneously
# This ensures only one scheduler instance runs across Flask and Streamlit
_LOCK_FILE = Path(__file__).parent.parent / 'logs' / '.scheduler_lock'
_LOCK_TIMEOUT = 10  # seconds to wait for lock file to be released

# Worker Utilization Tracking
_active_job_count = 0
_active_job_lock = threading.Lock()
WORKER_WARNING_THRESHOLD = 6  # Warn if 6 or 7 workers are active


def _update_heartbeat():
    """Update the heartbeat file with current timestamp."""
    try:
        _HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HEARTBEAT_FILE.write_text(str(time.time()))
        
        # Log the path on first update for debugging
        if not hasattr(_update_heartbeat, '_path_logged'):
            heartbeat_logger.debug(f"💓 Heartbeat file path: {_HEARTBEAT_FILE}")
            _update_heartbeat._path_logged = True
        
        # Log at INFO level periodically so we can see it's working (every 10th update = ~200 seconds)
        # Use a simple counter to avoid logging every time
        if not hasattr(_update_heartbeat, '_counter'):
            _update_heartbeat._counter = 0
        _update_heartbeat._counter += 1
        if _update_heartbeat._counter % 10 == 0:
            heartbeat_logger.info(f"💓 Heartbeat updated (check #{_update_heartbeat._counter})")
    except Exception as e:
        # Log the error so we can see what's failing
        heartbeat_logger.error(f"❌ Failed to update heartbeat file at {_HEARTBEAT_FILE}: {e}", exc_info=True)
        # Still pass - non-fatal but we want to know about it


def _check_heartbeat() -> bool:
    """Check if scheduler is alive based on heartbeat file.
    
    Returns True if heartbeat is recent (within timeout), False otherwise.
    """
    try:
        if not _HEARTBEAT_FILE.exists():
            return False
        last_beat = float(_HEARTBEAT_FILE.read_text().strip())
        return (time.time() - last_beat) < _HEARTBEAT_TIMEOUT
    except Exception:
        return False


def _acquire_startup_lock() -> bool:
    """Acquire a cross-process lock to prevent multiple processes from starting scheduler.
    
    Returns True if lock acquired successfully, False if another process has the lock.
    """
    try:
        _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        # Check if lock file exists and is recent (another process is starting)
        if _LOCK_FILE.exists():
            try:
                lock_time = float(_LOCK_FILE.read_text().strip())
                age = time.time() - lock_time
                if age < _LOCK_TIMEOUT:
                    # Lock is recent - another process is starting
                    logger.debug(f"  → Another process has startup lock (age: {age:.1f}s)")
                    return False
                else:
                    # Lock is stale - remove it
                    logger.debug(f"  → Removing stale lock file (age: {age:.1f}s)")
                    _LOCK_FILE.unlink()
            except (ValueError, OSError):
                # Lock file is corrupted or unreadable - remove it
                logger.debug("  → Removing corrupted lock file")
                try:
                    _LOCK_FILE.unlink()
                except OSError:
                    pass
        
        # Create lock file with current timestamp and PID
        pid = os.getpid() if hasattr(os, 'getpid') else 0
        _LOCK_FILE.write_text(f"{time.time()}\n{pid}")
        logger.debug(f"  → Acquired startup lock (PID: {pid})")
        return True
        
    except Exception as e:
        logger.warning(f"  ⚠️ Failed to acquire startup lock: {e}")
        # If we can't create lock file, allow startup to proceed (graceful degradation)
        return True


def _release_startup_lock() -> None:
    """Release the cross-process startup lock."""
    try:
        if _LOCK_FILE.exists():
            _LOCK_FILE.unlink()
            logger.debug("  → Released startup lock")
    except Exception as e:
        logger.debug(f"  → Failed to release startup lock: {e}")


def _check_if_another_process_starting() -> bool:
    """Check if another process is currently starting the scheduler.
    
    Returns True if another process has the lock and it's recent.
    """
    try:
        if not _LOCK_FILE.exists():
            return False
        
        lock_time = float(_LOCK_FILE.read_text().strip().split('\n')[0])
        age = time.time() - lock_time
        return age < _LOCK_TIMEOUT
    except Exception:
        return False


def get_scheduler(create=True) -> Optional[BackgroundScheduler]:
    """Get or create the scheduler instance (thread-safe).
    
    Args:
        create: If True, create new instance if one doesn't exist.
                If False, return None if one doesn't exist.
    """
    global _scheduler
    
    # Fast path if already exists
    if _scheduler is not None:
        return _scheduler
        
    # If not creating, return None
    if not create:
        return None
    
    # Double-checked locking pattern to prevent race conditions
    if _scheduler is None:
        with _scheduler_lock:
            # Check again after acquiring lock (another thread may have created it)
            if _scheduler is None:
                # Use SQLAlchemyJobStore with Supabase PostgreSQL for persistent job storage
                database_url = os.getenv("SUPABASE_DATABASE_URL")
                if not database_url:
                    raise ValueError("SUPABASE_DATABASE_URL must be set in environment for SQLAlchemyJobStore")
                
                # Fix IPv6 connection issues by forcing IPv4 preference
                # Add connect_timeout and prefer IPv4 if connection string doesn't already have parameters
                if '?' not in database_url:
                    # Add connection parameters to prefer IPv4
                    database_url = f"{database_url}?connect_timeout=10"
                elif 'connect_timeout' not in database_url:
                    # Add connect_timeout if other parameters exist
                    database_url = f"{database_url}&connect_timeout=10"
                
                # Note: psycopg2 doesn't directly support IPv4-only mode via connection string
                # If IPv6 issues persist, the connection will fail and we'll catch it in start_scheduler()
                
                jobstores = {
                    'default': SQLAlchemyJobStore(url=database_url, tablename='apscheduler_jobs')
                }
                executors = {
                    'default': ThreadPoolExecutor(max_workers=7)
                }
                job_defaults = {
                    'coalesce': True,  # Combine multiple missed executions into one
                    'max_instances': 1,  # Only one instance of each job at a time
                    'misfire_grace_time': 60 * 60 * 24  # 24 hour grace period (if missed due to sleep/downtime, run it now)
                }
                
                _scheduler = BackgroundScheduler(
                    jobstores=jobstores,
                    executors=executors,
                    job_defaults=job_defaults,
                    timezone='America/Los_Angeles'  # Pacific Time
                )
                
                # Add event listeners to catch errors and shutdowns
                _scheduler.add_listener(_scheduler_event_listener, 
                                       mask=0xFFFFFFFF)  # Listen to all events
                
                # Log with print() fallback
                import sys
                msg = "Created new BackgroundScheduler instance with event listeners"
                print(f"[scheduler_core] {msg}", file=sys.stderr, flush=True)
                try:
                    logger.info(msg)
                except:
                    pass
    
    return _scheduler


def _get_job_name_for_logging(job_id: Optional[str]) -> str:
    """Get job name for logging purposes.
    
    Args:
        job_id: The job ID from the event
        
    Returns:
        Job name if available, otherwise job_id or 'N/A'
    """
    if not job_id:
        return 'N/A'
    
    try:
        scheduler = get_scheduler(create=False)
        if scheduler:
            job = scheduler.get_job(job_id)
            if job and job.name:
                return f"{job.name} ({job_id})"
    except Exception:
        pass  # Fall through to return job_id
    
    return job_id


def _scheduler_event_listener(event) -> None:
    """Event listener for scheduler events - catches errors and shutdowns."""
    # Use print() as fallback - always works even if logging is broken
    import sys
    import traceback
    
    # Access global tracking variables
    global _active_job_count
    
    try:
        from apscheduler.events import (
            EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_MISSED,
            EVENT_SCHEDULER_STARTED, EVENT_SCHEDULER_SHUTDOWN,
            EVENT_SCHEDULER_PAUSED, EVENT_SCHEDULER_RESUMED,
            EVENT_JOB_ADDED, EVENT_JOB_REMOVED, EVENT_JOB_MODIFIED,
            EVENT_JOB_SUBMITTED
        )
        
        # Get job ID and name for logging
        job_id = getattr(event, 'job_id', None)
        job_display = _get_job_name_for_logging(job_id)
        
        # Only log important events to stderr (not routine job add/remove/modify/execute)
        # Routine events are logged at debug level only
        should_log_stderr = event.code not in (EVENT_JOB_ADDED, EVENT_JOB_REMOVED, EVENT_JOB_MODIFIED, EVENT_JOB_EXECUTED, EVENT_JOB_SUBMITTED)
        if should_log_stderr:
            event_msg = f"[SCHEDULER EVENT] Code: {event.code}, Job: {job_display}"
            print(event_msg, file=sys.stderr, flush=True)
        
        if event.code == EVENT_JOB_EXECUTED:
            # Normal event - job completed successfully
            # Only log at debug level to reduce noise
            # Skip heartbeat job - it has its own logger category
            try:
                if job_id == 'scheduler_heartbeat':
                    heartbeat_logger.debug(f"Job executed: {job_display}")
                else:
                    logger.debug(f"Job executed: {job_display}")
            except:
                pass
            
            # Decrement active job count
            with _active_job_lock:
                _active_job_count = max(0, _active_job_count - 1)
                
        elif event.code == EVENT_JOB_ERROR:
            # Decrement active job count
            with _active_job_lock:
                _active_job_count = max(0, _active_job_count - 1)
                
            error_msg = f"❌ SCHEDULER EVENT: Job {job_display} raised exception: {event.exception}"
            print(error_msg, file=sys.stderr, flush=True)
            if hasattr(event, 'exception') and event.exception:
                traceback.print_exception(type(event.exception), event.exception, event.exception.__traceback__, file=sys.stderr)
            try:
                logger.error(error_msg, exc_info=event.exception)
            except:
                pass  # Logger might not work
                
        elif event.code == EVENT_JOB_MISSED:
            msg = f"⚠️ SCHEDULER EVENT: Job {job_display} missed execution time"
            print(msg, file=sys.stderr, flush=True)
            try:
                logger.warning(msg)
            except:
                pass
                
        elif event.code == EVENT_SCHEDULER_SHUTDOWN:
            shutdown_msg = "❌ SCHEDULER EVENT: Scheduler shutdown detected!"
            print(shutdown_msg, file=sys.stderr, flush=True)
            # Log additional context
            try:
                import traceback
                print(f"[scheduler_core] Shutdown context - intentional: {_scheduler_intentional_shutdown}", file=sys.stderr, flush=True)
                print(f"[scheduler_core] Scheduler state: {getattr(_scheduler, 'state', 'unknown') if _scheduler else 'None'}", file=sys.stderr, flush=True)
            except:
                pass
            try:
                logger.error(shutdown_msg)
            except:
                pass
            # Only restart if this was an unexpected shutdown (not intentional)
            if not _scheduler_intentional_shutdown:
                restart_msg = "⚠️ Unexpected scheduler shutdown detected - will attempt restart"
                print(restart_msg, file=sys.stderr, flush=True)
                try:
                    logger.warning(restart_msg)
                except:
                    pass
                _attempt_scheduler_restart()
            else:
                msg = "ℹ️ Scheduler shutdown was intentional - not restarting"
                print(msg, file=sys.stderr, flush=True)
                try:
                    logger.info(msg)
                except:
                    pass
                    
        elif event.code == EVENT_SCHEDULER_STARTED:
            msg = "✅ SCHEDULER EVENT: Scheduler started"
            print(msg, file=sys.stderr, flush=True)
            try:
                logger.info(msg)
            except:
                pass
                
        elif event.code == EVENT_SCHEDULER_PAUSED:
            msg = "⚠️ SCHEDULER EVENT: Scheduler paused"
            print(msg, file=sys.stderr, flush=True)
            try:
                logger.warning(msg)
            except:
                pass
                
        elif event.code == EVENT_SCHEDULER_RESUMED:
            msg = "✅ SCHEDULER EVENT: Scheduler resumed"
            print(msg, file=sys.stderr, flush=True)
            try:
                logger.info(msg)
            except:
                pass
                
        elif event.code == EVENT_JOB_ADDED:
            # Normal event - job was added to scheduler
            # Only log at debug level to reduce noise
            try:
                logger.debug(f"Job added: {job_display}")
            except:
                pass
                
        elif event.code == EVENT_JOB_REMOVED:
            # Normal event - job was removed from scheduler
            # Only log at debug level to reduce noise
            try:
                logger.debug(f"Job removed: {job_display}")
            except:
                pass
                
        elif event.code == EVENT_JOB_MODIFIED:
            # Normal event - job was modified in scheduler
            # Only log at debug level to reduce noise
            try:
                logger.debug(f"Job modified: {job_display}")
            except:
                pass
                
        elif event.code == EVENT_JOB_SUBMITTED:
            # Normal event - job was submitted to executor
            # Only log at debug level to reduce noise
            # Skip heartbeat job - it has its own logger category
            try:
                if job_id == 'scheduler_heartbeat':
                    heartbeat_logger.debug(f"Job submitted: {job_display}")
                else:
                    logger.debug(f"Job submitted: {job_display}")
            except:
                pass
            
            # Increment active job count and check threshold
            # Skip heartbeat job from counting towards saturation
            if job_id != 'scheduler_heartbeat':
                with _active_job_lock:
                    _active_job_count += 1
                    current_count = _active_job_count
                    
                if current_count >= WORKER_WARNING_THRESHOLD:
                    msg = f"⚠️ HIGH LOAD WARNING: {current_count}/7 scheduler threads are active! (Threshold: {WORKER_WARNING_THRESHOLD})"
                    # Force print to stderr to ensure visibility
                    print(msg, file=sys.stderr, flush=True)
                    try:
                        logger.warning(msg)
                    except:
                        pass
                
        else:
            # Truly unknown event code - log it
            msg = f"ℹ️ SCHEDULER EVENT: Unknown event code {event.code}"
            print(msg, file=sys.stderr, flush=True)
            try:
                logger.info(msg)
            except:
                pass
                
    except Exception as e:
        # Critical: Log event listener errors with print() since logger might be broken
        error_msg = f"❌ CRITICAL: Error in scheduler event listener: {e}"
        print(error_msg, file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        try:
            logger.error(error_msg, exc_info=True)
        except:
            pass  # Even logger failed - at least print() worked


def _attempt_scheduler_restart() -> None:
    """Attempt to restart the scheduler if it stopped unexpectedly."""
    global _scheduler, _scheduler_restart_count
    
    if _scheduler_restart_count >= MAX_RESTART_ATTEMPTS:
        logger.error(
            f"❌ Scheduler restart limit reached ({MAX_RESTART_ATTEMPTS} attempts). "
            "Manual intervention required. Check logs for root cause."
        )
        return
    
    try:
        logger.warning(f"🔄 Attempting to restart scheduler (attempt {_scheduler_restart_count + 1}/{MAX_RESTART_ATTEMPTS})...")
        
        # Check if scheduler exists and is not running
        if _scheduler and not _scheduler.running:
            _scheduler_restart_count += 1
            
            # Try to restart
            with _scheduler_lock:
                # Double-check after acquiring lock
                if _scheduler and not _scheduler.running:
                    try:
                        # Don't re-register jobs - they should still be in the jobstore
                        # Just restart the scheduler
                        _scheduler.start()
                        # Wait briefly to verify it started
                        time.sleep(0.5)
                        if _scheduler.running:
                            logger.info("✅ Scheduler restarted successfully after unexpected shutdown")
                            _scheduler_restart_count = 0  # Reset counter on success
                        else:
                            logger.error("❌ Scheduler restart failed - not running after start()")
                    except Exception as e:
                        logger.error(f"❌ Failed to restart scheduler: {e}", exc_info=True)
        else:
            # Scheduler is already running or doesn't exist
            if _scheduler and _scheduler.running:
                logger.info("ℹ️ Scheduler is already running - no restart needed")
                _scheduler_restart_count = 0  # Reset counter
    except Exception as e:
        logger.error(f"Error attempting scheduler restart: {e}", exc_info=True)


def check_scheduler_health() -> bool:
    """Check if scheduler is running and restart if needed.
    
    Returns True if scheduler is healthy, False otherwise.
    """
    global _scheduler, _scheduler_last_health_check
    import sys
    
    try:
        scheduler = get_scheduler()
        _scheduler_last_health_check = datetime.now(timezone.utc)
        
        if not scheduler.running:
            error_msg = "❌ SCHEDULER HEALTH CHECK: Scheduler is not running!"
            print(f"[scheduler_core] {error_msg}", file=sys.stderr, flush=True)
            logger.error(error_msg)
            # Log scheduler state for debugging
            try:
                print(f"[scheduler_core] Scheduler state: running={scheduler.running}, state={getattr(scheduler, 'state', 'unknown')}", file=sys.stderr, flush=True)
            except:
                pass
            _attempt_scheduler_restart()
            return False
        
        # Verify scheduler is actually functioning by checking if it has jobs
        jobs = scheduler.get_jobs()
        if len(jobs) == 0:
            logger.warning("⚠️ SCHEDULER HEALTH CHECK: Scheduler running but no jobs registered")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"❌ SCHEDULER HEALTH CHECK failed: {e}", exc_info=True)
        return False


def cleanup_stale_running_jobs() -> int:
    """Clean up stale 'running' jobs on startup and add to retry queue.
    
    When the container restarts, any jobs that were running are interrupted.
    This function:
    1. Marks them as failed in job_executions
    2. Adds calculation jobs to retry queue
    3. Deletes the stale records
    
    Returns:
        Number of stale jobs cleaned up
    """
    try:
        from supabase_client import SupabaseClient
        
        # Defensive import with retry logic
        try:
            from utils.job_tracking import add_to_retry_queue, is_calculation_job, mark_job_failed
        except ModuleNotFoundError:
            # Race condition: path wasn't set up in time
            # Force add project root to path and retry
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))
            # Retry import
            from utils.job_tracking import add_to_retry_queue, is_calculation_job, mark_job_failed
        
        from datetime import datetime
        
        client = SupabaseClient(use_service_role=True)
        
        # Find all jobs still marked as running
        result = client.supabase.table("job_executions")\
            .select("id, job_name, target_date, fund_name, started_at")\
            .eq("status", "running")\
            .execute()
        
        if not result.data:
            logger.info("No stale running jobs to clean up")
            return 0
        
        count = len(result.data)
        logger.info(f"Found {count} stale 'running' job(s), cleaning up...")
        
        # Process each stale job
        for job in result.data:
            job_name = job['job_name']
            target_date_str = job.get('target_date')
            fund_name = job.get('fund_name') or None
            
            # Mark as failed in job_executions
            if target_date_str:
                try:
                    target_date = datetime.fromisoformat(target_date_str).date()
                    mark_job_failed(
                        job_name=job_name,
                        target_date=target_date,
                        fund_name=fund_name,
                        error="Container restarted - job interrupted"
                    )
                except Exception as e:
                    logger.warning(f"  Failed to mark {job_name} as failed: {e}")
            
            # Add to retry queue if calculation job
            if target_date_str and is_calculation_job(job_name):
                try:
                    target_date = datetime.fromisoformat(target_date_str).date()
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
            
            # Delete the stale record
            client.supabase.table("job_executions")\
                .delete()\
                .eq("id", job['id'])\
                .execute()
            
            logger.info(f"  ✓ Cleaned up stale run for {job_name} (started: {job.get('started_at')})")
        
        logger.info(f"✅ Cleaned up {count} stale running job records")
        return count
        
    except Exception as e:
        logger.error(f"Failed to clean up stale running jobs: {e}")
        return 0


def start_scheduler() -> bool:
    """Start the scheduler and register default jobs (thread-safe).
    
    Returns True if started successfully, False if already running.
    
    IMPORTANT: This function is designed to minimize lock hold time to prevent
    deadlocks in Streamlit's multi-worker environment.
    """
    global _scheduler
    
    import threading
    start_time = time.time()
    
    logger.info("="*60)
    logger.info("SCHEDULER START_SCHEDULER() CALLED")
    logger.debug(f"  Process ID: {os.getpid() if hasattr(os, 'getpid') else 'N/A'}")
    logger.debug(f"  Thread: {threading.current_thread().name} ({threading.current_thread().ident})")
    logger.debug("="*60)
    
    # PHASE 0: Ensure logs are captured (both file and unhandled exceptions)
    try:
        # 1. Setup file logging if not already set
        try:
            from log_handler import setup_logging
            setup_logging()
            logger.debug("  → Log handler configured (logs will appear in Web UI)")
        except ImportError:
            logger.warning("  ⚠️ Could not import log_handler.setup_logging")

        # 2. Install global exception handler to catch crashes
        def handle_exception(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return
            logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
        
        sys.excepthook = handle_exception
        logger.debug("  → Global exception handler installed")
        
    except Exception as e:
        logger.error(f"  ❌ Failed to setup extended logging: {e}")

    # PHASE 1: Check if already running (in-process check)
    logger.debug("[PHASE 1] Checking if scheduler is already running (in-process)...")
    with _scheduler_lock:
        scheduler = get_scheduler()
        if scheduler.running:
            logger.info("  → Scheduler already running in this process, returning False")
            return False
        logger.debug("  → Scheduler not running in this process")
    
    # PHASE 1.5: Check if another process has scheduler running (cross-process check)
    logger.debug("[PHASE 1.5] Checking if another process has scheduler running...")
    if _check_heartbeat():
        try:
            if _HEARTBEAT_FILE.exists():
                last_beat = float(_HEARTBEAT_FILE.read_text().strip())
                age = time.time() - last_beat
                logger.info(f"  → Another process has scheduler running (heartbeat: {age:.1f}s ago), returning False")
            else:
                logger.info("  → Another process has scheduler running (heartbeat detected), returning False")
        except Exception as e:
            logger.debug(f"  → Error reading heartbeat file: {e}")
            logger.info("  → Another process has scheduler running (heartbeat detected), returning False")
        return False
    
    # PHASE 1.6: Check if another process is currently starting scheduler
    if _check_if_another_process_starting():
        logger.info("  → Another process is starting scheduler (lock detected), returning False")
        return False
    
    # PHASE 1.7: Acquire cross-process startup lock
    logger.debug("[PHASE 1.7] Acquiring cross-process startup lock...")
    if not _acquire_startup_lock():
        logger.info("  → Failed to acquire startup lock (another process is starting), returning False")
        return False
    
    # Use try/finally to ensure lock is always released
    try:
        # Double-check heartbeat after acquiring lock (another process might have started)
        if _check_heartbeat():
            try:
                if _HEARTBEAT_FILE.exists():
                    last_beat = float(_HEARTBEAT_FILE.read_text().strip())
                    age = time.time() - last_beat
                    logger.info(f"  → Another process started scheduler while we were acquiring lock (heartbeat: {age:.1f}s ago), returning False")
                else:
                    logger.info("  → Another process started scheduler while we were acquiring lock, returning False")
            except Exception as e:
                logger.debug(f"  → Error reading heartbeat file: {e}")
                logger.info("  → Another process started scheduler while we were acquiring lock, returning False")
            return False
        
        # PHASE 2: Cleanup stale jobs OUTSIDE lock (DB operation, may be slow)
        logger.debug("[PHASE 2] Cleaning up stale running jobs (outside lock)...")
        try:
            cleanup_stale_running_jobs()
            logger.debug(f"  → Cleanup completed in {time.time() - start_time:.2f}s")
        except Exception as e:
            logger.error(f"  ❌ Cleanup failed (non-fatal): {e}")
            # Continue - cleanup failure shouldn't prevent scheduler start
        
        # PHASE 3: Start scheduler under lock (critical section)
        logger.debug("[PHASE 3] Starting scheduler (in lock)...")
        phase3_start = time.time()
        
        with _scheduler_lock:
            # Triple-check no one else started it while we were cleaning up
            if scheduler.running:
                logger.info("  → Scheduler was started by another thread, returning False")
                return False
            
            # Register default jobs (defensive import)
            try:
                from scheduler.jobs import register_default_jobs
            except ModuleNotFoundError:
                if str(project_root) not in sys.path:
                    sys.path.insert(0, str(project_root))
                from scheduler.jobs import register_default_jobs
            
            logger.debug("  → Registering default jobs...")
            register_default_jobs(scheduler)
            
            # Start scheduler
            try:
                scheduler.start()
                logger.debug("  → scheduler.start() called")
            except Exception as e:
                error_msg = str(e)
                # Check for IPv6 connection issues
                if 'Network is unreachable' in error_msg or 'IPv6' in error_msg or '2600:' in error_msg:
                    logger.error(f"  ❌ Failed to start scheduler: Database connection error (IPv6 issue)")
                    logger.error(f"     Error: {error_msg}")
                    logger.error(f"     This may be due to IPv6 connectivity issues.")
                    logger.error(f"     Try using IPv4 address or check network/firewall settings.")
                    raise ConnectionError(
                        "Failed to connect to Supabase database. This may be due to IPv6 connectivity issues. "
                        "Check your network settings or contact your administrator."
                    ) from e
                else:
                    logger.error(f"  ❌ Failed to start scheduler: {e}", exc_info=True)
                    raise
            
            # Verify scheduler actually started (APScheduler.start() is async)
            max_wait = 2.0
            wait_interval = 0.1
            waited = 0.0
            while not scheduler.running and waited < max_wait:
                time.sleep(wait_interval)
                waited += wait_interval
            
            if not scheduler.running:
                logger.error("  ❌ Scheduler not running after start()")
                raise RuntimeError("Scheduler failed to start - not running after start() call")
            
            logger.debug(f"  ✅ Scheduler running (verified in {waited:.2f}s)")
        
        logger.debug(f"  → Phase 3 completed in {time.time() - phase3_start:.2f}s")
        
        # PHASE 4: Add startup jobs OUTSIDE lock (scheduler is already running)
        logger.debug("[PHASE 4] Adding startup jobs (outside lock)...")
        
        # Log startup summary
        jobs = scheduler.get_jobs()
        logger.info("="*50)
        logger.info(f"✅ SCHEDULER STARTED - {len(jobs)} jobs registered")
        for job in jobs:
            next_run = job.next_run_time.strftime('%Y-%m-%d %H:%M %Z') if job.next_run_time else 'PAUSED'
            logger.debug(f"   📋 {job.id}: {next_run}")
        logger.info("="*50)
        
        # Add startup jobs (wrapped in try/catch - non-fatal if they fail)
        try:
            from scheduler.backfill import startup_backfill_check
        except ModuleNotFoundError:
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))
            from scheduler.backfill import startup_backfill_check
        
        try:
            scheduler.add_job(
                startup_backfill_check,
                trigger='date',
                id='startup_backfill',
                name='Startup Backfill Check',
                replace_existing=True
            )
            logger.debug("  📋 Scheduled startup backfill check")
        except Exception as e:
            logger.warning(f"  ⚠️ Failed to schedule backfill check: {e}")
        
        # Note: check_overdue_jobs() removed - no longer needed with SQLAlchemyJobStore
        # APScheduler handles misfires automatically via misfire_grace_time
        
        try:
            from apscheduler.triggers.interval import IntervalTrigger
            scheduler.add_job(
                check_scheduler_health,
                trigger=IntervalTrigger(minutes=5),
                id='scheduler_health_check',
                name='Scheduler Health Check',
                replace_existing=True,
                max_instances=1,
                coalesce=True
            )
            logger.debug("  📋 Scheduled scheduler health check (every 5 minutes)")
        except Exception as e:
            logger.warning(f"  ⚠️ Failed to schedule health check: {e}")
        
        # Add heartbeat job to update status file for cross-process detection
        try:
            from apscheduler.triggers.interval import IntervalTrigger
            scheduler.add_job(
                _update_heartbeat,
                trigger=IntervalTrigger(seconds=_HEARTBEAT_INTERVAL),
                id='scheduler_heartbeat',
                name='Scheduler Heartbeat',
                replace_existing=True,
                max_instances=1,
                coalesce=True
            )
            # Also do an immediate heartbeat update
            _update_heartbeat()
            logger.debug(f"  💓 Heartbeat job registered (every {_HEARTBEAT_INTERVAL}s)")
        except Exception as e:
            logger.warning(f"  ⚠️ Failed to schedule heartbeat: {e}")
        
        total_time = time.time() - start_time
        logger.info(f"✅ SCHEDULER STARTUP COMPLETE in {total_time:.2f}s")
        
        return True
        
    finally:
        # Always release the startup lock, even if startup failed
        _release_startup_lock()




# check_overdue_jobs() function removed - no longer needed with SQLAlchemyJobStore
# APScheduler automatically handles misfires via misfire_grace_time when jobs are loaded from persistent storage


def is_scheduler_running() -> bool:
    """Check if the scheduler is running (cross-process safe).
    
    Uses heartbeat file to detect scheduler status, which works across
    Streamlit workers that don't share memory.
    
    Returns:
        True if scheduler is running (heartbeat is recent), False otherwise.
    """
    # First check in-process scheduler (if we're in the same process that started it)
    if _scheduler is not None and _scheduler.running:
        return True
    
    # Cross-process check: use heartbeat file
    heartbeat_status = _check_heartbeat()
    
    # Add diagnostic logging if heartbeat check fails
    if not heartbeat_status:
        try:
            if _HEARTBEAT_FILE.exists():
                last_beat = float(_HEARTBEAT_FILE.read_text().strip())
                age_seconds = time.time() - last_beat
                logger.debug(f"Scheduler heartbeat file exists but is stale (age: {age_seconds:.1f}s, timeout: {_HEARTBEAT_TIMEOUT}s)")
            else:
                logger.debug(f"Scheduler heartbeat file does not exist at {_HEARTBEAT_FILE}")
        except Exception as e:
            logger.debug(f"Error checking heartbeat file: {e}")
    
    return heartbeat_status



def get_scheduler_status() -> Dict[str, Any]:
    """Get detailed scheduler status for debugging.
    
    Returns:
        Dictionary with scheduler status information
    """
    status = {
        'in_process_running': _scheduler is not None and _scheduler.running if _scheduler else False,
        'heartbeat_file_exists': _HEARTBEAT_FILE.exists(),
        'heartbeat_recent': False,
        'heartbeat_age_seconds': None,
        'heartbeat_file_path': str(_HEARTBEAT_FILE),
    }
    
    try:
        if _HEARTBEAT_FILE.exists():
            last_beat = float(_HEARTBEAT_FILE.read_text().strip())
            age = time.time() - last_beat
            status['heartbeat_age_seconds'] = age
            status['heartbeat_recent'] = age < _HEARTBEAT_TIMEOUT
    except Exception as e:
        status['heartbeat_error'] = str(e)
    
    return status


def shutdown_scheduler() -> None:
    """Gracefully shutdown the scheduler."""
    global _scheduler, _scheduler_intentional_shutdown
    
    if _scheduler and _scheduler.running:
        _scheduler_intentional_shutdown = True
        try:
            _scheduler.shutdown(wait=True)
            logger.info("Scheduler shutdown complete")
        finally:
            _scheduler_intentional_shutdown = False


def log_job_execution(job_id: str, success: bool, message: str, duration_ms: int = 0) -> None:
    """Log a job execution result."""
    global _job_logs
    
    if job_id not in _job_logs:
        _job_logs[job_id] = []
    
    log_entry = {
        'timestamp': datetime.now(timezone.utc),
        'success': success,
        'message': message,
        'duration_ms': duration_ms
    }
    
    _job_logs[job_id].insert(0, log_entry)
    
    # Trim old entries
    if len(_job_logs[job_id]) > MAX_LOG_ENTRIES:
        _job_logs[job_id] = _job_logs[job_id][:MAX_LOG_ENTRIES]


def _map_job_id_to_job_name(job_id: str) -> str:
    """Map scheduler job ID to job_executions.job_name.
    
    Some scheduler job IDs have variants (e.g., 'update_portfolio_prices_close')
    that map to the same job_name in the database.
    
    Args:
        job_id: The scheduler job ID
        
    Returns:
        The job_name to use in job_executions table
    """
    # Handle special cases for job variants
    if job_id == 'update_portfolio_prices_close':
        return 'update_portfolio_prices'
    elif job_id.startswith('market_research_collect_'):
        return 'market_research'
    # Remove verb suffixes to get base job name for grouping
    # This allows variants to be grouped together in the database
    if job_id.endswith('_refresh'):
        return job_id[:-8]  # Remove '_refresh'
    elif job_id.endswith('_populate'):
        return job_id[:-9]  # Remove '_populate'
    elif job_id.endswith('_collect'):
        return job_id[:-8]  # Remove '_collect'
    elif job_id.endswith('_scan'):
        return job_id[:-5]  # Remove '_scan'
    elif job_id.endswith('_fetch'):
        return job_id[:-6]  # Remove '_fetch'
    elif job_id.endswith('_cleanup'):
        return job_id[:-8]  # Remove '_cleanup'
    # Default: use job_id as-is
    return job_id


def get_job_logs(job_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Get recent execution logs for a job.
    
    Reads from both:
    1. Database job_executions table (persistent, survives restarts)
    2. In-memory _job_logs (recent executions in current session)
    
    Args:
        job_id: The scheduler job ID
        limit: Maximum number of logs to return
        
    Returns:
        List of log entries with keys: timestamp, success, message, duration_ms
    """
    job_name = _map_job_id_to_job_name(job_id)
    logs: List[Dict[str, Any]] = []
    
    # First, try to read from database (persistent)
    try:
        from supabase_client import SupabaseClient
        client = SupabaseClient(use_service_role=True)
        
        # Get recent successful/failed executions from database
        # Use completed_at for ordering (most recent first)
        result = client.supabase.table("job_executions")\
            .select("*")\
            .eq("job_name", job_name)\
            .in_("status", ["success", "failed"])\
            .order("completed_at", desc=True)\
            .limit(limit)\
            .execute()
        
        if result.data:
            for record in result.data:
                # Convert database record to log format
                completed_at = record.get('completed_at')
                if completed_at:
                    try:
                        # Parse timestamp string to datetime
                        if isinstance(completed_at, str):
                            # Handle ISO format strings
                            timestamp = datetime.fromisoformat(completed_at.replace('Z', '+00:00'))
                        else:
                            timestamp = completed_at
                    except Exception:
                        # Fallback to current time if parsing fails
                        timestamp = datetime.now(timezone.utc)
                else:
                    timestamp = datetime.now(timezone.utc)
                
                status = record.get('status', 'failed')
                success = (status == 'success')
                
                # Build message from error_message or funds_processed
                message = record.get('error_message', '')
                if not message and record.get('funds_processed'):
                    funds = record.get('funds_processed', [])
                    if isinstance(funds, list) and funds:
                        message = f"Processed {len(funds)} fund(s)"
                    else:
                        message = "Completed successfully"
                elif not message:
                    message = "Completed successfully" if success else "Job failed"
                
                # Use stored duration_ms if available, otherwise calculate from timestamps
                duration_ms = record.get('duration_ms')
                if duration_ms is None:
                    # Fallback: calculate from timestamps if duration_ms not stored
                    duration_ms = 0
                    started_at = record.get('started_at')
                    if started_at and completed_at:
                        try:
                            # Parse started_at
                            if isinstance(started_at, str):
                                start_dt = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                            else:
                                start_dt = started_at
                            
                            # Parse completed_at
                            if isinstance(completed_at, str):
                                end_dt = datetime.fromisoformat(completed_at.replace('Z', '+00:00'))
                            else:
                                end_dt = completed_at
                            
                            # Ensure both are timezone-aware (UTC)
                            if start_dt.tzinfo is None:
                                start_dt = start_dt.replace(tzinfo=timezone.utc)
                            else:
                                start_dt = start_dt.astimezone(timezone.utc)
                            
                            if end_dt.tzinfo is None:
                                end_dt = end_dt.replace(tzinfo=timezone.utc)
                            else:
                                end_dt = end_dt.astimezone(timezone.utc)
                            
                            # Calculate duration and ensure it's never negative
                            delta = end_dt - start_dt
                            duration_seconds = delta.total_seconds()
                            duration_ms = max(0, int(duration_seconds * 1000))  # Clamp to 0 if negative
                        except Exception as e:
                            logger.debug(f"Error calculating duration: {e}")
                            duration_ms = 0
                else:
                    # Ensure stored duration is never negative
                    duration_ms = max(0, int(duration_ms))
                
                logs.append({
                    'timestamp': timestamp,
                    'success': success,
                    'message': message,
                    'duration_ms': duration_ms
                })
    except Exception as e:
        logger.warning(f"Failed to read job logs from database for {job_id}: {e}")
    
    # Also include in-memory logs (for very recent executions not yet in DB)
    # Merge and deduplicate by timestamp
    in_memory_logs = _job_logs.get(job_id, [])
    for mem_log in in_memory_logs:
        # Check if we already have this log from database
        mem_ts = mem_log.get('timestamp')
        if mem_ts:
            # Check if timestamp is close to any existing log (within 1 second)
            is_duplicate = False
            for existing_log in logs:
                existing_ts = existing_log.get('timestamp')
                if existing_ts and abs((mem_ts - existing_ts).total_seconds()) < 1:
                    is_duplicate = True
                    break
            if not is_duplicate:
                logs.append(mem_log)
    
    # Sort by timestamp (most recent first) and limit
    logs.sort(key=lambda x: x.get('timestamp', datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    return logs[:limit]


def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    """Get status of a specific job."""
    scheduler = get_scheduler()
    job = scheduler.get_job(job_id)
    
    if not job:
        return None
    
    # Map job_id to job_name for database lookup
    job_name = _map_job_id_to_job_name(job_id)
    
    # Check if job is currently running
    is_running = False
    running_since = None
    try:
        from supabase_client import SupabaseClient
        client = SupabaseClient(use_service_role=True)
        
        # Query for running executions
        running_result = client.supabase.table("job_executions")\
            .select("started_at")\
            .eq("job_name", job_name)\
            .eq("status", "running")\
            .order("started_at", desc=True)\
            .limit(1)\
            .execute()
        
        if running_result.data and len(running_result.data) > 0:
            started_at = running_result.data[0].get('started_at')
            if started_at:
                try:
                    if isinstance(started_at, str):
                        running_since = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                    else:
                        running_since = started_at
                    
                    # Ensure timezone awareness
                    if running_since.tzinfo is None:
                        running_since = running_since.replace(tzinfo=timezone.utc)
                    else:
                        running_since = running_since.astimezone(timezone.utc)
                        
                    # Ignore if older than 6 hours (likely stale/crashed)
                    now_utc = datetime.now(timezone.utc)
                    if (now_utc - running_since).total_seconds() < 6 * 3600:
                        is_running = True
                    else:
                         # It's stale - ignore it for UI purposes
                         # (Cleanup job will eventually catch it on restart, or we could trigger cleanup here)
                         is_running = False
                         logger.debug(f"Ignoring stale running status for {job_id} (started {running_since})")

                except Exception as e:
                    logger.warning(f"Error parsing running_since for {job_id}: {e}")
                    pass
    except Exception as e:
        logger.warning(f"Failed to check running status for {job_id}: {e}")
    
    # Get last error from failed executions
    last_error = None
    try:
        from supabase_client import SupabaseClient
        client = SupabaseClient(use_service_role=True)
        
        # Query for most recent failed execution
        failed_result = client.supabase.table("job_executions")\
            .select("error_message, completed_at")\
            .eq("job_name", job_name)\
            .eq("status", "failed")\
            .order("completed_at", desc=True)\
            .limit(1)\
            .execute()
        
        if failed_result.data and len(failed_result.data) > 0:
            last_error = failed_result.data[0].get('error_message')
    except Exception as e:
        logger.warning(f"Failed to fetch last error for {job_id}: {e}")
    
    # Safely access next_run_time (may not be available when scheduler is stopped)
    next_run_time = getattr(job, 'next_run_time', None)
    
    # Check if scheduler is stopped
    scheduler = get_scheduler(create=False)
    scheduler_stopped = (scheduler is None or (hasattr(scheduler, 'running') and not scheduler.running))
    
    # If next_run_time is None and scheduler is stopped, try to calculate from trigger
    # When scheduler is running, APScheduler handles paused jobs correctly, so don't override
    if next_run_time is None and scheduler_stopped and job.trigger is not None:
        try:
            # Calculate next fire time from trigger even when scheduler is stopped
            now = datetime.now(timezone.utc)
            # Some triggers need timezone-aware datetime
            if hasattr(job.trigger, 'timezone') and job.trigger.timezone:
                now = now.astimezone(job.trigger.timezone)
            next_run_time = job.trigger.get_next_fire_time(None, now)
        except Exception as e:
            logger.debug(f"Could not calculate next_run_time from trigger for job {job.id}: {e}")
            next_run_time = None
    
    return {
        'id': job.id,
        'name': job.name or job.id,
        'next_run': next_run_time,
        'is_paused': next_run_time is None,
        'trigger': str(job.trigger),
        'is_running': is_running,
        'running_since': running_since,
        'last_error': last_error,
        'recent_logs': get_job_logs(job.id, limit=5)
    }


def _format_trigger_readable(trigger: Any) -> str:
    """Format an APScheduler trigger object into a readable string.
    
    Args:
        trigger: APScheduler trigger object (IntervalTrigger, CronTrigger, etc.)
    
    Returns:
        Human-readable schedule description
    """
    if trigger is None:
        return 'Manual'
    
    # Handle string triggers (from DummyJob)
    if isinstance(trigger, str):
        if trigger == 'unknown':
            return 'Unknown'
        return trigger
    
    # Get the class name to determine trigger type
    trigger_type = type(trigger).__name__
    
    if trigger_type == 'IntervalTrigger':
        # Format interval triggers
        interval = trigger.interval
        if isinstance(interval, timedelta):
            total_seconds = int(interval.total_seconds())
            if total_seconds < 60:
                return f'Every {total_seconds} second{"s" if total_seconds != 1 else ""}'
            elif total_seconds < 3600:
                minutes = total_seconds // 60
                return f'Every {minutes} minute{"s" if minutes != 1 else ""}'
            elif total_seconds < 86400:
                hours = total_seconds // 3600
                return f'Every {hours} hour{"s" if hours != 1 else ""}'
            else:
                days = total_seconds // 86400
                return f'Every {days} day{"s" if days != 1 else ""}'
        else:
            return f'Interval: {interval}'
    
    elif trigger_type == 'CronTrigger':
        # Format cron triggers
        parts = []
        
        # Handle time - use getattr() safely as CronTrigger may not have these attributes directly
        hour_str = None
        minute_str = None
        
        hour = getattr(trigger, 'hour', None)
        if hour is not None:
            if isinstance(hour, int):
                hour_str = f"{hour:02d}"
            elif isinstance(hour, str):
                # Handle ranges like '9-15', '*/6', etc.
                if '-' in hour:
                    hour_str = f"{hour} (range)"
                elif hour.startswith('*/'):
                    interval = hour[2:]
                    hour_str = f"Every {interval} hours"
                else:
                    hour_str = str(hour)
            else:
                hour_str = str(hour)
        
        minute = getattr(trigger, 'minute', None)
        if minute is not None:
            if isinstance(minute, int):
                minute_str = f"{minute:02d}"
            elif isinstance(minute, str):
                # Handle lists like '0,15,30,45' or ranges
                if ',' in minute:
                    minute_str = f"at {minute.replace(',', ', ')}"
                elif '-' in minute:
                    minute_str = f"{minute} (range)"
                elif minute.startswith('*/'):
                    interval = minute[2:]
                    minute_str = f"Every {interval} minutes"
                else:
                    minute_str = str(minute)
            else:
                minute_str = str(minute)
        
        # Combine hour and minute
        if hour_str and minute_str:
            if isinstance(hour, int) and isinstance(minute, int):
                time_str = f"{hour_str}:{minute_str}"
                tz = getattr(trigger, 'timezone', None)
                if tz:
                    parts.append(f"At {time_str} ({tz})")
                else:
                    parts.append(f"At {time_str}")
            else:
                # Complex time expression
                time_desc = f"Hour {hour_str}, Minute {minute_str}"
                tz = getattr(trigger, 'timezone', None)
                if tz:
                    time_desc += f" ({tz})"
                parts.append(time_desc)
        elif hour_str:
            parts.append(f"Hour {hour_str}")
        elif minute_str:
            parts.append(f"Minute {minute_str}")
        
        # Handle day of week
        day_of_week = getattr(trigger, 'day_of_week', None)
        if day_of_week is not None:
            days = day_of_week
            if isinstance(days, (list, tuple)):
                day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
                day_str = ', '.join([day_names[d] if isinstance(d, int) and 0 <= d < 7 else str(d) for d in days])
                parts.append(f"on {day_str}")
            elif isinstance(days, str):
                # Handle string like 'mon-fri'
                if '-' in days:
                    parts.append(f"on {days}")
                else:
                    parts.append(f"on {days}")
            elif isinstance(days, int):
                day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
                if 0 <= days < 7:
                    parts.append(f"on {day_names[days]}")
                else:
                    parts.append(f"on day {days}")
            else:
                parts.append(f"on {days}")
        
        day = getattr(trigger, 'day', None)
        if day is not None:
            parts.append(f"Day {day}")
        
        month = getattr(trigger, 'month', None)
        if month is not None:
            month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            if isinstance(month, int) and 1 <= month <= 12:
                parts.append(f"in {month_names[month - 1]}")
            else:
                parts.append(f"in {month}")
        
        if parts:
            return ' '.join(parts)
        else:
            # Fallback: try to get readable representation from trigger
            try:
                # APScheduler CronTrigger has a __str__ that might be useful
                trigger_repr = str(trigger)
                # Clean up common patterns
                if 'CronTrigger' in trigger_repr:
                    # Extract the cron expression part
                    if '(' in trigger_repr and ')' in trigger_repr:
                        expr = trigger_repr[trigger_repr.find('(')+1:trigger_repr.rfind(')')]
                        return f"Cron: {expr}"
                return trigger_repr
            except:
                return "Cron schedule"
    
    elif trigger_type == 'DateTrigger':
        run_date = getattr(trigger, 'run_date', None)
        if run_date:
            return f"Once at {run_date}"
        return "One-time"
    
    # Fallback: convert to string and try to clean it up
    trigger_str = str(trigger)
    # Try to extract useful info from string representation
    if 'interval' in trigger_str.lower():
        return trigger_str
    elif 'cron' in trigger_str.lower():
        return trigger_str
    else:
        return trigger_str


def get_all_jobs_status_batched() -> List[Dict[str, Any]]:
    """Get status of all scheduled jobs using batched database queries for performance.
    
    This is an optimized version that makes 3-5 total queries instead of N queries per job.
    Reduces load time from 20+ seconds to <1 second for 10+ jobs.
    
    Returns:
        List of job status dictionaries
    """
    import time
    start_time = time.perf_counter()
    
    # Import AVAILABLE_JOBS for parameter definitions
    try:
        from scheduler.jobs import AVAILABLE_JOBS
    except ImportError:
        # Fallback if import fails (shouldn't happen in normal operation)
        AVAILABLE_JOBS = {}
        
    # Use create=False to avoid creating a new scheduler instance if one doesn't exist
    # This prevents "Duplicate scheduler created" logs from UI workers
    scheduler = get_scheduler(create=False)
    
    if scheduler:
        # With SQLAlchemyJobStore, jobs are always available from the database,
        # even if the scheduler is stopped
        jobs = scheduler.get_jobs()
    else:
        # If scheduler doesn't exist, we can't get jobs
        # This only happens in worker processes that haven't initialized the scheduler
        logger.debug("Scheduler not initialized, no jobs available")
        return []
    
    if not jobs:
        logger.debug("No jobs found in jobstore (scheduler may not have been started yet)")
        return []
    
    # Map all job IDs to job names
    job_id_to_name = {}
    job_id_to_job = {}
    job_names = set()
    
    for job in jobs:
        job_name = _map_job_id_to_job_name(job.id)
        job_id_to_name[job.id] = job_name
        job_id_to_job[job.id] = job
        job_names.add(job_name)
    
    job_names_list = list(job_names)
    
    # Initialize result structure
    job_statuses = {}
    scheduler_stopped = (scheduler is None or (hasattr(scheduler, 'running') and not scheduler.running))
    
    for job in jobs:
        # With SQLAlchemyJobStore, jobs always have proper trigger objects
        # Safely access next_run_time (may not be available when scheduler is stopped)
        next_run_time = getattr(job, 'next_run_time', None)
        
        # If next_run_time is None and scheduler is stopped, try to calculate from trigger
        # When scheduler is running, APScheduler handles paused jobs correctly, so don't override
        if next_run_time is None and scheduler_stopped and job.trigger is not None:
            try:
                # Calculate next fire time from trigger even when scheduler is stopped
                now = datetime.now(timezone.utc)
                # Some triggers need timezone-aware datetime
                if hasattr(job.trigger, 'timezone') and job.trigger.timezone:
                    now = now.astimezone(job.trigger.timezone)
                next_run_time = job.trigger.get_next_fire_time(None, now)
            except Exception as e:
                logger.debug(f"Could not calculate next_run_time from trigger for job {job.id}: {e}")
                next_run_time = None
        
        # Check if job is paused (next_run_time is None when paused)
        # A job is paused if it has no next_run_time even after trying to calculate from trigger
        # This is independent of whether the scheduler is running or stopped
        is_paused = (next_run_time is None and job.trigger is not None)
        
        # Determine if job has a schedule (not manual-only)
        # A job has a schedule if it has a trigger that's not None
        has_schedule = job.trigger is not None
        
        job_statuses[job.id] = {
            'id': job.id,
            'name': job.name or job.id,
            'next_run': next_run_time,
            'is_paused': is_paused,
            'trigger': _format_trigger_readable(job.trigger),
            'is_running': False,
            'running_since': None,
            'last_error': None,
            'recent_logs': [],
            'scheduler_stopped': scheduler_stopped,  # Flag to help frontend show appropriate message
            'has_schedule': has_schedule,  # Flag to show if job has a schedule
            'parameters': AVAILABLE_JOBS.get(job.id, {}).get('parameters', {})  # Expose parameters for frontend UI
        }
    
    # Batch query 1: Get all running jobs
    running_jobs = {}
    try:
        from supabase_client import SupabaseClient
        client = SupabaseClient(use_service_role=True)
        
        # Get all running executions for our job names
        running_result = client.supabase.table("job_executions")\
            .select("job_name, started_at")\
            .in_("job_name", job_names_list)\
            .eq("status", "running")\
            .order("started_at", desc=True)\
            .execute()
        
        if running_result.data:
            # Group by job_name, keeping only the most recent for each
            job_name_to_latest = {}
            for record in running_result.data:
                job_name = record.get('job_name')
                if job_name not in job_name_to_latest:
                    job_name_to_latest[job_name] = record
            
            # Map back to job IDs and check if still valid (not stale)
            now_utc = datetime.now(timezone.utc)
            for job_id, job_name in job_id_to_name.items():
                if job_name in job_name_to_latest:
                    record = job_name_to_latest[job_name]
                    started_at = record.get('started_at')
                    if started_at:
                        try:
                            if isinstance(started_at, str):
                                running_since = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                            else:
                                running_since = started_at
                            
                            if running_since.tzinfo is None:
                                running_since = running_since.replace(tzinfo=timezone.utc)
                            else:
                                running_since = running_since.astimezone(timezone.utc)
                            
                            # Ignore if older than 6 hours (stale)
                            if (now_utc - running_since).total_seconds() < 6 * 3600:
                                job_statuses[job_id]['is_running'] = True
                                job_statuses[job_id]['running_since'] = running_since
                        except Exception as e:
                            logger.debug(f"Error parsing running_since for {job_id}: {e}")
    except Exception as e:
        logger.warning(f"Failed to batch query running jobs: {e}")
    
    # Batch query 2: Get most recent execution status (to check for errors vs success)
    try:
        from supabase_client import SupabaseClient
        client = SupabaseClient(use_service_role=True)
        
        # Get most recent execution (success or failed) for each job
        # We need to see if the *last* run was a failure
        status_result = client.supabase.table("job_executions")\
            .select("job_name, status, error_message, completed_at")\
            .in_("job_name", job_names_list)\
            .in_("status", ["success", "failed"])\
            .order("completed_at", desc=True)\
            .limit(200)\
            .execute()
        
        if status_result.data:
            # Group by job_name, keeping only the absolute most recent for each
            job_name_to_latest_status = {}
            for record in status_result.data:
                job_name = record.get('job_name')
                # Since we ordered by completed_at desc, the first one we see is the latest
                if job_name not in job_name_to_latest_status:
                    job_name_to_latest_status[job_name] = record
            
            # Map back to job IDs
            for job_id, job_name in job_id_to_name.items():
                if job_name in job_name_to_latest_status:
                    latest = job_name_to_latest_status[job_name]
                    # Only show error if the MOST RECENT execution was a failure
                    if latest.get('status') == 'failed':
                        job_statuses[job_id]['last_error'] = latest.get('error_message')
                    else:
                        # Job succeeded recently, so clear any error status
                        job_statuses[job_id]['last_error'] = None
    except Exception as e:
        logger.warning(f"Failed to batch query last errors: {e}")
    
    # Batch query 3: Get recent logs for all jobs
    # We'll get recent executions and group by job_name in memory
    try:
        from supabase_client import SupabaseClient
        client = SupabaseClient(use_service_role=True)
        
        # Get recent successful/failed executions for all our jobs
        # Get more than we need, then group by job_name
        logs_result = client.supabase.table("job_executions")\
            .select("*")\
            .in_("job_name", job_names_list)\
            .in_("status", ["success", "failed"])\
            .order("completed_at", desc=True)\
            .limit(200)\
            .execute()  # Get enough to have recent logs for each job
        
        if logs_result.data:
            # Group logs by job_name, keeping most recent per job
            job_name_to_logs = {}
            for record in logs_result.data:
                job_name = record.get('job_name')
                if job_name not in job_name_to_logs:
                    job_name_to_logs[job_name] = []
                job_name_to_logs[job_name].append(record)
            
            # Process logs for each job (limit to 5 per job)
            for job_id, job_name in job_id_to_name.items():
                if job_name in job_name_to_logs:
                    logs = []
                    for record in job_name_to_logs[job_name][:5]:  # Limit to 5 per job
                        # Convert database record to log format (same logic as get_job_logs)
                        completed_at = record.get('completed_at')
                        if completed_at:
                            try:
                                if isinstance(completed_at, str):
                                    timestamp = datetime.fromisoformat(completed_at.replace('Z', '+00:00'))
                                else:
                                    timestamp = completed_at
                            except Exception:
                                timestamp = datetime.now(timezone.utc)
                        else:
                            timestamp = datetime.now(timezone.utc)
                        
                        status = record.get('status', 'failed')
                        success = (status == 'success')
                        
                        message = record.get('error_message', '')
                        if not message and record.get('funds_processed'):
                            funds = record.get('funds_processed', [])
                            if isinstance(funds, list) and funds:
                                message = f"Processed {len(funds)} fund(s)"
                            else:
                                message = "Completed successfully"
                        elif not message:
                            message = "Completed successfully" if success else "Job failed"
                        
                        duration_ms = record.get('duration_ms')
                        if duration_ms is None:
                            duration_ms = 0
                            started_at = record.get('started_at')
                            if started_at and completed_at:
                                try:
                                    if isinstance(started_at, str):
                                        start_dt = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                                    else:
                                        start_dt = started_at
                                    
                                    if isinstance(completed_at, str):
                                        end_dt = datetime.fromisoformat(completed_at.replace('Z', '+00:00'))
                                    else:
                                        end_dt = completed_at
                                    
                                    if start_dt.tzinfo is None:
                                        start_dt = start_dt.replace(tzinfo=timezone.utc)
                                    else:
                                        start_dt = start_dt.astimezone(timezone.utc)
                                    
                                    if end_dt.tzinfo is None:
                                        end_dt = end_dt.replace(tzinfo=timezone.utc)
                                    else:
                                        end_dt = end_dt.astimezone(timezone.utc)
                                    
                                    delta = end_dt - start_dt
                                    duration_seconds = delta.total_seconds()
                                    duration_ms = max(0, int(duration_seconds * 1000))
                                except Exception:
                                    duration_ms = 0
                        else:
                            duration_ms = max(0, int(duration_ms))
                        
                        logs.append({
                            'timestamp': timestamp,
                            'success': success,
                            'message': message,
                            'duration_ms': duration_ms
                        })
                    
                    job_statuses[job_id]['recent_logs'] = logs
    except Exception as e:
        logger.warning(f"Failed to batch query job logs: {e}")
    
    # Also include in-memory logs (for very recent executions not yet in DB)
    for job_id in job_statuses.keys():
        in_memory_logs = _job_logs.get(job_id, [])
        existing_logs = job_statuses[job_id]['recent_logs']
        
        # Merge and deduplicate
        for mem_log in in_memory_logs:
            mem_ts = mem_log.get('timestamp')
            if mem_ts:
                is_duplicate = False
                for existing_log in existing_logs:
                    existing_ts = existing_log.get('timestamp')
                    if existing_ts and abs((mem_ts - existing_ts).total_seconds()) < 1:
                        is_duplicate = True
                        break
                if not is_duplicate:
                    existing_logs.append(mem_log)
        
        # Sort and limit
        existing_logs.sort(key=lambda x: x.get('timestamp', datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
        job_statuses[job_id]['recent_logs'] = existing_logs[:5]
    
    elapsed_ms = (time.perf_counter() - start_time) * 1000
    logger.debug(f"⏱️ get_all_jobs_status_batched: {elapsed_ms:.2f}ms for {len(jobs)} jobs")
    
    return list(job_statuses.values())


def get_all_jobs_status() -> List[Dict[str, Any]]:
    """Get status of all scheduled jobs.
    
    Uses batched queries for performance. For single job queries, use get_job_status().
    """
    return get_all_jobs_status_batched()


def _safe_job_wrapper(job_func, job_id: str, **kwargs):
    """Wrapper that catches all exceptions from manually triggered jobs.
    
    This prevents manual job failures from crashing the scheduler thread pool.
    """
    try:
        logger.debug(f"Executing manual job: {job_id}")
        job_func(**kwargs)
        logger.debug(f"Manual job completed: {job_id}")
    except Exception as e:
        # Log the error but don't re-raise - this prevents scheduler crashes
        logger.error(f"Manual job {job_id} failed with exception: {e}", exc_info=True)
        try:
            # Try to log to job_executions if possible
            log_job_execution(job_id, success=False, message=f"Manual execution failed: {str(e)}", duration_ms=0)
        except:
            pass  # Best effort logging


def run_job_now(job_id: str, **kwargs) -> bool:
    """Trigger a job to run immediately in the background.
    
    This schedules the job to run asynchronously via the scheduler's thread pool
    instead of calling it synchronously in the main thread, which prevents UI freezing.
    
    Args:
        job_id: The job identifier
        **kwargs: Arguments to pass to the job function
    
    Returns True if job was scheduled, False if job not found.
    """
    try:
        scheduler = get_scheduler()
        if not scheduler:
            logger.error("Scheduler not available")
            return False
            
        if not scheduler.running:
            logger.error("Scheduler is not running")
            return False
        
        job = scheduler.get_job(job_id)
        
        if not job:
            logger.warning(f"Job not found: {job_id}")
            return False
        
        if not job.func:
            logger.error(f"Job {job_id} has no function attached")
            return False
        
        # Schedule the job to run ASYNCHRONOUSLY via the scheduler
        # This prevents blocking the main thread (and the UI)
        try:
            logger.debug(f"Scheduling job for immediate async execution: {job_id} (args: {kwargs})")
            
            # Generate unique ID for manual run
            manual_id = f"{job_id}_manual_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}"
            
            # IMPORTANT: Wrap the job function to prevent exceptions from crashing the scheduler
            # Use add_job with trigger='date' to run once, immediately, in background thread
            scheduler.add_job(
                _safe_job_wrapper,  # Use wrapper instead of direct job.func
                trigger='date',  # Run once at a specific datetime (now)
                args=(job.func, job_id),  # Pass the actual function and ID as args
                kwargs=kwargs,   # Pass keyword arguments to the wrapped function
                id=manual_id,
                name=f"Manual: {job.name or job_id}",
                replace_existing=False,  # Allow multiple manual runs
                misfire_grace_time=None  # Don't skip manual jobs if delayed
            )
            
            logger.debug(f"Job {job_id} scheduled for async execution as {manual_id}")
            return True
        except Exception as e:
            logger.error(f"Error adding job {job_id} to scheduler: {e}", exc_info=True)
            return False
    except Exception as e:
        logger.error(f"Unexpected error in run_job_now for {job_id}: {e}", exc_info=True)
        return False


def pause_job(job_id: str) -> bool:
    """Pause a scheduled job."""
    scheduler = get_scheduler()
    job = scheduler.get_job(job_id)
    
    if not job:
        return False
    
    scheduler.pause_job(job_id)
    logger.info(f"Paused job: {job_id}")
    return True


def resume_job(job_id: str) -> bool:
    """Resume a paused job."""
    scheduler = get_scheduler()
    job = scheduler.get_job(job_id)
    
    if not job:
        return False
    
    scheduler.resume_job(job_id)
    logger.info(f"Resumed job: {job_id}")
    return True
