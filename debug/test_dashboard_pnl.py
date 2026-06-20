#!/usr/bin/env python3
"""
Test web dashboard P&L processing
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

def test_dashboard_pnl():
    # Add project root to path
    project_root = Path.cwd()
    sys.path.insert(0, str(project_root))

    # Test the web dashboard load_portfolio_data function
    sys.path.append(str(project_root / 'web_dashboard'))

    from app import load_portfolio_data

    # Test loading Project Chimera data
    print('=== Testing Web Dashboard Data Processing ===')
    try:
        data = load_portfolio_data('Project Chimera')
        portfolio_df = data['portfolio']

        print(f'Portfolio shape: {portfolio_df.shape}')
        print(f'Columns: {list(portfolio_df.columns)}')

        # Check a few positions
        print('\nFirst 3 positions:')
        for i, row in enumerate(portfolio_df.head(3).to_dict('records')):
            print(f'{i+1}. {row["ticker"]}: PnL = {row.get("total_pnl", "N/A")}')

        # Check if PnL values are correct
        if 'total_pnl' in portfolio_df.columns:
            total_pnl = portfolio_df['total_pnl'].sum()
            print(f'\nTotal PnL from all positions: ${total_pnl:.2f}')

            # Check for any positions with non-zero PnL
            non_zero_pnl = portfolio_df[portfolio_df['total_pnl'] != 0]
            print(f'Positions with non-zero PnL: {len(non_zero_pnl)}')

            if len(non_zero_pnl) > 0:
                print('Sample non-zero PnL positions:')
                for row in non_zero_pnl.head(3).to_dict('records'):
                    pnl_pct = (row['total_pnl'] / row['total_cost_basis'] * 100) if row['total_cost_basis'] > 0 else 0
                    print(f'  {row["ticker"]}: ${row["total_pnl"]:.2f} ({pnl_pct:.2f}%)')
        else:
            print('No total_pnl column found!')

    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_dashboard_pnl()
