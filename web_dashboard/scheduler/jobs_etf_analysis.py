#!/usr/bin/env python3
"""
ETF Group Analysis Job
======================

Analyzes ETF holdings changes as groups using AI.
Runs daily at 9 PM EST after ETF Watchtower.
Resumable via ai_analysis_queue table.
"""

import logging
import time
from datetime import datetime, timedelta, UTC
from typing import Any

# Import log_job_execution if available (optional for standalone testing)
try:
    from scheduler.scheduler_core import log_job_execution
except ImportError:
    # Fallback for standalone testing
    def log_job_execution(job_id, success, message="", duration_ms=0):
        logger.info(f"Job {job_id}: {'SUCCESS' if success else 'FAILED'} - {message} ({duration_ms}ms)")
from supabase_client import SupabaseClient
from ollama_client import get_ollama_client
from postgres_client import PostgresClient
from research_repository import ResearchRepository
from etf_group_analysis import ETFGroupAnalysisService

logger = logging.getLogger(__name__)

# Finish within one deploy window; queue resumes next run.
MAX_JOB_DURATION = 35 * 60  # 35 minutes total
MAX_ITEMS_PER_RUN = 6  # ~5–6 LLM calls per night; avoids 1h+ runs killed on deploy
QUEUE_LOOKBACK_DAYS = 7  # queue missing articles for recent trading days only


def reset_stale_in_progress_queue(max_age_hours: float = 2.0) -> int:
    """Reset ``in_progress`` rows left by container restart so the job can resume."""
    try:
        db = SupabaseClient(use_service_role=True)
        cutoff = (datetime.now(UTC) - timedelta(hours=max_age_hours)).isoformat()
        result = (
            db.supabase.table("ai_analysis_queue")
            .update({"status": "pending", "started_at": None})
            .eq("analysis_type", "etf_group")
            .eq("status", "in_progress")
            .lt("started_at", cutoff)
            .execute()
        )
        n = len(result.data or [])
        if n:
            logger.info("Reset %s stale in_progress etf_group queue item(s) to pending", n)
        return n
    except Exception as e:
        logger.warning("Could not reset stale in_progress queue rows: %s", e)
        return 0


def get_pending_etf_analysis(limit: int = MAX_ITEMS_PER_RUN) -> list[dict]:
    """Pending/failed ETF group work, newest ``target_key`` dates first (bounded per run)."""
    try:
        db = SupabaseClient(use_service_role=True)
        result = (
            db.supabase.table("ai_analysis_queue")
            .select("*")
            .eq("analysis_type", "etf_group")
            .in_("status", ["pending", "failed"])
            .order("created_at", desc=True)
            .limit(max(limit * 3, limit))
            .execute()
        )
        rows = list(result.data or [])

        def _sort_key(item: dict[str, Any]) -> str:
            key = str(item.get("target_key") or "")
            parts = key.split("_", 1)
            return parts[1] if len(parts) > 1 else ""

        rows.sort(key=_sort_key, reverse=True)
        return rows[:limit]
    except Exception as e:
        logger.error(f"Error fetching pending ETF analysis: {e}")
        return []


def _article_exists(repo: ResearchRepository, etf_ticker: str, day_str: str) -> bool:
    url = f"etf-analysis://{etf_ticker.upper()}/{day_str}"
    try:
        rows = repo.client.execute_query(
            "SELECT 1 FROM research_articles WHERE url = %s LIMIT 1",
            (url,),
        )
        return bool(rows)
    except Exception:
        return False


