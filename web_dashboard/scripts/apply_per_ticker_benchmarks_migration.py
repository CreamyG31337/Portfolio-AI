#!/usr/bin/env python3
"""Apply database/migrations/2026-07_add_per_ticker_benchmarks.sql to the Research DB.

Measurement rig M2a: adds securities.market_cap / benchmark_override and
stance_outcomes.benchmark_symbol / scoring_version.

Additive only (ADD COLUMN IF NOT EXISTS); safe to re-run. Default mode is a
read-only check; pass --apply to execute.

Usage:
    python web_dashboard/scripts/apply_per_ticker_benchmarks_migration.py          # check
    python web_dashboard/scripts/apply_per_ticker_benchmarks_migration.py --apply  # run
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
    _REPO_ROOT / "database" / "migrations" / "2026-07_add_per_ticker_benchmarks.sql"
)

EXPECTED = (
    ("securities", "market_cap"),
    ("securities", "market_cap_set_at"),
    ("securities", "benchmark_override"),
    ("stance_outcomes", "benchmark_symbol"),
    ("stance_outcomes", "scoring_version"),
)


def main() -> int:
    apply = "--apply" in sys.argv

    from postgres_client import PostgresClient

    pg = PostgresClient()

    def status() -> dict[str, bool]:
        out: dict[str, bool] = {}
        for table, column in EXPECTED:
            rows = pg.execute_query(
                "SELECT COUNT(*) > 0 AS ok FROM information_schema.columns "
                "WHERE table_name = %s AND column_name = %s",
                (table, column),
            )
            out[f"{table}.{column}"] = bool(rows[0]["ok"]) if rows else False
        return out

    print("Schema status (Research DB):")
    for name, ok in status().items():
        print(f"  {name}: {'EXISTS' if ok else 'missing'}")

    if not apply:
        print("\nCheck-only mode. Re-run with --apply to execute the migration.")
        return 0

    sql_text = MIGRATION_FILE.read_text(encoding="utf-8")
    print(f"\nApplying {MIGRATION_FILE.name} ({len(sql_text)} bytes)...")
    pg.execute_update(sql_text)

    missing = [name for name, ok in status().items() if not ok]
    if missing:
        print(f"FAILED: still missing after apply: {missing}")
        return 1
    print("Migration applied; all columns present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
