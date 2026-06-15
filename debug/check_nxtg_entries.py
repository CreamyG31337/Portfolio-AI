#!/usr/bin/env python3
"""
Check all NXTG entries in the portfolio
"""

import pandas as pd

def check_nxtg_entries():
    """Check all NXTG entries in the portfolio."""
    
    # Check the latest portfolio data for NXTG
    df = pd.read_csv('trading_data/funds/RRSP Lance Webull/llm_portfolio_update.csv')
    nxtg_entries = df[df['Ticker'] == 'NXTG']

    print('All NXTG entries in portfolio:')
    print('=' * 50)

    for row in nxtg_entries.to_dict('records'):
        print(f'Date: {row["Date"]}')
        print(f'  Company: {row["Company"]}')
        print(f'  Shares: {row["Shares"]}')
        print(f'  Avg Price: ${row["Average Price"]:.2f}')
        print(f'  Current Price: ${row["Current Price"]:.2f}')
        print(f'  P&L: ${row["PnL"]:.2f}')
        print(f'  Total Value: ${row["Total Value"]:.2f}')
        print(f'  Currency: {row["Currency"]}')
        print()

if __name__ == "__main__":
    check_nxtg_entries()
