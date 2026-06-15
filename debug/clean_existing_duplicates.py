#!/usr/bin/env python3
"""
Clean existing duplicate portfolio positions before adding unique constraint.
Keeps the most recent record for each (fund, date, ticker) combination.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

from supabase_client import SupabaseClient
import pandas as pd
from datetime import datetime

def clean_existing_duplicates(dry_run: bool = True, fund_name: str = None):
    """Remove duplicate positions, keeping the most recent one for each (fund, date, ticker)"""
    client = SupabaseClient(use_service_role=True)
    
    print("="*80)
    print("CLEANING EXISTING DUPLICATE PORTFOLIO POSITIONS")
    print("="*80)
    if dry_run:
        print("[DRY RUN MODE - No changes will be made]\n")
    else:
        print("[LIVE MODE - Duplicates will be deleted]\n")
    
    # Get all positions (with pagination)
    all_positions = []
    offset = 0
    batch_size = 1000
    
    print("Fetching all portfolio positions...")
    while True:
        query = client.supabase.table('portfolio_positions').select('*')
        if fund_name:
            query = query.eq('fund', fund_name)
        
        result = query.order('date', desc=False).range(offset, offset + batch_size - 1).execute()
        
        if not result.data:
            break
        
        all_positions.extend(result.data)
        print(f"  Fetched {len(all_positions)} positions so far...")
        
        if len(result.data) < batch_size:
            break
        
        offset += batch_size
    
    if not all_positions:
        print("No positions found!")
        return
    
    print(f"\nTotal positions fetched: {len(all_positions)}")
    
    # Convert to DataFrame
    df = pd.DataFrame(all_positions)
    df['date'] = pd.to_datetime(df['date'])
    df['date_key'] = df['date'].dt.date
    
    # Find duplicates by (fund, date_key, ticker)
    duplicate_check = df.groupby(['fund', 'date_key', 'ticker']).size().reset_index(name='count')
    duplicates = duplicate_check[duplicate_check['count'] > 1]
    
    if len(duplicates) == 0:
        print("\n[OK] No duplicates found! Database is clean.")
        return
    
    print(f"\n[WARNING] Found {len(duplicates)} duplicate (fund, date, ticker) combinations")
    print(f"Total duplicate records to remove: {duplicates['count'].sum() - len(duplicates)}\n")
    
    # Process each duplicate group
    ids_to_delete = []
    kept_count = 0
    deleted_count = 0
    
    for dup in duplicates.to_dict('records'):
        fund = dup['fund']
        date_key = dup['date_key']
        ticker = dup['ticker']
        count = dup['count']
        
        # Get all records for this duplicate
        dup_records = df[
            (df['fund'] == fund) & 
            (df['date_key'] == date_key) & 
            (df['ticker'] == ticker)
        ].copy()
        
        # Sort by created_at (most recent first)
        dup_records = dup_records.sort_values('created_at', ascending=False)
        
        # Keep the first (most recent), mark the rest for deletion
        keep_record = dup_records.iloc[0]
        delete_records = dup_records.iloc[1:]
        
        kept_count += 1
        
        print(f"{fund} | {date_key} | {ticker}: {count} records")
        print(f"  [KEEP] ID={keep_record['id'][:8]}... created={keep_record.get('created_at', 'N/A')}")
        
        for record in delete_records.to_dict('records'):
            print(f"  [DELETE] ID={record['id'][:8]}... created={record.get('created_at', 'N/A')}")
            ids_to_delete.append(record['id'])
            deleted_count += 1
    
    print(f"\n{'='*80}")
    print(f"SUMMARY")
    print(f"{'='*80}")
    print(f"Duplicate combinations found: {len(duplicates)}")
    print(f"Records to keep: {kept_count}")
    print(f"Records to delete: {deleted_count}")
    
    if dry_run:
        print(f"\n[DRY RUN] Would delete {deleted_count} duplicate records")
        print(f"Run with --execute to actually delete them")
    else:
        print(f"\n[LIVE MODE] Deleting {deleted_count} duplicate records...")
        
        # Delete in batches to avoid timeout
        batch_size = 100
        deleted_actual = 0
        
        for i in range(0, len(ids_to_delete), batch_size):
            batch = ids_to_delete[i:i+batch_size]
            try:
                result = client.supabase.table('portfolio_positions')\
                    .delete()\
                    .in_('id', batch)\
                    .execute()
                
                deleted_actual += len(batch)
                print(f"  Deleted batch {i//batch_size + 1}: {len(batch)} records")
            except Exception as e:
                print(f"  ERROR deleting batch {i//batch_size + 1}: {e}")
        
        print(f"\n[SUCCESS] Deleted {deleted_actual} duplicate records")
        print(f"Database is now clean!")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Clean duplicate portfolio positions')
    parser.add_argument('--execute', action='store_true', help='Actually delete duplicates (default is dry run)')
    parser.add_argument('--fund', type=str, help='Only clean duplicates for specific fund')
    args = parser.parse_args()
    
    clean_existing_duplicates(dry_run=not args.execute, fund_name=args.fund)

