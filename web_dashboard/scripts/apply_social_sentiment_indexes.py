#!/usr/bin/env python3
"""Apply database/migrations/2026-08_social_sentiment_pipeline_indexes.sql.

Every statement is CREATE INDEX CONCURRENTLY, which Postgres refuses to run
inside a transaction block. PostgresClient.get_connection() commits as one
transaction, so this migration needs its own autocommit runner rather than the
usual execute_update(whole_file) pattern.

Safe to re-run: every statement is IF NOT EXISTS, and CONCURRENTLY means no
table is locked against reads or writes while an index builds.

Usage:
    python web_dashboard/scripts/apply_social_sentiment_indexes.py          # check
    python web_dashboard/scripts/apply_social_sentiment_indexes.py --apply  # run
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_WEB_DASHBOARD = _SCRIPT_DIR.parent
_REPO_ROOT = _WEB_DASHBOARD.parent
for p in (str(_WEB_DASHBOARD), str(_REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

MIGRATION_FILE = (
    _REPO_ROOT / "database" / "migrations" / "2026-08_social_sentiment_pipeline_indexes.sql"
)

EXPECTED_INDEXES = (
    "uq_social_posts_platform_post_id",
    "idx_social_posts_unassigned",
    "idx_social_posts_session_id",
    "idx_social_posts_metric_id",
    "idx_sentiment_sessions_ticker_day",
    "idx_sentiment_sessions_pending",
    "idx_social_sentiment_analysis_analyzed_at",
    "idx_extracted_tickers_analysis_id",
    "uq_social_sentiment_analysis_session",
)

EXPECTED_COLUMNS = (("social_posts", "session_id"),)


def _statements(sql_text: str) -> list[str]:
    """Split the migration into individual statements, dropping comments."""
    without_comments = "\n".join(
        line for line in sql_text.splitlines() if not line.strip().startswith("--")
    )
    return [s.strip() for s in without_comments.split(";") if s.strip()]


def main() -> int:
    apply = "--apply" in sys.argv

    from postgres_client import PostgresClient

    pg = PostgresClient()

    def status() -> dict[str, bool]:
        rows = pg.execute_query(
            "SELECT indexname FROM pg_indexes WHERE indexname = ANY(%s)",
            (list(EXPECTED_INDEXES),),
        )
        present = {r["indexname"] for r in rows}
        return {name: name in present for name in EXPECTED_INDEXES}

    def column_status() -> dict[str, bool]:
        out: dict[str, bool] = {}
        for table, column in EXPECTED_COLUMNS:
            rows = pg.execute_query(
                "SELECT COUNT(*) > 0 AS ok FROM information_schema.columns "
                "WHERE table_name = %s AND column_name = %s",
                (table, column),
            )
            out[f"{table}.{column}"] = bool(rows[0]["ok"]) if rows else False
        return out

    print("Schema status (Research DB):")
    for name, ok in column_status().items():
        print(f"  {name}: {'EXISTS' if ok else 'missing'}")

    print("\nIndex status (Research DB):")
    for name, ok in status().items():
        print(f"  {name}: {'EXISTS' if ok else 'missing'}")

    if not apply:
        print("\nCheck-only mode. Re-run with --apply to execute the migration.")
        return 0

    statements = _statements(MIGRATION_FILE.read_text(encoding="utf-8"))
    print(f"\nApplying {MIGRATION_FILE.name}: {len(statements)} statement(s)\n")

    failures: list[str] = []
    with pg.get_connection() as conn:
        # CREATE INDEX CONCURRENTLY cannot run in a transaction block.
        previous_autocommit = conn.autocommit
        conn.autocommit = True
        try:
            for stmt in statements:
                label = re.sub(r"\s+", " ", stmt)[:80]
                started = time.time()
                try:
                    with conn.cursor() as cur:
                        cur.execute(stmt)
                    print(f"  ok   ({time.time() - started:5.1f}s) {label}")
                except Exception as exc:
                    failures.append(f"{label}: {exc}")
                    print(f"  FAIL ({time.time() - started:5.1f}s) {label}\n         {exc}")
        finally:
            conn.autocommit = previous_autocommit

    print("\nFinal schema status:")
    for name, ok in column_status().items():
        print(f"  {name}: {'EXISTS' if ok else 'MISSING'}")
    print("Final index status:")
    for name, ok in status().items():
        print(f"  {name}: {'EXISTS' if ok else 'MISSING'}")

    if failures:
        print(f"\nFAILED: {len(failures)} statement(s) did not apply.")
        return 1

    # A CONCURRENTLY build that fails partway leaves an invalid index behind.
    invalid = pg.execute_query(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_index i ON i.indexrelid = c.oid
        WHERE NOT i.indisvalid AND c.relname = ANY(%s)
        """,
        (list(EXPECTED_INDEXES),),
    )
    if invalid:
        print(f"\nWARNING: invalid index left behind: {[r['relname'] for r in invalid]}")
        print("Drop and re-create those before relying on them.")
        return 1

    print("\nMigration applied; all indexes present and valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
