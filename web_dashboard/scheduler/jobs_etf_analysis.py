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
from etf_meta_pipeline import get_etf_queue_lookback_days

logger = logging.getLogger(__name__)

# Finish within one deploy window; queue resumes next run.
MAX_JOB_DURATION = 35 * 60  # 35 minutes total
MAX_ITEMS_PER_RUN = 6  # ~5–6 LLM calls per night; avoids 1h+ runs killed on deploy
# Default queue window; auto-expands up to ETF_GROUP_QUEUE_MAX_LOOKBACK_DAYS when behind.
QUEUE_LOOKBACK_DAYS = 14

# Queue-mode constants — mirror the Q4a/Q4b pattern. Cron-enqueued ETF group
# tasks use a low priority so any future manual rebuild route (priority >= 1000)
# can jump ahead in the queue, matching the convention established for
# ticker_analysis / ticker_meta_analysis.
_ETF_GROUP_ENQUEUE_PRIORITY = 10
# Mirror MAX_ITEMS_PER_RUN so cron does not enqueue more than the legacy path
# would have processed in one window. The worker pool runs all enqueued tasks
# concurrently, so this stays modest to keep a steady cadence per cron.
_MAX_ETF_GROUPS_PER_RUN = MAX_ITEMS_PER_RUN


def _etf_group_analysis_queue_mode_enabled() -> bool:
    try:
        from scheduler.ai_task_workers import is_ai_queue_job_enabled

        return bool(is_ai_queue_job_enabled("etf_group_analysis"))
    except Exception as exc:
        logger.warning(
            "AI queue mode check failed for etf_group_analysis (using legacy path): %s",
            exc,
        )
        return False


