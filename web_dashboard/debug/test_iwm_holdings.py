#!/usr/bin/env python3
"""
Test script to investigate IWM holdings comparison issue.
Checks why IWM is flagging all holdings as changes.
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from supabase_client import SupabaseClient
from scheduler.jobs_etf_watchtower import (
    fetch_ishares_holdings,
    get_previous_holdings,
    calculate_diff,
    ETF_CONFIGS
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    etf_ticker = "IWM"
    db = SupabaseClient(use_service_role=True)
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    print("=" * 80)
    print(f"Testing {etf_ticker} Holdings Comparison")
    print("=" * 80)
    
    # 1. Fetch today's holdings
    print(f"\n1. Fetching today's {etf_ticker} holdings from iShares...")
    config = ETF_CONFIGS[etf_ticker]
    today_holdings = fetch_ishares_holdings(etf_ticker, config['url'])
    
    if today_holdings is None or today_holdings.empty:
        print(f"[ERROR] Failed to fetch today's holdings")
        return
    
    print(f"[OK] Fetched {len(today_holdings)} holdings")
    print(f"   Columns: {today_holdings.columns.tolist()}")
    print(f"\n   Sample tickers (first 10):")
    for ticker in today_holdings['ticker'].head(10):
        print(f"     '{ticker}' (type: {type(ticker).__name__}, len: {len(str(ticker))})")
    
    # 2. Get previous holdings from database
    print(f"\n2. Fetching previous {etf_ticker} holdings from database...")
    yesterday_holdings = get_previous_holdings(db, etf_ticker, today)
    
    if yesterday_holdings.empty:
        print(f"[WARNING] No previous holdings found in database")
        print(f"   This means this is the first snapshot - all holdings will appear as 'new'")
        
        # Check if there's ANY data for IWM
        print(f"\n   Checking if ANY IWM data exists in database...")
        result = db.supabase.table('etf_holdings_log').select('date, etf_ticker').eq('etf_ticker', etf_ticker).execute()
        if result.data:
            dates = sorted(set(r['date'] for r in result.data), reverse=True)
            print(f"   Found {len(dates)} dates: {dates[:5]}")
            if dates:
                latest_date = dates[0]
                print(f"   Latest date: {latest_date}")
                print(f"   Today's date: {today.date()}")
                if latest_date == today.date().isoformat():
                    print(f"   ⚠️  Latest date matches today - checking if data was saved today...")
                    # Get holdings for today
                    today_result = db.supabase.table('etf_holdings_log').select(
                        'holding_ticker, shares_held'
                    ).eq('etf_ticker', etf_ticker).eq('date', latest_date).limit(10).execute()
                    if today_result.data:
                        print(f"   Found {len(today_result.data)} holdings for today")
                        print(f"   Sample: {today_result.data[:3]}")
        return
    
    print(f"[OK] Found {len(yesterday_holdings)} previous holdings")
    print(f"   Columns: {yesterday_holdings.columns.tolist()}")
    print(f"\n   Sample tickers (first 10):")
    for ticker in yesterday_holdings['ticker'].head(10):
        print(f"     '{ticker}' (type: {type(ticker).__name__}, len: {len(str(ticker))})")
    
    # 3. Compare ticker formats
    print(f"\n3. Comparing ticker formats...")
    today_tickers = set(today_holdings['ticker'].str.upper().str.strip())
    yesterday_tickers = set(yesterday_holdings['ticker'].str.upper().str.strip())
    
    print(f"   Today: {len(today_tickers)} unique tickers")
    print(f"   Yesterday: {len(yesterday_tickers)} unique tickers")
    print(f"   Common tickers: {len(today_tickers & yesterday_tickers)}")
    print(f"   Only in today: {len(today_tickers - yesterday_tickers)}")
    print(f"   Only in yesterday: {len(yesterday_tickers - today_tickers)}")
    
    if len(today_tickers & yesterday_tickers) == 0:
        print(f"\n   ❌ NO MATCHING TICKERS! This explains why everything is flagged as a change.")
        print(f"   Sample today tickers: {sorted(list(today_tickers))[:10]}")
        print(f"   Sample yesterday tickers: {sorted(list(yesterday_tickers))[:10]}")
        
        # Check for whitespace or formatting differences
        print(f"\n   Checking for formatting differences...")
        today_sample = sorted(list(today_tickers))[:5]
        yesterday_sample = sorted(list(yesterday_tickers))[:5]
        for t_today in today_sample:
            for t_yest in yesterday_sample:
                if t_today.replace(' ', '') == t_yest.replace(' ', ''):
                    print(f"     Found similar: '{t_today}' vs '{t_yest}'")
                if t_today.strip() == t_yest.strip() and t_today != t_yest:
                    print(f"     Found whitespace diff: '{t_today}' vs '{t_yest}'")
    else:
        print(f"   [OK] Found {len(today_tickers & yesterday_tickers)} matching tickers")
    
    # 4. Run the actual diff calculation
    print(f"\n4. Running calculate_diff()...")
    changes = calculate_diff(today_holdings, yesterday_holdings, etf_ticker)
    
    print(f"   Found {len(changes)} significant changes")
    if changes:
        print(f"\n   Sample changes (first 5):")
        for change in changes[:5]:
            print(f"     {change['ticker']}: {change['share_diff']:,.0f} shares ({change['percent_change']:.1f}%)")
    
    # 5. Check if shares match for common tickers
    print(f"\n5. Checking share values for common tickers...")
    common_tickers = today_tickers & yesterday_tickers
    if common_tickers:
        sample_tickers = sorted(list(common_tickers))[:5]
        for ticker in sample_tickers:
            today_row = today_holdings[today_holdings['ticker'].str.upper().str.strip() == ticker]
            yest_row = yesterday_holdings[yesterday_holdings['ticker'].str.upper().str.strip() == ticker]
            
            if not today_row.empty and not yest_row.empty:
                today_shares = today_row.iloc[0]['shares']
                yest_shares = yest_row.iloc[0]['shares']
                diff = today_shares - yest_shares
                pct = (diff / yest_shares * 100) if yest_shares != 0 else 0
                print(f"   {ticker}: {yest_shares:,.0f} -> {today_shares:,.0f} (diff: {diff:,.0f}, {pct:.2f}%)")
    
    print("\n" + "=" * 80)
    print("Investigation complete!")
    print("=" * 80)

if __name__ == "__main__":
    main()
