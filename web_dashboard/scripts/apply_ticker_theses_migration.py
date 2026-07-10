#!/usr/bin/env python3
"""Apply database/migrations/2026-07_add_ticker_theses.sql to the Research DB."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_WEB_DASHBOARD = _SCRIPT_DIR.parent
_REPO_ROOT = _WEB_DASHBOARD.parent
for p in (str(_WEB_DASHBOARD), str(_REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

MIGRATION_FILE = _REPO_ROOT / "database" / "migrations" / "2026-07_add_ticker_theses.sql"
TABLES = ("ticker_theses", "thesis_entries", "thesis_evidence")


def main() -> int:
    apply = "--apply" in sys.argv

    from postgres_client import PostgresClient

    pg = PostgresClient()

    def table_status() -> dict[str, bool]:
        rows = pg.execute_query(
            "SELECT t.name, to_regclass('public.' || t.name) IS NOT NULL AS exists "
            "FROM unnest(%s::text[]) AS t(name)",
            (list(TABLES),),
        )
        return {r["name"]: r["exists"] for r in rows}

    before = table_status()
    print("Table status (Research DB):")
    for name, exists in before.items():
        print(f"  {name}: {'EXISTS' if exists else 'missing'}")

    if not apply:
        print("\nCheck-only mode. Re-run with --apply to execute the migration.")
        return 0

    sql_text = MIGRATION_FILE.read_text(encoding="utf-8")
    print(f"\nApplying {MIGRATION_FILE.name} ({len(sql_text)} bytes)...")
    pg.execute_update(sql_text)

    after = table_status()
    missing = [name for name, exists in after.items() if not exists]
    if missing:
        print(f"FAILED: tables still missing after apply: {missing}")
        return 1

    print("All Insights tables present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
