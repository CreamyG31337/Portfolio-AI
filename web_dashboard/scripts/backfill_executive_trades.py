#!/usr/bin/env python3
"""
One-time backfill of executive trades from Open Cabinet JSON.

Uses cache + securities lookup first; optional --use-yfinance for unresolved rows.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

WEB_DASHBOARD_PATH = Path(__file__).resolve().parents[1]
PROJECT_ROOT = WEB_DASHBOARD_PATH.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(WEB_DASHBOARD_PATH))

from dotenv import load_dotenv

from scheduler.jobs_executive import (  # noqa: E402
    TRUMP_BIOGUIDE_ID,
    TRUMP_OPEN_CABINET_URL,
    fetch_open_cabinet_transactions,
    process_executive_transactions,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

load_dotenv("web_dashboard/.env")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=TRUMP_OPEN_CABINET_URL)
    parser.add_argument("--dry-run", action="store_true", help="Resolve only; do not write")
    parser.add_argument(
        "--use-yfinance",
        action="store_true",
        help="Enable yfinance fallback for unresolved corporate names",
    )
    args = parser.parse_args()

    from supabase_client import SupabaseClient

    client = SupabaseClient(use_service_role=True)
    politician_row = (
        client.supabase.table("politicians")
        .select("id, party, state")
        .eq("bioguide_id", TRUMP_BIOGUIDE_ID)
        .limit(1)
        .execute()
    )
    if not politician_row.data:
        raise SystemExit(
            f"Politician {TRUMP_BIOGUIDE_ID} not found. "
            "Apply database/schema/supabase/migrations/add_executive_trades_support.sql"
        )

    politician_id = int(politician_row.data[0]["id"])
    party = politician_row.data[0].get("party")
    state = politician_row.data[0].get("state")

    transactions = fetch_open_cabinet_transactions(args.source)
    stats = process_executive_transactions(
        client,
        transactions,
        politician_id=politician_id,
        party=party,
        state=state,
        use_yfinance=args.use_yfinance,
        dry_run=args.dry_run,
    )

    logger.info("Backfill complete (dry_run=%s)", args.dry_run)
    for key, value in stats.items():
        logger.info("  %s: %s", key, value)


if __name__ == "__main__":
    main()
