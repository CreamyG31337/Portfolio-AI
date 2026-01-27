#!/usr/bin/env python3
"""
Test script to verify ETF query fix - all ETFs should appear in Latest Changes
"""

import sys
from pathlib import Path
from datetime import date

sys.path.append(str(Path(__file__).resolve().parent.parent))

from routes.etf_routes import get_holdings_changes
from supabase_client import SupabaseClient

def main():
    print("=" * 80)
    print("Testing ETF Query Fix")
    print("=" * 80)
    print()
    
    db_client = SupabaseClient(use_service_role=True)
    target_date = date.today()
    
    print(f"Target date: {target_date}")
    print()
    
    # Test the function
    print("Calling get_holdings_changes()...")
    changes_df, as_of_date = get_holdings_changes(db_client, target_date, None, None)
    
    print(f"As of date returned: {as_of_date}")
    print()
    
    if changes_df.empty:
        print("WARNING: No changes found")
        return
    
    print(f"Total changes found: {len(changes_df)}")
    print()
    
    # Check which ETFs appear
    if 'etf_ticker' in changes_df.columns:
        unique_etfs = changes_df['etf_ticker'].unique()
        print(f"ETFs appearing in results: {len(unique_etfs)}")
        print(f"ETFs: {', '.join(sorted(unique_etfs))}")
        print()
        
        # Check dates per ETF
        print("Dates per ETF:")
        print("-" * 80)
        for etf in sorted(unique_etfs):
            etf_rows = changes_df[changes_df['etf_ticker'] == etf]
            if 'date' in etf_rows.columns:
                dates = etf_rows['date'].dropna().unique()
                if len(dates) > 0:
                    latest_date = max(dates) if isinstance(dates[0], str) else max([d for d in dates if d])
                    print(f"  {etf}: {latest_date} ({len(etf_rows)} changes)")
                else:
                    print(f"  {etf}: No dates ({len(etf_rows)} changes)")
            else:
                print(f"  {etf}: No date column ({len(etf_rows)} changes)")
    
    print()
    print("=" * 80)
    print("Test complete!")
    print("=" * 80)

if __name__ == "__main__":
    main()
