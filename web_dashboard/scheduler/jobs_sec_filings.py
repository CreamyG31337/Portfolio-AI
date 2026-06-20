"""US SEC (EDGAR) filing-risk watch job (ROADMAP G2).

Polls EDGAR submissions for production-fund holdings + active watchlist (US
tickers only) and records new dilution / distress / delisting / activist filing
events into the Research-DB ``filing_events`` table. The FORWARD/structural
signal the share-count dilution watch (G3) can't show — a shelf S-3 means
dilution is *coming*. No LLM.

Distinct from G3: this is ``JOB_ID="sec_filings"`` writing ``filing_events``;
G3 is ``JOB_ID="dilution_watch"`` writing ``dilution_observations``.

DB note: ``filing_events`` is in the Research DB schema; enable the job in the
Jobs admin UI once the table is applied in your environment.
"""

from __future__ import annotations

import json
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

JOB_ID = "sec_filings"

# Supabase REST returns at most 1000 rows per request regardless of .limit().
_PAGE_SIZE = 1000

# Re-scan a week each run: SEC filings only post on business days, the dedupe on
# accession_no makes overlapping windows free, and a 7d window never misses a
# filing across a weekend/holiday gap.
SCAN_LOOKBACK_DAYS = 7


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
        logger.warning("sec_filings: production-fund lookup failed: %s", exc)
        return []


def _collect_tickers(supabase_client) -> list[str]:
    """Holdings (production funds only) + active watchlist tickers.

    Production-fund filter avoids wasting SEC calls on TEST_* fixture tickers
    the test suite leaves in prod Supabase. Falls back to all holdings if the
    funds lookup is empty (mirrors ticker_analysis_service / dilution_watch).
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
        logger.warning("sec_filings ticker load failed: %s", exc)
    return sorted(tickers)


def sec_filings_job() -> None:
    start = time.time()
    target_date = datetime.now(UTC).date()
    scanned = 0
    skipped_no_cik = 0
    events_found = 0
    inserted = 0
    try:
        from postgres_client import PostgresClient
        from scheduler.sec_http import fetch_json
        from sec_filings_service import (
            SUBMISSIONS_URL,
            default_since_date,
            dedupe_events,
            extract_filing_events,
            load_ticker_cik_map,
        )
        from supabase_client import SupabaseClient
        from utils.job_tracking import mark_job_completed, mark_job_started

        mark_job_started(JOB_ID, target_date)
        supabase = SupabaseClient(use_service_role=True)
        postgres = PostgresClient()

        tickers = _collect_tickers(supabase)
        cik_map = load_ticker_cik_map()
        since_date = default_since_date(SCAN_LOOKBACK_DAYS)
        seen_accessions: set[str] = set()

        for ticker in tickers:
            cik = cik_map.get(ticker)
            if not cik:
                # US tickers not in the map (delisted/renamed micro-caps) and all
                # .TO/.V names land here — skip and log, never error. G3 covers .TO.
                skipped_no_cik += 1
                logger.info("sec_filings: no CIK for %s (skip; .TO/.V or unmapped US)", ticker)
                continue

            submissions = fetch_json(SUBMISSIONS_URL.format(cik=cik))
            if not submissions:
                continue
            scanned += 1

            events = dedupe_events(
                extract_filing_events(ticker, cik, submissions, since_date=since_date)
            )
            for ev in events:
                acc = ev["accession_no"]
                if acc in seen_accessions:
                    continue
                seen_accessions.add(acc)
                events_found += 1
                try:
                    affected = postgres.execute_update(
                        """
                        INSERT INTO filing_events (
                            ticker, cik, form_type, category, direction,
                            filed_at, accession_no, title, url, raw
                        ) VALUES (
                            %s, %s, %s, %s, %s,
                            %s::date, %s, %s, %s, %s::jsonb
                        )
                        ON CONFLICT (accession_no) DO NOTHING
                        """,
                        (
                            ev["ticker"],
                            ev["cik"],
                            ev["form_type"],
                            ev["category"],
                            ev["direction"],
                            ev["filed_at"],
                            ev["accession_no"],
                            ev["title"],
                            ev["url"],
                            json.dumps(ev["raw"]),
                        ),
                    )
                    inserted += affected or 0
                except Exception as row_exc:
                    logger.warning(
                        "sec_filings insert failed for %s %s: %s",
                        ev["ticker"], ev["accession_no"], row_exc,
                    )

        duration_ms = int((time.time() - start) * 1000)
        msg = (
            f"tickers={len(tickers)} scanned={scanned} no_cik={skipped_no_cik} "
            f"events={events_found} inserted={inserted}"
        )
        log_job_execution(JOB_ID, True, msg, duration_ms)
        mark_job_completed(JOB_ID, target_date, None, [], duration_ms=duration_ms, message=msg)
        logger.info("sec_filings_job: %s", msg)
    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        err = str(exc)
        log_job_execution(JOB_ID, False, err, duration_ms)
        try:
            from utils.job_tracking import mark_job_failed

            mark_job_failed(JOB_ID, target_date, None, err, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error("sec_filings_job failed: %s", exc, exc_info=True)
