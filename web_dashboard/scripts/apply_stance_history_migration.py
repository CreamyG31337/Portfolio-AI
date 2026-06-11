#!/usr/bin/env python3
"""Apply database/migrations/2026-06_add_stance_history_and_outcomes.sql to the Research DB.

Additive-only migration (CREATE TABLE IF NOT EXISTS x3 + indexes). Default mode
is a read-only check; pass --apply to execute. Verifies table presence and the
ticker column width after applying.

Usage:
    python web_dashboard/scripts/apply_stance_history_migration.py          # check only
    python web_dashboard/scripts/apply_stance_history_migration.py --apply  # run migration
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

MIGRATION_FILE = _REPO_ROOT / "database" / "migrations" / "2026-06_add_stance_history_and_outcomes.sql"
TABLES = ("stance_history", "stance_outcomes", "idea_triage")


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

    width_rows = pg.execute_query(
        "SELECT character_maximum_length AS len FROM information_schema.columns "
        "WHERE table_name = 'stance_history' AND column_name = 'ticker'"
    )
    ticker_len = width_rows[0]["len"] if width_rows else None
    print("All three tables present.")
    print(f"stance_history.ticker width: {ticker_len} (expected 20)")
    return 0 if ticker_len == 20 else 1


if __name__ == "__main__":
    sys.exit(main())
