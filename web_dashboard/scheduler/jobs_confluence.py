"""Cross-signal confluence scorer job (ROADMAP G4).

Nightly, no-LLM job that counts aligned signal families per ticker and
persists high-confluence events. See docs/PHASE_G_PLAN.md G4.
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

JOB_ID = "confluence"


def confluence_job() -> None:
    start = time.time()
    target_date = datetime.now(UTC).date()
    try:
        from confluence_service import run_confluence_scan
        from postgres_client import PostgresClient
        from supabase_client import SupabaseClient
        from utils.job_tracking import mark_job_completed, mark_job_started

        mark_job_started(JOB_ID, target_date)
        postgres = PostgresClient()
        supabase = SupabaseClient(use_service_role=True)
        stats = run_confluence_scan(postgres, supabase)

        duration_ms = int((time.time() - start) * 1000)
        msg = (
            f"tickers={stats['tickers']} events={stats['events']} "
            f"inserted={stats['inserted']} skipped_dedupe={stats['skipped_dedupe']} "
            f"stances_written={stats['stances_written']}"
        )
        log_job_execution(JOB_ID, True, msg, duration_ms)
        mark_job_completed(JOB_ID, target_date, None, [], duration_ms=duration_ms, message=msg)
        logger.info("confluence_job: %s", msg)
    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        err = str(exc)
        log_job_execution(JOB_ID, False, err, duration_ms)
        try:
            from utils.job_tracking import mark_job_failed

            mark_job_failed(JOB_ID, target_date, None, err, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error("confluence_job failed: %s", exc, exc_info=True)
