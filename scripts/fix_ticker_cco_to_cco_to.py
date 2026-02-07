"""
Data fix script: Rename ticker CCO -> CCO.TO (Cameco Corp) across all Supabase tables.

CCO on the Toronto Stock Exchange is Cameco Corporation. The correct Yahoo Finance
ticker is CCO.TO. This script updates all references from 'CCO' to 'CCO.TO'.

Tables affected:
  - securities (PK = ticker, so insert new + update refs + delete old)
  - trade_log
  - portfolio_positions
  - dividend_log
  - watched_tickers

Usage:
    python scripts/fix_ticker_cco_to_cco_to.py [--dry-run]
"""

import sys
import os
import argparse

# Add project root and web_dashboard to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "web_dashboard"))

from supabase_client import SupabaseClient


OLD_TICKER = "CCO"
NEW_TICKER = "CCO.TO"

# Tables with a 'ticker' column to update (excluding securities which needs special handling)
TICKER_TABLES = [
    "trade_log",
    "portfolio_positions",
    "dividend_log",
    "watched_tickers",
]


def count_rows(client: SupabaseClient, table: str, ticker: str) -> int:
    """Count rows matching a ticker in a table."""
    try:
        result = client.supabase.table(table).select("*", count="exact").eq("ticker", ticker).execute()
        return result.count or 0
    except Exception as e:
        print(f"  Warning: Could not query {table}: {e}")
        return 0


def run_fix(dry_run: bool = True) -> None:
    print(f"{'[DRY RUN] ' if dry_run else ''}Renaming ticker {OLD_TICKER} -> {NEW_TICKER}")
    print("=" * 60)

    client = SupabaseClient(use_service_role=True)

    # 1. Check current state of securities table
    print("\n--- Securities table ---")
    old_sec = client.supabase.table("securities").select("*").eq("ticker", OLD_TICKER).execute()
    new_sec = client.supabase.table("securities").select("*").eq("ticker", NEW_TICKER).execute()

    if old_sec.data:
        print(f"  Found {OLD_TICKER}: {old_sec.data[0].get('company_name', 'N/A')}")
    else:
        print(f"  {OLD_TICKER} not found in securities table")

    if new_sec.data:
        print(f"  Found {NEW_TICKER}: {new_sec.data[0].get('company_name', 'N/A')}")
    else:
        print(f"  {NEW_TICKER} not found in securities table")

    # 2. Count affected rows in each table
    print("\n--- Affected rows ---")
    for table in TICKER_TABLES:
        count = count_rows(client, table, OLD_TICKER)
        print(f"  {table}: {count} rows with ticker={OLD_TICKER}")

    if dry_run:
        print("\n[DRY RUN] No changes made. Run without --dry-run to apply.")
        return

    # 3. Ensure CCO.TO exists in securities with proper metadata
    print("\n--- Step 1: Ensure CCO.TO in securities ---")
    if not new_sec.data:
        # Copy metadata from old record if it exists, or fetch from yfinance
        if old_sec.data:
            metadata = dict(old_sec.data[0])
            metadata["ticker"] = NEW_TICKER
            # Remove timestamps so they get fresh defaults
            metadata.pop("last_updated", None)
            metadata.pop("created_at", None)
            client.supabase.table("securities").insert(metadata).execute()
            print(f"  Inserted {NEW_TICKER} with copied metadata")
        else:
            # Use ensure_ticker_in_securities to fetch from yfinance
            client.ensure_ticker_in_securities(NEW_TICKER, "CAD")
            print(f"  Inserted {NEW_TICKER} via yfinance lookup")
    else:
        print(f"  {NEW_TICKER} already exists, skipping insert")

    # Refresh metadata from yfinance to make sure it's correct
    print("  Refreshing metadata from yfinance...")
    client.ensure_ticker_in_securities(NEW_TICKER, "CAD")

    # 4. Update all reference tables
    print("\n--- Step 2: Update reference tables ---")
    for table in TICKER_TABLES:
        count = count_rows(client, table, OLD_TICKER)
        if count > 0:
            try:
                client.supabase.table(table).update(
                    {"ticker": NEW_TICKER}
                ).eq("ticker", OLD_TICKER).execute()
                print(f"  {table}: Updated {count} rows")
            except Exception as e:
                print(f"  ERROR updating {table}: {e}")
        else:
            print(f"  {table}: No rows to update")

    # 5. Delete old securities record
    print("\n--- Step 3: Remove old securities record ---")
    if old_sec.data:
        # Verify no remaining references
        remaining = sum(count_rows(client, t, OLD_TICKER) for t in TICKER_TABLES)
        if remaining == 0:
            client.supabase.table("securities").delete().eq("ticker", OLD_TICKER).execute()
            print(f"  Deleted {OLD_TICKER} from securities")
        else:
            print(f"  WARNING: {remaining} rows still reference {OLD_TICKER}, skipping delete")
    else:
        print(f"  {OLD_TICKER} not in securities, nothing to delete")

    # 6. Verify final state
    print("\n--- Verification ---")
    final_sec = client.supabase.table("securities").select("ticker, company_name, sector, currency").eq("ticker", NEW_TICKER).execute()
    if final_sec.data:
        rec = final_sec.data[0]
        print(f"  {NEW_TICKER}: {rec.get('company_name', 'N/A')} | {rec.get('sector', 'N/A')} | {rec.get('currency', 'N/A')}")
    for table in TICKER_TABLES:
        new_count = count_rows(client, table, NEW_TICKER)
        old_count = count_rows(client, table, OLD_TICKER)
        status = "OK" if old_count == 0 else "NEEDS ATTENTION"
        print(f"  {table}: {new_count} rows as {NEW_TICKER}, {old_count} remaining as {OLD_TICKER} [{status}]")

    print("\nDone! You may want to trigger a portfolio rebuild for the affected fund.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=f"Rename ticker {OLD_TICKER} -> {NEW_TICKER}")
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="Preview changes without applying them (default: apply changes)")
    args = parser.parse_args()
    run_fix(dry_run=args.dry_run)
