#!/usr/bin/env python3
"""
Check for duplicates on specific dates mentioned in error logs
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

from supabase_client import SupabaseClient
import pandas as pd
from datetime import datetime

def check_specific_date():
    """Check for duplicates on 2025-09-07 (date from error)"""
    client = SupabaseClient(use_service_role=True)
    fund_name = 'Project Chimera'
    
    print("="*80)
    print("CHECKING FOR DUPLICATES ON SPECIFIC DATE")
    print("="*80)
    print(f"Fund: {fund_name}\n")
    
    # Check the date from the error: 2025-09-07
    target_date = "2025-09-07"
    
    # Get all positions for this date (no limit)
    result = client.supabase.table('portfolio_positions')\
        .select('*')\
        .eq('fund', fund_name)\
        .gte('date', f'{target_date}T00:00:00')\
        .lte('date', f'{target_date}T23:59:59')\
        .execute()
    
    if not result.data:
        print(f"No positions found for {target_date}")
        return
    
    df = pd.DataFrame(result.data)
    print(f"Positions on {target_date}: {len(df)} records\n")
    
    # Check for duplicates by ticker
    duplicate_check = df.groupby('ticker').size().reset_index(name='count')
    duplicates = duplicate_check[duplicate_check['count'] > 1]
    
    if len(duplicates) == 0:
        print("[OK] No duplicates found on this date!")
    else:
        print(f"[ERROR] Found {len(duplicates)} tickers with duplicates:\n")
        for dup in duplicates.to_dict('records'):
            ticker = dup['ticker']
            count = dup['count']
            print(f"  {ticker}: {count} records")
            
            # Show the duplicate records
            dup_records = df[df['ticker'] == ticker].copy()
            dup_records = dup_records.sort_values('created_at')
            
            for i, record in enumerate(dup_records.to_dict('records'), 1):
                print(f"\n    Record {i}:")
                print(f"      ID: {record['id']}")
                print(f"      Date: {record['date']}")
                print(f"      Created At: {record.get('created_at', 'N/A')}")
                print(f"      Shares: {record['shares']}, Price: {record['price']}")
    
    # Also check all dates for duplicates (with pagination)
    print("\n" + "="*80)
    print("CHECKING ALL DATES FOR DUPLICATES (with pagination)")
    print("="*80)
    
    all_duplicates = []
    offset = 0
    batch_size = 1000
    
    while True:
        result = client.supabase.table('portfolio_positions')\
            .select('*')\
            .eq('fund', fund_name)\
            .order('date', desc=False)\
            .range(offset, offset + batch_size - 1)\
            .execute()
        
        if not result.data:
            break
        
        df_batch = pd.DataFrame(result.data)
        df_batch['date'] = pd.to_datetime(df_batch['date'])
        df_batch['date_key'] = df_batch['date'].dt.date
        
        # Find duplicates in this batch
        duplicate_check = df_batch.groupby(['date_key', 'ticker']).size().reset_index(name='count')
        batch_dups = duplicate_check[duplicate_check['count'] > 1]
        
        if len(batch_dups) > 0:
            all_duplicates.append(batch_dups)
            print(f"\nBatch {offset//batch_size + 1} (rows {offset} to {offset + len(df_batch)}):")
            for dup in batch_dups.to_dict('records'):
                print(f"  {dup['date_key']} | {dup['ticker']}: {dup['count']} records")
        
        if len(result.data) < batch_size:
            break
        
        offset += batch_size
    
    if all_duplicates:
        combined = pd.concat(all_duplicates, ignore_index=True)
        print(f"\n[ERROR] Total duplicate combinations found: {len(combined)}")
    else:
        print("\n[OK] No duplicates found in any batch!")

if __name__ == "__main__":
    check_specific_date()

