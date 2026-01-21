#!/usr/bin/env python3
"""Find an example date with ETF changes that should show up on the page"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from supabase_client import SupabaseClient
from datetime import datetime, date
import pandas as pd
from collections import defaultdict

def main():
    # Use service role to bypass RLS
    db = SupabaseClient(use_service_role=True)
    
    # Get all available dates
    print("Fetching available dates from etf_holdings_log...")
    result = db.supabase.table('etf_holdings_log').select('date, etf_ticker').execute()
    
    if not result.data:
        print("No data found in etf_holdings_log!")
        return
    
    # Group by date and ETF
    date_etf_counts = defaultdict(lambda: defaultdict(int))
    for row in result.data:
        date_etf_counts[row['date']][row['etf_ticker']] += 1
    
    # Sort dates descending
    dates = sorted(date_etf_counts.keys(), reverse=True)
    
    print(f"\nFound {len(dates)} unique dates with data")
    print("\nMost recent dates with data:")
    for d in dates[:10]:
        etfs = list(date_etf_counts[d].keys())
        print(f"  {d}: {len(etfs)} ETFs ({', '.join(sorted(etfs))})")
    
    # Find a date that has a previous date (so we can see changes)
    print("\n" + "="*80)
    print("Looking for dates with previous data (to show actual changes)...")
    print("="*80)
    
    for i, current_date in enumerate(dates):
        if i == len(dates) - 1:
            # Last date, no previous
            continue
        
        # Check if any ETF has previous data
        current_etfs = set(date_etf_counts[current_date].keys())
        
        # Check previous dates
        for j in range(i + 1, min(i + 5, len(dates))):  # Check up to 5 days back
            prev_date = dates[j]
            prev_etfs = set(date_etf_counts[prev_date].keys())
            
            # Find ETFs that exist in both dates
            common_etfs = current_etfs & prev_etfs
            
            if common_etfs:
                # Found a date with previous data - check for actual changes
                print(f"\n[OK] Found date with previous data: {current_date}")
                print(f"  Previous date: {prev_date}")
                print(f"  ETFs with data on both dates: {', '.join(sorted(common_etfs))}")
                
                # Pick first ETF and show an example change
                example_etf = sorted(common_etfs)[0]
                print(f"\n  Example ETF: {example_etf}")
                
                # Get ALL holdings for both dates (not just 10)
                current_res = db.supabase.table('etf_holdings_log').select(
                    'holding_ticker, shares_held'
                ).eq('etf_ticker', example_etf).eq('date', current_date).execute()
                
                prev_res = db.supabase.table('etf_holdings_log').select(
                    'holding_ticker, shares_held'
                ).eq('etf_ticker', example_etf).eq('date', prev_date).execute()
                
                if current_res.data and prev_res.data:
                    current_df = pd.DataFrame(current_res.data)
                    prev_df = pd.DataFrame(prev_res.data)
                    
                    # Merge to find changes
                    merged = current_df.merge(
                        prev_df,
                        on='holding_ticker',
                        how='outer',
                        suffixes=('_current', '_prev')
                    )
                    merged['shares_held_current'] = merged['shares_held_current'].fillna(0)
                    merged['shares_held_prev'] = merged['shares_held_prev'].fillna(0)
                    merged['change'] = merged['shares_held_current'] - merged['shares_held_prev']
                    
                    # Find non-zero changes
                    changes = merged[merged['change'] != 0]
                    
                    if not changes.empty:
                        print(f"\n  Example changes for {example_etf}:")
                        for _, row in changes.head(5).iterrows():
                            ticker = row['holding_ticker']
                            curr_shares = int(row['shares_held_current'])
                            prev_shares = int(row['shares_held_prev'])
                            change = int(row['change'])
                            action = "BUY" if change > 0 else "SELL"
                            print(f"    {ticker}: {prev_shares:,} -> {curr_shares:,} ({change:+,} shares) [{action}]")
                        
                        print(f"\n{'='*80}")
                        print(f"[RECOMMENDED] DATE TO TEST: {current_date}")
                        print(f"  This date has previous data from {prev_date}")
                        print(f"  ETF {example_etf} has {len(changes)} holdings with changes")
                        print(f"  Set the date filter to: {current_date}")
                        print(f"{'='*80}")
                        return
                    else:
                        print(f"  (No changes found for {example_etf} between these dates)")
                
                break
    
    # If no changes found, show first date (will show all as "new")
    print(f"\n{'='*80}")
    print(f"[WARNING] No dates with changes found. Use latest date: {dates[0]}")
    print(f"  This will show all holdings as 'new' (BUY) since there's no previous data")
    print(f"{'='*80}")

if __name__ == '__main__':
    main()
