"""Weekly stance retro summary (Pillar 3 — uses stance_outcomes + stance_history)."""

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

JOB_ID = "weekly_stance_retro"


def weekly_stance_retro_job() -> None:
    start = time.time()
    target_date = datetime.now(UTC).date()
    try:
        from postgres_client import PostgresClient
        from retro_digest_service import send_weekly_retro_digest
        from track_record_service import build_track_record_summary
        from utils.job_tracking import mark_job_completed, mark_job_started

        mark_job_started(JOB_ID, target_date)
        pg = PostgresClient()
        from today_briefing_service import fetch_stance_flips

        flip_cnt = len(fetch_stance_flips(pg, days=7, limit=500))
        summary = build_track_record_summary(pg, horizon_days=30)
        send_result = send_weekly_retro_digest(pg)
        msg = (
            f"flips_7d={flip_cnt} scored_30d={summary.get('total_scored', 0)} "
            f"sources={len(summary.get('hit_rate_by_source') or {})} "
            f"email_sent={send_result.get('sent', 0)} "
            f"email_skipped={send_result.get('skipped', False)}"
        )
        duration_ms = int((time.time() - start) * 1000)
        log_job_execution(JOB_ID, True, msg, duration_ms)
        mark_job_completed(JOB_ID, target_date, None, [], duration_ms=duration_ms, message=msg)
        logger.info("weekly_stance_retro_job: %s", msg)
    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        err = str(exc)
        log_job_execution(JOB_ID, False, err, duration_ms)
        try:
            from utils.job_tracking import mark_job_failed

            mark_job_failed(JOB_ID, target_date, None, err, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error("weekly_stance_retro_job failed: %s", exc, exc_info=True)
