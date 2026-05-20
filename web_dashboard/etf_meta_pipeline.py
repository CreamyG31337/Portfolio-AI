"""ETF holdings → ETF Analysis articles → sector meta (shared helpers).

Single place for gap detection and queue lookback so schedulers and ops scripts stay aligned.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from postgres_client import PostgresClient

EtfDatePair = tuple[str, str]  # (ETF_TICKER, YYYY-MM-DD)

logger = logging.getLogger(__name__)


def get_etf_queue_lookback_days(postgres: PostgresClient | None = None) -> int:
    """How many calendar days back to queue missing ETF group analyses.

    - ``ETF_GROUP_QUEUE_LOOKBACK_DAYS`` (default 14): normal nightly window.
    - ``ETF_GROUP_QUEUE_MAX_LOOKBACK_DAYS`` (default 30): cap when auto catch-up expands.
    - If many pairs are missing in the max window, use the max lookback so a week/month
      outage self-heals without a manual script.
    """
    base = max(1, int(os.getenv("ETF_GROUP_QUEUE_LOOKBACK_DAYS", "14")))
    max_lb = max(base, int(os.getenv("ETF_GROUP_QUEUE_MAX_LOOKBACK_DAYS", "30")))

    pc = postgres or PostgresClient()
    missing_at_max = count_missing_etf_article_pairs(pc, max_lb)
    if missing_at_max <= 0:
        return base
    # Behind: scan downward from max_lb to find smallest window that still has gaps
    for days in range(max_lb, base - 1, -1):
        if count_missing_etf_article_pairs(pc, days) > 0:
            return days
    return base


def purge_stale_etf_group_queue(keep_lookback_days: int) -> int:
    """Complete pending/failed queue rows older than the active lookback window.

    Stale rows (often from an earlier outage) can starve newer work because the job
    used to fetch only a small ``created_at`` page before sorting by holdings date.
    """
    from supabase_client import SupabaseClient

    keep_lookback_days = max(1, int(keep_lookback_days))
    cutoff = (datetime.now(UTC).date() - timedelta(days=keep_lookback_days - 1)).isoformat()
    db = SupabaseClient(use_service_role=True)
    purged = 0
    offset = 0
    page_size = 500
    while True:
        result = (
            db.supabase.table("ai_analysis_queue")
            .select("id,target_key,status")
            .eq("analysis_type", "etf_group")
            .in_("status", ["pending", "failed"])
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = list(result.data or [])
        if not batch:
            break
        for row in batch:
            key = str(row.get("target_key") or "")
            parts = key.split("_", 1)
            day = parts[1] if len(parts) > 1 else ""
            if not day or day >= cutoff:
                continue
            db.supabase.table("ai_analysis_queue").update(
                {
                    "status": "completed",
                    "completed_at": datetime.now(UTC).isoformat(),
                    "error_message": "stale_queue_purge: outside lookback window",
                }
            ).eq("id", row["id"]).execute()
            purged += 1
        if len(batch) < page_size:
            break
        offset += page_size
    if purged:
        logger.info(
            "Purged %s stale etf_group queue row(s) with holdings date before %s",
            purged,
            cutoff,
        )
    return purged


_MISSING_PAIRS_SQL = """
    SELECT DISTINCT UPPER(c.etf_ticker) AS etf, c.date::text AS d
    FROM etf_holdings_changes c
    WHERE c.date >= CURRENT_DATE - %s::int
      AND NOT EXISTS (
        SELECT 1
        FROM research_articles r
        WHERE r.article_type = 'ETF Analysis'
          AND r.url = 'etf-analysis://' || UPPER(c.etf_ticker) || '/' || c.date::text
      )
"""


def fetch_missing_etf_article_pair_keys(
    postgres: PostgresClient,
    lookback_days: int,
) -> set[EtfDatePair]:
    """Distinct (etf_ticker, holdings_date) missing an ETF Analysis article."""
    lookback_days = max(1, int(lookback_days))
    rows = postgres.execute_query(_MISSING_PAIRS_SQL, (lookback_days,))
    return {
        (str(row["etf"]).upper(), str(row["d"]))
        for row in (rows or [])
        if row.get("etf") and row.get("d")
    }


def count_missing_etf_article_pairs(postgres: PostgresClient, lookback_days: int) -> int:
    """Distinct (holdings_date, etf_ticker) with changes but no ETF Analysis article."""
    return len(fetch_missing_etf_article_pair_keys(postgres, lookback_days))


@dataclass(frozen=True)
class BackfillProgress:
    """Per-run gap delta (before/after missing-pair snapshots)."""

    filled: int
    new_gaps: int
    net_delta: int
    filled_pairs: frozenset[EtfDatePair]
    new_pairs: frozenset[EtfDatePair]


def measure_backfill_progress(
    before: set[EtfDatePair],
    after: set[EtfDatePair],
) -> BackfillProgress:
    """Compare missing-pair snapshots; new watchtower rows count as new_gaps, not stall."""
    filled_pairs = before - after
    new_pairs = after - before
    return BackfillProgress(
        filled=len(filled_pairs),
        new_gaps=len(new_pairs),
        net_delta=len(after) - len(before),
        filled_pairs=frozenset(filled_pairs),
        new_pairs=frozenset(new_pairs),
    )


def print_gap_table(postgres: PostgresClient, lookback_days: int = 14) -> None:
    """Print per-day gap summary to stdout (ops / backfill script)."""
    today = datetime.now(UTC).date()
    from datetime import timedelta

    print(f"\nETF article gaps (last {lookback_days} days)\n")
    print(f"{'Date':<12} {'ETFs w/changes':>14} {'Articles':>10} {'Missing':>8}")
    print("-" * 48)
    for i in range(lookback_days):
        d = (today - timedelta(days=i)).isoformat()
        ch = postgres.execute_query(
            "SELECT COUNT(DISTINCT etf_ticker) AS n FROM etf_holdings_changes WHERE date = %s",
            (d,),
        )[0]["n"]
        ar = postgres.execute_query(
            """
            SELECT COUNT(*) AS n FROM research_articles
            WHERE article_type = 'ETF Analysis' AND url LIKE %s
            """,
            (f"etf-analysis://%/{d}",),
        )[0]["n"]
        gap = max(0, int(ch) - int(ar))
        mark = " <--" if gap > 0 else ""
        print(f"{d:<12} {int(ch):>14} {int(ar):>10} {gap:>8}{mark}")
    missing = count_missing_etf_article_pairs(postgres, lookback_days)
    print(f"\nTotal missing (etf, date) pairs: {missing}")
