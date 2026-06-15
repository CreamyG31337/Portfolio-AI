"""
Dilution watch job (ROADMAP G3).

Free, country-agnostic dilution detection: a rising shares-outstanding count IS
dilution. Pulls share-count history from yfinance (`get_shares_full`, works for
US and `.TO`/`.V` tickers alike), computes 90/365-day growth for production-fund
holdings + watchlist, and records flagged movers into `dilution_observations`.

Replaces the old §4.1 placeholder. No LLM. The complementary US filing watch
(shelf/distress/delisting/activist) is a separate job (G2). See
docs/PHASE_G_PLAN.md G3.
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

# Supabase REST returns at most 1000 rows per request regardless of .limit().
_PAGE_SIZE = 1000


def _production_fund_names(supabase_client) -> list[str]:
    try:
        res = (
            supabase_client.supabase.table("funds")
            .select("name")
            .eq("is_production", True)
            .execute()
        )
        return [r["name"] for r in (res.data or []) if r.get("name")]
    except Exception as exc:
        logger.warning("dilution_watch: production-fund lookup failed: %s", exc)
        return []


def _collect_tickers(supabase_client) -> list[str]:
    """Holdings (production funds only) + active watchlist tickers.

    Production-fund filter avoids wasting yfinance calls on TEST_* fixture
    tickers (STOCK1, FIFO, …) the test suite leaves in prod Supabase. Falls
    back to all holdings if the funds lookup is empty (see ticker_analysis_service).
    """
    tickers: set[str] = set()
    production_funds = _production_fund_names(supabase_client)
    try:
        offset = 0
        while True:
            holdings_query = supabase_client.supabase.table("latest_positions").select(
                "ticker,fund"
            )
            if production_funds:
                holdings_query = holdings_query.in_("fund", production_funds)
            pos = holdings_query.range(offset, offset + _PAGE_SIZE - 1).execute()
            page = pos.data or []
            for row in page:
                if row.get("ticker"):
                    tickers.add(str(row["ticker"]).upper())
            if len(page) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE

        offset = 0
        while True:
            wl = (
                supabase_client.supabase.table("watched_tickers_v2")
                .select("ticker")
                .eq("is_active", True)
                .range(offset, offset + _PAGE_SIZE - 1)
                .execute()
            )
            page = wl.data or []
            for row in page:
                if row.get("ticker"):
                    tickers.add(str(row["ticker"]).upper())
            if len(page) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
    except Exception as exc:
        logger.warning("dilution_watch ticker load failed: %s", exc)
    return sorted(tickers)


def dilution_watch_job() -> None:
    start = time.time()
    target_date = datetime.now(UTC).date()
    flagged = 0
    observed = 0
    try:
        from dilution_service import compute_dilution_observations, fetch_shares_history
        from postgres_client import PostgresClient
        from supabase_client import SupabaseClient
        from utils.job_tracking import mark_job_completed, mark_job_started

        mark_job_started(JOB_ID, target_date)
        supabase = SupabaseClient(use_service_role=True)
        postgres = PostgresClient()

        tickers = _collect_tickers(supabase)
        history = fetch_shares_history(tuple(tickers))
        observations = compute_dilution_observations(history, as_of=target_date)
        observed = len(observations)

        # Persist only flagged movers; clean readings are noise here.
        for obs in observations:
            if not obs.get("flagged"):
                continue
            try:
                postgres.execute_update(
                    """
                    INSERT INTO dilution_observations (
                        ticker, as_of, window_days, shares_start, shares_end,
                        pct_change, flagged
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (ticker, as_of, window_days) DO NOTHING
                    """,
                    (
                        obs["ticker"],
                        obs["as_of"],
                        obs["window_days"],
                        obs["shares_start"],
                        obs["shares_end"],
                        obs["pct_change"],
                        True,
                    ),
                )
                flagged += 1
            except Exception as row_exc:
                logger.warning("dilution_watch insert failed for %s: %s", obs["ticker"], row_exc)

        duration_ms = int((time.time() - start) * 1000)
        msg = (
            f"tickers={len(tickers)} with_history={len(history)} "
            f"observations={observed} flagged={flagged}"
        )
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
