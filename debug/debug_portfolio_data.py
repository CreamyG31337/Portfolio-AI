import pandas as pd
import sys
from pathlib import Path

# Load the data and show what's happening
df = pd.read_csv('trading_data/funds/TEST/llm_portfolio_update.csv')
print('📊 Data shape:', df.shape)
print()

# Show first few rows
print('🔍 First 5 rows:')
print(df[['Date', 'Ticker', 'Total Value', 'Action']].head())
print()

# Group by date and show daily totals
print('📈 Daily portfolio totals:')
df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
df['Total Value'] = pd.to_numeric(df['Total Value'], errors='coerce')

for date, group in df.groupby('Date'):
    if pd.isna(date):
        continue
    total = group['Total Value'].dropna().sum()
    count = len(group)
    print(f'{date.date()}: ${total:,.2f} ({count} positions)')
    if count <= 3:  # Show details for days with few positions
        for row in group.to_dict('records'):
            ticker = row['Ticker']
            value = row['Total Value']
            action = row['Action']
            print(f'  - {ticker}: ${value:.2f} ({action})')
    print()

print("\n🔍 Looking for potential issues:")
print("- Days with very low totals (possible SELL days with $0 positions):")
for date, group in df.groupby('Date'):
    if pd.isna(date):
        continue
    total = group['Total Value'].dropna().sum()
    if total < 500:  # Less than $500 total portfolio
        print(f'  {date.date()}: ${total:.2f}')
        for row in group.to_dict('records'):
            if row['Total Value'] == 0:
                print(f'    - {row["Ticker"]}: ${row["Total Value"]:.2f} ({row["Action"]})')
