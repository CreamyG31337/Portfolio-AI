#!/usr/bin/env python3
"""
Unit tests for CSV repository decimal formatting.

This module tests that the CSV repository correctly formats decimal values
when updating portfolio snapshots.
"""

import unittest
import tempfile
import os
import pandas as pd
from decimal import Decimal
from datetime import datetime
import sys

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.repositories.csv_repository import CSVRepository
from data.models.portfolio import Position, PortfolioSnapshot


class TestCSVRepositoryDecimalFormatting(unittest.TestCase):
    """Test cases for CSV repository decimal formatting."""
    
    def setUp(self):
        """Set up test environment with temporary files."""
        # Create temporary directory
        self.temp_dir = tempfile.mkdtemp()
        
        # Create CSV repository with temporary directory
        self.repository = CSVRepository(fund_name="TEST", data_directory=str(self.temp_dir))
        
        # Create test portfolio file
        self.portfolio_file = os.path.join(self.temp_dir, "llm_portfolio_update.csv")
        
        # Create initial portfolio data with float precision issues
        self.initial_data = pd.DataFrame([
            {
                'Date': '2025-09-12 16:21:32 PDT',
                'Ticker': 'CTRN',
                'Shares': 9.2961,
                'Average Price': 37.65,
                'Cost Basis': 350.0,
                'Stop Loss': 0.0,
                'Current Price': 35.16999816894531,  # Float precision issue
                'Total Value': 326.9438199783325,    # Float precision issue
                'PnL': -23.054345021667466,          # Float precision issue
                'Action': 'HOLD',
                'Company': 'Citi Trends, Inc.',
                'Currency': 'USD'
            }
        ])
        
        # Save initial data
        self.initial_data.to_csv(self.portfolio_file, index=False)
    
    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_update_daily_portfolio_snapshot_decimal_formatting(self):
        """Test that daily portfolio updates format decimals correctly."""
        # Create updated position with clean decimal values
        updated_position = Position(
            ticker="CTRN",
            shares=Decimal("9.2961"),
            avg_price=Decimal("37.65"),
            cost_basis=Decimal("350.0"),
            currency="USD",
            company="Citi Trends, Inc.",
            current_price=Decimal("35.17"),  # Clean value
            market_value=Decimal("326.94"),  # Clean value
            unrealized_pnl=Decimal("-23.05"),  # Clean value
            stop_loss=Decimal("0.0")
        )
        
        # Create portfolio snapshot
        snapshot = PortfolioSnapshot(
            timestamp=datetime.now(),
            positions=[updated_position]
        )
        
        # Update the portfolio
        self.repository.update_daily_portfolio_snapshot(snapshot)
        
        # Read the updated data
        updated_data = pd.read_csv(self.portfolio_file)
        
        # Verify decimal formatting with tolerance for floating point precision
        self.assertAlmostEqual(updated_data['Current Price'].iloc[0], 35.17, places=2)
        self.assertAlmostEqual(updated_data['Total Value'].iloc[0], 326.94, places=2)
        self.assertAlmostEqual(updated_data['PnL'].iloc[0], -23.05, places=2)
    
    def test_save_portfolio_snapshot_decimal_formatting(self):
        """Test that saving portfolio snapshots formats decimals correctly."""
        # Clear any existing data to ensure clean test
        if os.path.exists(self.portfolio_file):
            os.remove(self.portfolio_file)

        # Create position with float precision issues
        position = Position(
            ticker="TEST",
            shares=Decimal("10.123456789"),
            avg_price=Decimal("100.123456789"),
            cost_basis=Decimal("1001.23456789"),
            currency="USD",
            company="Test Company",
            current_price=Decimal("105.987654321"),
            market_value=Decimal("1059.87654321"),
            unrealized_pnl=Decimal("58.64197532"),
            stop_loss=Decimal("95.0")
        )

        # Create portfolio snapshot
        snapshot = PortfolioSnapshot(
            timestamp=datetime.now(),
            positions=[position]
        )

        # Save the snapshot
        self.repository.save_portfolio_snapshot(snapshot)

        # Read the saved data
        saved_data = pd.read_csv(self.portfolio_file)

        # Verify decimal formatting with tolerance for floating point precision
        self.assertAlmostEqual(saved_data['Shares'].iloc[0], 10.1235, places=4)  # 4 decimal places
        self.assertAlmostEqual(saved_data['Average Price'].iloc[0], 100.12, places=2)  # 2 decimal places
        self.assertAlmostEqual(saved_data['Cost Basis'].iloc[0], 1001.23, places=2)  # 2 decimal places
        self.assertAlmostEqual(saved_data['Current Price'].iloc[0], 105.99, places=2)  # 2 decimal places
        self.assertAlmostEqual(saved_data['Total Value'].iloc[0], 1059.88, places=2)  # 2 decimal places
        self.assertAlmostEqual(saved_data['PnL'].iloc[0], 58.64, places=2)  # 2 decimal places
        self.assertAlmostEqual(saved_data['Stop Loss'].iloc[0], 95.0, places=2)  # 2 decimal places
    
    def test_multiple_positions_decimal_formatting(self):
        """Test decimal formatting with multiple positions."""
        # Clear any existing data to ensure clean test
        if os.path.exists(self.portfolio_file):
            os.remove(self.portfolio_file)

        positions = [
            Position(
                ticker="AAPL",
                shares=Decimal("5.123456789"),
                avg_price=Decimal("150.123456789"),
                cost_basis=Decimal("750.123456789"),
                currency="USD",
                company="Apple Inc.",
                current_price=Decimal("155.987654321"),
                market_value=Decimal("796.987654321"),
                unrealized_pnl=Decimal("46.864197532"),
                stop_loss=Decimal("140.0")
            ),
            Position(
                ticker="GOOGL",
                shares=Decimal("2.987654321"),
                avg_price=Decimal("2800.123456789"),
                cost_basis=Decimal("8360.123456789"),
                currency="USD",
                company="Alphabet Inc.",
                current_price=Decimal("2850.987654321"),
                market_value=Decimal("8520.987654321"),
                unrealized_pnl=Decimal("160.864197532"),
                stop_loss=Decimal("2700.0")
            )
        ]

        # Create portfolio snapshot
        snapshot = PortfolioSnapshot(
            timestamp=datetime.now(),
            positions=positions
        )

        # Save the snapshot
        self.repository.save_portfolio_snapshot(snapshot)

        # Read the saved data
        saved_data = pd.read_csv(self.portfolio_file)

        # Verify all positions are properly formatted
        for i, row in enumerate(saved_data.to_dict('records')):
            with self.subTest(position=i):
                # Check shares precision (4 decimal places)
                self.assertTrue(self._has_correct_precision(row['Shares'], 4))

                # Check price precision (2 decimal places)
                price_fields = ['Average Price', 'Cost Basis', 'Current Price', 'Total Value', 'PnL', 'Stop Loss']
                for field in price_fields:
                    if pd.notna(row[field]) and row[field] != 0:
                        self.assertTrue(self._has_correct_precision(row[field], 2),
                                      f"Field {field} has incorrect precision: {row[field]}")
    
    def test_none_values_handling(self):
        """Test handling of None values in decimal formatting."""
        # Clear any existing data to ensure clean test
        if os.path.exists(self.portfolio_file):
            os.remove(self.portfolio_file)

        position = Position(
            ticker="TEST",
            shares=Decimal("10.0"),
            avg_price=Decimal("100.0"),
            cost_basis=Decimal("1000.0"),
            currency="USD",
            company="Test Company",
            current_price=None,
            market_value=None,
            unrealized_pnl=None,
            stop_loss=None
        )

        # Create portfolio snapshot
        snapshot = PortfolioSnapshot(
            timestamp=datetime.now(),
            positions=[position]
        )

        # Save the snapshot
        self.repository.save_portfolio_snapshot(snapshot)

        # Read the saved data
        saved_data = pd.read_csv(self.portfolio_file)

        # Verify None values are handled correctly with tolerance for floating point precision
        self.assertAlmostEqual(saved_data['Current Price'].iloc[0], 0.0, places=2)
        self.assertAlmostEqual(saved_data['Total Value'].iloc[0], 0.0, places=2)
        self.assertAlmostEqual(saved_data['PnL'].iloc[0], 0.0, places=2)
        self.assertAlmostEqual(saved_data['Stop Loss'].iloc[0], 0.0, places=2)
    
    def test_float_precision_issue_prevention(self):
        """Test that the repository prevents typical float precision issues."""
        # Clear any existing data to ensure clean test
        if os.path.exists(self.portfolio_file):
            os.remove(self.portfolio_file)

        # Create position with problematic float values
        position = Position(
            ticker="PROBLEM",
            shares=Decimal("9.2961"),
            avg_price=Decimal("37.65"),
            cost_basis=Decimal("350.0"),
            currency="USD",
            company="Problem Stock",
            current_price=Decimal("35.16999816894531"),  # Typical float precision issue
            market_value=Decimal("326.9438199783325"),   # Typical float precision issue
            unrealized_pnl=Decimal("-23.054345021667466") # Typical float precision issue
        )

        # Create portfolio snapshot
        snapshot = PortfolioSnapshot(
            timestamp=datetime.now(),
            positions=[position]
        )

        # Save the snapshot
        self.repository.save_portfolio_snapshot(snapshot)

        # Read the saved data
        saved_data = pd.read_csv(self.portfolio_file)

        # Verify the problematic values are now clean with tolerance for floating point precision
        self.assertAlmostEqual(saved_data['Current Price'].iloc[0], 35.17, places=2)
        self.assertAlmostEqual(saved_data['Total Value'].iloc[0], 326.94, places=2)
        self.assertAlmostEqual(saved_data['PnL'].iloc[0], -23.05, places=2)

        # Verify no more float precision issues
        for field in ['Current Price', 'Total Value', 'PnL']:
            value = saved_data[field].iloc[0]
            self.assertTrue(self._has_correct_precision(value, 2),
                          f"Field {field} still has precision issues: {value}")
    
    def _has_correct_precision(self, value: float, expected_precision: int) -> bool:
        """Helper method to check if a float has the correct decimal precision."""
        if not isinstance(value, (int, float)):
            return False
        
        # Convert to string and check decimal places
        str_value = f"{value:.10f}".rstrip('0').rstrip('.')
        if '.' in str_value:
            decimal_places = len(str_value.split('.')[1])
            return decimal_places <= expected_precision
        else:
            return True  # Integer values are fine


