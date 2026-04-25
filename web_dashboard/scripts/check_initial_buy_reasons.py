#!/usr/bin/env python3
"""
Report earliest qualifying BUY per ticker for a fund: which still need real reasons.

Uses the same eligibility rules as mark_chimera_initial_buys.py (action + shares + DRIP skip).

Flags as "incomplete":
  - empty reason
  - exact placeholder (default: Initial buy (rationale pending))
  - reason starting with "Imported from Webull"
  - broker/email stubs (see utils.trade_reason.is_boilerplate_buy_rationale)

Usage (repo root):
  python web_dashboard/scripts/check_initial_buy_reasons.py
  python web_dashboard/scripts/check_initial_buy_reasons.py --fund "Project Chimera"
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_WEB_DASH = _REPO_ROOT / "web_dashboard"
sys.path.insert(0, str(_WEB_DASH))
sys.path.insert(0, str(_REPO_ROOT))

from env_loader import load_project_dotenv

load_project_dotenv()

from mark_chimera_initial_buys import (  # noqa: E402
    CHIMERA_FUND_DEFAULT,
    PLACEHOLDER_REASON,
    _fetch_fund_trades,
    _is_qualifying_buy,
    _parse_ts,
)
from supabase_client import SupabaseClient  # noqa: E402
from utils.trade_reason import is_boilerplate_buy_rationale  # noqa: E402

WEBULL_PREFIX = "Imported from Webull"


def _classify(reason: str, *, placeholder: str) -> str:
    s = (reason or "").strip()
    if not s:
        return "empty"
    if s == placeholder.strip():
        return "placeholder"
    if s.startswith(WEBULL_PREFIX):
        return "webull_import"
    if is_boilerplate_buy_rationale(s):
        return "boilerplate"
    return "ok"


def _initial_buys_for_fund(supabase: Any, fund: str) -> Dict[str, Dict[str, Any]]:
    rows = _fetch_fund_trades(supabase, fund)
    by_ticker: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        t = str(r.get("ticker") or "")
        if t:
            by_ticker[t].append(r)
    initial: Dict[str, Dict[str, Any]] = {}
    for ticker, lst in by_ticker.items():
        buys = [x for x in lst if _is_qualifying_buy(x)]
        if not buys:
            continue
        buys.sort(key=lambda x: _parse_ts(x["date"]))
        initial[ticker] = buys[0]
    return initial


def run() -> int:
    p = argparse.ArgumentParser(description="List initial BUY rows and reason completeness.")
    p.add_argument("--fund", default=CHIMERA_FUND_DEFAULT)
    p.add_argument("--placeholder", default=PLACEHOLDER_REASON)
    p.add_argument("--json", action="store_true", help="Print machine-readable summary only")
    args = p.parse_args()
    fund = args.fund.strip()
    if not fund:
        print("Empty --fund", file=sys.stderr)
        return 2

    supabase = SupabaseClient(use_service_role=True).supabase
    initial = _initial_buys_for_fund(supabase, fund)
    if not initial:
        print(f"No qualifying initial BUY rows for fund {fund!r}.")
        return 0

    ph = (args.placeholder or "").strip()
    buckets: Dict[str, List[Tuple[str, Dict[str, Any], str]]] = defaultdict(list)
    for ticker in sorted(initial.keys()):
        row = initial[ticker]
        reason = str(row.get("reason") or "")
        cat = _classify(reason, placeholder=ph)
        buckets[cat].append((ticker, row, reason))

    incomplete = (
        len(buckets["empty"])
        + len(buckets["placeholder"])
        + len(buckets["webull_import"])
        + len(buckets["boilerplate"])
    )
    summary = {
        "fund": fund,
        "initial_buy_tickers": len(initial),
        "ok": len(buckets["ok"]),
        "incomplete": incomplete,
        "by_category": {k: len(v) for k, v in buckets.items()},
    }

    if args.json:
        out_rows = []
        for cat in sorted(buckets.keys()):
            for ticker, row, reason in sorted(buckets[cat], key=lambda x: x[0]):
                out_rows.append(
                    {
                        "category": cat,
                        "ticker": ticker,
                        "id": row.get("id"),
                        "date": row.get("date"),
                        "reason_preview": reason[:200],
                    }
                )
        print(json.dumps({"summary": summary, "rows": out_rows}, indent=2))
        return 0

    print(f"Fund: {fund}")
    print(f"Earliest qualifying BUY tickers: {len(initial)}")
    print(f"  OK (substantive reason):    {len(buckets['ok'])}")
    print(f"  Broker/email boilerplate:   {len(buckets['boilerplate'])}")
    print(f"  Placeholder:                {len(buckets['placeholder'])}")
    print(f"  Webull import text:         {len(buckets['webull_import'])}")
    print(f"  Empty reason:               {len(buckets['empty'])}")
    print(f"  --- Incomplete total:       {incomplete}")
    print()

    for label, key in (
        ("Broker/email boilerplate", "boilerplate"),
        ("Placeholder", "placeholder"),
        ("Webull import", "webull_import"),
        ("Empty", "empty"),
    ):
        items = buckets[key]
        if not items:
            continue
        print(f"{label} ({len(items)}):")
        for ticker, row, reason in sorted(items, key=lambda x: x[0]):
            rid = row.get("id")
            d = row.get("date")
            prev = (reason[:100] + "…") if len(reason) > 100 else reason
            print(f"  {ticker:12} id={rid} date={d}")
            if prev:
                print(f"               {prev!r}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(run())
