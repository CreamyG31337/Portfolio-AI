#!/usr/bin/env python3
"""
Mark earliest qualifying BUY per (fund, ticker) with a placeholder reason.

Uses trade_log.action when present (BUY/SELL/DIVIDEND); otherwise infers from reason.

Default fund: Project Chimera. Pass --funds for multiple funds (e.g. Webull accounts).

If you use ``backfill_webull_trade_reasons.py`` next, keep ``--placeholder`` here aligned with
that script's ``--placeholder-reason`` (defaults match).

Default: dry-run. Production writes require --apply and --confirm-production.

Usage (repo root):
  python web_dashboard/scripts/mark_chimera_initial_buys.py
  python web_dashboard/scripts/mark_chimera_initial_buys.py --funds "Project Chimera,RRSP Lance Webull"
  python web_dashboard/scripts/mark_chimera_initial_buys.py --apply --confirm-production
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_WEB_DASH = _REPO_ROOT / "web_dashboard"
sys.path.insert(0, str(_WEB_DASH))
sys.path.insert(0, str(_REPO_ROOT))

from env_loader import load_project_dotenv

load_project_dotenv()

from supabase_client import SupabaseClient
from utils.trade_reason import infer_trade_action

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

CHIMERA_FUND_DEFAULT = "Project Chimera"
PLACEHOLDER_REASON = "Initial buy (rationale pending)"


def _fingerprint_supabase() -> str:
    url = os.getenv("SUPABASE_URL") or ""
    try:
        return urlparse(url).hostname or url[:60]
    except Exception:
        return url[:60] or "(no SUPABASE_URL)"


def _is_likely_test_supabase() -> bool:
    url = (os.getenv("SUPABASE_URL") or "").lower()
    return "localhost" in url or "127.0.0.1" in url or ":5433" in url or "test" in url


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s.replace(" ", "T", 1))


def _is_qualifying_buy(row: Dict[str, Any]) -> bool:
    act = str(row.get("action") or "").strip().upper()
    if act == "DIVIDEND":
        return False
    shares = float(row.get("shares") or 0)
    if shares <= 0:
        return False
    if act == "SELL":
        return False
    if act == "BUY":
        return True
    reason = str(row.get("reason") or "")
    rlow = reason.lower()
    if "drip" in rlow or "dividend reinvest" in rlow:
        return False
    return infer_trade_action(reason, default="BUY") == "BUY"


def _fetch_fund_trades(supabase: Any, fund: str) -> List[Dict[str, Any]]:
    page_size = 1000
    offset = 0
    out: List[Dict[str, Any]] = []
    while True:
        q = (
            supabase.table("trade_log")
            .select("id,fund,ticker,date,reason,shares,action")
            .eq("fund", fund)
            .order("date")
            .range(offset, offset + page_size - 1)
        )
        res = q.execute()
        batch = res.data or []
        out.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return out


def run() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--funds",
        default="",
        help=f"Comma-separated funds (default: {CHIMERA_FUND_DEFAULT!r})",
    )
    p.add_argument(
        "--fund",
        default="",
        help="Single fund; ignored if --funds is non-empty",
    )
    p.add_argument("--placeholder", default=PLACEHOLDER_REASON)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--confirm-production", action="store_true")
    p.add_argument("--audit-file", default="")
    args = p.parse_args()

    logger.info("Supabase host fingerprint: %s", _fingerprint_supabase())
    likely_test = _is_likely_test_supabase()
    if likely_test:
        logger.info("Heuristic: SUPABASE_URL looks like test/local.")
    else:
        logger.warning("Heuristic: non-test Supabase — treat as production.")

    if args.apply and not likely_test and not args.confirm_production:
        logger.error("Refusing --apply without --confirm-production on non-test Supabase URL.")
        return 3

    if args.funds.strip():
        funds = tuple(f.strip() for f in args.funds.split(",") if f.strip())
    elif args.fund.strip():
        funds = (args.fund.strip(),)
    else:
        funds = (CHIMERA_FUND_DEFAULT,)

    supabase = SupabaseClient(use_service_role=True).supabase
    to_update: List[Dict[str, Any]] = []
    for fund in funds:
        rows = _fetch_fund_trades(supabase, fund)
        if not rows:
            logger.info("No trade_log rows for fund %r.", fund)
            continue

        by_ticker: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            t = str(r.get("ticker") or "")
            by_ticker.setdefault(t, []).append(r)

        initial: Dict[str, Dict[str, Any]] = {}
        for ticker, lst in by_ticker.items():
            buys = [x for x in lst if _is_qualifying_buy(x)]
            if not buys:
                continue
            buys.sort(key=lambda x: _parse_ts(x["date"]))
            initial[ticker] = buys[0]

        for ticker, row in sorted(initial.items(), key=lambda kv: kv[0]):
            rid = row["id"]
            old = str(row.get("reason") or "")
            if old == args.placeholder:
                continue
            to_update.append(
                {
                    "id": rid,
                    "fund": fund,
                    "ticker": ticker,
                    "date": row.get("date"),
                    "old_reason": old,
                }
            )

    if not to_update:
        logger.info("No qualifying initial buys to update (or all already placeholder).")
        return 0

    print("Planned updates (dry-run unless --apply):")
    for u in to_update:
        print(f"  fund={u['fund']!r} id={u['id']} ticker={u['ticker']} date={u['date']}")
        print(f"    old: {u['old_reason'][:120]}{'...' if len(u['old_reason']) > 120 else ''}")
        print(f"    new: {args.placeholder}")
        print("  ---")

    print(f"Total rows to update: {len(to_update)}")

    if not args.apply:
        logger.info("Dry-run complete. No writes.")
        return 0

    audit = open(args.audit_file, "a", encoding="utf-8") if args.audit_file else None
    try:
        for u in to_update:
            if audit:
                audit.write(
                    json.dumps(
                        {
                            "id": str(u["id"]),
                            "fund": u["fund"],
                            "ticker": u["ticker"],
                            "old_reason": u["old_reason"],
                            "new_reason": args.placeholder,
                            "script": "mark_chimera_initial_buys",
                            "utc_timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                    + "\n"
                )
            supabase.table("trade_log").update({"reason": args.placeholder, "action": "BUY"}).eq("id", str(u["id"])).eq(
                "reason", u["old_reason"]
            ).execute()
    finally:
        if audit:
            audit.close()

    logger.info("Apply complete: %s rows updated.", len(to_update))
    return 0


if __name__ == "__main__":
    sys.exit(run())
