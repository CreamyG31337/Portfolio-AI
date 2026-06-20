#!/usr/bin/env python3
"""
Add HLIT.TO sell entry - keep the buy entry and add a new sell entry
"""

import pandas as pd
from pathlib import Path
import sys
from datetime import datetime

def add_hlit_sell_entry():
    """Add a new HLIT.TO sell entry while keeping the buy entry intact."""
    
    print("🔧 Adding HLIT.TO Sell Entry")
    print("=" * 40)
    
    # Load files
    portfolio_file = Path("my trading/llm_portfolio_update.csv")
    trade_log_file = Path("my trading/llm_trade_log.csv")
    
    portfolio_df = pd.read_csv(portfolio_file)
    trade_df = pd.read_csv(trade_log_file)
    
    print(f"📊 Loaded portfolio with {len(portfolio_df)} records")
    print(f"📊 Loaded trade log with {len(trade_df)} records")
    
    # Find HLIT.TO sell trade
    hlit_sell = trade_df[(trade_df['Ticker'] == 'HLIT.TO') & (trade_df['Reason'].str.contains('sell', case=False))]
    
    if hlit_sell.empty:
        print("❌ No HLIT.TO sell transaction found in trade log")
        return False
    
    sell_trade = hlit_sell.iloc[0]
    print(f"\n🔍 Found HLIT.TO sell trade:")
    print(f"   Date: {sell_trade['Date']}")
    print(f"   Shares: {sell_trade['Shares']}")
    print(f"   Price: ${sell_trade['Price']}")
    print(f"   PnL: ${sell_trade['PnL']}")
    
    # Find the latest HLIT.TO entry to get company info
    hlit_entries = portfolio_df[portfolio_df['Ticker'] == 'HLIT.TO']
    if hlit_entries.empty:
        print("❌ No HLIT.TO entries found in portfolio")
        return False
    
    latest_hlit = hlit_entries.iloc[-1]
    
    # Create new sell entry
    sell_date = sell_trade['Date']
    sell_shares = float(sell_trade['Shares'])
    sell_price = float(sell_trade['Price'])
    sell_pnl = float(sell_trade['PnL'])
    
    new_entry = {
        'Date': sell_date,
        'Ticker': 'HLIT.TO',
        'Shares': 0.0,  # 0 shares remaining after sell
        'Average Price': 0.0,  # Not applicable for sell
        'Cost Basis': 0.0,  # Not applicable for sell
        'Stop Loss': 0.0,
        'Current Price': sell_price,
        'Total Value': 0.0,  # 0 shares * price = 0
        'PnL': sell_pnl,
        'Action': 'SELL',
        'Company': latest_hlit['Company'],
        'Currency': latest_hlit['Currency']
    }
    
    print(f"\n➕ Adding new SELL entry:")
    print(f"   Date: {new_entry['Date']}")
    print(f"   Ticker: {new_entry['Ticker']}")
    print(f"   Shares: {new_entry['Shares']}")
    print(f"   Action: {new_entry['Action']}")
    print(f"   Current Price: ${new_entry['Current Price']}")
    print(f"   PnL: ${new_entry['PnL']}")
    
    # Add the new entry to the portfolio
    portfolio_df = pd.concat([portfolio_df, pd.DataFrame([new_entry])], ignore_index=True)
    
    # Sort by Date to maintain chronological order
    portfolio_df = portfolio_df.sort_values('Date').reset_index(drop=True)
    
    # Save updated portfolio
    portfolio_df.to_csv(portfolio_file, index=False)
    print(f"\n💾 Portfolio updated and saved to: {portfolio_file}")
    
    # Verify the result
    print(f"\n✅ Verification - Portfolio now has {len(portfolio_df)} records")
    hlit_entries_after = portfolio_df[portfolio_df['Ticker'] == 'HLIT.TO']
    print(f"   HLIT.TO entries: {len(hlit_entries_after)}")
    
    for entry in hlit_entries_after.itertuples():
        print(f"   Row {entry.Index}: {entry.Date} - {entry.Action} - {entry.Shares} shares")
    
    return True

if __name__ == "__main__":
    success = add_hlit_sell_entry()
    sys.exit(0 if success else 1)
