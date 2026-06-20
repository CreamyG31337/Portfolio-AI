#!/usr/bin/env python3
"""
Check when the last trade occurred
"""

import pandas as pd
from pathlib import Path

def check_last_trade():
    # Check if there's a trade log CSV
    trade_files = [
        'trading_data/funds/Project Chimera/trade_log.csv',
        'trading_data/funds/Project Chimera/llm_trade_log.csv',
        'trading_data/funds/Project Chimera/trades.csv'
    ]

    for trade_file in trade_files:
        if Path(trade_file).exists():
            print(f'Found trade file: {trade_file}')
            df = pd.read_csv(trade_file)
            print(f'Columns: {list(df.columns)}')
            print(f'Total trades: {len(df)}')
            
            # Show last 5 trades
            print('\nLast 5 trades:')
            last_trades = df.tail(5)
            for row in last_trades.to_dict('records'):
                date = row.get('Date', row.get('date', 'Unknown'))
                ticker = row.get('Ticker', row.get('ticker', 'Unknown'))
                action = row.get('Action', row.get('action', row.get('Reason', 'Unknown')))
                shares = row.get('Shares', row.get('shares', 'Unknown'))
                price = row.get('Price', row.get('price', 'Unknown'))
                print(f'  {date}: {action} {shares} shares of {ticker} at ${price}')
            return
    
    print('No trade log CSV files found')
    
    # Check the portfolio CSV for trade info
    portfolio_file = Path('trading_data/funds/Project Chimera/llm_portfolio_update.csv')
    if portfolio_file.exists():
        df = pd.read_csv(portfolio_file)
        print(f'\nChecking portfolio CSV for trade info...')
        print(f'Columns: {list(df.columns)}')
        
        # Look for Action column
        if 'Action' in df.columns:
            actions = df['Action'].value_counts()
            print(f'Action counts: {dict(actions)}')
            
            # Show last few entries with actions
            recent = df.tail(10)
            print('\nLast 10 portfolio entries:')
            for row in recent.to_dict('records'):
                if pd.notna(row.get('Action')):
                    print(f'  {row["Date"]}: {row["Action"]} {row["Ticker"]}')
                    
            # Find the last trade date
            trade_entries = df[df['Action'].notna()]
            if len(trade_entries) > 0:
                last_trade = trade_entries.iloc[-1]
                print(f'\nLast trade: {last_trade["Date"]} - {last_trade["Action"]} {last_trade["Ticker"]}')

if __name__ == "__main__":
    check_last_trade()
