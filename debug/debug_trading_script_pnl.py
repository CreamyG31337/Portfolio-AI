#!/usr/bin/env python3
"""
Debug script to test the actual trading script workflow for GLO.TO daily P&L.

This script will simulate the exact workflow that trading_script.py uses
to identify where the daily P&L calculation is failing.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pathlib import Path
import pandas as pd
from decimal import Decimal
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def test_actual_portfolio_loading():
    """Test loading the actual portfolio data from TEST fund."""
    
    print("🔍 Testing Actual Portfolio Loading Workflow")
    print("=" * 70)
    
    # Use the actual TEST fund path
    fund_path = Path("trading_data/funds/TEST")
    portfolio_csv = fund_path / "llm_portfolio_update.csv"
    
    if not portfolio_csv.exists():
        print(f"❌ Portfolio CSV not found at: {portfolio_csv}")
        return
    
    print(f"📁 Loading portfolio from: {portfolio_csv}")
    
    # Load the CSV data
    try:
        df = pd.read_csv(portfolio_csv)
        print(f"✅ Loaded CSV with {len(df)} rows")
        
        # Filter for GLO.TO entries
        glo_entries = df[df['Ticker'] == 'GLO.TO'].copy()
        print(f"📊 Found {len(glo_entries)} GLO.TO entries")
        
        if len(glo_entries) == 0:
            print("❌ No GLO.TO entries found in CSV")
            return
            
        # Show the last few GLO.TO entries
        print("\n📈 Recent GLO.TO entries:")
        for row in glo_entries.tail(3).to_dict('records'):
            timestamp = row.get('Date', 'N/A')
            price = row.get('Current Price', 'N/A')
            print(f"  {timestamp}: ${price}")
        
        # Get the latest two entries for daily P&L calculation
        if len(glo_entries) >= 2:
            latest_entry = glo_entries.iloc[-1]
            previous_entry = glo_entries.iloc[-2]
            
            current_price = Decimal(str(latest_entry['Current Price']))
            previous_price = Decimal(str(previous_entry['Current Price']))
            shares = Decimal(str(latest_entry['Shares']))
            
            print(f"\n💰 Price comparison:")
            print(f"  Previous: ${previous_price} ({previous_entry['Date']})")
            print(f"  Current:  ${current_price} ({latest_entry['Date']})")
            print(f"  Shares:   {shares}")
            
            # Calculate expected daily P&L
            price_change = current_price - previous_price
            daily_pnl = price_change * shares
            
            print(f"\n📊 Expected daily P&L calculation:")
            print(f"  Price change: ${price_change}")
            print(f"  Daily P&L: ${price_change} × {shares} = ${daily_pnl:.2f}")
            
            # Now test with the actual portfolio manager
            test_with_portfolio_manager(fund_path)
            
        else:
            print("❌ Not enough GLO.TO entries for daily P&L calculation")
            
    except Exception as e:
        print(f"❌ Error loading CSV: {e}")

def test_with_portfolio_manager(fund_path):
    """Test with the actual portfolio manager to see what snapshots are loaded."""
    
    print(f"\n🔍 Testing with Portfolio Manager")
    print("=" * 50)
    
    try:
        # Import the actual portfolio manager
        from portfolio.portfolio_manager import PortfolioManager
        from data.repositories.repository_factory import get_repository_container, configure_repositories
        
        # Configure repository for TEST fund
        repo_config = {
            'type': 'csv',
            'data_dir': str(fund_path)
        }
        configure_repositories({'default': repo_config})
        repository = get_repository_container().get_repository('default')
        
        # Create portfolio manager
        portfolio_manager = PortfolioManager(repository)
        
        # Load portfolio snapshots
        print("📁 Loading portfolio snapshots...")
        snapshots = portfolio_manager.load_portfolio()
        
        print(f"✅ Loaded {len(snapshots)} portfolio snapshots")
        
        # Find GLO.TO in the latest snapshots
        glo_positions = []
        for i, snapshot in enumerate(snapshots[-5:]):  # Check last 5 snapshots
            snapshot_idx = len(snapshots) - 5 + i
            glo_pos = None
            for pos in snapshot.positions:
                if pos.ticker == 'GLO.TO':
                    glo_pos = pos
                    break
            
            if glo_pos:
                glo_positions.append((snapshot_idx, snapshot.timestamp, glo_pos))
                print(f"  Snapshot {snapshot_idx}: {snapshot.timestamp} - GLO.TO @ ${glo_pos.current_price}")
        
        if len(glo_positions) >= 2:
            # Get the last two GLO.TO positions
            prev_snapshot_idx, prev_timestamp, prev_pos = glo_positions[-2]
            curr_snapshot_idx, curr_timestamp, curr_pos = glo_positions[-1]
            
            print(f"\n📊 Portfolio Manager Data:")
            print(f"  Previous: Snapshot {prev_snapshot_idx} @ {prev_timestamp} - ${prev_pos.current_price}")
            print(f"  Current:  Snapshot {curr_snapshot_idx} @ {curr_timestamp} - ${curr_pos.current_price}")
            
            # Now test the daily P&L calculation using the actual function
            from financial.pnl_calculator import calculate_daily_pnl_from_snapshots
            
            print(f"\n🧮 Testing actual daily P&L function...")
            result = calculate_daily_pnl_from_snapshots(curr_pos, snapshots)
            print(f"✅ Daily P&L result: {result}")
            
            # Calculate what we expect
            expected_change = curr_pos.current_price - prev_pos.current_price
            expected_pnl = expected_change * curr_pos.shares
            print(f"💭 Expected result: ${expected_pnl:.2f}")
            
            if result == "$0.00" and abs(expected_pnl) > 0.01:
                print("❌ BUG CONFIRMED: Function returned $0.00 when it should show a change")
                
                # Debug the function more deeply
                debug_pnl_function(curr_pos, snapshots)
            else:
                print("✅ Function working correctly")
        else:
            print("❌ Not enough GLO.TO positions found in snapshots")
            
    except Exception as e:
        print(f"❌ Error testing with portfolio manager: {e}")
        import traceback
        traceback.print_exc()

def debug_pnl_function(position, snapshots):
    """Debug the P&L function in detail."""
    
    print(f"\n🔍 Debugging P&L Function in Detail")
    print("=" * 50)
    
    print(f"Position details:")
    print(f"  Ticker: {position.ticker}")
    print(f"  Current price: {position.current_price}")
    print(f"  Shares: {position.shares}")
    print(f"  Avg price: {position.avg_price}")
    
    print(f"\nSnapshots overview:")
    for i, snapshot in enumerate(snapshots[-5:]):
        snapshot_idx = len(snapshots) - 5 + i
        glo_count = sum(1 for pos in snapshot.positions if pos.ticker == 'GLO.TO')
        print(f"  Snapshot {snapshot_idx}: {snapshot.timestamp} - {glo_count} GLO.TO positions")
    
    # Manually walk through the P&L calculation logic
    print(f"\n🚶 Manual walkthrough of P&L logic:")
    
    # Check if ticker exists in previous days
    ticker_exists_in_previous_days = False
    for i in range(len(snapshots) - 1):  # Check all snapshots except the latest
        previous_snapshot = snapshots[i]
        if any(pos.ticker == position.ticker for pos in previous_snapshot.positions):
            ticker_exists_in_previous_days = True
            print(f"  ✅ Found {position.ticker} in snapshot {i}")
            break
    
    if not ticker_exists_in_previous_days:
        print(f"  ❌ {position.ticker} not found in previous snapshots (new position)")
        return
    
    # Look for previous day data
    print(f"  🔍 Looking for previous day data...")
    for i in range(1, len(snapshots)):
        previous_snapshot = snapshots[-(i+1)]
        print(f"    Checking snapshot from {previous_snapshot.timestamp}")
        
        # Find the same ticker in previous snapshot
        prev_position = None
        for prev_pos in previous_snapshot.positions:
            if prev_pos.ticker == position.ticker:
                prev_position = prev_pos
                break
        
        if prev_position and prev_position.current_price is not None:
            prev_price = prev_position.current_price
            print(f"    ✅ Found previous price: ${prev_price}")
            
            # Calculate P&L
            current_price = position.current_price
            print(f"    📊 Current price: ${current_price}")
            print(f"    📊 Price difference: ${current_price - prev_price}")
            print(f"    📊 Abs difference: {abs(current_price - prev_price)}")
            print(f"    📊 > 0.01?: {abs(current_price - prev_price) > 0.01}")
            
            if abs(current_price - prev_price) > 0.01:
                daily_price_change = current_price - prev_price
                daily_pnl_amount = daily_price_change * position.shares
                print(f"    ✅ Calculated daily P&L: ${daily_pnl_amount:.2f}")
                return f"${daily_pnl_amount:.2f}"
            else:
                print(f"    ❌ Price change too small (≤ 1 cent)")
                return "$0.00"
        else:
            print(f"    ❌ No position or price data in this snapshot")
    
    print(f"  ❌ No previous day data found")

def main():
    """Main function."""
    test_actual_portfolio_loading()

if __name__ == "__main__":
    main()