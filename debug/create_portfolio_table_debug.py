#!/usr/bin/env python3
"""
Debug script to test the exact create_portfolio_table function logic
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

def debug_create_portfolio_table_logic():
    """Debug the exact create_portfolio_table function logic"""
    print("🔍 Debugging create_portfolio_table Logic")
    print("=" * 60)
    
    # Load portfolio using the exact same function as the main script
    print("📁 Loading portfolio using load_latest_portfolio_state...")
    portfolio_df, cash = load_latest_portfolio_state(str(PORTFOLIO_CSV))
    print(f"_safe_emoji('✅') Portfolio loaded: {len(portfolio_df)} rows")
    print(f"_safe_emoji('📊') Portfolio columns: {list(portfolio_df.columns)}")
    print(f"_safe_emoji('📊') Portfolio tickers: {list(portfolio_df['ticker'].unique())}")
    print()
    
    # Load trade log using the exact same logic as create_portfolio_table
    print("📁 Loading trade log...")
    trade_log_df = None
    try:
        trade_log_df = pd.read_csv(TRADE_LOG_CSV)
        print(f"_safe_emoji('✅') Trade log loaded: {len(trade_log_df)} rows")
        print(f"_safe_emoji('📊') Trade log columns: {list(trade_log_df.columns)}")
        print(f"_safe_emoji('📊') Trade log tickers: {list(trade_log_df['Ticker'].unique())}")
        
        # Apply date parsing (exact logic from create_portfolio_table)
        trade_log_df['Date'] = trade_log_df['Date'].apply(parse_csv_timestamp)
        print("_safe_emoji('✅') Date parsing applied to trade log")
        print(f"📅 Parsed dates sample: {trade_log_df['Date'].head().tolist()}")
        print()
        
    except Exception as e:
        print(f"❌ Error loading trade log: {e}")
        trade_log_df = None
    
    # Test the exact fallback mode logic from create_portfolio_table
    print("🔬 Testing Fallback Mode Logic (exact copy from create_portfolio_table):")
    print("-" * 60)
    
    # Create display_df (exact logic from create_portfolio_table)
    display_df = portfolio_df.copy()
    print(f"_safe_emoji('📊') Display DF shape: {display_df.shape}")
    print(f"_safe_emoji('📊') Display DF columns: {list(display_df.columns)}")
    print()
    
    # Add position open dates (exact logic from create_portfolio_table lines 485-499)
    open_dates = []
    if trade_log_df is not None:
        print("_safe_emoji('✅') Trade log is not None, processing dates...")
        for i, row in enumerate(display_df.to_dict('records')):
            ticker = str(row.get('ticker', ''))
            print(f"  Processing row {i+1}: {ticker}")
            
            ticker_trades = trade_log_df[trade_log_df['Ticker'] == ticker]
            print(f"    Found {len(ticker_trades)} matching trades")
            
            if not ticker_trades.empty:
                print(f"    Trades found, getting min date...")
                min_date = ticker_trades['Date'].min()
                print(f"    Min date: {min_date} (type: {type(min_date)})")
                
                if pd.isna(min_date):
                    print(f"    ❌ Min date is NaN!")
                    open_dates.append("N/A")
                else:
                    try:
                        open_date = min_date.strftime("%m/%d")
                        print(f"    _safe_emoji('✅') Formatted date: {open_date}")
                        open_dates.append(open_date)
                    except Exception as e:
                        print(f"    ❌ strftime error: {e}")
                        open_dates.append("N/A")
            else:
                print(f"    ❌ No trades found for {ticker}")
                open_dates.append("N/A")
            print()
    else:
        print("❌ Trade log is None, using N/A for all dates")
        open_dates = ["N/A"] * len(display_df)
    
    print(f"📋 Final open_dates: {open_dates}")
    display_df['Opened'] = open_dates
    
    # Show the final result
    print("\n_safe_emoji('📊') Final Display DataFrame:")
    print(display_df[['ticker', 'Opened']].to_string(index=False))

if __name__ == "__main__":
    debug_create_portfolio_table_logic()
