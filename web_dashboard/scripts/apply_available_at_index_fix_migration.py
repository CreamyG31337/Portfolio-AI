#!/usr/bin/env python3
"""Apply database/migrations/2026-08_fix_available_at_index_and_provenance.sql.

Replaces the unusable plain-column available_at indexes with expression indexes that
match the predicate pit_time actually emits, drops the indexes nothing queries, and
adds the available_at_is_estimated risk flag.

Run the read-only diagnostic first:
    python web_dashboard/scripts/diagnose_available_at_state.py

Usage:
    python web_dashboard/scripts/apply_available_at_index_fix_migration.py
    python web_dashboard/scripts/apply_available_at_index_fix_migration.py --apply
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_WEB_DASHBOARD = _SCRIPT_DIR.parent
_REPO_ROOT = _WEB_DASHBOARD.parent
for p in (str(_WEB_DASHBOARD), str(_REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

MIGRATION_FILE = (
    _REPO_ROOT
    / "database"
    / "migrations"
    / "2026-08_fix_available_at_index_and_provenance.sql"
)

_NEW_INDEXES = ["idx_research_articles_as_of", "idx_social_metrics_ticker_as_of"]
_DROPPED_INDEXES = [
    "idx_research_available_at",
    "idx_social_metrics_available_at",
    "idx_research_articles_available_unvalidated",
]


def main() -> int:
    apply = "--apply" in sys.argv
    from postgres_client import PostgresClient

    pg = PostgresClient()

    def index_names() -> set[str]:
        rows = pg.execute_query(
            "SELECT indexname FROM pg_indexes WHERE indexname = ANY(%s)",
            (_NEW_INDEXES + _DROPPED_INDEXES,),
        )
        return {r["indexname"] for r in (rows or [])}

    def flag_exists() -> bool:
        rows = pg.execute_query(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'research_articles'
              AND column_name = 'available_at_is_estimated'
            """
        )
        return bool(rows)

    def report() -> None:
        present = index_names()
        print("Indexes:")
        for name in _NEW_INDEXES:
            print(f"  {name}: {'EXISTS' if name in present else 'missing'}  (wanted)")
        for name in _DROPPED_INDEXES:
            print(f"  {name}: {'STILL PRESENT' if name in present else 'dropped'}  (unwanted)")
        print(f"research_articles.available_at_is_estimated: "
              f"{'EXISTS' if flag_exists() else 'missing'}")

    print("Schema status (Research DB):")
    report()

    if not apply:
        print("\nCheck-only mode. Re-run with --apply to execute the migration.")
        return 0

    sql_text = MIGRATION_FILE.read_text(encoding="utf-8")
    print(f"\nApplying {MIGRATION_FILE.name}...")
    pg.execute_update(sql_text)

    print("\nPost-migration status:")
    report()

    present = index_names()
    problems = [n for n in _NEW_INDEXES if n not in present]
    problems += [f"{n} (not dropped)" for n in _DROPPED_INDEXES if n in present]
    if not flag_exists():
        problems.append("available_at_is_estimated (missing)")
    if problems:
        print(f"\nFAILED: {problems}")
        return 1

    flagged = pg.execute_query(
        "SELECT COUNT(*) AS n FROM research_articles WHERE available_at_is_estimated"
    )
    print(f"\nRows flagged as likely-overstated available_at: {flagged[0]['n']}")
    print("Migration applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
