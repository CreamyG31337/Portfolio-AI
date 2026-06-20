#!/usr/bin/env python3
"""
Monitor portfolio data file to detect corruption during testing.
"""

import pandas as pd
import time
from pathlib import Path
from datetime import datetime

def monitor_portfolio_file():
    """Monitor the portfolio CSV file for changes and corruption."""
    file_path = Path('trading_data/funds/TEST/llm_portfolio_update.csv')
    
    print("🔍 Portfolio Data Monitor")
    print("=" * 50)
    print(f"Monitoring: {file_path}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Get initial state
    initial_size = file_path.stat().st_size
    initial_mtime = file_path.stat().st_mtime
    
    try:
        df_initial = pd.read_csv(file_path)
        initial_entries = len(df_initial)
        print(f"Initial state: {initial_entries} entries, {initial_size} bytes")
        
        # Check for suspicious data
        check_for_corruption(df_initial, "Initial")
        
    except Exception as e:
        print(f"❌ Error reading initial file: {e}")
        return
    
    print("\nMonitoring for changes... (Press Ctrl+C to stop)")
    
    try:
        while True:
            time.sleep(5)  # Check every 5 seconds
            
            if not file_path.exists():
                print(f"⚠️  File disappeared: {datetime.now().strftime('%H:%M:%S')}")
                continue
                
            current_size = file_path.stat().st_size
            current_mtime = file_path.stat().st_mtime
            
            if current_mtime != initial_mtime:
                print(f"📝 File changed: {datetime.now().strftime('%H:%M:%S')}")
                print(f"   Size: {initial_size} → {current_size} bytes")
                
                try:
                    df_current = pd.read_csv(file_path)
                    current_entries = len(df_current)
                    print(f"   Entries: {initial_entries} → {current_entries}")
                    
                    # Check for corruption
                    check_for_corruption(df_current, "Current")
                    
                    # Update baseline
                    initial_size = current_size
                    initial_mtime = current_mtime
                    initial_entries = current_entries
                    df_initial = df_current
                    
                except Exception as e:
                    print(f"❌ Error reading updated file: {e}")
                    
            time.sleep(1)  # Brief pause
            
    except KeyboardInterrupt:
        print(f"\n🛑 Monitoring stopped: {datetime.now().strftime('%H:%M:%S')}")

def check_for_corruption(df, label):
    """Check for signs of data corruption."""
    print(f"\n🔍 {label} corruption check:")
    
    # Check for suspicious prices
    suspicious_prices = df[
        (df['Current Price'] < 0.01) | 
        (df['Current Price'] > 10000) |
        (df['Current Price'].isna())
    ]
    
    if not suspicious_prices.empty:
        print(f"   ⚠️  Suspicious prices found: {len(suspicious_prices)} entries")
        for row in suspicious_prices.head(3).to_dict('records'):
            print(f"      {row['Ticker']}: ${row['Current Price']}")
    else:
        print("   ✅ No suspicious prices")
    
    # Check for duplicate entries
    duplicates = df.duplicated(subset=['Ticker', 'Date'], keep=False)
    if duplicates.any():
        print(f"   ⚠️  Duplicate entries found: {duplicates.sum()} rows")
    else:
        print("   ✅ No duplicate entries")
    
    # Check for missing data
    missing_data = df.isnull().sum()
    if missing_data.any():
        print(f"   ⚠️  Missing data:")
        for col, count in missing_data[missing_data > 0].items():
            print(f"      {col}: {count} missing")
    else:
        print("   ✅ No missing data")
    
    # Check specific problematic tickers
    problem_tickers = ['DOL.TO', 'NXTG', 'KEY']
    for ticker in problem_tickers:
        ticker_data = df[df['Ticker'] == ticker]
        if not ticker_data.empty:
            latest = ticker_data.iloc[-1]
            price = latest['Current Price']
            if price < 1 or price > 1000:
                print(f"   ⚠️  {ticker}: Suspicious price ${price}")
            else:
                print(f"   ✅ {ticker}: Price ${price} looks normal")

if __name__ == "__main__":
    monitor_portfolio_file()
