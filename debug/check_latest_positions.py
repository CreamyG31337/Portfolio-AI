#!/usr/bin/env python3
"""Check for duplicate positions on latest date"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

from supabase_client import SupabaseClient
import pandas as pd

client = SupabaseClient(use_service_role=True)
fund_name = 'Project Chimera'

# Get latest positions
result = client.supabase.table('portfolio_positions')\
    .select('*')\
    .eq('fund', fund_name)\
    .order('date', desc=True)\
    .limit(200)\
    .execute()

df = pd.DataFrame(result.data)

if df.empty:
    print("No data!")
    exit(1)

latest_date = df['date'].max()
print(f"Latest date: {latest_date}")

latest_df = df[df['date'] == latest_date].copy()
print(f"\nPositions on {latest_date}: {len(latest_df)} rows")

# Check for duplicates
duplicates = latest_df.groupby('ticker').size()
duplicates = duplicates[duplicates > 1]

if len(duplicates) > 0:
    print(f"\n!! DUPLICATES FOUND: {len(duplicates)} tickers with multiple rows!!")
    for ticker, count in duplicates.items():
        print(f"  {ticker}: {count} rows")
        ticker_rows = latest_df[latest_df['ticker'] == ticker]
        for row in ticker_rows.to_dict('records'):
            print(f"    shares={row['shares']}, price={row['price']}, created_at={row.get('created_at', 'N/A')}")
else:
    print("\nNo duplicates found")

# Calculate value
latest_df['value'] = latest_df['shares'].astype(float) * latest_df['price'].astype(float)
total_value = latest_df['value'].sum()

print(f"\nTotal portfolio value: ${total_value:,.2f}")
print(f"Number of positions: {len(latest_df)}")

# Show top 10 positions by value
print("\nTop 10 positions by value:")
top_positions = latest_df.nlargest(10, 'value')[['ticker', 'shares', 'price', 'value']]
for row in top_positions.to_dict('records'):
    print(f"  {row['ticker']:6s}: {float(row['shares']):>8.2f} shares @ ${float(row['price']):>7.2f} = ${float(row['value']):>10,.2f}")