def _run_etf_group_analysis_enqueue_mode(job_id: str, start_time: float) -> None:
    """Queue-mode ETF group analysis: select pending items and enqueue per-group tasks.

    Mirrors :func:`_run_sector_meta_analysis_enqueue_mode` (Q4b) and
    :func:`_run_ticker_meta_analysis_enqueue_mode` (Q4a). Notes:

    - Candidate selection re-uses the legacy ``ai_analysis_queue`` discovery
      path (``queue_recent_missing_etf_analysis`` + ``get_pending_etf_analysis``)
      so the queue mode does not invent a new selection policy. Each pending
      row's ``id`` is forwarded to the worker via ``payload.legacy_queue_id``
      so the worker can keep that row's ``status`` in sync (``completed`` on
      success / ``failed`` on raise) — preserving the legacy resumability log.
    - There is no separate per-(ETF, date) freshness gate because the legacy
      queue discovery step already filters out (ETF, date) pairs whose
      ``etf-analysis://`` article exists. The ``ai_task_queue`` dedupe index
      ``(analysis_type, target_key) WHERE status IN ('pending','leased')``
      prevents double-enqueue while a task is active.
    - ``reset_stale_in_progress_queue()`` still runs so legacy rows left
      ``in_progress`` by a prior container restart get reset to ``pending`` and
      become candidates again. The queue's own ``leased`` lifecycle is
      independent and reclaimed via ``leased_until``.
    """

    import os
    from typing import Any as _Any

    target_date = datetime.now(UTC).date()
    mark_job_completed: _Any = None
    mark_job_failed: _Any = None
    AIQueueConfig: _Any = None
    enqueue_etf_group_analysis_tasks: _Any = None
    try:
        from scheduler.ai_task_workers import (
            AIQueueConfig as _AIQueueConfig,
        )
        from scheduler.ai_task_workers import (
            enqueue_etf_group_analysis_tasks as _enqueue_etf_group_analysis_tasks,
        )
        from utils.job_tracking import (
            mark_job_completed as _mark_job_completed,
        )
        from utils.job_tracking import (
            mark_job_failed as _mark_job_failed,
        )
        from utils.job_tracking import (
            mark_job_started as _mark_job_started,
        )

        AIQueueConfig = _AIQueueConfig
        enqueue_etf_group_analysis_tasks = _enqueue_etf_group_analysis_tasks
        mark_job_completed = _mark_job_completed
        mark_job_failed = _mark_job_failed
        _mark_job_started(job_id, target_date)
    except Exception as exc:
        logger.warning("Could not initialize queue-mode job tracking: %s", exc)

    logger.info("Starting %s enqueue job (AI task queue mode)...", job_id)

    try:
        if enqueue_etf_group_analysis_tasks is None or AIQueueConfig is None:
            raise RuntimeError("AI task queue helpers unavailable")

        postgres = PostgresClient()
        repo = ResearchRepository(postgres_client=postgres)

        # Reset legacy stale in_progress rows so they re-appear as candidates.
        # The queue's own lease lifecycle is unaffected by this.
        reset_stale_in_progress_queue()

        active_lookback = get_etf_queue_lookback_days()
        queue_recent_missing_etf_analysis(repo, lookback_days=active_lookback)
        pending = get_pending_etf_analysis(
            limit=_MAX_ETF_GROUPS_PER_RUN,
            lookback_days=active_lookback,
        )

        selected: list[tuple[str, str, int]] = []
        queue_id_map: dict[str, str] = {}
        for item in pending:
            if len(selected) >= _MAX_ETF_GROUPS_PER_RUN:
                break
            target_key = str(item.get("target_key") or "")
            parts = target_key.split("_", 1)
            if len(parts) != 2:
                logger.warning(
                    "etf_group_analysis: skipping invalid target_key=%r in queue mode",
                    target_key,
                )
                continue
            etf_ticker = parts[0].upper().strip()
            date_str = parts[1].strip()
            if not etf_ticker or not date_str:
                continue
            queue_id = item.get("id")
            selected.append((etf_ticker, date_str, _ETF_GROUP_ENQUEUE_PRIORITY))
            if queue_id:
                queue_id_map[f"{etf_ticker}_{date_str}"] = str(queue_id)

        if not selected:
            duration_ms = int((time.time() - start_time) * 1000)
            message = (
                f"No etf_group_analysis tasks to enqueue (candidates={len(pending)})"
            )
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            if mark_job_completed is not None:
                mark_job_completed(
                    job_id, target_date, None, [], duration_ms=duration_ms, message=message
                )
            logger.info("ℹ️ %s", message)
            return

        supabase = SupabaseClient(use_service_role=True)
        config = AIQueueConfig.from_env()
        enqueued_by = os.getenv("AI_QUEUE_ENQUEUED_BY", "cron").strip() or "cron"
        enqueue_stats = enqueue_etf_group_analysis_tasks(
            supabase,
            selected,
            enqueued_by=enqueued_by,
            max_attempts=config.max_attempts,
            queue_ids=queue_id_map,
        )
        duration_ms = int((time.time() - start_time) * 1000)
        message = (
            f"Enqueued {enqueue_stats['enqueued']}/{enqueue_stats['attempted']} "
            f"etf_group_analysis task(s); failed={enqueue_stats['failed']} "
            f"(candidates={len(pending)})."
        )
        log_job_execution(
            job_id,
            success=enqueue_stats["failed"] == 0,
            message=message,
            duration_ms=duration_ms,
        )
        if enqueue_stats["failed"] == 0:
            if mark_job_completed is not None:
                mark_job_completed(
                    job_id, target_date, None, [], duration_ms=duration_ms, message=message
                )
        elif mark_job_failed is not None:
            mark_job_failed(job_id, target_date, None, message, duration_ms=duration_ms)
        logger.info("✅ ETF group analysis enqueue complete: %s", message)
    except Exception as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"ETF group analysis enqueue failed: {exc}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        if mark_job_failed is not None:
            mark_job_failed(job_id, target_date, None, message, duration_ms=duration_ms)
        logger.error("❌ %s", message, exc_info=True)


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


