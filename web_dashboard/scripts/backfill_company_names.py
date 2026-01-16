#!/usr/bin/env python3
"""
Backfill Missing Company Names in Securities Table
====================================================
Populates missing company names for existing tickers in the securities table
by fetching data from yfinance.

This script processes tickers where company_name IS NULL or company_name = 'Unknown'.
"""

import sys
import logging
import time
from pathlib import Path
from typing import List, Dict

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from web_dashboard.supabase_client import SupabaseClient
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Load environment
load_dotenv("web_dashboard/.env")


def get_tickers_with_missing_names(client: SupabaseClient) -> List[Dict]:
    """Get all tickers that need company name updates.
    
    Returns tickers where company_name IS NULL or company_name = 'Unknown'.
    """
    try:
        # Query for tickers with missing or unknown company names
        result = client.supabase.table("securities")\
            .select("ticker, currency, company_name")\
            .or_("company_name.is.null,company_name.eq.Unknown")\
            .execute()
        
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Error querying securities table: {e}")
        return []


def backfill_company_names(dry_run: bool = True, batch_size: int = 50, delay_seconds: float = 0.5) -> None:
    """Backfill missing company names using ensure_ticker_in_securities.
    
    Args:
        dry_run: If True, only report what would be done without making changes
        batch_size: Number of tickers to process in each batch
        delay_seconds: Delay between yfinance API calls to avoid rate limits
    """
    print("=" * 80)
    print("Backfill Missing Company Names in Securities Table")
    print("=" * 80)
    if dry_run:
        print("[DRY RUN MODE] - No changes will be made")
    print("=" * 80)
    
    client = SupabaseClient(use_service_role=True)
    
    # Get all tickers that need updates
    print("\n[1/3] Querying securities table for tickers with missing company names...")
    tickers_to_update = get_tickers_with_missing_names(client)
    
    if not tickers_to_update:
        print("\n[OK] No tickers found with missing company names. Nothing to backfill.")
        print(f"\n[RESULT] Fixed: 0 tickers (all tickers already have company names)")
        return
    
    print(f"   Found {len(tickers_to_update)} tickers needing company name updates")
    
    # Show sample
    print("\n   Sample tickers (first 10):")
    for ticker_info in tickers_to_update[:10]:
        ticker = ticker_info.get('ticker', 'N/A')
        currency = ticker_info.get('currency', 'USD')
        current_name = ticker_info.get('company_name') or 'NULL'
        print(f"      - {ticker} ({currency}): current_name={current_name}")
    if len(tickers_to_update) > 10:
        print(f"      ... and {len(tickers_to_update) - 10} more")
    
    # Process in batches
    if not dry_run:
        print(f"\n[2/3] Processing {len(tickers_to_update)} tickers in batches of {batch_size}...")
        print(f"   Delay between API calls: {delay_seconds}s (to avoid rate limits)")
        
        success_count = 0
        error_count = 0
        skipped_count = 0
        
        for i in range(0, len(tickers_to_update), batch_size):
            batch = tickers_to_update[i:i+batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(tickers_to_update) + batch_size - 1) // batch_size
            
            print(f"\n   Processing batch {batch_num}/{total_batches} ({len(batch)} tickers)...")
            
            for ticker_info in batch:
                ticker = ticker_info.get('ticker')
                currency = ticker_info.get('currency', 'USD')
                
                if not ticker:
                    skipped_count += 1
                    continue
                
                try:
                    # Use ensure_ticker_in_securities which will fetch from yfinance
                    success = client.ensure_ticker_in_securities(ticker, currency)
                    
                    if success:
                        success_count += 1
                        # Small delay to avoid rate limits
                        time.sleep(delay_seconds)
                    else:
                        error_count += 1
                        logger.warning(f"Failed to update {ticker}")
                        
                except Exception as e:
                    error_count += 1
                    logger.error(f"Error updating {ticker}: {e}")
                    # Continue with next ticker even if one fails
            
            print(f"   Batch {batch_num} complete: {success_count} succeeded, {error_count} errors, {skipped_count} skipped")
        
        print(f"\n[3/3] Summary:")
        print(f"   Total tickers needing updates: {len(tickers_to_update)}")
        print(f"   Successfully fixed: {success_count}")
        print(f"   Errors: {error_count}")
        print(f"   Skipped: {skipped_count}")
        
        print(f"\n[RESULT] FIXED: {success_count} ticker(s) with missing company names")
        if success_count > 0:
            print(f"   Successfully populated company names for {success_count} ticker(s)!")
        elif error_count > 0:
            print(f"   WARNING: {error_count} ticker(s) failed to update (see errors above)")
        else:
            print(f"   All tickers already had company names or were skipped")
        
        # Verify results
        print("\n[4/4] Verifying results...")
        remaining = get_tickers_with_missing_names(client)
        remaining_count = len(remaining)
        
        if remaining_count == 0:
            print(f"   [OK] All tickers now have company names!")
        else:
            print(f"   [INFO] {remaining_count} tickers still have missing company names")
            print("   This may be due to:")
            print("      - Invalid ticker symbols")
            print("      - yfinance API rate limits")
            print("      - Tickers not found in yfinance")
            print("   Run the script again later to retry failed tickers")
    else:
        print(f"\n[2/3] DRY RUN - Would process {len(tickers_to_update)} tickers")
        print(f"   Batch size: {batch_size}")
        print(f"   Delay between calls: {delay_seconds}s")
        print("\n[3/3] DRY RUN - Use --execute to actually update company names")
    
    print("\n" + "=" * 80)
    print("Backfill Complete")
    print("=" * 80)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Backfill missing company names in securities table")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform the backfill (default is dry-run)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of tickers to process per batch (default: 50)"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay in seconds between API calls (default: 0.5)"
    )
    
    args = parser.parse_args()
    
    backfill_company_names(
        dry_run=not args.execute,
        batch_size=args.batch_size,
        delay_seconds=args.delay
    )
