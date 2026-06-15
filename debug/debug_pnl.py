#!/usr/bin/env python3
"""
Debug script to analyze P&L calculations
"""

import sys
from pathlib import Path
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

def analyze_pnl():
    """Analyze P&L calculations for problematic tickers."""
    
    # Read the portfolio CSV
    df = pd.read_csv('trading_data/funds/RRSP Lance Webull/llm_portfolio_update.csv')
    
    # Get the latest entry for each ticker
    latest_entries = df.groupby('Ticker').last().reset_index()
    
    problematic_tickers = ['ATRL', 'CGL', 'VFV', 'XEQT', 'XGD', 'XHAK', 'XHC', 'XIC', 'ZEA']
    
    print('P&L Analysis for problematic tickers:')
    print('=' * 80)
    print(f"{'Ticker':<6} {'Shares':<8} {'Avg Price':<10} {'Current':<10} {'Total Value':<12} {'P&L':<12} {'P&L %':<8}")
    print('-' * 80)
    
    for ticker in problematic_tickers:
        entry = latest_entries[latest_entries['Ticker'] == ticker]
        if not entry.empty:
            row = entry.iloc[0]
            shares = row['Shares']
            avg_price = row['Average Price']
            current_price = row['Current Price']
            total_value = row['Total Value']
            pnl = row['PnL']
            cost_basis = shares * avg_price
            pnl_pct = (pnl / cost_basis) * 100 if cost_basis > 0 else 0
            
            print(f"{ticker:<6} {shares:<8.0f} ${avg_price:<9.2f} ${current_price:<9.2f} ${total_value:<11.2f} ${pnl:<11.2f} {pnl_pct:<7.1f}%")
            
            # Flag large P&L
            if abs(pnl_pct) > 50:
                print(f"         ⚠️  WARNING: Large P&L ({pnl_pct:+.1f}%) detected!")
        else:
            print(f"{ticker:<6} Not found in CSV")
    
    print('\n' + '=' * 80)
    print('Summary:')
    print('=' * 80)
    
    # Check for any extreme P&L values
    latest_entries['cost_basis'] = latest_entries['Shares'] * latest_entries['Average Price']
    latest_entries['pnl_pct'] = (latest_entries['PnL'] / latest_entries['cost_basis']) * 100
    extreme_pnl = latest_entries[abs(latest_entries['pnl_pct']) > 50]
    
    if not extreme_pnl.empty:
        print('Tickers with >50% P&L:')
        for row in extreme_pnl.to_dict('records'):
            print(f"  {row['Ticker']}: {row['pnl_pct']:+.1f}%")
    else:
        print('No extreme P&L values found (>50%)')
    
    # Show the top 10 highest P&L percentages
    print('\nTop 10 highest P&L percentages:')
    print('-' * 40)
    top_pnl = latest_entries.nlargest(10, 'pnl_pct')[['Ticker', 'pnl_pct', 'PnL', 'Total Value']]
    for row in top_pnl.to_dict('records'):
        print(f"{row['Ticker']:<6} {row['pnl_pct']:+6.1f}% (${row['PnL']:+8.2f})")
    
    print('\nTop 10 lowest P&L percentages:')
    print('-' * 40)
    bottom_pnl = latest_entries.nsmallest(10, 'pnl_pct')[['Ticker', 'pnl_pct', 'PnL', 'Total Value']]
    for row in bottom_pnl.to_dict('records'):
        print(f"{row['Ticker']:<6} {row['pnl_pct']:+6.1f}% (${row['PnL']:+8.2f})")

if __name__ == "__main__":
    analyze_pnl()