def queue_recent_missing_etf_analysis(
    repo: ResearchRepository,
    lookback_days: int = QUEUE_LOOKBACK_DAYS,
) -> int:
    """Queue ETF/date pairs with holdings changes but no saved ETF Analysis article yet."""
    try:
        db = SupabaseClient(use_service_role=True)
        today = datetime.now(UTC).date()
        queued = 0
        for offset in range(lookback_days):
            day = today - timedelta(days=offset)
            day_str = day.strftime("%Y-%m-%d")
            result = (
                db.supabase.from_("etf_holdings_changes")
                .select("etf_ticker")
                .eq("date", day_str)
                .execute()
            )
            etf_tickers = sorted({row["etf_ticker"] for row in (result.data or []) if row.get("etf_ticker")})
            for etf_ticker in etf_tickers:
                if _article_exists(repo, etf_ticker, day_str):
                    continue
                target_key = f"{etf_ticker}_{day_str}"
                try:
                    db.supabase.table("ai_analysis_queue").insert(
                        {
                            "analysis_type": "etf_group",
                            "target_key": target_key,
                            "priority": 0,
                            "status": "pending",
                        }
                    ).execute()
                    queued += 1
                except Exception as exc:
                    # unique_pending_analysis: duplicate pending row is fine
                    if "duplicate" not in str(exc).lower() and "unique" not in str(exc).lower():
                        logger.debug("Queue insert skip %s: %s", target_key, exc)
        if queued:
            logger.info("Queued %s ETF group analysis item(s) for last %s day(s)", queued, lookback_days)
        return queued
    except Exception as e:
        logger.error(f"Error queueing ETF analysis: {e}", exc_info=True)
        return 0

def mark_analysis_started(queue_id: str):
    """Mark analysis as started in queue."""
    try:
        db = SupabaseClient(use_service_role=True)
        db.supabase.table('ai_analysis_queue') \
            .update({
                'status': 'in_progress',
                'started_at': datetime.now(UTC).isoformat()
            }) \
            .eq('id', queue_id) \
            .execute()
    except Exception as e:
        logger.warning(f"Error marking analysis started: {e}")

def mark_analysis_completed(queue_id: str):
    """Mark analysis as completed in queue."""
    try:
        db = SupabaseClient(use_service_role=True)
        db.supabase.table('ai_analysis_queue') \
            .update({
                'status': 'completed',
                'completed_at': datetime.now(UTC).isoformat()
            }) \
            .eq('id', queue_id) \
            .execute()
    except Exception as e:
        logger.warning(f"Error marking analysis completed: {e}")

def mark_analysis_failed(queue_id: str, error: str):
    """Mark analysis as failed in queue."""
    try:
        db = SupabaseClient(use_service_role=True)
        cur = (
            db.supabase.table("ai_analysis_queue")
            .select("retry_count")
            .eq("id", queue_id)
            .limit(1)
            .execute()
        )
        prev = 0
        if cur.data:
            prev = int(cur.data[0].get("retry_count") or 0)
        db.supabase.table("ai_analysis_queue").update(
            {
                "status": "failed",
                "error_message": (error or "")[:500],
                "retry_count": prev + 1,
            }
        ).eq("id", queue_id).execute()
    except Exception as e:
        logger.warning(f"Error marking analysis failed: {e}")

