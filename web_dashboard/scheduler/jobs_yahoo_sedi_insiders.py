"""Weekly yfinance SEDI insider ingest for Canadian tickers (ROADMAP G7)."""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, UTC
from pathlib import Path

current_dir = Path(__file__).resolve().parent
if str(current_dir.parent) not in sys.path:
    sys.path.insert(0, str(current_dir.parent))

from scheduler.scheduler_core import log_job_execution

logger = logging.getLogger(__name__)

JOB_ID = "yahoo_sedi_insiders"
_PAGE_SIZE = 1000
_UPSERT_CONFLICT = "ticker,insider_name,transaction_date,type,shares,price_per_share"


def _lookback_days() -> int:
    raw = (os.getenv("YAHOO_SEDI_INSIDER_DAYS") or "365").strip()
    try:
        return max(30, min(int(raw), 730))
    except ValueError:
        return 365


def _production_fund_names(supabase_client) -> list[str] | None:
    """Production fund names, or ``None`` if the lookup itself failed.

    Distinguishing failure (``None``) from "none flagged" (``[]``) matters: on
    failure the caller must NOT fall back to an unfiltered holdings scan, which
    would pull TEST_* fund pollution that lives alongside production data.
    """
    try:
        res = (
            supabase_client.supabase.table("funds")
            .select("name")
            .eq("is_production", True)
            .execute()
        )
        return [r["name"] for r in (res.data or []) if r.get("name")]
    except Exception as exc:
        logger.warning("yahoo_sedi_insiders: production-fund lookup failed: %s", exc)
        return None


def _trade_exists(supabase_client, record: dict) -> bool:
    """Existence check matching ``insider_trades_unique_key``, incl. NULL price.

    Postgres treats a NULL ``price_per_share`` as *distinct* in the unique index,
    so a plain ``upsert(on_conflict=...)`` never collides for priceless rows and
    re-inserts them on every weekly run. Pre-checking here (with an explicit IS
    NULL branch) mirrors the SEC Form-4 path's dedup guard and keeps the table
    free of duplicates.
    """
    query = (
        supabase_client.supabase.table("insider_trades")
        .select("id")
        .eq("ticker", record["ticker"])
        .eq("insider_name", record["insider_name"])
        .eq("transaction_date", record["transaction_date"])
        .eq("type", record["type"])
        .eq("shares", record["shares"])
    )
    if record.get("price_per_share") is None:
        query = query.is_("price_per_share", "null")
    else:
        query = query.eq("price_per_share", record["price_per_share"])
    try:
        res = query.limit(1).execute()
        return bool(res.data)
    except Exception as exc:
        logger.debug("yahoo_sedi dup-check failed (will upsert): %s", exc)
        return False


def collect_canadian_tickers(supabase_client) -> list[str]:
    """Production-fund holdings + active watchlist, Canadian suffixes only."""
    from yahoo_sedi_insider_service import is_canadian_ticker

    tickers: set[str] = set()
    production_funds = _production_fund_names(supabase_client)
    try:
        # Only scan holdings with a concrete production-fund filter. An empty or
        # failed lookup must skip the scan rather than run unfiltered (which
        # would pull TEST_* tickers); the watchlist scan below runs regardless.
        # .order() makes range() pagination stable across pages.
        if production_funds:
            offset = 0
            while True:
                pos = (
                    supabase_client.supabase.table("latest_positions")
                    .select("ticker,fund")
                    .in_("fund", production_funds)
                    .order("fund")
                    .order("ticker")
                    .range(offset, offset + _PAGE_SIZE - 1)
                    .execute()
                )
                page = pos.data or []
                for row in page:
                    t = str(row.get("ticker") or "").upper().strip()
                    if t and is_canadian_ticker(t):
                        tickers.add(t)
                if len(page) < _PAGE_SIZE:
                    break
                offset += _PAGE_SIZE
        else:
            logger.warning(
                "yahoo_sedi_insiders: no production funds resolved (%s); "
                "skipping holdings scan (watchlist only)",
                "lookup failed" if production_funds is None else "none flagged",
            )

        offset = 0
        while True:
            wl = (
                supabase_client.supabase.table("watched_tickers_v2")
                .select("ticker")
                .eq("is_active", True)
                .order("fund")
                .order("ticker")
                .range(offset, offset + _PAGE_SIZE - 1)
                .execute()
            )
            page = wl.data or []
            for row in page:
                t = str(row.get("ticker") or "").upper().strip()
                if t and is_canadian_ticker(t):
                    tickers.add(t)
            if len(page) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
    except Exception as exc:
        logger.warning("yahoo_sedi_insiders ticker load failed: %s", exc)
    return sorted(tickers)


def yahoo_sedi_insiders_job() -> None:
    start = time.time()
    target_date = datetime.now(UTC).date()
    parsed = 0
    inserted = 0
    skipped_dupes = 0
    errors = 0
    lookback = _lookback_days()

    try:
        from supabase_client import SupabaseClient
        from utils.job_tracking import mark_job_completed, mark_job_started
        from yahoo_sedi_insider_service import fetch_yahoo_insider_rows

        mark_job_started(JOB_ID, target_date)
        supabase = SupabaseClient(use_service_role=True)
        tickers = collect_canadian_tickers(supabase)

        for ticker in tickers:
            try:
                rows = fetch_yahoo_insider_rows(
                    ticker,
                    lookback_days=lookback,
                    as_of=target_date,
                )
                if not rows:
                    continue
                parsed += len(rows)
                for record in rows:
                    try:
                        if _trade_exists(supabase, record):
                            skipped_dupes += 1
                            continue
                        result = (
                            supabase.supabase.table("insider_trades")
                            .upsert(record, on_conflict=_UPSERT_CONFLICT)
                            .execute()
                        )
                        if result.data:
                            inserted += 1
                    except Exception as row_exc:
                        errors += 1
                        logger.warning(
                            "yahoo_sedi upsert failed %s %s: %s",
                            ticker,
                            record.get("insider_name"),
                            row_exc,
                        )
            except Exception as ticker_exc:
                errors += 1
                logger.warning("yahoo_sedi fetch failed for %s: %s", ticker, ticker_exc)

        duration_ms = int((time.time() - start) * 1000)
        msg = (
            f"tickers={len(tickers)} lookback_days={lookback} "
            f"parsed={parsed} inserted={inserted} skipped_dupes={skipped_dupes} errors={errors}"
        )
        log_job_execution(JOB_ID, True, msg, duration_ms)
        mark_job_completed(JOB_ID, target_date, None, [], duration_ms=duration_ms, message=msg)
        logger.info("yahoo_sedi_insiders_job: %s", msg)
    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        err = str(exc)
        log_job_execution(JOB_ID, False, err, duration_ms)
        try:
            from utils.job_tracking import mark_job_failed

            mark_job_failed(JOB_ID, target_date, None, err, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error("yahoo_sedi_insiders_job failed: %s", exc, exc_info=True)
