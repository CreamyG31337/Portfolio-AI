#!/usr/bin/env python3
"""
Simple test to verify ETF query fix - check database directly
"""

import sys
from pathlib import Path
from datetime import date

sys.path.append(str(Path(__file__).resolve().parent.parent))

from postgres_client import PostgresClient
from supabase_client import SupabaseClient

def main():
    print("=" * 80)
    print("Testing ETF Query Fix - Database Check")
    print("=" * 80)
    print()
    
    pc = PostgresClient()
    db_client = SupabaseClient(use_service_role=True)
    target_date = date.today()
    
    print(f"Target date: {target_date}")
    print()
    
    # Get all available ETFs
    print("Getting all available ETFs...")
    from routes.etf_routes import get_available_etfs
    available_etfs = get_available_etfs(db_client)
    print(f"Found {len(available_etfs)} ETFs")
    print()
    
    # Check dates per ETF
    print("Checking latest date per ETF:")
    print("-" * 80)
    
    from routes.etf_routes import get_as_of_date
    
    etf_dates = {}
    for etf_info in available_etfs:
        etf = etf_info['ticker']
        etf_latest_date = get_as_of_date(db_client, target_date, etf)
        if etf_latest_date:
            etf_dates[etf] = etf_latest_date
            print(f"  {etf}: {etf_latest_date}")
        else:
            print(f"  {etf}: No data")
    
    print()
    print(f"ETFs with data: {len(etf_dates)}")
    print(f"ETFs without data: {len(available_etfs) - len(etf_dates)}")
    print()
    
    # Check if we can query changes for all ETFs
    print("Testing get_holdings_changes() with new logic...")
    print("-" * 80)
    
    try:
        from routes.etf_routes import get_holdings_changes
        changes_df, as_of_date = get_holdings_changes(db_client, target_date, None, None)
        
        print(f"As of date returned: {as_of_date}")
        print(f"Total changes found: {len(changes_df)}")
        
        if not changes_df.empty and 'etf_ticker' in changes_df.columns:
            unique_etfs = changes_df['etf_ticker'].unique()
            print(f"ETFs appearing in results: {len(unique_etfs)}")
            print(f"ETFs: {', '.join(sorted(unique_etfs))}")
            print()
            
            # Compare with available ETFs
            missing_etfs = set(etf_dates.keys()) - set(unique_etfs)
            if missing_etfs:
                print(f"WARNING: {len(missing_etfs)} ETFs with data not appearing in results:")
                for etf in sorted(missing_etfs):
                    print(f"  - {etf} (has data on {etf_dates[etf]})")
            else:
                print("SUCCESS: All ETFs with data appear in results!")
        else:
            print("WARNING: No changes found or missing etf_ticker column")
            
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    
    print()
    print("=" * 80)
    print("Test complete!")
    print("=" * 80)

if __name__ == "__main__":
    main()
