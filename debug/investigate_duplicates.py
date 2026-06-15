#!/usr/bin/env python3
"""
Investigate duplicate portfolio positions to understand root cause
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

from supabase_client import SupabaseClient
import pandas as pd
from datetime import datetime

def investigate_duplicates():
    """Investigate duplicate positions in detail"""
    client = SupabaseClient(use_service_role=True)
    fund_name = 'Project Chimera'
    
    print("="*80)
    print("INVESTIGATING DUPLICATE PORTFOLIO POSITIONS")
    print("="*80)
    print(f"Fund: {fund_name}\n")
    
    # Get all positions for the fund
    result = client.supabase.table('portfolio_positions')\
        .select('*')\
        .eq('fund', fund_name)\
        .order('date', desc=False)\
        .execute()
    
    if not result.data:
        print("No positions found!")
        return
    
    df = pd.DataFrame(result.data)
    print(f"Total positions in database: {len(df)}")
    
    # Convert date to datetime for grouping
    df['date'] = pd.to_datetime(df['date'])
    df['date_key'] = df['date'].dt.date
    
    # Find duplicates by date + ticker
    duplicate_check = df.groupby(['date_key', 'ticker']).size().reset_index(name='count')
    duplicates = duplicate_check[duplicate_check['count'] > 1]
    
    if len(duplicates) == 0:
        print("\n[OK] No duplicates found!")
        return
    
    print(f"\n[ERROR] Found {len(duplicates)} duplicate date+ticker combinations\n")
    
    # Analyze each duplicate
    print("="*80)
    print("DUPLICATE ANALYSIS")
    print("="*80)
    
    # itertuples preserves the original (gappy) index label used in the [{idx+1}] display.
    for dup in duplicates.itertuples():
        date_key = dup.date_key
        ticker = dup.ticker
        count = dup.count
        
        print(f"\n[{dup.Index+1}] {date_key} | {ticker} ({count} records)")
        print("-" * 80)
        
        # Get all records for this duplicate
        dup_records = df[(df['date_key'] == date_key) & (df['ticker'] == ticker)].copy()
        
        # Sort by created_at to see order
        dup_records = dup_records.sort_values('created_at')
        
        for i, record in enumerate(dup_records.to_dict('records'), 1):
            print(f"\n  Record {i}:")
            print(f"    ID: {record['id']}")
            print(f"    Date: {record['date']}")
            print(f"    Created At: {record.get('created_at', 'N/A')}")
            print(f"    Updated At: {record.get('updated_at', 'N/A')}")
            print(f"    Shares: {record['shares']}")
            print(f"    Price: {record['price']}")
            print(f"    Cost Basis: {record.get('cost_basis', 'N/A')}")
            print(f"    Currency: {record.get('currency', 'N/A')}")
            print(f"    Fund: {record.get('fund', 'N/A')}")
            
            # Check if values are identical
            if i > 1:
                prev_record = dup_records.iloc[i-2]
                values_match = (
                    float(record['shares']) == float(prev_record['shares']) and
                    float(record['price']) == float(prev_record['price']) and
                    float(record.get('cost_basis', 0)) == float(prev_record.get('cost_basis', 0))
                )
                if values_match:
                    print(f"    [WARNING] VALUES MATCH previous record (likely duplicate insert)")
                else:
                    print(f"    [WARNING] VALUES DIFFER from previous record (possible update)")
    
    # Check for patterns
    print("\n" + "="*80)
    print("PATTERN ANALYSIS")
    print("="*80)
    
    # Group by date to see if duplicates cluster on specific dates
    dup_dates = duplicates.groupby('date_key').size().reset_index(name='dup_count')
    dup_dates = dup_dates.sort_values('dup_count', ascending=False)
    
    print(f"\nDates with most duplicates:")
    for row in dup_dates.head(10).to_dict('records'):
        print(f"  {row['date_key']}: {row['dup_count']} duplicate tickers")
    
    # Check time differences between duplicates
    print(f"\nTime differences between duplicate records:")
    time_diffs = []
    for dup in duplicates.to_dict('records'):
        date_key = dup['date_key']
        ticker = dup['ticker']
        dup_records = df[(df['date_key'] == date_key) & (df['ticker'] == ticker)].copy()
        dup_records = dup_records.sort_values('created_at')
        
        if len(dup_records) > 1:
            for i in range(1, len(dup_records)):
                time1 = pd.to_datetime(dup_records.iloc[i-1]['created_at'])
                time2 = pd.to_datetime(dup_records.iloc[i]['created_at'])
                diff = (time2 - time1).total_seconds()
                time_diffs.append(diff)
                print(f"  {date_key} | {ticker}: {diff:.1f} seconds between records")
    
    if time_diffs:
        avg_diff = sum(time_diffs) / len(time_diffs)
        print(f"\n  Average time between duplicates: {avg_diff:.1f} seconds")
        print(f"  Min: {min(time_diffs):.1f}s, Max: {max(time_diffs):.1f}s")
    
    # Check if duplicates have same fund value
    print(f"\n" + "="*80)
    print("IMPACT ANALYSIS")
    print("="*80)
    
    # Calculate how much NAV is inflated
    total_duplicate_value = 0
    for dup in duplicates.to_dict('records'):
        date_key = dup['date_key']
        ticker = dup['ticker']
        dup_records = df[(df['date_key'] == date_key) & (df['ticker'] == ticker)]
        
        # Get first record value
        first_value = float(dup_records.iloc[0]['shares']) * float(dup_records.iloc[0]['price'])
        # Count how many extra times it's counted
        extra_count = len(dup_records) - 1
        total_duplicate_value += first_value * extra_count
    
    print(f"\nEstimated NAV inflation: ${total_duplicate_value:,.2f}")
    print(f"  (This is the extra value being counted due to duplicates)")

if __name__ == "__main__":
    investigate_duplicates()

