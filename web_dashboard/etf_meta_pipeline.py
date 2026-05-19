"""ETF holdings → ETF Analysis articles → sector meta (shared helpers).

Single place for gap detection and queue lookback so schedulers and ops scripts stay aligned.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from postgres_client import PostgresClient


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


def count_missing_etf_article_pairs(postgres: PostgresClient, lookback_days: int) -> int:
    """Distinct (holdings_date, etf_ticker) with changes but no ETF Analysis article."""
    lookback_days = max(1, int(lookback_days))
    row = postgres.execute_query(
        """
        SELECT COUNT(*) AS n
        FROM (
            SELECT DISTINCT c.date::text AS d, c.etf_ticker
            FROM etf_holdings_changes c
            WHERE c.date >= CURRENT_DATE - %s::int
              AND NOT EXISTS (
                SELECT 1
                FROM research_articles r
                WHERE r.article_type = 'ETF Analysis'
                  AND r.url = 'etf-analysis://' || UPPER(c.etf_ticker) || '/' || c.date::text
              )
        ) x
        """,
        (lookback_days,),
    )
    if not row:
        return 0
    return int(row[0].get("n") or 0)


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
