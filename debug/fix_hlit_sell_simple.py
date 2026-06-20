#!/usr/bin/env python3
"""
Simple fix for HLIT.TO sell transaction - only update the latest entry
"""

import pandas as pd
from pathlib import Path
import sys

def fix_hlit_sell_simple():
    """Fix HLIT.TO sell transaction by only updating the latest entry."""
    
    print("🔧 Simple HLIT.TO Sell Fix")
    print("=" * 40)
    
    # Load files
    portfolio_file = Path("my trading/llm_portfolio_update.csv")
    trade_log_file = Path("my trading/llm_trade_log.csv")
    
    portfolio_df = pd.read_csv(portfolio_file)
    trade_df = pd.read_csv(trade_log_file)
    
    print(f"📊 Loaded portfolio with {len(portfolio_df)} records")
    print(f"📊 Loaded trade log with {len(trade_df)} records")
    
    # Find HLIT.TO trades
    hlit_trades = trade_df[trade_df['Ticker'] == 'HLIT.TO']
    print(f"\n🔍 HLIT.TO trades:")
    for trade in hlit_trades.to_dict('records'):
        print(f"   {trade['Date']} - {trade['Reason']} - {trade['Shares']} shares @ ${trade['Price']}")
    
    # Calculate net position
    total_buy_shares = 0
    total_buy_cost = 0
    sell_shares = 0
    sell_price = 0
    
    for trade in hlit_trades.to_dict('records'):
        shares = float(trade['Shares'])
        price = float(trade['Price'])
        cost = float(trade['Cost Basis'])
        reason = trade['Reason']
        
        if 'BUY' in reason.upper():
            total_buy_shares += shares
            total_buy_cost += cost
        elif 'SELL' in reason.upper() or 'sell' in reason.lower():
            sell_shares = shares
            sell_price = price
    
    net_shares = total_buy_shares - sell_shares
    print(f"\n📊 HLIT.TO Position:")
    print(f"   Bought: {total_buy_shares} shares for ${total_buy_cost}")
    print(f"   Sold: {sell_shares} shares at ${sell_price}")
    print(f"   Net: {net_shares} shares")
    
    # Find the latest HLIT.TO entry in portfolio
    hlit_entries = portfolio_df[portfolio_df['Ticker'] == 'HLIT.TO']
    if hlit_entries.empty:
        print("❌ No HLIT.TO entries found")
        return False
    
    # Get the latest entry index
    latest_idx = hlit_entries.index[-1]
    latest_entry = hlit_entries.iloc[-1]
    
    print(f"\n🔍 Latest HLIT.TO entry (index {latest_idx}):")
    print(f"   Date: {latest_entry['Date']}")
    print(f"   Current: {latest_entry['Shares']} shares, {latest_entry['Action']}")
    
    # Update only the latest entry
    if sell_shares > 0:
        # This is a sell transaction
        portfolio_df.at[latest_idx, 'Shares'] = net_shares
        portfolio_df.at[latest_idx, 'Average Price'] = round(total_buy_cost / total_buy_shares, 2) if total_buy_shares > 0 else 0
        portfolio_df.at[latest_idx, 'Cost Basis'] = round(total_buy_cost, 2)
        portfolio_df.at[latest_idx, 'Action'] = 'SELL'
        portfolio_df.at[latest_idx, 'Current Price'] = sell_price
        portfolio_df.at[latest_idx, 'Total Value'] = round(net_shares * sell_price, 2)
        
        # Calculate PnL: (sell_price * sold_shares) - (buy_cost)
        pnl = (sell_price * sell_shares) - total_buy_cost
        portfolio_df.at[latest_idx, 'PnL'] = round(pnl, 2)
        
        print(f"\n✅ Updated latest HLIT.TO entry:")
        print(f"   Shares: {latest_entry['Shares']} → {net_shares}")
        print(f"   Action: {latest_entry['Action']} → SELL")
        print(f"   Current Price: {latest_entry['Current Price']} → {sell_price}")
        print(f"   PnL: {latest_entry['PnL']} → {round(pnl, 2)}")
    else:
        print("✅ No sell transaction found")
    
    # Save updated portfolio
    portfolio_df.to_csv(portfolio_file, index=False)
    print(f"\n💾 Portfolio saved to: {portfolio_file}")
    
    return True

if __name__ == "__main__":
    success = fix_hlit_sell_simple()
    sys.exit(0 if success else 1)
