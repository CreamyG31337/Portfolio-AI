#!/usr/bin/env python3
"""
Ticker Analysis Job
===================

Analyzes tickers with 3 months of multi-source data.
Runs daily at 10 PM EST.
Processes holdings first (priority=100), then watched tickers (priority=10).
Stops after 2 hours, resumes next day where it left off.
"""

import logging
import os
import time
from datetime import datetime, timezone
from typing import List, Tuple

# Import log_job_execution if available (optional for standalone testing)
try:
    from scheduler.scheduler_core import log_job_execution
except ImportError:
    # Fallback for standalone testing
    def log_job_execution(job_id, success, message="", duration_ms=0):
        logger.info(f"Job {job_id}: {'SUCCESS' if success else 'FAILED'} - {message} ({duration_ms}ms)")
from supabase_client import SupabaseClient
from postgres_client import PostgresClient
from ollama_client import get_ollama_client
from ticker_analysis_service import TickerAnalysisService
from ai_skip_list_manager import AISkipListManager

logger = logging.getLogger(__name__)


def _format_no_tickers_message(service: TickerAnalysisService) -> str:
    stats = getattr(service, "last_selection_stats", {}) or {}
    manual = stats.get("manual_candidates", 0)
    holdings = stats.get("holdings_candidates", 0)
    watchlist = stats.get("watchlist_candidates", 0)
    skipped = stats.get("filtered_by_skip_list", 0)
    recent = stats.get("filtered_by_recently_analyzed", 0)
    total_candidates = manual + holdings + watchlist
    if total_candidates == 0:
        return "No tickers to analyze (no candidates: manual=0, holdings=0, watchlist=0)"
    return (
        f"No tickers to analyze — all {total_candidates} candidates filtered "
        f"(skip_list={skipped}, recently_analyzed={recent}; "
        f"manual={manual}, holdings={holdings}, watchlist={watchlist}). "
        "Check ai_analysis_skip_list if this persists."
    )


def _ticker_analysis_queue_mode_enabled() -> bool:
    try:
        from scheduler.ai_task_workers import is_ai_queue_job_enabled

        return is_ai_queue_job_enabled("ticker_analysis")
    except Exception as exc:
        logger.warning("AI queue mode check failed for ticker_analysis (using legacy path): %s", exc)
        return False


def _run_ticker_analysis_enqueue_mode(job_id: str, start_time: float) -> None:
    """Queue-mode ticker analysis: select tickers and enqueue one task per ticker."""

    try:
        from utils.job_tracking import mark_job_completed, mark_job_failed, mark_job_started
        from scheduler.ai_task_workers import AIQueueConfig, enqueue_ticker_analysis_tasks

        target_date = datetime.now(timezone.utc).date()
        mark_job_started(job_id, target_date)
    except Exception as exc:
        logger.warning("Could not initialize queue-mode job tracking: %s", exc)
        target_date = datetime.now(timezone.utc).date()
        mark_job_completed = None
        mark_job_failed = None
        AIQueueConfig = None
        enqueue_ticker_analysis_tasks = None

    logger.info("Starting Ticker Analysis enqueue job (AI task queue mode)...")

    try:
        supabase = SupabaseClient(use_service_role=True)
        postgres = PostgresClient()
        skip_list = AISkipListManager(supabase)
        service = TickerAnalysisService(get_ollama_client(), supabase, postgres, skip_list)
        tickers = service.get_tickers_to_analyze()

        if not tickers:
            duration_ms = int((time.time() - start_time) * 1000)
            message = _format_no_tickers_message(service)
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            if mark_job_completed:
                mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=message)
            logger.info("ℹ️ %s", message)
            return

        if enqueue_ticker_analysis_tasks is None or AIQueueConfig is None:
            raise RuntimeError("AI task queue helpers unavailable")

        config = AIQueueConfig.from_env()
        enqueued_by = os.getenv("AI_QUEUE_ENQUEUED_BY", "cron").strip() or "cron"
        enqueue_stats = enqueue_ticker_analysis_tasks(
            supabase,
            tickers,
            enqueued_by=enqueued_by,
            max_attempts=config.max_attempts,
        )
        duration_ms = int((time.time() - start_time) * 1000)
        message = (
            f"Enqueued {enqueue_stats['enqueued']}/{enqueue_stats['attempted']} ticker_analysis "
            f"task(s); failed={enqueue_stats['failed']}."
        )
        log_job_execution(job_id, success=enqueue_stats["failed"] == 0, message=message, duration_ms=duration_ms)
        if enqueue_stats["failed"] == 0:
            if mark_job_completed:
                mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=message)
        elif mark_job_failed:
            mark_job_failed(job_id, target_date, None, message, duration_ms=duration_ms)
        logger.info("✅ Ticker Analysis enqueue complete: %s", message)
    except Exception as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Ticker Analysis enqueue failed: {exc}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        if mark_job_failed:
            mark_job_failed(job_id, target_date, None, message, duration_ms=duration_ms)
        logger.error("❌ %s", message, exc_info=True)

