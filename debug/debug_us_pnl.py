#!/usr/bin/env python3
"""
Debug script to investigate why US stocks have invalid 1-day P&L
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from portfolio.portfolio_manager import PortfolioManager
from data.repositories.csv_repository import CSVRepository
from portfolio.fund_manager import FundManager, Fund
from financial.pnl_calculator import calculate_daily_pnl_from_snapshots

def main():
    print("=== Debugging US Stock P&L Issues ===")
    
    # Initialize components
    fund_manager = FundManager("funds.yml")
    fund = fund_manager.get_fund_by_id("TEST")
    repository = CSVRepository(fund)
    portfolio_manager = PortfolioManager(repository, fund)
    
    # Load current portfolio and snapshots
    current_portfolio = portfolio_manager.get_current_portfolio()
    portfolio_snapshots = portfolio_manager.load_portfolio()
    
    print(f"Current portfolio has {len(current_portfolio.positions)} positions")
    print(f"Historical snapshots: {len(portfolio_snapshots)}")
    
    # Check US stocks specifically
    us_stocks = []
    for pos in current_portfolio.positions:
        # US stocks typically don't have .TO, .V, or .CN suffixes
        if not pos.ticker.endswith(('.TO', '.V', '.CN')):
            us_stocks.append(pos)
    
    print(f"\nFound {len(us_stocks)} US stocks:")
    for pos in us_stocks:
        print(f"  {pos.ticker}: ${pos.current_price} (shares: {pos.shares})")
    
    # Check what tickers exist in snapshots
    print(f"\nChecking snapshots for US stock tickers...")
    snapshot_tickers = set()
    for snapshot in portfolio_snapshots:
        for pos in snapshot.positions:
            snapshot_tickers.add(pos.ticker)
    
    print(f"Snapshot tickers: {sorted(snapshot_tickers)}")
    
    # Test P&L calculation for each US stock
    print(f"\n=== Testing P&L Calculation ===")
    for pos in us_stocks:
        print(f"\n--- {pos.ticker} ---")
        print(f"Current price: ${pos.current_price}")
        print(f"Shares: {pos.shares}")
        print(f"Avg price: ${pos.avg_price}")
        
        # Check if ticker exists in snapshots
        ticker_in_snapshots = pos.ticker in snapshot_tickers
        print(f"Ticker in snapshots: {ticker_in_snapshots}")
        
        if ticker_in_snapshots:
            # Find the most recent previous snapshot with this ticker
            for i in range(1, len(portfolio_snapshots)):
                prev_snapshot = portfolio_snapshots[-(i+1)]
                prev_pos = None
                for prev_pos in prev_snapshot.positions:
                    if prev_pos.ticker == pos.ticker:
                        break
                
                if prev_pos and prev_pos.current_price is not None:
                    print(f"Previous price: ${prev_pos.current_price} (from {prev_snapshot.timestamp})")
                    break
            else:
                print("No previous price found in snapshots")
        else:
            print("Ticker not found in any snapshot - this is a new position")
        
        # Calculate P&L
        pnl = calculate_daily_pnl_from_snapshots(pos, portfolio_snapshots)
        print(f"Calculated P&L: {pnl}")

if __name__ == "__main__":
    main()
