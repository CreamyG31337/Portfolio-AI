#!/usr/bin/env python3
"""
Debug script to investigate date parsing issues in trading_script.py
"""

import sys
import os
import pandas as pd
from pathlib import Path

# Add the parent directory to the path so we can import from trading_script
sys.path.append(str(Path(__file__).parent.parent))

from trading_script import parse_csv_timestamp, get_trading_timezone, get_timezone_config

def debug_date_parsing():
    """Debug the date parsing functionality"""
    print("🔍 Debugging Date Parsing Issues")
    print("=" * 50)
    
    # Test data directory
    test_data_dir = Path(__file__).parent.parent / "test_data"
    trade_log_csv = test_data_dir / "llm_trade_log.csv"
    
    print(f"📁 Reading trade log from: {trade_log_csv}")
    
    if not trade_log_csv.exists():
        print("❌ Trade log file not found!")
        return
    
    # Read the CSV
    try:
        trade_log_df = pd.read_csv(trade_log_csv)
        print(f"✅ Successfully read CSV with {len(trade_log_df)} rows")
        print(f"📊 Columns: {list(trade_log_df.columns)}")
        print(f"📅 Date column sample values:")
        print(trade_log_df['Date'].head())
        print()
        
        # Test the parse_csv_timestamp function
        print("🧪 Testing parse_csv_timestamp function:")
        for i, date_str in enumerate(trade_log_df['Date'].head(3)):
            print(f"  Row {i+1}: '{date_str}'")
            try:
                parsed_date = parse_csv_timestamp(date_str)
                print(f"    ✅ Parsed: {parsed_date}")
                print(f"    📅 Type: {type(parsed_date)}")
                if hasattr(parsed_date, 'strftime'):
                    formatted = parsed_date.strftime("%m/%d")
                    print(f"    🎯 Formatted (mm/dd): {formatted}")
                else:
                    print(f"    ❌ No strftime method available")
            except Exception as e:
                print(f"    ❌ Error parsing: {e}")
            print()
        
        # Test the actual logic from trading_script.py
        print("🔬 Testing the actual portfolio display logic:")
        print("-" * 40)
        
        # Simulate the logic from the script
        for ticker in trade_log_df['Ticker'].unique():
            print(f"🎯 Testing ticker: {ticker}")
            ticker_trades = trade_log_df[trade_log_df['Ticker'] == ticker]
            print(f"   Found {len(ticker_trades)} trades")
            
            if not ticker_trades.empty:
                # Parse dates
                ticker_trades_copy = ticker_trades.copy()
                ticker_trades_copy['Date'] = ticker_trades_copy['Date'].apply(parse_csv_timestamp)
                
                print(f"   📅 Parsed dates:")
                for row in ticker_trades_copy.itertuples():
                    print(f"     Row {row.Index}: {row.Date} (type: {type(row.Date)})")
                
                # Test min() operation
                try:
                    min_date = ticker_trades_copy['Date'].min()
                    print(f"   📊 Min date: {min_date} (type: {type(min_date)})")
                    
                    if pd.isna(min_date):
                        print("   ❌ Min date is NaN!")
                    else:
                        # Test strftime
                        try:
                            formatted_date = min_date.strftime("%m/%d")
                            print(f"   ✅ Formatted date: {formatted_date}")
                        except Exception as e:
                            print(f"   ❌ strftime error: {e}")
                except Exception as e:
                    print(f"   ❌ Min date error: {e}")
            print()
        
    except Exception as e:
        print(f"❌ Error reading CSV: {e}")

def debug_timezone_config():
    """Debug timezone configuration"""
    print("\n🌍 Debugging Timezone Configuration")
    print("=" * 50)
    
    try:
        tz_config = get_timezone_config()
        print(f"📋 Timezone config: {tz_config}")
        
        tz = get_trading_timezone()
        print(f"🕐 Trading timezone: {tz}")
        
    except Exception as e:
        print(f"❌ Timezone config error: {e}")

if __name__ == "__main__":
    debug_timezone_config()
    debug_date_parsing()
