#!/usr/bin/env python3
"""
Debug script to test the exact Rich table logic
"""

import sys
import os
import pandas as pd
from pathlib import Path

# Add the parent directory to the path so we can import from trading_script
sys.path.append(str(Path(__file__).parent.parent))

from trading_script import (
    parse_csv_timestamp, 
    get_trading_timezone, 
    get_timezone_config,
    DATA_DIR,
    PORTFOLIO_CSV,
    TRADE_LOG_CSV,
    load_latest_portfolio_state
)

def debug_rich_table_logic():
    """Debug the exact Rich table logic"""
    print("🔍 Debugging Rich Table Logic")
    print("=" * 60)
    
    # Load portfolio using the exact same function as the main script
    print("📁 Loading portfolio using load_latest_portfolio_state...")
    portfolio_df, cash = load_latest_portfolio_state(str(PORTFOLIO_CSV))
    print(f"✅ Portfolio loaded: {len(portfolio_df)} rows")
    print(f"📊 Portfolio columns: {list(portfolio_df.columns)}")
    print(f"📊 Portfolio tickers: {list(portfolio_df['ticker'].unique())}")
    print()
    
    # Load trade log using the exact same logic as create_portfolio_table
    print("📁 Loading trade log...")
    trade_log_df = None
    try:
        trade_log_df = pd.read_csv(TRADE_LOG_CSV)
        print(f"✅ Trade log loaded: {len(trade_log_df)} rows")
        print(f"📊 Trade log columns: {list(trade_log_df.columns)}")
        print(f"📊 Trade log tickers: {list(trade_log_df['Ticker'].unique())}")
        
        # Apply date parsing (exact logic from create_portfolio_table)
        trade_log_df['Date'] = trade_log_df['Date'].apply(parse_csv_timestamp)
        print("✅ Date parsing applied to trade log")
        print(f"📅 Parsed dates sample: {trade_log_df['Date'].head().tolist()}")
        print()
        
    except Exception as e:
        print(f"❌ Error loading trade log: {e}")
        trade_log_df = None
    
    # Test the exact Rich table logic from create_portfolio_table
    print("🔬 Testing Rich Table Logic (exact copy from create_portfolio_table):")
    print("-" * 60)
    
    for i, row in enumerate(portfolio_df.to_dict('records')):
        ticker = str(row.get('ticker', ''))
        print(f"Processing row {i+1}: {ticker}")
        
        # Get position open date from trade log (exact logic from Rich table)
        open_date = "N/A"
        if trade_log_df is not None:
            ticker_trades = trade_log_df[trade_log_df['Ticker'] == ticker]
            print(f"  Found {len(ticker_trades)} matching trades")
            
            if not ticker_trades.empty:
                # Get the earliest trade date for this ticker
                min_date = ticker_trades['Date'].min()
                print(f"  Min date: {min_date} (type: {type(min_date)})")
                
                if not pd.isna(min_date):
                    try:
                        open_date = min_date.strftime("%m/%d")
                        print(f"  ✅ Formatted date: {open_date}")
                    except Exception as e:
                        print(f"  ❌ strftime error: {e}")
                        open_date = "N/A"
                else:
                    print(f"  ❌ Min date is NaN!")
            else:
                print(f"  ❌ No trades found for {ticker}")
        else:
            print(f"  ❌ Trade log is None")
        
        print(f"  📋 Final open_date: {open_date}")
        print()

if __name__ == "__main__":
    debug_rich_table_logic()
