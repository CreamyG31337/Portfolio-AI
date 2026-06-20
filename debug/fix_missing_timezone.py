#!/usr/bin/env python3
"""
Fix missing timezone in trade log CSV file.

This script fixes the row that has missing timezone information by adding PST/PDT
based on the date.
"""

import pandas as pd
from pathlib import Path
from datetime import datetime
import sys
sys.path.append('.')
from market_config import _is_dst

def fix_missing_timezone_in_trade_log():
    """Fix missing timezone in the trade log CSV file."""
    trade_log_path = Path("my trading/llm_trade_log.csv")
    
    if not trade_log_path.exists():
        print(f"❌ Trade log file not found: {trade_log_path}")
        return
    
    # Read the CSV file
    df = pd.read_csv(trade_log_path)
    
    print(f"📊 Found {len(df)} rows in trade log")
    
    # Check for rows with missing timezone (ending with space)
    problematic_rows = []
    # itertuples preserves the index label needed by df.at[idx, ...] below.
    for row in df.itertuples():
        date_str = str(row.Date)
        if date_str.endswith(' '):
            problematic_rows.append((row.Index, date_str))
            print(f"⚠️  Found problematic row {row.Index}: '{date_str}'")
    
    if not problematic_rows:
        print("✅ No problematic rows found")
        return
    
    # Fix each problematic row
    for idx, date_str in problematic_rows:
        # Extract the date part (remove trailing space)
        clean_date = date_str.strip()
        
        # Parse the date to determine if it's DST
        try:
            dt = datetime.strptime(clean_date, '%Y-%m-%d %H:%M:%S')
            tz_name = "PDT" if _is_dst(dt) else "PST"
            fixed_date = f"{clean_date} {tz_name}"
            
            # Update the dataframe
            df.at[idx, 'Date'] = fixed_date
            print(f"✅ Fixed row {idx}: '{date_str}' -> '{fixed_date}'")
            
        except ValueError as e:
            print(f"❌ Could not parse date '{clean_date}': {e}")
    
    # Save the fixed CSV
    df.to_csv(trade_log_path, index=False)
    print(f"💾 Saved fixed trade log to {trade_log_path}")
    
    # Verify the fix
    print("\n🔍 Verification:")
    df_verify = pd.read_csv(trade_log_path)
    for row in df_verify.itertuples():
        date_str = str(row.Date)
        if date_str.endswith(' '):
            print(f"❌ Row {row.Index} still has trailing space: '{date_str}'")
        else:
            print(f"✅ Row {row.Index} looks good: '{date_str}'")

if __name__ == "__main__":
    fix_missing_timezone_in_trade_log()