def _etf_queue_target_date(item: dict[str, Any]) -> str:
    key = str(item.get("target_key") or "")
    parts = key.split("_", 1)
    return parts[1] if len(parts) > 1 else ""


def get_pending_etf_analysis(
    limit: int = MAX_ITEMS_PER_RUN,
    lookback_days: int | None = None,
) -> list[dict]:
    """Pending/failed ETF group work, newest holdings dates first within lookback."""
    try:
        if lookback_days is None:
            lookback_days = get_etf_queue_lookback_days()
        cutoff = (datetime.now(UTC).date() - timedelta(days=max(1, lookback_days) - 1)).isoformat()

        db = SupabaseClient(use_service_role=True)
        rows: list[dict[str, Any]] = []
        page_size = 500
        offset = 0
        while True:
            result = (
                db.supabase.table("ai_analysis_queue")
                .select("*")
                .eq("analysis_type", "etf_group")
                .in_("status", ["pending", "failed"])
                .order("created_at", desc=True)
                .range(offset, offset + page_size - 1)
                .execute()
            )
            batch = list(result.data or [])
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size

        rows = [r for r in rows if _etf_queue_target_date(r) >= cutoff]
        rows.sort(key=_etf_queue_target_date, reverse=True)
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
    lookback_days: int | None = None,
) -> int:
    """Queue ETF/date pairs with holdings changes but no saved ETF Analysis article yet."""
    try:
        pc = repo.client
        if lookback_days is None:
            lookback_days = get_etf_queue_lookback_days(pc)
        today = datetime.now(UTC).date()
        queued = 0
        for offset in range(lookback_days):
            day = today - timedelta(days=offset)
            day_str = day.strftime("%Y-%m-%d")
            rows = pc.execute_query(
                """
                SELECT DISTINCT etf_ticker
                FROM etf_holdings_changes
                WHERE date = %s
                """,
                (day_str,),
            )
            etf_tickers = sorted(
                {str(row["etf_ticker"]).upper() for row in (rows or []) if row.get("etf_ticker")}
            )
            for etf_ticker in etf_tickers:
                if _article_exists(repo, etf_ticker, day_str):
                    continue
                target_key = f"{etf_ticker}_{day_str}"
                try:
                    SupabaseClient(use_service_role=True).supabase.table("ai_analysis_queue").insert(
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

    if _etf_group_analysis_queue_mode_enabled():
        _run_etf_group_analysis_enqueue_mode(job_id, start_time)
        return

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
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed

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
            try:
                mark_job_failed(job_id, target_date, None, message, duration_ms=duration_ms)
            except Exception:
                pass
            return

        service = ETFGroupAnalysisService(ollama, supabase, repo)
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Failed to initialize clients: {e}"
        log_job_step(job_id, "init", message, status="failed")
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        logger.error(f"❌ {message}")
        try:
            mark_job_failed(job_id, target_date, None, message, duration_ms=duration_ms)
        except Exception:
            pass
        return

    try:
        reset_stale_in_progress_queue()

        # Check queue for pending work (bounded so deploy restarts do not kill 1h+ runs)
        log_job_step(job_id, "queue_check", "Checking analysis queue for pending work...")
        active_lookback = get_etf_queue_lookback_days()
        queue_recent_missing_etf_analysis(repo, lookback_days=active_lookback)
        pending = get_pending_etf_analysis(lookback_days=active_lookback)

        if not pending:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "No ETF groups to analyze"
            log_job_step(job_id, "queue_check", message, status="skipped")
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            try:
                mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=message)
            except Exception:
                pass
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
            mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=message)
        except Exception:
            pass
        logger.info(f"✅ ETF Group Analysis complete: {message}")
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"ETF Group Analysis failed: {e}"
        log_job_step(job_id, "fatal", message, status="failed")
        try:
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        except Exception:
            pass
        try:
            mark_job_failed(job_id, target_date, None, message, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error(f"❌ {message}", exc_info=True)
