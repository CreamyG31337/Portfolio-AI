#!/usr/bin/env python3
"""
Backfill trade_log.action from reason (infer_trade_action) where action IS NULL.

Run after applying schema/41_add_trade_log_action.sql.

  cd web_dashboard
  python scripts/backfill_trade_log_action.py
  python scripts/backfill_trade_log_action.py --apply --confirm-production --audit-file action_backfill.jsonl

Optional second SQL (after this succeeds):

  ALTER TABLE trade_log ALTER COLUMN action SET DEFAULT 'BUY';
  ALTER TABLE trade_log ALTER COLUMN action SET NOT NULL;
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_WEB_DASH = _REPO_ROOT / "web_dashboard"
sys.path.insert(0, str(_WEB_DASH))
sys.path.insert(0, str(_REPO_ROOT))

from env_loader import load_project_dotenv

load_project_dotenv()

from supabase_client import SupabaseClient
from utils.trade_reason import infer_trade_action

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SCRIPT_NAME = "backfill_trade_log_action"
BATCH = 500


def _fingerprint() -> str:
    url = os.getenv("SUPABASE_URL") or ""
    try:
        return urlparse(url).hostname or url[:60]
    except Exception:
        return url[:60] or "(no SUPABASE_URL)"


def _is_test() -> bool:
    u = (os.getenv("SUPABASE_URL") or "").lower()
    return "localhost" in u or "127.0.0.1" in u or ":5433" in u or "test" in u


def _coerce_action(reason: str | None) -> str:
    a = infer_trade_action(reason, default="BUY")
    if a in ("BUY", "SELL", "DIVIDEND"):
        return a
    return "BUY"


def run() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    p.add_argument("--confirm-production", action="store_true")
    p.add_argument("--audit-file", default="")
    args = p.parse_args()

    logger.info("Supabase: %s", _fingerprint())
    likely_test = _is_test()
    if args.apply and not likely_test and not args.confirm_production:
        logger.error("Refusing --apply without --confirm-production on non-test Supabase.")
        return 3

    supabase = SupabaseClient(use_service_role=True).supabase
    offset = 0
    to_fix: list[dict[str, Any]] = []

    while True:
        res = (
            supabase.table("trade_log")
            .select("id,fund,ticker,reason,action")
            .is_("action", "null")
            .range(offset, offset + BATCH - 1)
            .execute()
        )
        rows = res.data or []
        for r in rows:
            new_a = _coerce_action(r.get("reason"))
            to_fix.append({"id": str(r["id"]), "fund": r.get("fund"), "ticker": r.get("ticker"), "new_action": new_a})
        if len(rows) < BATCH:
            break
        offset += BATCH

    logger.info("Rows with NULL action: %s", len(to_fix))
    if not to_fix:
        return 0

    for r in to_fix[:20]:
        print(f"  id={r['id']} {r.get('ticker')} -> {r['new_action']}")
    if len(to_fix) > 20:
        print(f"  ... and {len(to_fix) - 20} more")

    if not args.apply:
        logger.info("Dry-run only. Use --apply --confirm-production to write.")
        return 0

    audit = open(args.audit_file, "a", encoding="utf-8") if args.audit_file else None
    try:
        for r in to_fix:
            supabase.table("trade_log").update({"action": r["new_action"]}).eq("id", r["id"]).execute()
            if audit:
                audit.write(
                    json.dumps(
                        {
                            "id": r["id"],
                            "fund": r.get("fund"),
                            "ticker": r.get("ticker"),
                            "new_action": r["new_action"],
                            "script": SCRIPT_NAME,
                            "utc_timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                    + "\n"
                )
    finally:
        if audit:
            audit.close()

    logger.info("Updated %s rows.", len(to_fix))
    return 0


if __name__ == "__main__":
    sys.exit(run())
