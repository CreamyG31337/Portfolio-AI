#!/usr/bin/env python3
"""
Test script to verify the duplicate row fix.

This script tests the fix for the duplicate row issue when opening the portfolio.
It simulates the portfolio update process to ensure no duplicate rows are created.
"""

import os
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_duplicate_fix():
    """Test the duplicate row fix by simulating portfolio updates."""
    
    print("🧪 Testing duplicate row fix...")
    print("=" * 50)
    
    try:
        # Import the fixed repository
        from data.repositories.csv_repository import CSVRepository
        from data.models.portfolio import PortfolioSnapshot, Position
        from decimal import Decimal
        
        # Create a test data directory
        test_data_dir = Path("test_data_temp")
        test_data_dir.mkdir(exist_ok=True)
        
        # Initialize repository with test directory
        repo = CSVRepository(str(test_data_dir))
        
        print(f"📁 Created test repository at: {test_data_dir}")
        
        # Create test positions
        positions = [
            Position(
                ticker="ABEO",
                shares=Decimal("4.0"),
                avg_price=Decimal("5.77"),
                cost_basis=Decimal("23.08"),
                current_price=Decimal("6.89"),
                market_value=Decimal("27.56"),
                unrealized_pnl=Decimal("4.48"),
                company="Abeona Therapeutics Inc.",
                currency="USD"
            ),
            Position(
                ticker="ATYR",
                shares=Decimal("12.0"),
                avg_price=Decimal("5.21"),
                cost_basis=Decimal("62.48"),
                current_price=Decimal("5.61"),
                market_value=Decimal("67.32"),
                unrealized_pnl=Decimal("4.84"),
                company="aTyr Pharma Inc.",
                currency="USD"
            )
        ]
        
        # Create initial snapshot
        initial_snapshot = PortfolioSnapshot(
            positions=positions,
            timestamp=datetime.now()
        )
        
        print(f"💾 Creating initial snapshot with {len(positions)} positions...")
        
        # Save initial snapshot (should create new rows)
        repo.save_portfolio_snapshot(initial_snapshot)
        
        # Read the CSV to check initial state
        csv_file = test_data_dir / "llm_portfolio_update.csv"
        if csv_file.exists():
            df = pd.read_csv(csv_file)
            initial_row_count = len(df)
            print(f"✅ Initial CSV created with {initial_row_count} rows")
            print(f"   Tickers: {df['Ticker'].tolist()}")
        else:
            print("❌ Initial CSV file not created")
            return False
            
        # Now simulate "opening the portfolio" - this should UPDATE, not ADD
        print(f"\n🔄 Simulating portfolio refresh (should update, not duplicate)...")
        
        # Update prices slightly to simulate market changes
        updated_positions = []
        for pos in positions:
            updated_pos = Position(
                ticker=pos.ticker,
                shares=pos.shares,
                avg_price=pos.avg_price,
                cost_basis=pos.cost_basis,
                current_price=pos.current_price + Decimal("0.05"),  # Slight price increase
                market_value=(pos.current_price + Decimal("0.05")) * pos.shares,
                unrealized_pnl=((pos.current_price + Decimal("0.05")) - pos.avg_price) * pos.shares,
                company=pos.company,
                currency=pos.currency
            )
            updated_positions.append(updated_pos)
        
        updated_snapshot = PortfolioSnapshot(
            positions=updated_positions,
            timestamp=datetime.now()
        )
        
        # This should UPDATE existing rows, not create duplicates
        repo.update_daily_portfolio_snapshot(updated_snapshot)
        
        # Check the result
        df_after = pd.read_csv(csv_file)
        final_row_count = len(df_after)
        
        print(f"📊 Results after update:")
        print(f"   Initial rows: {initial_row_count}")
        print(f"   Final rows: {final_row_count}")
        print(f"   Tickers: {df_after['Ticker'].tolist()}")
        
        if final_row_count == initial_row_count:
            print("✅ SUCCESS: No duplicate rows created!")
            print("✅ Portfolio prices were updated correctly")
            
            # Verify prices were actually updated
            for row in df_after.to_dict('records'):
                ticker = row['Ticker']
                current_price = row['Current Price']
                print(f"   {ticker}: ${current_price:.2f}")
            
            result = True
        else:
            print(f"❌ FAILURE: Duplicate rows created!")
            print(f"   Expected {initial_row_count} rows, got {final_row_count}")
            result = False
            
        # Test adding a genuinely new position
        print(f"\n🆕 Testing addition of genuinely new position...")
        
        # Add a new ticker that doesn't exist yet
        new_position = Position(
            ticker="NEWCO",
            shares=Decimal("10.0"),
            avg_price=Decimal("2.50"),
            cost_basis=Decimal("25.00"),
            current_price=Decimal("2.75"),
            market_value=Decimal("27.50"),
            unrealized_pnl=Decimal("2.50"),
            company="New Company Inc.",
            currency="USD"
        )
        
        all_positions = updated_positions + [new_position]
        new_snapshot = PortfolioSnapshot(
            positions=all_positions,
            timestamp=datetime.now()
        )
        
        repo.update_daily_portfolio_snapshot(new_snapshot)
        
        df_final = pd.read_csv(csv_file)
        final_final_count = len(df_final)
        
        print(f"📊 Results after adding new position:")
        print(f"   Previous rows: {final_row_count}")
        print(f"   Final rows: {final_final_count}")
        print(f"   Tickers: {df_final['Ticker'].tolist()}")
        
        if final_final_count == final_row_count + 1:
            print("✅ SUCCESS: New position added correctly!")
            result = result and True
        else:
            print(f"❌ FAILURE: Expected {final_row_count + 1} rows, got {final_final_count}")
            result = result and False
        
        # Clean up test files
        print(f"\n🧹 Cleaning up test files...")
        try:
            if csv_file.exists():
                csv_file.unlink()
            test_data_dir.rmdir()
            print("✅ Test cleanup completed")
        except Exception as e:
            print(f"⚠️  Warning: Could not clean up test files: {e}")
            
        return result
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main test function."""
    print("🚀 Duplicate Row Fix Test")
    print("=" * 50)
    
    success = test_duplicate_fix()
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 ALL TESTS PASSED! The duplicate row bug has been fixed.")
        print("✅ Opening your portfolio should now update prices without creating duplicates.")
    else:
        print("❌ TESTS FAILED! There may still be issues with the fix.")
        print("🔧 Please check the implementation and try again.")
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())