#!/usr/bin/env python3
"""
Clean duplicate portfolio positions that are causing inflated NAV calculations
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

from supabase_client import SupabaseClient
import pandas as pd
from datetime import datetime

def find_duplicates():
    """Find all duplicate positions"""
    client = SupabaseClient(use_service_role=True)
    
    # Get all positions
    res = client.supabase.table('portfolio_positions').select('*').execute()
    df = pd.DataFrame(res.data)
    
    if df.empty:
        print("No positions found")
        return None
    
    # Convert date to datetime
    df['date'] = pd.to_datetime(df['date'])
    
    # Find duplicates by date + ticker (not fund, since these are cross-fund duplicates)
    df['dup_key'] = df['date'].astype(str) + '_' + df['ticker']
    duplicates = df[df.duplicated(subset='dup_key', keep=False)].sort_values(['date', 'ticker'])
    
    return duplicates

def clean_duplicates(dry_run=True):
    """Remove duplicate positions, keeping the most recent one"""
    client = SupabaseClient(use_service_role=True)
    
    duplicates = find_duplicates()
    if duplicates is None or duplicates.empty:
        print("No duplicates found!")
        return
    
    print(f"\n{'='*80}")
    print(f"Found {len(duplicates)} duplicate position records")
    print(f"{'='*80}\n")
    
    # Group by date, ticker
    grouped = duplicates.groupby(['date', 'ticker'])
    
    deleted_count = 0
    kept_count = 0
    
    for (date, ticker), group in grouped:
        print(f"\n{date.strftime('%Y-%m-%d')} | {ticker}")
        print(f"  Found {len(group)} records:")
        
        # Sort by created_at to keep the most recent
        group_sorted = group.sort_values('created_at', ascending=False)
        
        # Keep the first (most recent), delete the rest
        keep_record = group_sorted.iloc[0]
        delete_records = group_sorted.iloc[1:]
        
        print(f"  [KEEP] ID={keep_record['id'][:8]}... created={keep_record['created_at']}")
        kept_count += 1
        
        for record in delete_records.to_dict('records'):
            print(f"  [DELETE] ID={record['id'][:8]}... created={record['created_at']}")
            
            if not dry_run:
                try:
                    client.supabase.table('portfolio_positions').delete().eq('id', record['id']).execute()
                    print(f"     Deleted successfully")
                    deleted_count += 1
                except Exception as e:
                    print(f"     ERROR: {e}")
            else:
                deleted_count += 1
    
    print(f"\n{'='*80}")
    if dry_run:
        print(f"DRY RUN COMPLETE")
        print(f"Would keep: {kept_count} records")
        print(f"Would delete: {deleted_count} records")
        print(f"\nRun with --execute to actually delete the duplicates")
    else:
        print(f"CLEANUP COMPLETE")
        print(f"Kept: {kept_count} records")
        print(f"Deleted: {deleted_count} records")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Clean duplicate portfolio positions')
    parser.add_argument('--execute', action='store_true', help='Actually delete duplicates (default is dry run)')
    args = parser.parse_args()
    
    clean_duplicates(dry_run=not args.execute)
