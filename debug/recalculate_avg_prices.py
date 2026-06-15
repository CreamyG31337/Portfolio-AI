#!/usr/bin/env python3
"""
Recalculate Portfolio Data from Trade Log

This comprehensive script recalculates all portfolio data (shares, prices, cost basis) 
based on the actual trade log data. Use this when:
- You manually edit the trade log
- You suspect the portfolio CSV has stale data
- You want to verify all calculations are correct
- You notice share count discrepancies

Usage:
    python debug/recalculate_avg_prices.py
    python debug/recalculate_avg_prices.py test_data
"""

import pandas as pd
from pathlib import Path
from collections import defaultdict
import sys

def recalculate_portfolio_data(data_dir: str = "my trading"):
    """Recalculate all portfolio data (shares, prices, cost basis) from trade log and update portfolio CSV"""
    
    data_path = Path(data_dir)
    trade_log_file = data_path / "llm_trade_log.csv"
    portfolio_file = data_path / "llm_portfolio_update.csv"
    
    if not trade_log_file.exists():
        print(f"_safe_emoji('_safe_emoji('❌')') Trade log not found: {trade_log_file}")
        return False
    
    if not portfolio_file.exists():
        print(f"_safe_emoji('_safe_emoji('❌')') Portfolio file not found: {portfolio_file}")
        return False
    
    try:
        # Read trade log
        trade_df = pd.read_csv(trade_log_file)
        print(f"_safe_emoji('📊') Loaded {len(trade_df)} trades from trade log")
        
        # Read portfolio
        portfolio_df = pd.read_csv(portfolio_file)
        print(f"_safe_emoji('📊') Loaded {len(portfolio_df)} portfolio entries")
        
        # Calculate average prices from trade log
        ticker_data = defaultdict(lambda: {'total_shares': 0, 'total_cost': 0, 'trades': []})
        
        for trade in trade_df.to_dict('records'):
            ticker = trade['Ticker']
            shares = float(trade['Shares'])
            price = float(trade['Price'])
            cost = float(trade['Cost Basis'])
            
            ticker_data[ticker]['total_shares'] += shares
            ticker_data[ticker]['total_cost'] += cost
            ticker_data[ticker]['trades'].append({
                'shares': shares,
                'price': price,
                'cost': cost
            })
        
        print(f"\n📈 Calculated averages from trade log:")
        for ticker, data in ticker_data.items():
            if data['total_shares'] > 0:
                avg_price = data['total_cost'] / data['total_shares']
                print(f"   {ticker}: {data['total_shares']:.4f} shares, ${data['total_cost']:.2f} cost, ${avg_price:.2f} avg")
        
        # Update portfolio with recalculated data (shares, prices, cost basis)
        updated_count = 0
        changes_made = []
        
        # zip(index, to_dict) keeps the index label for df.at[idx, ...] while giving
        # dict rows (handles space-named columns) without per-row Series creation.
        for idx, row in zip(portfolio_df.index, portfolio_df.to_dict('records')):
            ticker = row['Ticker']
            
            if ticker in ticker_data and ticker_data[ticker]['total_shares'] > 0:
                # Get current values
                old_shares = float(row['Shares'])
                old_avg_price = float(row['Average Price'])
                old_cost_basis = float(row['Cost Basis'])
                
                # Calculate correct values from trade log
                new_shares = ticker_data[ticker]['total_shares']
                new_avg_price = ticker_data[ticker]['total_cost'] / ticker_data[ticker]['total_shares']
                new_cost_basis = new_shares * new_avg_price
                
                # Update all values
                portfolio_df.at[idx, 'Shares'] = new_shares
                portfolio_df.at[idx, 'Average Price'] = round(new_avg_price, 2)
                portfolio_df.at[idx, 'Cost Basis'] = round(new_cost_basis, 2)
                
                # Track changes
                shares_diff = abs(old_shares - new_shares)
                price_diff = abs(old_avg_price - new_avg_price)
                cost_diff = abs(old_cost_basis - new_cost_basis)
                
                if shares_diff > 0.001 or price_diff > 0.01 or cost_diff > 0.01:  # Only show if significant change
                    changes_made.append({
                        'ticker': ticker,
                        'old_shares': old_shares,
                        'new_shares': new_shares,
                        'old_price': old_avg_price,
                        'new_price': new_avg_price,
                        'old_cost': old_cost_basis,
                        'new_cost': new_cost_basis,
                        'shares_diff': shares_diff,
                        'price_diff': price_diff,
                        'cost_diff': cost_diff
                    })
                    updated_count += 1
        
        # Show detailed changes
        if changes_made:
            print(f"\n_safe_emoji('_safe_emoji('🔄')') Changes made to {updated_count} entries:")
            for change in changes_made:
                print(f"   {change['ticker']}:")
                print(f"     Shares: {change['old_shares']:.4f} → {change['new_shares']:.4f} ({change['shares_diff']:.4f} diff)")
                print(f"     Price:  ${change['old_price']:.2f} → ${change['new_price']:.2f} (${change['price_diff']:.2f} diff)")
                print(f"     Cost:   ${change['old_cost']:.2f} → ${change['new_cost']:.2f} (${change['cost_diff']:.2f} diff)")
        else:
            print(f"\n_safe_emoji('✅') No changes needed - all data is already accurate")
        
        # Save updated portfolio
        portfolio_df.to_csv(portfolio_file, index=False)
        
        print(f"\n_safe_emoji('✅') Portfolio updated and saved to: {portfolio_file}")
        
        return True
        
    except Exception as e:
        print(f"_safe_emoji('_safe_emoji('❌')') Error recalculating portfolio data: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main function to recalculate portfolio data"""
    print("_safe_emoji('_safe_emoji('🔄')') Recalculating Portfolio Data from Trade Log")
    print("=" * 50)
    
    # Check if data directory argument provided
    data_dir = "my trading"
    if len(sys.argv) > 1:
        data_dir = sys.argv[1]
    
    print(f"📁 Using data directory: {data_dir}")
    
    success = recalculate_portfolio_data(data_dir)
    
    if success:
        print("\n🎉 Portfolio data recalculated successfully!")
        print("   All shares, prices, and cost basis are now accurate based on the trade log")
    else:
        print("\n_safe_emoji('_safe_emoji('❌')') Failed to recalculate portfolio data")
        sys.exit(1)

if __name__ == "__main__":
    main()
