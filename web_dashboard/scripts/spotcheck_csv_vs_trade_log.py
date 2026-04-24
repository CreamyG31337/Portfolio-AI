#!/usr/bin/env python3
"""
Compare improved_reasons_from_chat.csv to trade_log for tickers NOT in the Webull audit JSONL.

Run from repo root or web_dashboard (script fixes sys.path):

  cd web_dashboard
  python scripts/spotcheck_csv_vs_trade_log.py --fund "RRSP Lance Webull" \\
      --csv scripts/improved_reasons_from_chat.csv

Needs SUPABASE_URL + service role key env vars (same as other admin scripts).

Optional:
  --audit ../../webull_trade_reason_backfill_audit.jsonl   (default: repo root)
  --tickers ETN,TSM     (subset only)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

# Allow `python web_dashboard/scripts/spotcheck_...py` from repo root
_WEB_DASH = Path(__file__).resolve().parent.parent
if str(_WEB_DASH) not in sys.path:
    sys.path.insert(0, str(_WEB_DASH))

from supabase_client import SupabaseClient  # noqa: E402


def _load_audit_tickers(audit_path: Path | None) -> set[str]:
    if not audit_path or not audit_path.is_file():
        return set()
    out: set[str] = set()
    with audit_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.add(json.loads(line)["ticker"])
    return out


def _load_csv(path: Path) -> dict[str, tuple[str, str]]:
    """ticker -> (date_cell, reason)"""
    out: dict[str, tuple[str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            t = row["ticker"].strip()
            out[t] = (row["date"].strip(), row["reason"].strip())
    return out


def _fetch_rows(supabase: Any, fund: str, tickers: list[str]) -> list[dict[str, Any]]:
    if not tickers:
        return []
    res = (
        supabase.table("trade_log")
        .select("id,fund,ticker,date,reason")
        .eq("fund", fund)
        .in_("ticker", tickers)
        .order("date", desc=True)
        .execute()
    )
    return res.data or []


def main() -> int:
    ap = argparse.ArgumentParser(description="Spot-check CSV reasons vs trade_log (non-audit tickers).")
    ap.add_argument("--fund", required=True, help="Fund name (exact trade_log.fund value)")
    ap.add_argument("--csv", type=Path, required=True, help="Path to improved_reasons_from_chat.csv")
    ap.add_argument(
        "--audit",
        type=Path,
        default=None,
        help="webull_trade_reason_backfill_audit.jsonl (default: <repo>/webull_trade_reason_backfill_audit.jsonl)",
    )
    ap.add_argument("--tickers", default="", help="Comma-separated subset; default = all CSV tickers not in audit")
    args = ap.parse_args()

    repo_root = _WEB_DASH.parent
    audit_path = args.audit
    if audit_path is None:
        audit_path = repo_root / "webull_trade_reason_backfill_audit.jsonl"

    csv_map = _load_csv(args.csv.resolve())
    audit_resolved = audit_path.resolve() if audit_path else None
    audited = _load_audit_tickers(audit_resolved)
    if audit_resolved and not audit_resolved.is_file():
        print(f"Note: audit file not found at {audit_resolved} — not skipping any CSV tickers.", file=sys.stderr)

    if args.tickers.strip():
        want_set = {t.strip().upper() for t in args.tickers.split(",") if t.strip()}
        tickers = sorted([t for t in csv_map if t.upper() in want_set])
    else:
        tickers = sorted(set(csv_map) - audited)

    if not tickers:
        print("No tickers to check.", file=sys.stderr)
        return 1

    if not os.getenv("SUPABASE_URL"):
        print("SUPABASE_URL not set.", file=sys.stderr)
        return 2

    client = SupabaseClient(use_service_role=True)
    rows = _fetch_rows(client.supabase, args.fund, tickers)
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_ticker.setdefault(r["ticker"], []).append(r)

    print(f"Fund: {args.fund}")
    print(f"CSV: {args.csv}")
    print(f"Audit file (skip tickers): {audit_path} ({len(audited)} tickers)" if audit_path else "No audit skip")
    print(f"Tickers requested: {len(tickers)}")
    print("-" * 80)

    for t in tickers:
        csv_date, csv_reason = csv_map.get(t, ("?", "?"))
        db_list = by_ticker.get(t, [])
        if not db_list:
            print(f"{t}\tNO ROWS in trade_log for this fund")
            print(f"  csv_date={csv_date}")
            print(f"  csv_reason={csv_reason[:120]}{'…' if len(csv_reason) > 120 else ''}")
            print()
            continue
        for r in db_list:
            db_reason = (r.get("reason") or "").strip()
            same = db_reason == csv_reason
            flag = "MATCH" if same else "DIFF"
            print(f"{t}\t{flag}\tid={r.get('id')}\tdate={r.get('date')}")
            print(f"  csv_date(cell)={csv_date}")
            if same:
                print(f"  reason: {db_reason[:160]}{'…' if len(db_reason) > 160 else ''}")
            else:
                print(f"  CSV:  {csv_reason[:200]}{'…' if len(csv_reason) > 200 else ''}")
                print(f"  DB:   {db_reason[:200]}{'…' if len(db_reason) > 200 else ''}")
            print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
