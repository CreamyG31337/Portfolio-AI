#!/usr/bin/env python3
"""
Ticker meta analysis job
========================

Runs after the main ticker analysis job in the schedule. Reconciles stored
analysis artifacts (standard ticker_analysis, social AI, congress, articles)
into ticker_meta_analysis. Short time budget; skips tickers that are fresh.
"""

import logging
import time
from datetime import datetime, UTC

try:
    from scheduler.scheduler_core import log_job_execution
except ImportError:
    def log_job_execution(job_id, success, message="", duration_ms=0):
        logger.info("Job %s: %s - %s (%sms)", job_id, "OK" if success else "FAIL", message, duration_ms)


from ai_skip_list_manager import AISkipListManager
from meta_analysis_service import TickerMetaAnalysisService
from ollama_client import OllamaClient, get_ollama_client
from postgres_client import PostgresClient
from settings import get_summarizing_model
from supabase_client import SupabaseClient
from ticker_analysis_service import TickerAnalysisService

logger = logging.getLogger(__name__)

# Do not starve the server: meta is cheaper than full ticker analysis but still LLM-bound.
_MAX_SECONDS = 45 * 60
# Digest-based refresh can increase nightly work; cap per run (tune if backlog grows).
_MAX_TICKERS_PER_RUN = 100


def ticker_meta_analysis_job() -> None:
    job_id = "ticker_meta_analysis"
    start = time.time()
    target_date = datetime.now(UTC).date()

    try:
        from utils.job_tracking import get_running_ai_job

        running = get_running_ai_job(exclude_job_name=job_id)
        if running:
            logger.info("AI lock active (%s). Skipping %s.", running, job_id)
            return
    except Exception as exc:
        logger.warning("AI lock check failed (continuing): %s", exc)

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
        preferred_model = get_summarizing_model()
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

        skip_list = AISkipListManager(supabase)
        ticker_service = TickerAnalysisService(ollama, supabase, postgres, skip_list)
        meta_service = TickerMetaAnalysisService(ollama, supabase, postgres)

        tickers: list[tuple[str, int]] = ticker_service.get_tickers_to_analyze()
        processed = 0
        skipped_fresh = 0
        skipped_no_standard = 0
        failed = 0

        for ticker, _prio in tickers:
            if time.time() - start > _MAX_SECONDS:
                logger.info("Meta job time budget reached (%ss).", _MAX_SECONDS)
                break
            if processed >= _MAX_TICKERS_PER_RUN:
                logger.info("Meta job ticker cap reached (%s).", _MAX_TICKERS_PER_RUN)
                break

            need, latest = meta_service.needs_refresh(ticker)
            if latest is None:
                skipped_no_standard += 1
                continue
            if not need:
                skipped_fresh += 1
                continue

            try:
                meta_service.run_meta_analysis(
                    ticker,
                    requested_by=None,
                    model_override=preferred_model,
                    force=True,
                )
                processed += 1
            except Exception as exc:
                logger.error("Meta analysis failed for %s: %s", ticker, exc, exc_info=True)
                failed += 1

        duration_ms = int((time.time() - start) * 1000)
        skipped_total = skipped_fresh + skipped_no_standard
        msg = (
            f"Processed {processed}, skipped {skipped_total} "
            f"(fresh_digest={skipped_fresh}, no_standard={skipped_no_standard}), failed {failed}"
        )
        log_job_execution(job_id, success=True, message=msg, duration_ms=duration_ms)
        try:
            mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=msg)
        except Exception:
            pass
        logger.info("Ticker meta analysis done: %s", msg)

    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        err = str(exc)
        log_job_execution(job_id, success=False, message=err, duration_ms=duration_ms)
        try:
            from utils.job_tracking import mark_job_failed

            mark_job_failed(job_id, target_date, None, err, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error("Ticker meta analysis job failed: %s", exc, exc_info=True)
