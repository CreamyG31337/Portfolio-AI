#!/usr/bin/env python3
"""
Backfill Missing Tickers in Securities Table
=============================================
Adds missing tickers from dividend_log, trade_log, and portfolio_positions
to the securities table with minimal data (ticker and currency).

Company names will be populated later by yfinance jobs.
"""

import sys
import logging
from pathlib import Path
from collections import defaultdict
from typing import Dict, Set

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from web_dashboard.supabase_client import SupabaseClient
from web_dashboard.scripts.audit_missing_tickers import audit_missing_tickers
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Load environment
load_dotenv("web_dashboard/.env")


def determine_currency_from_ticker(ticker: str) -> str:
    """Determine currency from ticker symbol.

    Canadian tickers typically end with .TO, .V, .CN, or are on TSX.
    Default to USD for others.
    """
    ticker_upper = ticker.upper()
    if ticker_upper.endswith(('.TO', '.V', '.CN')):
        return 'CAD'
    # Could add more heuristics here if needed
    return 'USD'


def backfill_missing_tickers(dry_run: bool = True) -> None:
    """Backfill missing tickers into securities table.

    Args:
        dry_run: If True, only report what would be done without making changes
    """
    print("=" * 80)
    print("Backfill Missing Tickers to Securities Table")
    print("=" * 80)
    if dry_run:
        print("[DRY RUN MODE] - No changes will be made")
    print("=" * 80)

    # First, audit to find missing tickers
    missing_by_table = audit_missing_tickers()

    if not missing_by_table:
        print("\n[OK] No missing tickers found. Nothing to backfill.")
        return

    # Collect all unique missing tickers
    all_missing = set()
    for tickers in missing_by_table.values():
        all_missing.update(tickers)

    print(f"\n[INFO] Found {len(all_missing)} unique missing tickers to backfill")

    if not all_missing:
        return

    client = SupabaseClient(use_service_role=True)

    # Determine currency for each ticker from the tables where it appears
    ticker_currencies = {}

    print("\n[1/3] Determining currencies for missing tickers...")
    for ticker in all_missing:
        # Try to find currency from trade_log (most reliable)
        try:
            trade_result = client.supabase.table("trade_log")\
                .select("currency")\
                .eq("ticker", ticker)\
                .limit(1)\
                .execute()

            if trade_result.data and trade_result.data[0].get('currency'):
                ticker_currencies[ticker] = trade_result.data[0]['currency']
                continue
        except:
            pass

        # Try dividend_log
        try:
            div_result = client.supabase.table("dividend_log")\
                .select("currency")\
                .eq("ticker", ticker)\
                .limit(1)\
                .execute()

            if div_result.data and div_result.data[0].get('currency'):
                ticker_currencies[ticker] = div_result.data[0]['currency']
                continue
        except:
            pass

        # Try portfolio_positions
        try:
            pos_result = client.supabase.table("portfolio_positions")\
                .select("currency")\
                .eq("ticker", ticker)\
                .limit(1)\
                .execute()

            if pos_result.data and pos_result.data[0].get('currency'):
                ticker_currencies[ticker] = pos_result.data[0]['currency']
                continue
        except:
            pass

        # Fallback to heuristic
        ticker_currencies[ticker] = determine_currency_from_ticker(ticker)

    print(f"   Determined currencies for {len(ticker_currencies)} tickers")

    # Prepare insert data
    print("\n[2/3] Preparing ticker records...")
    records_to_insert = []
    for ticker in sorted(all_missing):
        currency = ticker_currencies.get(ticker, 'USD')
        records_to_insert.append({
            'ticker': ticker,
            'currency': currency,
            'company_name': None  # Will be populated by yfinance jobs later
        })

    print(f"   Prepared {len(records_to_insert)} records to insert")

    # Show sample
    print("\n   Sample records (first 10):")
    for record in records_to_insert[:10]:
        print(f"      - {record['ticker']}: {record['currency']}")
    if len(records_to_insert) > 10:
        print(f"      ... and {len(records_to_insert) - 10} more")

    # Insert records
    if not dry_run:
        print("\n[3/3] Upserting records into securities table...")
        try:
            # Insert in batches to avoid hitting limits
            batch_size = 50
            inserted_count = 0

            for i in range(0, len(records_to_insert), batch_size):
                batch = records_to_insert[i:i+batch_size]
                result = client.supabase.table("securities")\
                    .upsert(batch, on_conflict="ticker")\
                    .execute()

                inserted_count += len(batch)
                print(f"   Upserted batch {i//batch_size + 1}: {len(batch)} tickers (total: {inserted_count}/{len(records_to_insert)})")

            print(f"\n[OK] Successfully upserted {inserted_count} tickers into securities table")

            # Verify
            print("\n[4/4] Verifying insertion...")
            verify_result = client.supabase.table("securities")\
                .select("ticker")\
                .in_("ticker", list(all_missing))\
                .execute()

            verified_count = len(verify_result.data)
            if verified_count == len(all_missing):
                print(f"   [OK] Verified: All {verified_count} tickers now exist in securities table")
            else:
                print(f"   [WARN] Only {verified_count}/{len(all_missing)} tickers verified")

        except Exception as e:
            logger.error(f"Error inserting records: {e}")
            print(f"\n[ERROR] Error inserting records: {e}")
    else:
        print("\n[3/3] DRY RUN - Would insert records (use --execute to actually insert)")

    print("\n" + "=" * 80)
    print("Backfill Complete")
    print("=" * 80)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Backfill missing tickers to securities table")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform the backfill (default is dry-run)"
    )

    args = parser.parse_args()

    backfill_missing_tickers(dry_run=not args.execute)
