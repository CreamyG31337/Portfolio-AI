#!/usr/bin/env python3
"""Scheduled refresh for tier-1 dashboard UI summaries and tier-2 per-fund rollups."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

try:
    from scheduler.scheduler_core import log_job_execution
except ImportError:
    def log_job_execution(job_id, success, message="", duration_ms=0):
        logging.getLogger(__name__).info("Job %s %s", job_id, message)


logger = logging.getLogger(__name__)

_JOB_ID = "ui_ai_summaries"
_DEFAULT_CURRENCY = "CAD"


def ui_ai_summaries_job() -> None:
    """Refresh dashboard.portfolio_overview per production fund; rollup when inputs change.

    Intended schedule: every ~2h on US market weekdays (see jobs.py). Rollup always invoked;
    service skips LLM when inputs_digest unchanged. When market is closed, tier-1 still runs
    (digest may change after trades); rollup remains cheap when hashes match.
    """
    start = time.time()
    target_date = datetime.now(UTC).date()

    try:
        from utils.job_tracking import get_running_ai_job

        running = get_running_ai_job(exclude_job_name=_JOB_ID)
        if running:
            logger.info("AI lock active (%s). Skipping %s.", running, _JOB_ID)
            return
    except Exception as exc:
        logger.warning("AI lock check failed: %s", exc)

    try:
        from utils.job_tracking import mark_job_completed, mark_job_failed, mark_job_started

        mark_job_started(_JOB_ID, target_date)
    except Exception:
        pass

    errors = 0

    try:
        from market_data.market_hours import MarketHours

        from ollama_client import OllamaClient, get_ollama_client
        from postgres_client import PostgresClient
        from supabase_client import SupabaseClient
        from ui_ai_summary_service import (
            refresh_dashboard_commodities,
            refresh_dashboard_currency,
            list_production_fund_names,
            refresh_dashboard_portfolio_overview,
            refresh_fund_cross_screen_rollup,
            refresh_research_feed,
            refresh_signals_overview,
        )

        market_open = MarketHours().is_market_open()
        supabase = SupabaseClient(use_service_role=True)
        postgres = PostgresClient()
        ollama = get_ollama_client()
        if not ollama:
            ollama = OllamaClient()

        funds = list_production_fund_names(supabase)
        if not funds:
            msg = "no production funds"
            log_job_execution(_JOB_ID, True, msg, int((time.time() - start) * 1000))
            try:
                mark_job_completed(_JOB_ID, target_date, None, [], duration_ms=0, message=msg)
            except Exception:
                pass
            return

        try:
            refresh_signals_overview(ollama, postgres, supabase, force_llm=False)
            refresh_research_feed(ollama, postgres, force_llm=False)
            refresh_dashboard_commodities(ollama, postgres, force_llm=False)
        except Exception as exc:
            errors += 1
            logger.error("ui_ai global tier1 refresh failed: %s", exc, exc_info=True)

        for fund in funds:
            try:
                refresh_dashboard_portfolio_overview(
                    ollama,
                    postgres,
                    fund=fund,
                    display_currency=_DEFAULT_CURRENCY,
                    time_range="ALL",
                    force_llm=False,
                )
            except Exception as exc:
                errors += 1
                logger.error("ui_ai tier1 failed %s: %s", fund, exc, exc_info=True)

            try:
                refresh_dashboard_currency(
                    ollama,
                    postgres,
                    fund=fund,
                    force_llm=False,
                )
            except Exception as exc:
                errors += 1
                logger.error("ui_ai currency tier1 failed %s: %s", fund, exc, exc_info=True)

            try:
                refresh_fund_cross_screen_rollup(
                    ollama,
                    postgres,
                    fund=fund,
                    display_currency=_DEFAULT_CURRENCY,
                    force_llm=False,
                    skip_if_unchanged=True,
                )
            except Exception as exc:
                errors += 1
                logger.error("ui_ai rollup failed %s: %s", fund, exc, exc_info=True)

        duration_ms = int((time.time() - start) * 1000)
        msg = f"market_open={market_open} funds={len(funds)} errors={errors}"
        log_job_execution(_JOB_ID, True, msg, duration_ms)
        try:
            mark_job_completed(_JOB_ID, target_date, None, [], duration_ms=duration_ms, message=msg)
        except Exception:
            pass
        logger.info("ui_ai_summaries_job: %s", msg)

    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        err = str(exc)
        log_job_execution(_JOB_ID, False, err, duration_ms)
        try:
            from utils.job_tracking import mark_job_failed

            mark_job_failed(_JOB_ID, target_date, None, err, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error("ui_ai_summaries_job failed: %s", exc, exc_info=True)