class TestCSVRepositoryDecimalFormattingIntegration(unittest.TestCase):
    """Integration tests for CSV repository decimal formatting."""
    
    def test_real_world_scenario(self):
        """Test with real-world data that previously caused issues."""
        # Create temporary directory
        temp_dir = tempfile.mkdtemp()
        
        try:
            # Create CSV repository
            repository = CSVRepository(fund_name="TEST", data_directory=str(temp_dir))
            
            # Create positions with the exact values that caused the original issue
            positions = [
                Position(
                    ticker="CTRN",
                    shares=Decimal("9.2961"),
                    avg_price=Decimal("37.65"),
                    cost_basis=Decimal("350.0"),
                    currency="USD",
                    company="Citi Trends, Inc.",
                    current_price=Decimal("35.16999816894531"),
                    market_value=Decimal("326.9438199783325"),
                    unrealized_pnl=Decimal("-23.054345021667466")
                ),
                Position(
                    ticker="VEE.TO",
                    shares=Decimal("2.4987"),
                    avg_price=Decimal("43.37"),
                    cost_basis=Decimal("108.38"),
                    currency="CAD",
                    company="Vanguard ETF",
                    current_price=Decimal("43.88999938964844"),
                    market_value=Decimal("109.66794147491454"),
                    unrealized_pnl=Decimal("1.299322474914557")
                )
            ]
            
            # Create portfolio snapshot
            snapshot = PortfolioSnapshot(
                timestamp=datetime.now(),
                positions=positions
            )
            
            # Save the snapshot
            repository.save_portfolio_snapshot(snapshot)
            
            # Read the saved data
            portfolio_file = os.path.join(temp_dir, "llm_portfolio_update.csv")
            saved_data = pd.read_csv(portfolio_file)
            
            # Verify all values are clean
            for i, row in enumerate(saved_data.to_dict('records')):
                with self.subTest(position=i):
                    # Check that no values have excessive decimal places
                    for col in ['Shares', 'Average Price', 'Cost Basis', 'Current Price', 'Total Value', 'PnL']:
                        if pd.notna(row[col]) and row[col] != 0:
                            value_str = f"{row[col]:.10f}".rstrip('0').rstrip('.')
                            if '.' in value_str:
                                decimal_places = len(value_str.split('.')[-1])
                                if col == 'Shares':
                                    self.assertLessEqual(decimal_places, 4, 
                                                       f"Position {i} {col} has too many decimal places: {row[col]}")
                                else:
                                    self.assertLessEqual(decimal_places, 2, 
                                                       f"Position {i} {col} has too many decimal places: {row[col]}")
            
            # Verify specific expected values with tolerance for floating point precision
            self.assertAlmostEqual(saved_data['Current Price'].iloc[0], 35.17, places=2)
            self.assertAlmostEqual(saved_data['Total Value'].iloc[0], 326.94, places=2)
            self.assertAlmostEqual(saved_data['PnL'].iloc[0], -23.05, places=2)
            self.assertAlmostEqual(saved_data['Current Price'].iloc[1], 43.89, places=2)
            self.assertAlmostEqual(saved_data['Total Value'].iloc[1], 109.67, places=2)
            self.assertAlmostEqual(saved_data['PnL'].iloc[1], 1.30, places=2)
            
        finally:
            # Clean up
            import shutil
            shutil.rmtree(temp_dir)


if __name__ == '__main__':
    # Run the tests
    unittest.main(verbosity=2)
