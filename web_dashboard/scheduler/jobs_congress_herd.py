"""Congress herd → stance_history ledger job (ROADMAP H5 / Pillar 5.1).

Nightly, no-LLM job that records scoreable BULLISH herd readings so outcome
scoring can grade the congress-herd source. Detection stays on-demand for
Today/API; this job is the Learn-layer write path only.
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

current_dir = Path(__file__).resolve().parent
if str(current_dir.parent) not in sys.path:
    sys.path.insert(0, str(current_dir.parent))

from scheduler.scheduler_core import log_job_execution  # noqa: E402

logger = logging.getLogger(__name__)

JOB_ID = "congress_herd"


def congress_herd_job() -> None:
    start = time.time()
    target_date = datetime.now(UTC).date()
    try:
        from congress_herd_service import record_congress_herd_stances
        from postgres_client import PostgresClient
        from supabase_client import SupabaseClient
        from utils.job_tracking import mark_job_completed, mark_job_started

        mark_job_started(JOB_ID, target_date)
        postgres = PostgresClient()
        supabase = SupabaseClient(use_service_role=True)
        stats = record_congress_herd_stances(postgres, supabase)

        duration_ms = int((time.time() - start) * 1000)
        msg = (
            f"herds={stats['herds']} stances_written={stats['stances_written']}"
        )
        log_job_execution(JOB_ID, True, msg, duration_ms)
        mark_job_completed(JOB_ID, target_date, None, [], duration_ms=duration_ms, message=msg)
        logger.info("congress_herd_job: %s", msg)
    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        err = str(exc)
        log_job_execution(JOB_ID, False, err, duration_ms)
        try:
            from utils.job_tracking import mark_job_failed

            mark_job_failed(JOB_ID, target_date, None, err, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error("congress_herd_job failed: %s", exc, exc_info=True)
