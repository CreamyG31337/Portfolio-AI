#!/usr/bin/env python3
"""Apply database/migrations/2026-07_add_story_corroboration.sql to the Research DB.

Phase I1: adds corroboration_count + corroboration_sources on research_articles.
Additive only; safe to re-run. Default is check-only; pass --apply to execute.

Usage:
    python web_dashboard/scripts/apply_story_corroboration_migration.py
    python web_dashboard/scripts/apply_story_corroboration_migration.py --apply
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

MIGRATION_FILE = _REPO_ROOT / "database" / "migrations" / "2026-07_add_story_corroboration.sql"


def main() -> int:
    apply = "--apply" in sys.argv

    from postgres_client import PostgresClient

    pg = PostgresClient()

    def status() -> dict[str, bool]:
        rows = pg.execute_query(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'research_articles'
              AND column_name IN ('corroboration_count', 'corroboration_sources')
            """
        )
        present = {r["column_name"] for r in (rows or [])}
        return {
            "research_articles.corroboration_count": "corroboration_count" in present,
            "research_articles.corroboration_sources": "corroboration_sources" in present,
        }

    print("Schema status (Research DB):")
    for name, ok in status().items():
        print(f"  {name}: {'EXISTS' if ok else 'missing'}")

    if not apply:
        print("\nCheck-only mode. Re-run with --apply to execute the migration.")
        return 0

    sql_text = MIGRATION_FILE.read_text(encoding="utf-8")
    print(f"\nApplying {MIGRATION_FILE.name} ({len(sql_text)} bytes)...")
    pg.execute_update(sql_text)

    after = status()
    missing = [name for name, ok in after.items() if not ok]
    if missing:
        print(f"FAILED: still missing after apply: {missing}")
        return 1
    print("Migration applied; corroboration columns present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
