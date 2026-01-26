"""
Unit tests for the calculate_daily_pnl_from_snapshots function.

Tests cover the 1-day P&L calculation logic used in trading_script.py.
"""

import unittest
from decimal import Decimal
from datetime import datetime
import sys
import os

# Add the parent directory to the path so we can import the financial modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from financial.pnl_calculator import calculate_daily_pnl_from_snapshots
from data.models.portfolio import Position


class TestCalculateDailyPnLFromSnapshots(unittest.TestCase):
    """Test cases for calculate_daily_pnl_from_snapshots function."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a mock position with current price
        self.position = Position(
            ticker="AAPL",
            shares=Decimal('100'),
            avg_price=Decimal('150.00'),
            cost_basis=Decimal('15000.00'),  # 100 shares * $150 avg price
            current_price=Decimal('160.00'),
            company="Apple Inc."
        )

        # Create mock portfolio snapshots
        self.snapshots = [
            # Day 1: Position doesn't exist (new position)
            MockPortfolioSnapshot(
                timestamp=datetime(2025, 1, 1, 16, 0, 0),
                positions=[]
            ),
            # Day 2: Position exists with previous price
            MockPortfolioSnapshot(
                timestamp=datetime(2025, 1, 2, 16, 0, 0),
                positions=[
                    Position(
                        ticker="AAPL",
                        shares=Decimal('100'),
                        avg_price=Decimal('150.00'),
                        cost_basis=Decimal('15000.00'),  # 100 shares * $150 avg price
                        current_price=Decimal('155.00'),  # Previous day price
                        company="Apple Inc."
                    )
                ]
            ),
            # Day 3: Current snapshot
            MockPortfolioSnapshot(
                timestamp=datetime(2025, 1, 3, 16, 0, 0),
                positions=[
                    self.position
                ]
            )
        ]

    def test_new_position_daily_pnl(self):
        """Test daily P&L for a new position (should compare with avg_price)."""
        new_position = Position(
            ticker="TSLA",
            shares=Decimal('50'),
            avg_price=Decimal('200.00'),
            cost_basis=Decimal('10000.00'),  # 50 shares * $200 avg price
            current_price=Decimal('205.00'),  # $5 gain
            company="Tesla Inc."
        )

        snapshots = [
            MockPortfolioSnapshot(
                timestamp=datetime(2025, 1, 1, 16, 0, 0),
                positions=[]  # New position, doesn't exist in previous snapshots
            ),
            MockPortfolioSnapshot(
                timestamp=datetime(2025, 1, 2, 16, 0, 0),
                positions=[new_position]
            )
        ]

        result = calculate_daily_pnl_from_snapshots(new_position, snapshots)
        # Should show $250.00 P&L (50 shares * $5.00 gain from buy price)
        self.assertEqual(result, "$250.00")

    def test_existing_position_daily_pnl(self):
        """Test daily P&L for existing position (should compare with previous day price)."""
        result = calculate_daily_pnl_from_snapshots(self.position, self.snapshots)

        # Current price: $160.00, Previous day price: $155.00
        # P&L should be: (160 - 155) * 100 = $500.00
        self.assertEqual(result, "$500.00")

    def test_no_price_change(self):
        """Test when there's no price change."""
        no_change_position = Position(
            ticker="MSFT",
            shares=Decimal('25'),
            avg_price=Decimal('300.00'),
            cost_basis=Decimal('7500.00'),  # 25 shares * $300 avg price
            current_price=Decimal('300.00'),
            company="Microsoft Corp."
        )

        snapshots = [
            MockPortfolioSnapshot(
                timestamp=datetime(2025, 1, 1, 16, 0, 0),
                positions=[
                    Position(
                        ticker="MSFT",
                        shares=Decimal('25'),
                        avg_price=Decimal('300.00'),
                        cost_basis=Decimal('7500.00'),  # 25 shares * $300 avg price
                        current_price=Decimal('300.00'),
                        company="Microsoft Corp."
                    )
                ]
            ),
            MockPortfolioSnapshot(
                timestamp=datetime(2025, 1, 2, 16, 0, 0),
                positions=[no_change_position]
            )
        ]

        result = calculate_daily_pnl_from_snapshots(no_change_position, snapshots)
        self.assertEqual(result, "$0.00")

    def test_loss_calculation(self):
        """Test daily P&L calculation for a loss."""
        loss_position = Position(
            ticker="GOOGL",
            shares=Decimal('10'),
            avg_price=Decimal('2500.00'),
            cost_basis=Decimal('25000.00'),  # 10 shares * $2500 avg price
            current_price=Decimal('2490.00'),
            company="Alphabet Inc."
        )

        snapshots = [
            MockPortfolioSnapshot(
                timestamp=datetime(2025, 1, 2, 16, 0, 0),  # Jan 2 is a trading day
                positions=[
                    Position(
                        ticker="GOOGL",
                        shares=Decimal('10'),
                        avg_price=Decimal('2500.00'),
                        cost_basis=Decimal('25000.00'),  # 10 shares * $2500 avg price
                        current_price=Decimal('2510.00'),  # Previous day was higher
                        company="Alphabet Inc."
                    )
                ]
            ),
            MockPortfolioSnapshot(
                timestamp=datetime(2025, 1, 3, 16, 0, 0),  # Jan 3 is a trading day
                positions=[loss_position]
            )
        ]

        result = calculate_daily_pnl_from_snapshots(loss_position, snapshots)
        # Should show -$200.00 loss (10 shares * $20.00 loss from previous day)
        self.assertEqual(result, "$-200.00")

    def test_no_snapshots(self):
        """Test with no portfolio snapshots."""
        position = Position(
            ticker="TEST",
            shares=Decimal('1'),
            avg_price=Decimal('100.00'),
            cost_basis=Decimal('100.00'),  # 1 share * $100 avg price
            current_price=Decimal('101.00'),
            company="Test Company"
        )

        result = calculate_daily_pnl_from_snapshots(position, [])
        self.assertEqual(result, "$0.00")

    def test_no_previous_data(self):
        """Test when position doesn't exist in previous snapshots."""
        position = Position(
            ticker="NEW",
            shares=Decimal('5'),
            avg_price=Decimal('50.00'),
            cost_basis=Decimal('250.00'),  # 5 shares * $50 avg price
            current_price=Decimal('52.00'),
            company="New Company"
        )

        # Only one snapshot with the position
        snapshots = [
            MockPortfolioSnapshot(
                timestamp=datetime(2025, 1, 1, 16, 0, 0),
                positions=[position]
            )
        ]

        result = calculate_daily_pnl_from_snapshots(position, snapshots)
        # Should show $10.00 P&L (5 shares * $2.00 gain from buy price)
        self.assertEqual(result, "$10.00")

    def test_position_with_none_current_price(self):
        """Test with position having None current price."""
        position = Position(
            ticker="NONE",
            shares=Decimal('1'),
            avg_price=Decimal('100.00'),
            cost_basis=Decimal('100.00'),  # 1 share * $100 avg price
            current_price=None,
            company="None Price Company"
        )

        snapshots = [
            MockPortfolioSnapshot(
                timestamp=datetime(2025, 1, 1, 16, 0, 0),
                positions=[position]
            )
        ]

        result = calculate_daily_pnl_from_snapshots(position, snapshots)
        self.assertEqual(result, "$0.00")

    def test_position_with_none_avg_price(self):
        """Test with position having None avg_price."""
        position = Position(
            ticker="NONEAVG",
            shares=Decimal('1'),
            avg_price=None,
            cost_basis=Decimal('0.00'),  # 0 cost basis since avg_price is None
            current_price=Decimal('100.00'),
            company="None Avg Price Company"
        )

        snapshots = [
            MockPortfolioSnapshot(
                timestamp=datetime(2025, 1, 1, 16, 0, 0),
                positions=[position]
            )
        ]

        result = calculate_daily_pnl_from_snapshots(position, snapshots)
        self.assertEqual(result, "$0.00")


class MockPortfolioSnapshot:
    """Mock PortfolioSnapshot class for testing."""

    def __init__(self, timestamp, positions):
        self.timestamp = timestamp
        self.positions = positions


if __name__ == '__main__':
    unittest.main()
