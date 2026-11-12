"""Alpha ideas → stance_history ledger job (ROADMAP §2.8 Z1/Z3).

Nightly, no-LLM job that records each directional Alpha/Opportunity idea so outcome
scoring grades ideas with no human triage. Backfill: scripts/backfill_alpha_idea_stances.py.
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

JOB_ID = "alpha_idea_ledger"


def alpha_idea_ledger_job() -> None:
    start = time.time()
    target_date = datetime.now(UTC).date()
    try:
        from idea_stance_service import record_alpha_idea_stances
        from postgres_client import PostgresClient
        from utils.job_tracking import mark_job_completed, mark_job_started

        mark_job_started(JOB_ID, target_date)
        postgres = PostgresClient()
        stats = record_alpha_idea_stances(postgres)

        duration_ms = int((time.time() - start) * 1000)
        msg = (
            f"articles={stats['articles']} candidates={stats['candidates']} "
            f"stances_written={stats['stances_written']} "
            f"skipped_basket={stats['skipped_too_many_tickers']}"
        )
        log_job_execution(JOB_ID, True, msg, duration_ms)
        mark_job_completed(JOB_ID, target_date, None, [], duration_ms=duration_ms, message=msg)
        logger.info("alpha_idea_ledger_job: %s", msg)
    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        err = str(exc)
        log_job_execution(JOB_ID, False, err, duration_ms)
        try:
            from utils.job_tracking import mark_job_failed

            mark_job_failed(JOB_ID, target_date, None, err, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error("alpha_idea_ledger_job failed: %s", exc, exc_info=True)
