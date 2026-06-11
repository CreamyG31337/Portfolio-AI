"""
Dilution watch advisory job (ROADMAP §4.1).

V1: scans holdings + watchlist tickers and logs advisory scan summary.
Full EDGAR S-3/424B5 parsing builds on sec_form4_poc plumbing in a later pass.
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

JOB_ID = "dilution_watch"
DILUTION_KEYWORDS = ("S-3", "424B5", "ATM", "reverse split")


def _collect_tickers(supabase_client) -> list[str]:
    tickers: set[str] = set()
    try:
        pos = supabase_client.supabase.table("latest_positions").select("ticker").execute()
        for row in pos.data or []:
            if row.get("ticker"):
                tickers.add(str(row["ticker"]).upper())
        wl = (
            supabase_client.supabase.table("watched_tickers_v2")
            .select("ticker")
            .eq("is_active", True)
            .execute()
        )
        for row in wl.data or []:
            if row.get("ticker"):
                tickers.add(str(row["ticker"]).upper())
    except Exception as exc:
        logger.warning("dilution_watch ticker load failed: %s", exc)
    return sorted(tickers)


def dilution_watch_job() -> None:
    start = time.time()
    target_date = datetime.now(UTC).date()
    try:
        from supabase_client import SupabaseClient
        from utils.job_tracking import mark_job_completed, mark_job_started

        mark_job_started(JOB_ID, target_date)
        supabase = SupabaseClient(use_service_role=True)
        tickers = _collect_tickers(supabase)
        # V1 placeholder: only enumerates scope — no EDGAR call happens yet, so the
        # message must say so. Do NOT report "scanned" until the EDGAR pass exists.
        msg = f"placeholder: no EDGAR scan yet; scope={len(tickers)} tickers"
        duration_ms = int((time.time() - start) * 1000)
        log_job_execution(JOB_ID, True, msg, duration_ms)
        mark_job_completed(JOB_ID, target_date, None, [], duration_ms=duration_ms, message=msg)
        logger.info("dilution_watch_job: %s", msg)
    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        err = str(exc)
        log_job_execution(JOB_ID, False, err, duration_ms)
        try:
            from utils.job_tracking import mark_job_failed

            mark_job_failed(JOB_ID, target_date, None, err, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error("dilution_watch_job failed: %s", exc, exc_info=True)
