"""Today advise_pack recommendations → stance_history ledger job (ROADMAP §2.8 Z3).

Nightly, no-LLM job that captures the Today briefing's ranked candidate pack into
stance_history so outcome scoring automatically evaluates recommendation performance.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
import sys
import time

current_dir = Path(__file__).resolve().parent
if str(current_dir.parent) not in sys.path:
    sys.path.insert(0, str(current_dir.parent))

from scheduler.scheduler_core import log_job_execution  # noqa: E402

logger = logging.getLogger(__name__)

JOB_ID = "advise_pack_ledger"


def advise_pack_ledger_job() -> None:
    start = time.time()
    target_date = datetime.now(UTC).date()
    try:
        try:
            import web_dashboard.advise_stance_service as _advise_mod
        except ImportError:
            import advise_stance_service as _advise_mod
        record_advise_pack_stances = _advise_mod.record_advise_pack_stances

        try:
            import web_dashboard.postgres_client as _pg_mod
        except ImportError:
            import postgres_client as _pg_mod
        PostgresClient = _pg_mod.PostgresClient

        try:
            import web_dashboard.supabase_client as _sb_mod
        except ImportError:
            import supabase_client as _sb_mod
        SupabaseClient = _sb_mod.SupabaseClient

        from utils.job_tracking import mark_job_completed, mark_job_started

        mark_job_started(JOB_ID, target_date)
        postgres = PostgresClient()
        supabase = SupabaseClient()
        stats = record_advise_pack_stances(postgres, supabase)
        if stats["errors"] > 0 and stats["funds"] == 0:
            raise RuntimeError(
                f"Advise pack failed for all funds (errors={stats['errors']})"
            )

        duration_ms = int((time.time() - start) * 1000)
        msg = (
            f"funds={stats['funds']} rows_seen={stats['rows_seen']} "
            f"written={stats['written']} "
            f"skipped_nondirectional={stats['skipped_nondirectional']} "
            f"errors={stats['errors']}"
        )
        log_job_execution(JOB_ID, True, msg, duration_ms)
        mark_job_completed(JOB_ID, target_date, None, [], duration_ms=duration_ms, message=msg)
        logger.info("advise_pack_ledger_job: %s", msg)
    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        err = str(exc)
        log_job_execution(JOB_ID, False, err, duration_ms)
        try:
            from utils.job_tracking import mark_job_failed

            mark_job_failed(JOB_ID, target_date, None, err, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error("advise_pack_ledger_job failed: %s", exc, exc_info=True)
