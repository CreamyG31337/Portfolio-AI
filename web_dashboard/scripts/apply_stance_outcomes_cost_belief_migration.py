#!/usr/bin/env python3
"""Apply database/migrations/2026-08_add_stance_outcomes_cost_belief.sql.

Usage:
    python web_dashboard/scripts/apply_stance_outcomes_cost_belief_migration.py
    python web_dashboard/scripts/apply_stance_outcomes_cost_belief_migration.py --apply
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
    _REPO_ROOT / "database" / "migrations" / "2026-08_add_stance_outcomes_cost_belief.sql"
)


def main() -> int:
    apply = "--apply" in sys.argv
    from postgres_client import PostgresClient

    pg = PostgresClient()

    def status() -> dict[str, bool]:
        cols = pg.execute_query(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'stance_outcomes'
              AND column_name = ANY(%s)
            """,
            (["cost_bps", "excess_after_cost", "belief_status"],),
        )
        found = {r["column_name"] for r in (cols or [])}
        return {
            "stance_outcomes.cost_bps": "cost_bps" in found,
            "stance_outcomes.excess_after_cost": "excess_after_cost" in found,
            "stance_outcomes.belief_status": "belief_status" in found,
        }

    print("Schema status (Research DB):")
    for name, ok in status().items():
        print(f"  {name}: {'EXISTS' if ok else 'missing'}")

    if not apply:
        print("\nCheck-only mode. Re-run with --apply to execute the migration.")
        return 0

    sql_text = MIGRATION_FILE.read_text(encoding="utf-8")
    print(f"\nApplying {MIGRATION_FILE.name}...")
    pg.execute_update(sql_text)
    missing = [n for n, ok in status().items() if not ok]
    if missing:
        print(f"FAILED: still missing: {missing}")
        return 1
    print("Migration applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
