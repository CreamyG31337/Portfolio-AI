#!/usr/bin/env python3
"""Scheduled jobs: market daily brief + action queue AI reviews."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date, datetime, timedelta, UTC
from typing import Any

# Only one market_daily_brief execution at a time (cron + lock-retry share this).
_market_daily_brief_run_lock = threading.Lock()

# Single pending one-shot retry when skipped due to global AI lock (replace_existing).
_MARKET_DAILY_BRIEF_LOCK_RETRY_JOB_ID = "market_daily_brief_lock_retry"
_MARKET_DAILY_BRIEF_LOCK_RETRY_DELAY_SEC = 60

try:
    from scheduler.scheduler_core import log_job_execution
except ImportError:
    def log_job_execution(job_id, success, message="", duration_ms=0):
        logging.getLogger(__name__).info("Job %s %s", job_id, message)


logger = logging.getLogger(__name__)


def _compute_missing_brief_dates(postgres, *, lookback_days: int = 12) -> list[date]:
    """Return missing weekday brief dates in a short recent window."""
    from market_brief_service import _ny_today

    today_ny = _ny_today()
    start_date = today_ny - timedelta(days=lookback_days)

    existing_rows = postgres.execute_query(
        """
        SELECT brief_date
        FROM market_daily_brief
        WHERE brief_date >= %s AND brief_date <= %s
        """,
        (start_date, today_ny),
    )
    existing_dates = {row["brief_date"] for row in (existing_rows or []) if row.get("brief_date")}

    missing: list[date] = []
    cursor = start_date
    while cursor <= today_ny:
        if cursor.weekday() < 5 and cursor not in existing_dates:
            missing.append(cursor)
        cursor += timedelta(days=1)
    return missing


def _schedule_market_daily_brief_after_ai_lock(blocking_job: str) -> None:
    """Re-run the brief soon after the global AI lock clears (one-shot, debounced)."""
    try:
        from scheduler.scheduler_core import get_scheduler

        sched = get_scheduler(create=False)
        if not sched or not getattr(sched, "running", False):
            return
        run_date = datetime.now(UTC) + timedelta(seconds=_MARKET_DAILY_BRIEF_LOCK_RETRY_DELAY_SEC)
        sched.add_job(
            market_daily_brief_job,
            trigger="date",
            run_date=run_date,
            id=_MARKET_DAILY_BRIEF_LOCK_RETRY_JOB_ID,
            name="Market Daily Brief (retry after AI lock)",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        logger.info(
            "Scheduled market_daily_brief retry at %s UTC (%ss) while AI lock held by %s",
            run_date.isoformat(),
            _MARKET_DAILY_BRIEF_LOCK_RETRY_DELAY_SEC,
            blocking_job,
        )
    except Exception as exc:
        logger.warning("Could not schedule market_daily_brief lock retry: %s", exc)


def market_daily_brief_job() -> None:
    if not _market_daily_brief_run_lock.acquire(blocking=False):
        logger.info("market_daily_brief: already in progress; skipping concurrent invocation")
        return

    job_id = "market_daily_brief"
    start = time.time()
    target_date = datetime.now(UTC).date()
    try:
        try:
            from utils.job_tracking import get_running_ai_job

            running = get_running_ai_job(exclude_job_name=job_id)
            if running:
                logger.info("AI lock active (%s). Skipping %s.", running, job_id)
                _schedule_market_daily_brief_after_ai_lock(running)
                return
        except Exception as exc:
            logger.warning("AI lock check failed: %s", exc)

        try:
            from utils.job_tracking import mark_job_completed, mark_job_failed, mark_job_started

            mark_job_started(job_id, target_date)
        except Exception:
            pass

        try:
            from market_brief_service import run_market_daily_brief
            from ollama_client import OllamaClient, get_ollama_client
            from postgres_client import PostgresClient
            from supabase_client import SupabaseClient

            ollama = get_ollama_client()
            if not ollama:
                ollama = OllamaClient()
            postgres = PostgresClient()
            supabase = SupabaseClient(use_service_role=True)
            from market_brief_service import _ny_today

            ny_today = _ny_today()
            weekend = ny_today.weekday() >= 5
            dates_to_fill = _compute_missing_brief_dates(postgres, lookback_days=12)
            if not dates_to_fill:
                if weekend:
                    # Do not write a Sat/Sun brief row; cron should be mon-fri only but lock-retry
                    # or manual runs can still hit weekends.
                    msg = "weekend: no missing weekday briefs to backfill"
                else:
                    row = run_market_daily_brief(ollama, postgres, supabase)
                    msg = "ok" if row else "no row (benchmark or LLM failure)"
            else:
                successes = 0
                for brief_day in dates_to_fill:
                    row = run_market_daily_brief(ollama, postgres, supabase, brief_date=brief_day)
                    if row:
                        successes += 1
                msg = f"backfill {successes}/{len(dates_to_fill)} day(s)"
            duration_ms = int((time.time() - start) * 1000)
            log_job_execution(job_id, True, msg, duration_ms)
            try:
                mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=msg)
            except Exception:
                pass
            logger.info("market_daily_brief_job: %s", msg)
        except Exception as exc:
            duration_ms = int((time.time() - start) * 1000)
            err = str(exc)
            log_job_execution(job_id, False, err, duration_ms)
            try:
                from utils.job_tracking import mark_job_failed

                mark_job_failed(job_id, target_date, None, err, duration_ms=duration_ms)
            except Exception:
                pass
            logger.error("market_daily_brief_job failed: %s", exc, exc_info=True)
    finally:
        _market_daily_brief_run_lock.release()


def _signal_date_to_sql(val: Any) -> date | None:
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    s = str(val)[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def action_queue_ai_review_job() -> None:
    job_id = "action_queue_ai_review"
    start = time.time()
    target_date = datetime.now(UTC).date()
    try:
        from utils.job_tracking import get_running_ai_job

        running = get_running_ai_job(exclude_job_name=job_id)
        if running:
            logger.info("AI lock active (%s). Skipping %s.", running, job_id)
            return
    except Exception as exc:
        logger.warning("AI lock check failed: %s", exc)

    try:
        from utils.job_tracking import mark_job_completed, mark_job_failed, mark_job_started

        mark_job_started(job_id, target_date)
    except Exception:
        pass

    processed = 0
    errors = 0
    try:
        from ai_prompts import ACTION_QUEUE_AI_REVIEW_PROMPT
        from action_queue_service import attach_research_context, build_action_queue_items
        from ollama_client import OllamaClient, collect_with_summary_model_chain, get_ollama_client
        from postgres_client import PostgresClient
        from settings import get_summarizing_model
        from supabase_client import SupabaseClient
        from ticker_analysis_service import extract_json

        ollama = get_ollama_client()
        if not ollama:
            ollama = OllamaClient()
        postgres = PostgresClient()
        supabase = SupabaseClient(use_service_role=True)
        model = get_summarizing_model()

        funds_res = supabase.supabase.table("funds").select("name").eq("is_production", True).execute()
        fund_names = [r["name"] for r in (funds_res.data or []) if r.get("name")]
        if not fund_names:
            funds_res = supabase.supabase.table("funds").select("name").limit(5).execute()
            fund_names = [r["name"] for r in (funds_res.data or []) if r.get("name")]

        # Load positions per fund via service-role Supabase. build_action_queue_items
        # falls back to Flask-scoped get_current_positions when positions_df is None,
        # which raises "Working outside of request context" inside the scheduler thread.
        import pandas as pd  # local import to avoid widening module-level imports

        for fund in fund_names:
            try:
                positions_df = pd.DataFrame(supabase.get_current_positions(fund) or [])
            except Exception as pos_exc:
                logger.warning(
                    "action_queue_ai_review_job: failed to load positions for %s: %s",
                    fund,
                    pos_exc,
                )
                positions_df = pd.DataFrame()
            items = build_action_queue_items(supabase, fund, 12, positions_df=positions_df)
            attach_research_context(postgres, items)
            for it in items[:5]:
                ticker = it.get("ticker")
                if not ticker:
                    continue
                sig_d = _signal_date_to_sql(it.get("analysis_date")) or date(1970, 1, 1)
                excerpt = ""
                try:
                    ta_rows = postgres.execute_query(
                        """
                        SELECT summary FROM ticker_analysis
                        WHERE ticker = %s AND analysis_type = 'standard'
                        ORDER BY updated_at DESC NULLS LAST
                        LIMIT 1
                        """,
                        (ticker,),
                    )
                    meta_rows = postgres.execute_query(
                        "SELECT narrative FROM ticker_meta_analysis WHERE ticker = %s LIMIT 1",
                        (ticker,),
                    )
                    s = (ta_rows[0].get("summary") if ta_rows else "") or ""
                    s = str(s)[:400]
                    n = (meta_rows[0].get("narrative") if meta_rows else "") or ""
                    n = str(n)[:400]
                    excerpt = f"Latest ticker_analysis summary: {s}\nMeta narrative: {n}"
                except Exception:
                    rc = it.get("research_context") or {}
                    excerpt = json.dumps(rc)[:600]

                queue_row = json.dumps(
                    {
                        "ticker": ticker,
                        "action": it.get("action"),
                        "overall_signal": it.get("overall_signal"),
                        "confidence": it.get("confidence"),
                        "fear_level": it.get("fear_level"),
                        "trend": it.get("trend"),
                        "note": it.get("note"),
                    },
                    default=str,
                )

                prompt = ACTION_QUEUE_AI_REVIEW_PROMPT.format(
                    queue_row=queue_row,
                    research_excerpt=excerpt or "(none)",
                )
                full, model_used = collect_with_summary_model_chain(
                    ollama,
                    prompt=prompt,
                    requested_model=model,
                    stream=True,
                    system_prompt="Return ONLY valid JSON with verdict and one_liner.",
                    json_mode=True,
                    temperature=0.15,
                    response_ok=lambda s: extract_json(s) is not None,
                    function_name="action_queue_ai_review",
                    audit_extra={
                        "tickers_extracted": [it.get("ticker")] if it.get("ticker") else None,
                    },
                )
                if not full:
                    errors += 1
                    continue
                parsed = extract_json(full)
                if not parsed:
                    errors += 1
                    continue
                verdict = (parsed.get("verdict") or "INSUFFICIENT_DATA")[:30]
                one_liner = (parsed.get("one_liner") or "")[:500]

                postgres.execute_update(
                    """
                    INSERT INTO action_queue_ai_review (
                        fund_key, ticker, signal_analysis_date, verdict, one_liner, model_used
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (fund_key, ticker, signal_analysis_date) DO UPDATE SET
                        verdict = EXCLUDED.verdict,
                        one_liner = EXCLUDED.one_liner,
                        model_used = EXCLUDED.model_used,
                        updated_at = NOW()
                    """,
                    (fund, ticker, sig_d, verdict, one_liner, model_used),
                )

                try:
                    from stance_history import record_stance_safe

                    mechanical_action = (it.get("action") or "").strip()
                    if mechanical_action:
                        record_stance_safe(
                            postgres,
                            ticker=ticker,
                            source="action_queue_ai_review",
                            fund_key=fund,
                            stance=mechanical_action,
                            confidence=it.get("confidence"),
                            model_used=model_used,
                            metadata={
                                "verdict": verdict,
                                "one_liner": one_liner,
                                "overall_signal": it.get("overall_signal"),
                                "signal_analysis_date": str(sig_d) if sig_d else None,
                            },
                        )
                except Exception as ledger_exc:
                    logger.warning(
                        "stance_history hook failed for %s/%s: %s",
                        fund,
                        ticker,
                        ledger_exc,
                    )

                processed += 1

        duration_ms = int((time.time() - start) * 1000)
        msg = f"upserts={processed} errors={errors}"
        log_job_execution(job_id, True, msg, duration_ms)
        try:
            mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=msg)
        except Exception:
            pass
        logger.info("action_queue_ai_review_job: %s", msg)
    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        err = str(exc)
        log_job_execution(job_id, False, err, duration_ms)
        try:
            from utils.job_tracking import mark_job_failed

            mark_job_failed(job_id, target_date, None, err, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error("action_queue_ai_review_job failed: %s", exc, exc_info=True)
