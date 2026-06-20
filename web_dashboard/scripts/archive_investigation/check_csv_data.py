#!/usr/bin/env python3
"""
Check CSV data for P&L values
"""

import pandas as pd
from pathlib import Path

def check_csv_data():
    # Check the CSV file to see what data is there
    csv_file = Path('trading_data/funds/Project Chimera/llm_portfolio_update.csv')
    if csv_file.exists():
        df = pd.read_csv(csv_file)
        print(f'CSV file exists with {len(df)} rows')

        # Check recent entries
        recent = df.tail(5)
        print('Recent CSV entries:')
        for row in recent.to_dict('records'):
            print(f'  {row["Date"]}: {row["Ticker"]} - PnL: ${row.get("PnL", "N/A")}')

        # Check if there are any non-zero PnL values
        non_zero_pnl = df[df['PnL'] != 0]
        print(f'Entries with non-zero PnL: {len(non_zero_pnl)}')

        if len(non_zero_pnl) > 0:
            print('Sample non-zero PnL:')
            for row in non_zero_pnl.head(3).to_dict('records'):
                print(f'  {row["Ticker"]}: ${row["PnL"]}')
    else:
        print('CSV file does not exist')

if __name__ == "__main__":
    check_csv_data()
