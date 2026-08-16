#!/usr/bin/env python3
"""Export fund trade_log / portfolio_positions / performance_metrics to JSON.

Phase 0 safety net for MNST split work. Paginate at 1000 rows (PostgREST cap).

Usage:
  .\\venv\\Scripts\\python.exe debug\\export_fund_snapshot.py
  .\\venv\\Scripts\\python.exe debug\\export_fund_snapshot.py --funds "RRSP Lance Webull" "TFSA"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "web_dashboard"))

from web_dashboard.supabase_client import SupabaseClient  # noqa: E402
from web_dashboard.supabase_pagination import fetch_all_rows  # noqa: E402


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def export_fund(client: SupabaseClient, fund: str, out_dir: Path) -> dict[str, int]:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe = fund.replace(" ", "_")
    counts: dict[str, int] = {}

    datasets = [
        (
            "trade_log",
            "*",
            [("fund", "eq", fund)],
            "date",
            None,
        ),
        (
            "portfolio_positions",
            "*",
            [("fund", "eq", fund), ("date_only", "gte", "2025-09-01")],
            "date_only",
            "ticker",
        ),
        (
            "performance_metrics",
            "*",
            [("fund", "eq", fund), ("date", "gte", "2025-09-01")],
            "date",
            None,
        ),
    ]

    for table, select, filters, order, order_secondary in datasets:
        rows = fetch_all_rows(
            client,
            table,
            select,
            filters=filters,
            order=order,
            order_secondary=order_secondary,
        )
        path = out_dir / f"{safe}_{table}_{ts}.json"
        payload = {
            "fund": fund,
            "table": table,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "filters": filters,
            "row_count": len(rows),
            "rows": rows,
        }
        path.write_text(json.dumps(payload, default=_json_default), encoding="utf-8")
        size = path.stat().st_size
        print(f"  Wrote {path.name}: {len(rows)} rows, {size:,} bytes")
        if size == 0:
            raise RuntimeError(f"Empty export file: {path}")
        counts[table] = len(rows)

    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--funds",
        nargs="+",
        default=["RRSP Lance Webull", "TFSA"],
        help="Fund names to export",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=project_root / "debug" / "backups",
    )
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    client = SupabaseClient(use_service_role=True)
    summary: dict[str, dict[str, int]] = {}

    for fund in args.funds:
        print(f"\nExporting {fund} ...")
        summary[fund] = export_fund(client, fund, args.out_dir)

    print("\n=== Export summary ===")
    for fund, counts in summary.items():
        print(f"{fund}: {counts}")

    # Hard asserts from plan (trade counts are stable; position counts may grow daily)
    expected_trades = {"RRSP Lance Webull": 89, "TFSA": 208}
    for fund, expected in expected_trades.items():
        if fund in summary and summary[fund].get("trade_log") != expected:
            raise SystemExit(
                f"FAIL: {fund} trade_log count {summary[fund].get('trade_log')} "
                f"!= expected {expected}"
            )

    print("\nTrade-log row counts match expected. Position/metric counts recorded above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
