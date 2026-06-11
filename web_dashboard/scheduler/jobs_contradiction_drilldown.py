"""
Contradiction drill-down enqueue job (Pillar 3 Shape C).

Gated by cheap-learn audit #4: only enqueues when contradiction supply is healthy.
Uses AI task queue — no new global-mutex LLM job.
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, UTC
from pathlib import Path

current_dir = Path(__file__).resolve().parent
if str(current_dir.parent) not in sys.path:
    sys.path.insert(0, str(current_dir.parent))

from scheduler.scheduler_core import log_job_execution

logger = logging.getLogger(__name__)

JOB_ID = "contradiction_drilldown"
MIN_DAILY_CONTRADICTIONS = 10


def contradiction_drilldown_job() -> None:
    start = time.time()
    target_date = datetime.now(UTC).date()
    try:
        from postgres_client import PostgresClient
        from scheduler.ai_task_workers import enqueue_ticker_analysis_tasks
        from supabase_client import SupabaseClient
        from utils.job_tracking import mark_job_completed, mark_job_started

        mark_job_started(JOB_ID, target_date)
        pg = PostgresClient()
        # Gate on an unbounded count: with LIMIT applied first, len(rows)/14
        # could never exceed ~3.6/day and the gate would never open.
        count_rows = pg.execute_query(
            """
            SELECT COUNT(*) AS cnt
            FROM ticker_meta_analysis
            WHERE updated_at >= NOW() - INTERVAL '14 days'
              AND confidence_adjusted < 0.5
              AND jsonb_array_length(COALESCE(contradictions, '[]'::jsonb)) >= 2
            """
        )
        total_count = int((count_rows[0] or {}).get("cnt") or 0) if count_rows else 0
        rows = pg.execute_query(
            """
            SELECT ticker, confidence_adjusted,
                   jsonb_array_length(COALESCE(contradictions, '[]'::jsonb)) AS c_count
            FROM ticker_meta_analysis
            WHERE updated_at >= NOW() - INTERVAL '14 days'
              AND confidence_adjusted < 0.5
              AND jsonb_array_length(COALESCE(contradictions, '[]'::jsonb)) >= 2
            ORDER BY updated_at DESC
            LIMIT 50
            """
        )
        daily_avg = total_count / 14.0
        if daily_avg < MIN_DAILY_CONTRADICTIONS:
            msg = f"skipped: supply {daily_avg:.1f}/day < {MIN_DAILY_CONTRADICTIONS} (audit #4 gate)"
            duration_ms = int((time.time() - start) * 1000)
            log_job_execution(JOB_ID, True, msg, duration_ms)
            mark_job_completed(JOB_ID, target_date, None, [], duration_ms=duration_ms, message=msg)
            logger.info("contradiction_drilldown_job: %s", msg)
            return

        tickers = [(str(r["ticker"]).upper(), 200) for r in rows if r.get("ticker")]
        supabase = SupabaseClient(use_service_role=True)
        stats = enqueue_ticker_analysis_tasks(
            supabase,
            tickers[:15],
            enqueued_by=JOB_ID,
        )
        duration_ms = int((time.time() - start) * 1000)
        msg = f"enqueued={stats.get('enqueued', 0)} candidates={len(tickers)}"
        log_job_execution(JOB_ID, True, msg, duration_ms)
        mark_job_completed(JOB_ID, target_date, None, [], duration_ms=duration_ms, message=msg)
        logger.info("contradiction_drilldown_job: %s", msg)
    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        err = str(exc)
        log_job_execution(JOB_ID, False, err, duration_ms)
        try:
            from utils.job_tracking import mark_job_failed

            mark_job_failed(JOB_ID, target_date, None, err, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error("contradiction_drilldown_job failed: %s", exc, exc_info=True)
