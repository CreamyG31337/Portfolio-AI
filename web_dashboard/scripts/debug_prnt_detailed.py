import sys
import logging
from pathlib import Path
import pandas as pd

# Add project root to path
sys.path.append(str(Path.cwd()))

from web_dashboard.scheduler.jobs_etf_watchtower import (
    fetch_ark_holdings,
    get_previous_holdings,
    is_stock_ticker,
    MIN_SHARE_CHANGE,
    MIN_PERCENT_CHANGE
)
from supabase_client import SupabaseClient
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)

db = SupabaseClient(use_service_role=True)

_ARK_BASE = "https://assets.ark-funds.com"
PRNT_URL = f"{_ARK_BASE}/fund-documents/funds-etf-csv/THE_3D_PRINTING_ETF_PRNT_HOLDINGS.csv"

print("=" * 80)
print("DEBUGGING PRNT ETF")
print("=" * 80)

# Fetch today's holdings
today = fetch_ark_holdings('PRNT', PRNT_URL)
print(f"\nToday's holdings: {len(today)} stocks")
print(f"Sample tickers: {today['ticker'].head(10).tolist()}")

# Fetch yesterday's holdings
yesterday = get_previous_holdings(db, 'PRNT', datetime(2026, 1, 24))
print(f"\nYesterday's holdings: {len(yesterday)} stocks")
print(f"Sample tickers: {yesterday['ticker'].head(10).tolist()}")

# Merge and calculate diff
merged = today.merge(
    yesterday,
    on='ticker',
    how='outer',
    suffixes=('_now', '_prev')
)

merged['shares_now'] = merged['shares_now'].fillna(0)
merged['shares_prev'] = merged['shares_prev'].fillna(0)
merged['share_diff'] = merged['shares_now'] - merged['shares_prev']
merged['percent_change'] = ((merged['share_diff'] / merged['shares_prev']) * 100).replace([float('inf'), -float('inf')], 100)

print(f"\nMerged: {len(merged)} total positions")
print(f"\nShare diff stats:")
print(merged['share_diff'].describe())

# Filter for significant changes
significant = merged[
    (merged['share_diff'].abs() >= MIN_SHARE_CHANGE) |
    (merged['percent_change'].abs() >= MIN_PERCENT_CHANGE)
].copy()

print(f"\nSignificant changes (before ticker filter): {len(significant)}")
print(f"MIN_SHARE_CHANGE: {MIN_SHARE_CHANGE}")
print(f"MIN_PERCENT_CHANGE: {MIN_PERCENT_CHANGE}")

if len(significant) > 0:
    print("\nTop changes:")
    print(significant[['ticker', 'share_diff', 'percent_change']].head(10))

    # Check which tickers pass the stock filter
    print("\n" + "=" * 80)
    print("TICKER FILTERING")
    print("=" * 80)
    for _, row in significant.head(10).iterrows():
        ticker = row['ticker']
        is_stock = is_stock_ticker(ticker)
        print(f"{ticker:10} -> is_stock_ticker = {is_stock}")

    # Apply stock filter
    significant_stocks = significant[significant['ticker'].apply(is_stock_ticker)].copy()
    print(f"\nSignificant changes (after ticker filter): {len(significant_stocks)}")
else:
    print("\nNo significant changes found!")
    print("\nAll changes:")
    print(merged[merged['share_diff'] != 0][['ticker', 'share_diff', 'percent_change']])
