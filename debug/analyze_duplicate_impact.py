#!/usr/bin/env python3
"""
Analyze duplicate positions to understand the NAV inflation issue
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

from supabase_client import SupabaseClient
import pandas as pd

def analyze_duplicates():
    client = SupabaseClient(use_service_role=True)
    
    # Get all positions
    res = client.supabase.table('portfolio_positions').select('id, date, ticker, fund, shares, price, total_value, created_at').execute()
    df = pd.DataFrame(res.data)
    
    print(f"Total positions: {len(df)}")
    print(f"Unique funds: {df['fund'].unique()}")
    
    # Convert date
    df['date'] = pd.to_datetime(df['date'])
    
    # Find duplicates by date + ticker (regardless of fund)
    df_sorted = df.sort_values(['date', 'ticker', 'created_at'])
    
    # Group by date and ticker
    grouped = df_sorted.groupby(['date', 'ticker'])
    
    duplicates = []
    for (date, ticker), group in grouped:
        if len(group) > 1:
            duplicates.append(group)
    
    if not duplicates:
        print("\nNo duplicates found!")
        return
    
    print(f"\nFound {len(duplicates)} sets of duplicates:")
    print("="*100)
    
    for dup_group in duplicates[:10]:  # Show first 10
        print(f"\n{dup_group.iloc[0]['date'].strftime('%Y-%m-%d')} | {dup_group.iloc[0]['ticker']}")
        for row in dup_group.to_dict('records'):
            print(f"  ID: {row['id'][:8]}... | Fund: {row['fund']} | Shares: {row['shares']} | Price: ${row['price']:.2f} | Value: ${row['total_value']:.2f} | Created: {row['created_at']}")
    
    print(f"\n... and {len(duplicates) - 10} more" if len(duplicates) > 10 else "")
    print("="*100)
    
    # Calculate impact on fund value
    print("\nCalculating impact on historical fund values...")
    
    # Group by date and sum total_value
    daily_values = df.groupby('date')['total_value'].sum().sort_index()
    
    # Now remove duplicates and recalculate
    df_deduped = df.drop_duplicates(subset=['date', 'ticker'], keep='first')
    daily_values_clean = df_deduped.groupby('date')['total_value'].sum().sort_index()
    
    # Show the difference
    comparison = pd.DataFrame({
        'with_dupes': daily_values,
        'without_dupes': daily_values_clean
    })
    comparison['difference'] = comparison['with_dupes'] - comparison['without_dupes']
    comparison['pct_inflation'] = (comparison['difference'] / comparison['without_dupes'] * 100)
    
    print("\nDates with inflated values:")
    inflated = comparison[comparison['difference'] > 0]
    print(inflated)
    
    print(f"\nAverage inflation: {inflated['pct_inflation'].mean():.2f}%")
    print(f"Max inflation: {inflated['pct_inflation'].max():.2f}%")

if __name__ == "__main__":
    analyze_duplicates()
