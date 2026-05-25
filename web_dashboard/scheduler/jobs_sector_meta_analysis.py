#!/usr/bin/env python3
"""
Sector meta analysis job (Phase 3b)
===================================

Nightly sector-level synthesis from ETF Analysis articles into ``sector_meta_analysis``.
Respects ``META_ANALYSIS_PHASE3_SECTOR`` (default on). Uses the global AI lock with a one-shot retry when blocked.

Upstream coupling: ``SectorMetaAnalysisService`` groups by ``research_articles.sector``. If that
column is empty for many rows, the job still runs but ``__UNTAGGED__`` dominates—monitor the SQL
invariant in ``docs/meta_analysis_roadmap.md`` (*Data foundation*).
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

try:
    from scheduler.scheduler_core import log_job_execution
except ImportError:

    def log_job_execution(job_id, success, message="", duration_ms=0):
        logger.info("Job %s: %s - %s (%sms)", job_id, "OK" if success else "FAIL", message, duration_ms)


from ollama_client import OllamaClient, get_ollama_client
from postgres_client import PostgresClient
from sector_meta_analysis_service import SectorMetaAnalysisService
from settings import get_summarizing_model, is_meta_analysis_phase3_sector_enabled
from supabase_client import SupabaseClient

logger = logging.getLogger(__name__)

_MAX_SECONDS = 40 * 60
_LOCK_RETRY_DELAY_SEC = 90
_LOCK_RETRY_JOB_ID = "sector_meta_analysis_lock_retry"

# Queue-mode constants — mirror the Q4a (ticker_meta_analysis) pattern.
# ``list_sector_keys()`` already caps the result at the service-level
# ``_MAX_SECTORS_PER_RUN = 18``; we mirror that here so the scheduler-side
# cap is explicit and easy to tune independently if needed.
_MAX_SECTORS_PER_RUN = 18
# Cron-enqueued sector meta tasks use a low priority so any future manual UI
# requests (priority >= 1000) can jump ahead, matching the convention
# established for ticker_analysis / ticker_meta_analysis.
_SECTOR_META_ENQUEUE_PRIORITY = 10


def _sector_meta_analysis_queue_mode_enabled() -> bool:
    try:
        from scheduler.ai_task_workers import is_ai_queue_job_enabled

        return is_ai_queue_job_enabled("sector_meta_analysis")
    except Exception as exc:
        logger.warning(
            "AI queue mode check failed for sector_meta_analysis (using legacy path): %s",
            exc,
        )
        return False


def _run_sector_meta_analysis_enqueue_mode(job_id: str, start_time: float) -> None:
    """Queue-mode sector meta analysis: select sectors and enqueue per-sector tasks.

    Mirrors :func:`_run_ticker_meta_analysis_enqueue_mode`. Notes:

    - The phase flag (``META_ANALYSIS_PHASE3_SECTOR``) is honored identically
      to the legacy inline path — when off, the cron is a no-op.
    - There is **no per-sector freshness gate** in the inline path (sector
      meta upserts on ``(sector, run_date)`` so re-running is idempotent), so
      queue mode does not synthesize one either. ``list_sector_keys()``
      already caps the candidate set; we re-apply ``_MAX_SECTORS_PER_RUN``
      defensively so the cron never enqueues an unbounded amount of work.
    """

    import os

    target_date = datetime.now(UTC).date()
    try:
        from scheduler.ai_task_workers import (
            AIQueueConfig,
            enqueue_sector_meta_analysis_tasks,
        )
        from utils.job_tracking import (
            mark_job_completed,
            mark_job_failed,
            mark_job_started,
        )

        mark_job_started(job_id, target_date)
    except Exception as exc:
        logger.warning("Could not initialize queue-mode job tracking: %s", exc)
        mark_job_completed = None
        mark_job_failed = None
        AIQueueConfig = None
        enqueue_sector_meta_analysis_tasks = None

    logger.info("Starting %s enqueue job (AI task queue mode)...", job_id)

    try:
        if enqueue_sector_meta_analysis_tasks is None or AIQueueConfig is None:
            raise RuntimeError("AI task queue helpers unavailable")

        supabase = SupabaseClient(use_service_role=True)
        postgres = PostgresClient()
        svc = SectorMetaAnalysisService(None, supabase, postgres)

        sector_keys = svc.list_sector_keys()

        selected: list[tuple[str, int]] = []
        for sk in sector_keys:
            if len(selected) >= _MAX_SECTORS_PER_RUN:
                break
            if not sk:
                continue
            selected.append((sk, _SECTOR_META_ENQUEUE_PRIORITY))

        if not selected:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"No sector meta tasks to enqueue (candidates={len(sector_keys)})"
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            if mark_job_completed:
                mark_job_completed(
                    job_id, target_date, None, [], duration_ms=duration_ms, message=message
                )
            logger.info("ℹ️ %s", message)
            return

        config = AIQueueConfig.from_env()
        enqueued_by = os.getenv("AI_QUEUE_ENQUEUED_BY", "cron").strip() or "cron"
        enqueue_stats = enqueue_sector_meta_analysis_tasks(
            supabase,
            selected,
            enqueued_by=enqueued_by,
            max_attempts=config.max_attempts,
        )
        duration_ms = int((time.time() - start_time) * 1000)
        message = (
            f"Enqueued {enqueue_stats['enqueued']}/{enqueue_stats['attempted']} "
            f"sector_meta_analysis task(s); failed={enqueue_stats['failed']} "
            f"(candidates={len(sector_keys)})."
        )
        log_job_execution(
            job_id,
            success=enqueue_stats["failed"] == 0,
            message=message,
            duration_ms=duration_ms,
        )
        if enqueue_stats["failed"] == 0:
            if mark_job_completed:
                mark_job_completed(
                    job_id, target_date, None, [], duration_ms=duration_ms, message=message
                )
        elif mark_job_failed:
            mark_job_failed(job_id, target_date, None, message, duration_ms=duration_ms)
        logger.info("✅ Sector meta analysis enqueue complete: %s", message)
    except Exception as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Sector meta analysis enqueue failed: {exc}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        if mark_job_failed:
            mark_job_failed(job_id, target_date, None, message, duration_ms=duration_ms)
        logger.error("❌ %s", message, exc_info=True)


def _schedule_sector_meta_after_ai_lock(blocking_job: str) -> None:
    """Re-run sector meta soon after the global AI lock clears (one-shot, debounced)."""
    try:
        from scheduler.scheduler_core import get_scheduler

        sched = get_scheduler(create=False)
        if not sched or not getattr(sched, "running", False):
            return
        run_date = datetime.now(UTC) + timedelta(seconds=_LOCK_RETRY_DELAY_SEC)
        sched.add_job(
            sector_meta_analysis_job,
            trigger="date",
            run_date=run_date,
            id=_LOCK_RETRY_JOB_ID,
            name="Sector meta (retry after AI lock)",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        logger.info(
            "Scheduled sector_meta_analysis retry at %s UTC (%ss) while AI lock held by %s",
            run_date.isoformat(),
            _LOCK_RETRY_DELAY_SEC,
            blocking_job,
        )
    except Exception as exc:
        logger.warning("Could not schedule sector_meta lock retry: %s", exc)


def sector_meta_analysis_job() -> None:
    job_id = "sector_meta_analysis"
    start = time.time()
    target_date = datetime.now(UTC).date()

    if not is_meta_analysis_phase3_sector_enabled():
        msg = "META_ANALYSIS_PHASE3_SECTOR disabled — no-op"
        logger.info("%s: %s", job_id, msg)
        try:
            from utils.job_tracking import mark_job_completed, mark_job_started

            mark_job_started(job_id, target_date)
            mark_job_completed(job_id, target_date, None, [], duration_ms=0, message=msg)
        except Exception as exc:
            logger.warning("job_tracking skip: %s", exc)
        log_job_execution(job_id, success=True, message=msg, duration_ms=0)
        return

    if _sector_meta_analysis_queue_mode_enabled():
        _run_sector_meta_analysis_enqueue_mode(job_id, start)
        return

    import os

    if os.getenv("SECTOR_META_IGNORE_AI_LOCK", "").strip().lower() in ("1", "true", "yes"):
        logger.warning("%s: SECTOR_META_IGNORE_AI_LOCK set — skipping global AI lock check", job_id)
    else:
        try:
            from utils.job_tracking import get_running_ai_job

            running = get_running_ai_job(exclude_job_name=job_id)
        except Exception as exc:
            logger.warning("AI lock check failed (continuing): %s", exc)
            running = None

        if running:
            logger.info("AI lock active (%s). Skipping %s.", running, job_id)
            _schedule_sector_meta_after_ai_lock(running)
            log_job_execution(
                job_id,
                success=True,
                message=f"Skipped — AI lock held by {running}",
                duration_ms=0,
            )
            return

    try:
        supabase_check = SupabaseClient(use_service_role=True)
        running_check = (
            supabase_check.supabase.table("job_executions")
            .select("id")
            .eq("job_name", job_id)
            .eq("status", "running")
            .execute()
        )
        if running_check.data:
            logger.info("Job %s already running. Skip.", job_id)
            return
    except Exception as exc:
        logger.warning("Could not check job_executions: %s", exc)

    try:
        from utils.job_tracking import mark_job_completed, mark_job_failed, mark_job_started

        mark_job_started(job_id, target_date)
    except Exception as exc:
        logger.warning("mark_job_started failed: %s", exc)

    logger.info("Starting %s...", job_id)

    try:
        supabase = SupabaseClient(use_service_role=True)
        postgres = PostgresClient()
        preferred_model = get_summarizing_model("sector_meta")
        is_glm = str(preferred_model).startswith("glm-")
        is_webai = False
        try:
            from webai_wrapper import is_webai_model

            is_webai = is_webai_model(str(preferred_model))
        except Exception:
            pass

        ollama = get_ollama_client()
        if not ollama and (is_glm or is_webai):
            ollama = OllamaClient()
        if not ollama:
            ollama = OllamaClient()

        svc = SectorMetaAnalysisService(ollama, supabase, postgres)
        sector_keys = svc.list_sector_keys()
        processed = 0
        failed = 0

        for sk in sector_keys:
            if time.time() - start > _MAX_SECONDS:
                logger.info("Sector meta job time budget reached (%ss).", _MAX_SECONDS)
                break
            try:
                out = svc.run_sector_meta(sk, model_override=preferred_model)
                if out is not None:
                    processed += 1
                else:
                    failed += 1
            except Exception as exc:
                logger.error("Sector meta failed for %s: %s", sk, exc, exc_info=True)
                failed += 1

        duration_ms = int((time.time() - start) * 1000)
        msg = f"Sectors attempted={len(sector_keys)}, ok={processed}, failed={failed}"
        log_job_execution(job_id, success=True, message=msg, duration_ms=duration_ms)
        try:
            mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=msg)
        except Exception:
            pass
        logger.info("Sector meta analysis done: %s", msg)

    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        err = str(exc)
        log_job_execution(job_id, success=False, message=err, duration_ms=duration_ms)
        try:
            from utils.job_tracking import mark_job_failed

            mark_job_failed(job_id, target_date, None, err, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error("Sector meta analysis job failed: %s", exc, exc_info=True)
