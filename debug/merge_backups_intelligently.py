#!/usr/bin/env python3
"""
Intelligently merge the two portfolio backups:
- Use the latest data from 2025-09-12 backup (has all the recent data)
- Add the missing HLIT.TO buy entry from 2025-09-11 backup
- Add the HLIT.TO sell entry based on trade log
"""

import pandas as pd
from pathlib import Path
import sys
from datetime import datetime

def merge_backups_intelligently():
    """Intelligently merge the two portfolio backups."""
    
    print("🔧 Intelligently Merging Portfolio Backups")
    print("=" * 50)
    
    # Load the latest backup (has all recent data)
    latest_backup = Path("my trading/llm_portfolio_update.csv.backup_20250912_224435")
    older_backup = Path("my trading/backups/llm_portfolio_update.csv.backup_20250911_131554")
    trade_log_file = Path("my trading/llm_trade_log.csv")
    
    if not latest_backup.exists():
        print(f"❌ Latest backup not found: {latest_backup}")
        return False
    
    if not older_backup.exists():
        print(f"❌ Older backup not found: {older_backup}")
        return False
    
    if not trade_log_file.exists():
        print(f"❌ Trade log not found: {trade_log_file}")
        return False
    
    # Load data
    latest_df = pd.read_csv(latest_backup)
    older_df = pd.read_csv(older_backup)
    trade_df = pd.read_csv(trade_log_file)
    
    print(f"📊 Latest backup: {len(latest_df)} records")
    print(f"📊 Older backup: {len(older_df)} records")
    print(f"📊 Trade log: {len(trade_df)} records")
    
    # Find HLIT.TO buy entry from older backup
    hlit_buy = older_df[older_df['Ticker'] == 'HLIT.TO']
    if hlit_buy.empty:
        print("❌ No HLIT.TO buy entry found in older backup")
        return False
    
    hlit_buy_entry = hlit_buy.iloc[0]
    print(f"\n🔍 Found HLIT.TO buy entry:")
    print(f"   Date: {hlit_buy_entry['Date']}")
    print(f"   Shares: {hlit_buy_entry['Shares']}")
    print(f"   Action: {hlit_buy_entry['Action']}")
    
    # Find HLIT.TO sell trade
    hlit_sell = trade_df[(trade_df['Ticker'] == 'HLIT.TO') & (trade_df['Reason'].str.contains('sell', case=False))]
    if hlit_sell.empty:
        print("❌ No HLIT.TO sell trade found")
        return False
    
    sell_trade = hlit_sell.iloc[0]
    print(f"\n🔍 Found HLIT.TO sell trade:")
    print(f"   Date: {sell_trade['Date']}")
    print(f"   Shares: {sell_trade['Shares']}")
    print(f"   Price: ${sell_trade['Price']}")
    print(f"   PnL: ${sell_trade['PnL']}")
    
    # Start with the latest backup (has all recent data)
    merged_df = latest_df.copy()
    
    # Add the HLIT.TO buy entry (insert it in chronological order)
    buy_date = hlit_buy_entry['Date']
    buy_row = hlit_buy_entry.copy()
    
    # Find the right position to insert the buy entry
    insert_idx = 0
    for row in merged_df.itertuples():
        if row.Date > buy_date:
            insert_idx = row.Index
            break
        insert_idx = row.Index + 1
    
    # Insert the buy entry
    merged_df = pd.concat([
        merged_df.iloc[:insert_idx],
        pd.DataFrame([buy_row]),
        merged_df.iloc[insert_idx:]
    ], ignore_index=True)
    
    print(f"\n➕ Added HLIT.TO buy entry at position {insert_idx}")
    
    # Add the HLIT.TO sell entry
    sell_date = sell_trade['Date']
    sell_shares = float(sell_trade['Shares'])
    sell_price = float(sell_trade['Price'])
    sell_pnl = float(sell_trade['PnL'])
    
    sell_entry = {
        'Date': sell_date,
        'Ticker': 'HLIT.TO',
        'Shares': 0.0,  # 0 shares remaining after sell
        'Average Price': 0.0,
        'Cost Basis': 0.0,
        'Stop Loss': 0.0,
        'Current Price': sell_price,
        'Total Value': 0.0,
        'PnL': sell_pnl,
        'Action': 'SELL',
        'Company': hlit_buy_entry['Company'],
        'Currency': hlit_buy_entry['Currency']
    }
    
    # Find position for sell entry
    sell_insert_idx = 0
    for row in merged_df.itertuples():
        if row.Date > sell_date:
            sell_insert_idx = row.Index
            break
        sell_insert_idx = row.Index + 1
    
    # Insert the sell entry
    merged_df = pd.concat([
        merged_df.iloc[:sell_insert_idx],
        pd.DataFrame([sell_entry]),
        merged_df.iloc[sell_insert_idx:]
    ], ignore_index=True)
    
    print(f"➕ Added HLIT.TO sell entry at position {sell_insert_idx}")
    
    # Sort by Date to ensure chronological order
    merged_df = merged_df.sort_values('Date').reset_index(drop=True)
    
    # Save the merged portfolio
    output_file = Path("my trading/llm_portfolio_update.csv")
    merged_df.to_csv(output_file, index=False)
    
    print(f"\n💾 Merged portfolio saved to: {output_file}")
    print(f"✅ Final portfolio has {len(merged_df)} records")
    
    # Show HLIT.TO entries
    hlit_entries = merged_df[merged_df['Ticker'] == 'HLIT.TO']
    print(f"\n🔍 HLIT.TO entries in final portfolio:")
    for entry in hlit_entries.itertuples():
        print(f"   Row {entry.Index}: {entry.Date} - {entry.Action} - {entry.Shares} shares")
    
    return True

if __name__ == "__main__":
    success = merge_backups_intelligently()
    sys.exit(0 if success else 1)
