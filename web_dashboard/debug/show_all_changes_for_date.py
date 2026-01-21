#!/usr/bin/env python3
"""Show all changes for a specific date across all ETFs"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from supabase_client import SupabaseClient
from datetime import datetime, date
import pandas as pd

def main():
    target_date = "2026-01-21"
    prev_date = "2026-01-18"
    
    db = SupabaseClient(use_service_role=True)
    
    print(f"Checking changes from {prev_date} to {target_date}")
    print("="*80)
    
    # Get all ETFs
    etfs_res = db.supabase.table('etf_holdings_log').select('etf_ticker').eq('date', target_date).execute()
    etfs = sorted(set(row['etf_ticker'] for row in etfs_res.data))
    
    all_changes = []
    
    for etf in etfs:
        # Get current holdings
        current_res = db.supabase.table('etf_holdings_log').select(
            'holding_ticker, shares_held, holding_name'
        ).eq('etf_ticker', etf).eq('date', target_date).execute()
        
        # Get previous holdings
        prev_res = db.supabase.table('etf_holdings_log').select(
            'holding_ticker, shares_held'
        ).eq('etf_ticker', etf).eq('date', prev_date).execute()
        
        if not current_res.data or not prev_res.data:
            continue
        
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
            print(f"\n{etf}: {len(changes)} changes")
            for _, row in changes.iterrows():
                ticker = row['holding_ticker']
                name = row.get('holding_name', 'N/A')
                curr_shares = int(row['shares_held_current'])
                prev_shares = int(row['shares_held_prev'])
                change = int(row['change'])
                pct_change = (change / prev_shares * 100) if prev_shares > 0 else 0
                action = "BUY" if change > 0 else "SELL"
                print(f"  {ticker:6s} ({name[:30]:30s}): {prev_shares:>8,} -> {curr_shares:>8,} ({change:>+8,} shares, {pct_change:>+6.1f}%) [{action}]")
                all_changes.append({
                    'etf': etf,
                    'ticker': ticker,
                    'name': name,
                    'action': action,
                    'change': change,
                    'pct_change': pct_change
                })
    
    print(f"\n{'='*80}")
    print(f"SUMMARY: {len(all_changes)} total changes across {len(etfs)} ETFs")
    print(f"Date to test: {target_date}")
    print(f"{'='*80}")

if __name__ == '__main__':
    main()
