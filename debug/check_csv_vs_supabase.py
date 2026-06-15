#!/usr/bin/env python3
"""
Check CSV vs Supabase data to understand the performance difference
"""

import pandas as pd
from pathlib import Path
import os
import sys
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from data.repositories.repository_factory import RepositoryFactory

def check_data_differences():
    print("=== Checking CSV vs Supabase Data ===")
    
    # Load CSV data
    csv_file = Path('trading_data/funds/Project Chimera/llm_portfolio_update.csv')
    df = pd.read_csv(csv_file)
    
    print(f"CSV entries: {len(df)}")
    
    # Check latest CSV entries
    latest_csv = df.tail(5)
    print('\n=== Latest CSV Data ===')
    for row in latest_csv.to_dict('records'):
        print(f'{row["Date"]}: {row["Ticker"]} - Avg: ${row["Average Price"]:.2f}, Current: ${row["Current Price"]:.2f}, PnL: ${row["PnL"]:.2f}')
    
    # Load Supabase data
    load_dotenv(Path('web_dashboard') / '.env')
    repository = RepositoryFactory.create_repository(
        'supabase',
        url=os.getenv('SUPABASE_URL'),
        key=os.getenv('SUPABASE_ANON_KEY'),
        fund='Project Chimera'
    )
    
    snapshots = repository.get_portfolio_data()
    if snapshots:
        latest_snapshot = snapshots[-1]
        print(f'\n=== Latest Supabase Data ===')
        print(f'Snapshot date: {latest_snapshot.timestamp}')
        for pos in latest_snapshot.positions[:5]:
            current_price = getattr(pos, 'current_price', pos.avg_price)
            pnl = getattr(pos, 'pnl', 0) or 0
            print(f'{pos.ticker} - Avg: ${pos.avg_price:.2f}, Current: ${current_price:.2f}, PnL: ${pnl:.2f}')
    
    print('\n=== Key Difference ===')
    print('CSV has separate "Average Price" and "Current Price" columns')
    print('Supabase only has "price" (average) - missing current market prices!')

if __name__ == "__main__":
    check_data_differences()
