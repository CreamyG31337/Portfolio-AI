#!/usr/bin/env python3
"""Apply database/migrations/2026-07_add_stance_outcome_attempts.sql to the Research DB.

Measurement rig M1: adds the scoring dead-letter table and securities.price_symbol.
Additive only (CREATE TABLE IF NOT EXISTS + ADD COLUMN IF NOT EXISTS); safe to re-run.
Default mode is a read-only check; pass --apply to execute.

The stance_outcomes job REQUIRES this migration -- select_unscored_stances joins
stance_outcome_attempts, so the job will fail until it is applied.

Usage:
    python web_dashboard/scripts/apply_stance_outcome_attempts_migration.py          # check only
    python web_dashboard/scripts/apply_stance_outcome_attempts_migration.py --apply  # run migration
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
    _REPO_ROOT / "database" / "migrations" / "2026-07_add_stance_outcome_attempts.sql"
)


def main() -> int:
    apply = "--apply" in sys.argv

    from postgres_client import PostgresClient

    pg = PostgresClient()

    def status() -> dict[str, bool]:
        table = pg.execute_query(
            "SELECT to_regclass('public.stance_outcome_attempts') IS NOT NULL AS ok"
        )
        column = pg.execute_query(
            "SELECT COUNT(*) > 0 AS ok FROM information_schema.columns "
            "WHERE table_name = 'securities' AND column_name = 'price_symbol'"
        )
        return {
            "stance_outcome_attempts": bool(table[0]["ok"]) if table else False,
            "securities.price_symbol": bool(column[0]["ok"]) if column else False,
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
    print("Migration applied; both objects present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
