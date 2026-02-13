#!/usr/bin/env python3
"""
Small test run of congress trade returns computation.
Tests with just 10 trades to verify the full pipeline works.
"""

import sys
import os
import time
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

# Path setup
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent
_web_dashboard = _script_dir.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_web_dashboard))

from dotenv import load_dotenv
load_dotenv(_web_dashboard / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Import the job functions we want to test
from scheduler.jobs_congress_returns import (
    estimate_midpoint,
    _batch_download_current_prices,
    _batch_fetch_entry_prices,
)


def test_run():
    from supabase_client import SupabaseClient
    client = SupabaseClient(use_service_role=True)
    print("Connected to Supabase")

    # Step 1: Fetch just 10 trades that have prices
    print("\n--- Step 1: Fetch 10 sample trades ---")
    resp = client.supabase.table("congress_trades") \
        .select("id, ticker, transaction_date, price, amount") \
        .not_.is_("price", "null") \
        .order("transaction_date", desc=True) \
        .limit(10) \
        .execute()

    trades = resp.data or []
    print(f"Fetched {len(trades)} trades:")
    for t in trades:
        print(f"  ID={t['id']} | {t['ticker']} | {t['transaction_date']} | price=${t['price']} | {t['amount']}")

    if not trades:
        print("No trades found!")
        return

    # Step 2: Test midpoint estimation
    print("\n--- Step 2: Test midpoint estimation ---")
    for t in trades:
        mid = estimate_midpoint(t.get("amount"))
        print(f"  '{t.get('amount')}' -> midpoint = {mid}")

    # Step 3: Test batch fetching adjusted entry prices
    print("\n--- Step 3: Batch fetch adjusted entry prices ---")
    entry_prices = _batch_fetch_entry_prices(trades)
    for t in trades:
        ep = entry_prices.get(t["id"])
        print(f"  {t['ticker']} ({t['transaction_date']}): adj entry = {ep}")

    # Step 4: Test batch current price download
    print("\n--- Step 4: Batch download current prices ---")
    unique_tickers = list(set(t["ticker"] for t in trades))
    print(f"  Unique tickers: {unique_tickers}")
    current_prices = _batch_download_current_prices(unique_tickers)
    for ticker, price in current_prices.items():
        print(f"  {ticker}: current adj close = {price}")

    # Step 5: Compute returns for all test trades
    print("\n--- Step 5: Compute returns ---")
    upsert_records = []
    for t in trades:
        tid = t["id"]
        ticker = t["ticker"]
        entry_adj = entry_prices.get(tid)
        current_adj = current_prices.get(ticker)

        if entry_adj is None or current_adj is None or entry_adj == 0:
            print(f"  Trade {tid} ({ticker}): SKIP (entry={entry_adj}, current={current_adj})")
            continue

        pct = round(((current_adj - entry_adj) / entry_adj) * 100, 2)
        midpoint = estimate_midpoint(t.get("amount"))
        print(f"  Trade {tid} ({ticker}): entry_adj={entry_adj}, current={current_adj}, return={pct:+.2f}%")

        upsert_records.append({
            "trade_id": tid,
            "entry_price_adj": float(entry_adj),
            "current_price": float(current_adj),
            "pct_change": float(pct),
            "midpoint_est": float(midpoint) if midpoint else None,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "price_source": "yfinance",
        })

    # Step 6: Upsert to congress_trade_returns
    print(f"\n--- Step 6: Upsert {len(upsert_records)} records ---")
    if upsert_records:
        result = client.supabase.table("congress_trade_returns") \
            .upsert(upsert_records, on_conflict="trade_id") \
            .execute()
        print(f"  Upserted {len(result.data)} records successfully!")

        # Step 7: Verify via the enriched view
        print("\n--- Step 7: Verify via congress_trades_enriched ---")
        trade_ids = [r["trade_id"] for r in upsert_records]
        for tid in trade_ids:
            verify = client.supabase.table("congress_trades_enriched") \
                .select("id, ticker, transaction_date, price, pct_change, current_price_adj, return_updated_at") \
                .eq("id", tid) \
                .execute()
            if verify.data:
                row = verify.data[0]
                print(f"  ID={row['id']} | {row['ticker']} | entry=${row['price']} | "
                      f"current_adj=${row['current_price_adj']} | return={row['pct_change']}% | "
                      f"updated={row['return_updated_at']}")
            else:
                print(f"  ID={tid}: NOT FOUND in enriched view!")
    else:
        print("  No records to upsert")

    print("\n=== TEST RUN COMPLETE ===")


if __name__ == "__main__":
    test_run()
