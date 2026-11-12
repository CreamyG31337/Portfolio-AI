"""ARK trade notifications → stance_history ledger job (ROADMAP §2.8 L4).

Nightly, no-LLM job that records new ARK active-fund buys as BEARISH stances
so outcome scoring grades the rule with no human triage.
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

JOB_ID = "ark_trade_ledger"


def ark_trade_ledger_job() -> None:
    start = time.time()
    target_date = datetime.now(UTC).date()
    try:
        from ark_stance_service import record_ark_stances
        from postgres_client import PostgresClient
        from utils.job_tracking import mark_job_completed, mark_job_started

        mark_job_started(JOB_ID, target_date)
        postgres = PostgresClient()
        stats = record_ark_stances(postgres)
        if stats["api_errors"] and stats["trades_fetched"] == 0:
            # Every fund failed: surface it as a job failure instead of a quiet "0 written"
            # (the iShares feed died silently for six months that way).
            raise RuntimeError(f"arkfunds.io unreachable for all funds (api_errors={stats['api_errors']})")

        duration_ms = int((time.time() - start) * 1000)
        msg = (
            f"trades={stats['trades_fetched']} candidates={stats['candidates']} "
            f"stances_written={stats['stances_written']} "
            f"skipped_throttle={stats['skipped_throttle']} "
            f"skipped_wash={stats['skipped_wash']} "
            f"skipped_foreign={stats['skipped_foreign']} "
            f"api_errors={stats['api_errors']}"
        )
        log_job_execution(JOB_ID, True, msg, duration_ms)
        mark_job_completed(JOB_ID, target_date, None, [], duration_ms=duration_ms, message=msg)
        logger.info("ark_trade_ledger_job: %s", msg)
    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        err = str(exc)
        log_job_execution(JOB_ID, False, err, duration_ms)
        try:
            from utils.job_tracking import mark_job_failed

            mark_job_failed(JOB_ID, target_date, None, err, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error("ark_trade_ledger_job failed: %s", exc, exc_info=True)
