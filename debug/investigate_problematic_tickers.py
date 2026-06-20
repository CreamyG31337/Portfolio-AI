#!/usr/bin/env python3
"""
Investigate problematic tickers to understand the data issues
"""

import sys
from pathlib import Path
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

def investigate_problematic_tickers():
    """Investigate the problematic tickers to understand the data issues."""
    
    # Check the original trade data for these problematic tickers
    df = pd.read_csv('trading_data/funds/RRSP Lance Webull/llm_trade_log.csv')
    
    problematic_tickers = ['KEY', 'NXTG', 'DOL']
    
    print('Original trade data for problematic tickers:')
    print('=' * 60)
    
    for ticker in problematic_tickers:
        trades = df[df['Ticker'] == ticker]
        if not trades.empty:
            print(f'\n{ticker}:')
            for trade in trades.to_dict('records'):
                print(f'  {trade["Date"]} | {trade["Shares"]} shares @ ${trade["Price"]:.2f} | P&L: ${trade["PnL"]:.2f}')
        else:
            print(f'\n{ticker}: No trades found in trade log')
    
    print('\n' + '=' * 60)
    print('Checking if these are in the original Webull data:')
    print('=' * 60)
    
    # Check original Webull data
    webull_df = pd.read_csv('trading_data/funds/RRSP Lance Webull/webull trades raw.csv')
    print('Original Webull symbols:')
    print(webull_df['Symbol'].unique())
    
    print('\n' + '=' * 60)
    print('Checking current portfolio data:')
    print('=' * 60)
    
    # Check current portfolio data
    portfolio_df = pd.read_csv('trading_data/funds/RRSP Lance Webull/llm_portfolio_update.csv')
    
    for ticker in problematic_tickers:
        entries = portfolio_df[portfolio_df['Ticker'] == ticker]
        if not entries.empty:
            latest = entries.iloc[-1]
            print(f'\n{ticker} (latest entry):')
            print(f'  Company: {latest["Company"]}')
            print(f'  Shares: {latest["Shares"]}')
            print(f'  Avg Price: ${latest["Average Price"]:.2f}')
            print(f'  Current Price: ${latest["Current Price"]:.2f}')
            print(f'  Currency: {latest["Currency"]}')
            print(f'  P&L: ${latest["PnL"]:.2f}')
            print(f'  Total Value: ${latest["Total Value"]:.2f}')
        else:
            print(f'\n{ticker}: Not found in portfolio')
    
    print('\n' + '=' * 60)
    print('Checking if these tickers exist in the original Webull data:')
    print('=' * 60)
    
    for ticker in problematic_tickers:
        if ticker in webull_df['Symbol'].values:
            print(f'{ticker}: Found in Webull data')
            webull_trades = webull_df[webull_df['Symbol'] == ticker]
            for trade in webull_trades.to_dict('records'):
                print(f'  {trade["Side"]} {trade["Filled Qty"]} @ ${trade["Average Filled Price"]:.2f} on {trade["Filled Time"]}')
        else:
            print(f'{ticker}: NOT found in Webull data')

if __name__ == "__main__":
    investigate_problematic_tickers()