def ticker_analysis_job() -> None:
    """Analyze tickers. Holdings first, then watched. 2-hour max. Resumable."""
    job_id = 'ticker_analysis'
    start_time = time.time()
    max_duration = 2 * 60 * 60  # 2 hours

    if _ticker_analysis_queue_mode_enabled():
        _run_ticker_analysis_enqueue_mode(job_id, start_time)
        return
    
    # Global AI lock (prevent overlapping AI jobs)
    try:
        from utils.job_tracking import get_running_ai_job
        running_ai = get_running_ai_job(exclude_job_name=job_id)
        if running_ai:
            logger.info(f"⏸️  AI lock active: {running_ai} is running. Skipping {job_id}.")
            return
    except Exception as e:
        logger.warning(f"AI lock check failed (continuing): {e}")

    # Check if job is already running (prevents concurrent execution)
    try:
        supabase_check = SupabaseClient(use_service_role=True)
        running_check = supabase_check.supabase.table('job_executions') \
            .select('id') \
            .eq('job_name', job_id) \
            .eq('status', 'running') \
            .execute()
        
        if running_check.data:
            logger.info(f"⏸️  Job {job_id} is already running. Skipping to prevent concurrent execution.")
            return
    except Exception as e:
        logger.warning(f"Could not check if job is running: {e}")
        # Continue anyway - better to run twice than fail silently
    
    try:
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        target_date = datetime.now(timezone.utc).date()
        mark_job_started(job_id, target_date)
    except Exception as e:
        logger.warning(f"Could not mark job started: {e}")
        target_date = datetime.now(timezone.utc).date()  # Still set target_date for error handling
    
    logger.info("Starting Ticker Analysis Job...")
    
    # Initialize clients
    try:
        supabase = SupabaseClient(use_service_role=True)
        postgres = PostgresClient()
        ollama = get_ollama_client()
        
        if not ollama:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "Ollama client not available"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            try:
                mark_job_failed(job_id, target_date, None, message, duration_ms=duration_ms)
            except Exception:
                pass
            logger.error(f"❌ {message}")
            return
        
        skip_list = AISkipListManager(supabase)
        service = TickerAnalysisService(ollama, supabase, postgres, skip_list)
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Failed to initialize clients: {e}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        try:
            mark_job_failed(job_id, target_date, None, message, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error(f"❌ {message}")
        return
    
    # Get priority-sorted tickers (holdings first, then watched)
    tickers = service.get_tickers_to_analyze()

    if not tickers:
        duration_ms = int((time.time() - start_time) * 1000)
        stats = getattr(service, "last_selection_stats", {}) or {}
        manual = stats.get("manual_candidates", 0)
        holdings = stats.get("holdings_candidates", 0)
        watchlist = stats.get("watchlist_candidates", 0)
        skipped = stats.get("filtered_by_skip_list", 0)
        recent = stats.get("filtered_by_recently_analyzed", 0)
        total_candidates = manual + holdings + watchlist
        if total_candidates == 0:
            message = (
                "No tickers to analyze (no candidates: manual=0, holdings=0, watchlist=0)"
            )
        else:
            message = (
                f"No tickers to analyze — all {total_candidates} candidates filtered "
                f"(skip_list={skipped}, recently_analyzed={recent}; "
                f"manual={manual}, holdings={holdings}, watchlist={watchlist}). "
                "Check ai_analysis_skip_list if this persists."
            )
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        try:
            mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=message)
        except Exception:
            pass
        logger.info("ℹ️ %s", message)
        return
    
    logger.info(f"Found {len(tickers)} tickers to analyze (prioritized)")
    
    processed = 0
    failed = 0
    
    try:
        for ticker, priority in tickers:
            # Check time limit
            elapsed = time.time() - start_time
            if elapsed > max_duration:
                duration_ms = int((time.time() - start_time) * 1000)
                message = f"Stopped after 2 hours. Processed {processed}/{len(tickers)} tickers. {failed} failed."
                log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
                try:
                    mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=message)
                except Exception:
                    pass
                logger.info(f"⏰ {message}")
                logger.info(f"   Remaining tickers will be processed in next run")
                break
            
            try:
                logger.info(f"Analyzing {ticker} (priority={priority})...")
                service.analyze_ticker(ticker)
                processed += 1
                
                # Mark manual request complete if this was a manual request (priority >= 1000)
                if priority >= 1000:
                    service.mark_manual_request_complete(ticker, success=True)
                
                # Log progress every 10 tickers
                if processed % 10 == 0:
                    elapsed_min = elapsed / 60
                    logger.info(f"Progress: {processed} processed, {elapsed_min:.1f} minutes elapsed")
                
            except Exception as e:
                logger.error(f"Failed to analyze {ticker}: {e}", exc_info=True)
                # Mark manual request as failed if this was a manual request
                if priority >= 1000:
                    service.mark_manual_request_complete(ticker, success=False, error_message=str(e)[:500])
                # Skip list manager handles repeated failures
                failed += 1
        
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Processed {processed}/{len(tickers)} tickers. {failed} failed."
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        try:
            mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=message)
        except Exception:
            pass
        logger.info(f"✅ Ticker Analysis complete: {message}")
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        duration_min = duration_ms / 60000
        error_msg = f"Job failed after {duration_min:.1f} minutes: {str(e)}. Progress: {processed}/{len(tickers)} processed, {failed} failed."
        log_job_execution(job_id, success=False, message=error_msg, duration_ms=duration_ms)
        try:
            mark_job_failed(job_id, target_date, None, error_msg, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error(f"❌ Ticker Analysis job failed: {e}", exc_info=True)
