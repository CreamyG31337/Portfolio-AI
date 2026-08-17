#!/usr/bin/env python3
"""READ-ONLY diagnostic for the applied available_at migrations.

Answers the questions that decide whether the corrective migration
(2026-08_fix_available_at_index_and_provenance.sql) is sufficient, or whether the
already-written available_at values also need re-backfilling:

1. What is the server's TimeZone? The original backfill ran
   ``SET available_at = COALESCE(fetched_at, NOW())`` with available_at TIMESTAMPTZ
   and fetched_at a naive TIMESTAMP. Postgres resolved that implicitly through the
   session TimeZone. If TimeZone was UTC the stored values are correct; if it was
   America/Vancouver every backfilled row is shifted by the UTC offset.

2. Do stored available_at values actually equal fetched_at interpreted as UTC, or do
   they differ by a whole-hour offset (the signature of the implicit cast)?

3. How many rows would the provenance flag mark as estimated?

4. Are the existing indexes being used at all?

Writes nothing. Run this before applying the corrective migration.

Usage:
    python web_dashboard/scripts/diagnose_available_at_state.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    from postgres_client import PostgresClient

    pg = PostgresClient()

    def q(label: str, sql: str) -> list:
        print(f"\n--- {label} ---")
        try:
            rows = pg.execute_query(sql)
        except Exception as exc:
            print(f"  FAILED: {exc}")
            return []
        if not rows:
            print("  (no rows)")
            return []
        for r in rows:
            print(f"  {dict(r) if not isinstance(r, (tuple, list)) else r}")
        return rows

    print("=" * 72)
    print("available_at diagnostic (READ-ONLY)")
    print("=" * 72)

    q("Server time settings", "SHOW TimeZone")
    q("UTC offset right now", "SELECT NOW() AS now_tz, NOW() AT TIME ZONE 'UTC' AS now_utc")

    q(
        "Column types",
        """
        SELECT table_name, column_name, data_type, column_default
        FROM information_schema.columns
        WHERE (table_name = 'research_articles'
               AND column_name IN ('available_at', 'fetched_at', 'published_at'))
           OR (table_name = 'social_metrics'
               AND column_name IN ('available_at', 'created_at'))
        ORDER BY table_name, column_name
        """,
    )

    # The decisive check. If the implicit cast shifted values, the difference between
    # available_at and fetched_at-interpreted-as-UTC is a constant whole-hour offset
    # across the backfilled rows rather than zero.
    q(
        "research_articles: available_at vs fetched_at AT TIME ZONE 'UTC'",
        """
        SELECT
            EXTRACT(EPOCH FROM (available_at - (fetched_at AT TIME ZONE 'UTC')))/3600.0
                AS offset_hours,
            COUNT(*) AS rows
        FROM research_articles
        WHERE available_at IS NOT NULL AND fetched_at IS NOT NULL
        GROUP BY 1
        ORDER BY rows DESC
        LIMIT 10
        """,
    )

    q(
        "social_metrics: available_at vs created_at AT TIME ZONE 'UTC'",
        """
        SELECT
            EXTRACT(EPOCH FROM (available_at - (created_at AT TIME ZONE 'UTC')))/3600.0
                AS offset_hours,
            COUNT(*) AS rows
        FROM social_metrics
        WHERE available_at IS NOT NULL AND created_at IS NOT NULL
        GROUP BY 1
        ORDER BY rows DESC
        LIMIT 10
        """,
    )

    q(
        "NULL available_at (invisible to a bare-column predicate)",
        """
        SELECT
            (SELECT COUNT(*) FROM research_articles WHERE available_at IS NULL)
                AS articles_null_available_at,
            (SELECT COUNT(*) FROM social_metrics WHERE available_at IS NULL)
                AS social_null_available_at
        """,
    )

    # How badly re-scraping inflated fetched_at, i.e. how much real history the
    # conservative backfill hid. Large gaps here are the rows the provenance flag
    # exists to mark.
    q(
        "research_articles: fetched_at long after published_at (re-scrape inflation)",
        """
        SELECT
            width_bucket(
                EXTRACT(EPOCH FROM (fetched_at - published_at))/86400.0,
                0, 720, 6
            ) AS bucket,
            MIN(EXTRACT(EPOCH FROM (fetched_at - published_at))/86400.0) AS min_days,
            MAX(EXTRACT(EPOCH FROM (fetched_at - published_at))/86400.0) AS max_days,
            COUNT(*) AS rows
        FROM research_articles
        WHERE published_at IS NOT NULL
          AND fetched_at IS NOT NULL
          AND fetched_at > published_at
        GROUP BY 1
        ORDER BY 1
        """,
    )

    q(
        "Index usage on the available_at indexes",
        """
        SELECT relname AS table, indexrelname AS index, idx_scan, idx_tup_read
        FROM pg_stat_user_indexes
        WHERE indexrelname IN (
            'idx_research_available_at',
            'idx_research_articles_available_unvalidated',
            'idx_social_metrics_available_at'
        )
        ORDER BY indexrelname
        """,
    )

    print("\n" + "=" * 72)
    print("Interpretation:")
    print("  offset_hours == 0 for ~all rows  -> stored values are correct UTC;")
    print("                                      the corrective migration is enough.")
    print("  offset_hours == a constant != 0  -> the implicit cast shifted the clock;")
    print("                                      available_at needs re-backfilling too.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