def etf_group_analysis_job() -> None:
    """Analyze ETF changes as groups. Resumable via queue."""
    job_id = 'etf_group_analysis'
    start_time = time.time()
    target_date = datetime.now(UTC).date()

    from utils.job_tracking import log_job_step

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
        from utils.job_tracking import mark_job_started, mark_job_completed

        mark_job_started(job_id, target_date)
    except Exception as e:
        logger.warning(f"Could not mark job started: {e}")

    log_job_step(job_id, "init", "Starting ETF Group Analysis Job")
    logger.info("Starting ETF Group Analysis Job...")

    # Initialize clients
    try:
        supabase = SupabaseClient(use_service_role=True)
        postgres = PostgresClient()
        ollama = get_ollama_client()
        repo = ResearchRepository(postgres_client=postgres)

        if not ollama:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "Ollama client not available"
            log_job_step(job_id, "init", message, status="failed")
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            return

        service = ETFGroupAnalysisService(ollama, supabase, repo)
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Failed to initialize clients: {e}"
        log_job_step(job_id, "init", message, status="failed")
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        logger.error(f"❌ {message}")
        return

    reset_stale_in_progress_queue()

    # Check queue for pending work (bounded so deploy restarts do not kill 1h+ runs)
    log_job_step(job_id, "queue_check", "Checking analysis queue for pending work...")
    queue_recent_missing_etf_analysis(repo)
    pending = get_pending_etf_analysis()

    if not pending:
        duration_ms = int((time.time() - start_time) * 1000)
        message = "No ETF groups to analyze"
        log_job_step(job_id, "queue_check", message, status="skipped")
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        logger.info(f"ℹ️ {message}")
        return

    total = len(pending)
    log_job_step(job_id, "queue_check", f"Found {total} ETF groups to analyze", status="success")
    logger.info(f"Processing {total} ETF groups...")

    processed = 0
    failed = 0

    for idx, item in enumerate(pending, 1):
        # Check overall job timeout
        elapsed = time.time() - start_time
        if elapsed > MAX_JOB_DURATION:
            log_job_step(job_id, "timeout", f"Job timeout reached ({elapsed/60:.1f}m). {total - idx + 1} items remaining.", status="failed")
            logger.warning(f"⏱️  Job timeout reached ({elapsed/60:.1f}m). Stopping ETF analysis.")
            break

        try:
            queue_id = item['id']
            target_key = item['target_key']

            # Parse ETF ticker and date from target_key (format: "IWC_2026-01-15")
            parts = target_key.split('_')
            if len(parts) < 2:
                logger.warning(f"Invalid target_key format: {target_key}")
                mark_analysis_failed(queue_id, f"Invalid target_key format: {target_key}")
                failed += 1
                continue

            etf_ticker = parts[0]
            date_str = '_'.join(parts[1:])  # Handle dates with underscores if needed
            try:
                analysis_date = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=UTC)
            except ValueError:
                logger.warning(f"Invalid date format in target_key: {target_key}")
                mark_analysis_failed(queue_id, f"Invalid date format: {date_str}")
                failed += 1
                continue

            # Mark as started
            mark_analysis_started(queue_id)

            # Analyze
            log_job_step(job_id, "analyze", f"Analyzing ETF group {idx}/{total}: {etf_ticker} on {date_str}")
            logger.info(f"Analyzing {etf_ticker} on {date_str}...")
            result = service.analyze_group(etf_ticker, analysis_date)

            if result:
                mark_analysis_completed(queue_id)
                processed += 1
                log_job_step(job_id, "analyze", f"Completed: {etf_ticker} on {date_str}", status="success")
                logger.info(f"✅ Analyzed {etf_ticker} on {date_str}")
            else:
                mark_analysis_failed(queue_id, "No changes found or analysis returned None")
                failed += 1
                log_job_step(job_id, "analyze", f"No result for {etf_ticker} on {date_str}", status="skipped")
                logger.warning(f"⚠️ No analysis result for {etf_ticker} on {date_str}")

        except Exception as e:
            logger.error(f"Error analyzing {item.get('target_key', 'unknown')}: {e}", exc_info=True)
            log_job_step(job_id, "error", f"Error analyzing {item.get('target_key', 'unknown')}: {str(e)[:100]}", status="failed")
            mark_analysis_failed(item['id'], str(e))
            failed += 1

    duration_ms = int((time.time() - start_time) * 1000)
    remaining = max(total - processed - failed, 0)
    message = f"Processed {processed} ETF groups, {failed} failed"
    if remaining:
        message += f", {remaining} left in queue (next run)"
    log_job_step(job_id, "complete", message, status="success")
    log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
    try:
        from utils.job_tracking import mark_job_completed

        mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=message)
    except Exception:
        pass
    logger.info(f"✅ ETF Group Analysis complete: {message}")
