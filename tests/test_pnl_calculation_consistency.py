"""
Test P&L calculation consistency between CSV and Supabase repositories.

This module tests that P&L calculations produce the same results whether
calculated from CSV data or from Supabase database views.
"""

import os
import tempfile
import shutil
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from typing import List, Dict, Any

import pytest
from dotenv import load_dotenv

from data.models.trade import Trade
from data.models.portfolio import Position, PortfolioSnapshot
from data.repositories.csv_repository import CSVRepository
from data.repositories.supabase_repository import SupabaseRepository
from data.repositories.dual_write_repository import DualWriteRepository
from financial.pnl_calculator import PnLCalculator
from portfolio.fifo_trade_processor import FIFOTradeProcessor


class TestPnLCalculationConsistency:
    """Test that P&L calculations are consistent between CSV and Supabase."""
    
    @pytest.fixture(autouse=True)
    def setup_test_environment(self):
        """Set up test environment with temporary directories and Supabase credentials."""
        # Load Supabase credentials
        load_dotenv("web_dashboard/.env")
        
        # Create temporary directory for CSV tests
        self.test_data_dir = Path(tempfile.mkdtemp(prefix="test_pnl_consistency_"))
        
        # Use unique fund name for each test run to avoid data contamination
        import uuid
        self.test_fund = f"TEST_{uuid.uuid4().hex[:8]}"
        
        # Create fund in Supabase if credentials are available
        try:
            from supabase import create_client
            supabase_url = os.getenv("SUPABASE_URL")
            supabase_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            
            if supabase_url and supabase_key:
                supabase = create_client(supabase_url, supabase_key)
                # Create fund
                supabase.table("funds").insert({
                    "name": self.test_fund,
                    "description": "Test fund for PnL consistency tests",
                    "currency": "CAD",
                    "fund_type": "investment"
                }).execute()
                # Initialize cash balances
                supabase.table("cash_balances").upsert([
                    {"fund": self.test_fund, "currency": "CAD", "amount": 0},
                    {"fund": self.test_fund, "currency": "USD", "amount": 0}
                ]).execute()
        except Exception as e:
            # If Supabase isn't available, tests will skip or fail gracefully
            pass
        
        yield
        
        # Cleanup - try to delete fund from Supabase
        try:
            from supabase import create_client
            supabase_url = os.getenv("SUPABASE_URL")
            supabase_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            
            if supabase_url and supabase_key:
                supabase = create_client(supabase_url, supabase_key)
                # Delete fund (cascade will clean up related data)
                supabase.table("funds").delete().eq("name", self.test_fund).execute()
        except Exception:
            # Ignore cleanup errors
            pass
        
        # Cleanup CSV test directory
        if self.test_data_dir.exists():
            try:
                shutil.rmtree(self.test_data_dir)
            except (PermissionError, OSError):
                # Windows sometimes has permission issues with temp files
                pass
    
    def test_basic_pnl_calculation_consistency(self):
        """Test that basic P&L calculations are consistent between CSV and Supabase."""
        # Create repositories
        csv_repo = CSVRepository(fund_name="TEST", data_directory=str(self.test_data_dir))
        supabase_repo = SupabaseRepository(fund_name=self.test_fund)
        
        # Create test position
        test_position = Position(
            ticker="TEST",
            shares=Decimal("100"),
            avg_price=Decimal("50.00"),
            cost_basis=Decimal("5000.00"),
            currency="CAD",
            company="Test Company",
            current_price=Decimal("55.00"),
            market_value=Decimal("5500.00"),
            unrealized_pnl=Decimal("500.00")
        )
        
        # Create portfolio snapshot
        snapshot = PortfolioSnapshot(
            positions=[test_position],
            timestamp=datetime.now(timezone.utc),
            total_value=Decimal("5500.00")
        )
        
        # Save to both repositories
        csv_repo.save_portfolio_snapshot(snapshot)
        supabase_repo.save_portfolio_snapshot(snapshot)
        
        # Get data from both repositories
        # Use a date range that includes today to ensure we get the snapshot we just saved
        from datetime import timedelta
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=1)
        date_range = (start_date, end_date)
        
        csv_snapshots = csv_repo.get_portfolio_data(date_range=date_range)
        supabase_snapshots = supabase_repo.get_portfolio_data(date_range=date_range)
        
        # Both should have the snapshot
        assert len(csv_snapshots) >= 1, "CSV should have the snapshot"
        assert len(supabase_snapshots) >= 1, "Supabase should have the snapshot"
        
        csv_snapshot = csv_snapshots[-1]
        supabase_snapshot = supabase_snapshots[-1]
        
        # Compare P&L calculations
        csv_position = csv_snapshot.positions[0]
        supabase_position = supabase_snapshot.positions[0]
        
        print(f"CSV P&L: {csv_position.unrealized_pnl}")
        print(f"Supabase P&L: {supabase_position.unrealized_pnl}")
        print(f"CSV Market Value: {csv_position.market_value}")
        print(f"Supabase Market Value: {supabase_position.market_value}")
        print(f"CSV Cost Basis: {csv_position.cost_basis}")
        print(f"Supabase Cost Basis: {supabase_position.cost_basis}")
        
        # Core P&L calculations should match
        assert csv_position.unrealized_pnl == supabase_position.unrealized_pnl, "Unrealized P&L should match"
        assert csv_position.market_value == supabase_position.market_value, "Market value should match"
        assert csv_position.cost_basis == supabase_position.cost_basis, "Cost basis should match"
    
    def test_daily_pnl_calculation_consistency(self):
        """Test that daily P&L calculations are consistent between CSV and Supabase."""
        # Create repositories
        csv_repo = CSVRepository(fund_name="TEST", data_directory=str(self.test_data_dir))
        supabase_repo = SupabaseRepository(fund_name=self.test_fund)
        
        # Create two snapshots with different prices to test daily P&L
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        today = datetime.now(timezone.utc)
        
        # Yesterday's position
        yesterday_position = Position(
            ticker="DAILY",
            shares=Decimal("50"),
            avg_price=Decimal("100.00"),
            cost_basis=Decimal("5000.00"),
            currency="CAD",
            company="Daily Test Company",
            current_price=Decimal("100.00"),  # Yesterday's price
            market_value=Decimal("5000.00"),
            unrealized_pnl=Decimal("0.00")
        )
        
        yesterday_snapshot = PortfolioSnapshot(
            positions=[yesterday_position],
            timestamp=yesterday,
            total_value=Decimal("5000.00")
        )
        
        # Today's position (price increased)
        today_position = Position(
            ticker="DAILY",
            shares=Decimal("50"),
            avg_price=Decimal("100.00"),
            cost_basis=Decimal("5000.00"),
            currency="CAD",
            company="Daily Test Company",
            current_price=Decimal("110.00"),  # Today's price (10% increase)
            market_value=Decimal("5500.00"),
            unrealized_pnl=Decimal("500.00")
        )
        
        today_snapshot = PortfolioSnapshot(
            positions=[today_position],
            timestamp=today,
            total_value=Decimal("5500.00")
        )
        
        # Save both snapshots to both repositories
        csv_repo.save_portfolio_snapshot(yesterday_snapshot)
        csv_repo.save_portfolio_snapshot(today_snapshot)
        supabase_repo.save_portfolio_snapshot(yesterday_snapshot)
        supabase_repo.save_portfolio_snapshot(today_snapshot)
        
        # Calculate daily P&L using PnLCalculator
        pnl_calculator = PnLCalculator()
        
        # Get latest snapshots - use date range to include both yesterday and today
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=2)
        date_range = (start_date, end_date)
        
        csv_snapshots = csv_repo.get_portfolio_data(date_range=date_range)
        supabase_snapshots = supabase_repo.get_portfolio_data(date_range=date_range)
        
        csv_latest = csv_snapshots[-1]
        supabase_latest = supabase_snapshots[-1]
        
        # Calculate daily P&L for CSV
        csv_position = csv_latest.positions[0]
        csv_daily_pnl = pnl_calculator.calculate_daily_pnl(
            current_price=csv_position.current_price,
            previous_price=Decimal("100.00"),  # Yesterday's price
            shares=csv_position.shares
        )
        
        # Calculate daily P&L for Supabase
        supabase_position = supabase_latest.positions[0]
        supabase_daily_pnl = pnl_calculator.calculate_daily_pnl(
            current_price=supabase_position.current_price,
            previous_price=Decimal("100.00"),  # Yesterday's price
            shares=supabase_position.shares
        )
        
        print(f"CSV Daily P&L: {csv_daily_pnl['daily_absolute_pnl']}")
        print(f"Supabase Daily P&L: {supabase_daily_pnl['daily_absolute_pnl']}")
        print(f"CSV Daily P&L %: {csv_daily_pnl['daily_percentage_pnl']}")
        print(f"Supabase Daily P&L %: {supabase_daily_pnl['daily_percentage_pnl']}")
        
        # Daily P&L calculations should match
        assert csv_daily_pnl['daily_absolute_pnl'] == supabase_daily_pnl['daily_absolute_pnl'], "Daily absolute P&L should match"
        assert csv_daily_pnl['daily_percentage_pnl'] == supabase_daily_pnl['daily_percentage_pnl'], "Daily percentage P&L should match"
    
    def test_fifo_pnl_calculation_consistency(self):
        """Test that FIFO P&L calculations are consistent between CSV and Supabase."""
        # Create repositories
        csv_repo = CSVRepository(fund_name="TEST", data_directory=str(self.test_data_dir))
        supabase_repo = SupabaseRepository(fund_name=self.test_fund)
        
        # Create FIFO trade processor for both repositories
        csv_processor = FIFOTradeProcessor(csv_repo)
        supabase_processor = FIFOTradeProcessor(supabase_repo)
        
        # Create a sequence of trades to test FIFO P&L
        trades = [
            Trade(
                ticker="FIFO",
                action="BUY",
                shares=Decimal("100"),
                price=Decimal("50.00"),
                currency="CAD",
                timestamp=datetime.now(timezone.utc) - timedelta(days=3),
                cost_basis=Decimal("5000.00"),
                pnl=Decimal("0.00")
            ),
            Trade(
                ticker="FIFO",
                action="BUY",
                shares=Decimal("50"),
                price=Decimal("60.00"),
                currency="CAD",
                timestamp=datetime.now(timezone.utc) - timedelta(days=2),
                cost_basis=Decimal("3000.00"),
                pnl=Decimal("0.00")
            ),
            Trade(
                ticker="FIFO",
                action="SELL",
                shares=Decimal("75"),
                price=Decimal("70.00"),
                currency="CAD",
                timestamp=datetime.now(timezone.utc) - timedelta(days=1),
                cost_basis=Decimal("5250.00"),  # 75 * 70
                pnl=Decimal("0.00")  # Will be calculated by FIFO processor
            )
        ]
        
        # Execute trades in both repositories
        for trade in trades:
            if trade.is_buy():
                csv_processor.execute_buy_trade(
                    ticker=trade.ticker,
                    shares=trade.shares,
                    price=trade.price,
                    currency=trade.currency
                )
                supabase_processor.execute_buy_trade(
                    ticker=trade.ticker,
                    shares=trade.shares,
                    price=trade.price,
                    currency=trade.currency
                )
            elif trade.is_sell():
                csv_processor.execute_sell_trade(
                    ticker=trade.ticker,
                    shares=trade.shares,
                    price=trade.price,
                    currency=trade.currency
                )
                supabase_processor.execute_sell_trade(
                    ticker=trade.ticker,
                    shares=trade.shares,
                    price=trade.price,
                    currency=trade.currency
                )
        
        # Get realized P&L summary from both processors
        csv_pnl_summary = csv_processor.get_realized_pnl_summary("FIFO")
        supabase_pnl_summary = supabase_processor.get_realized_pnl_summary("FIFO")
        
        print(f"CSV Realized P&L: {csv_pnl_summary['total_realized_pnl']}")
        print(f"Supabase Realized P&L: {supabase_pnl_summary['total_realized_pnl']}")
        print(f"CSV Shares Sold: {csv_pnl_summary['total_shares_sold']}")
        print(f"Supabase Shares Sold: {supabase_pnl_summary['total_shares_sold']}")
        
        # FIFO P&L calculations should match
        assert csv_pnl_summary['total_realized_pnl'] == supabase_pnl_summary['total_realized_pnl'], "FIFO realized P&L should match"
        assert csv_pnl_summary['total_shares_sold'] == supabase_pnl_summary['total_shares_sold'], "FIFO shares sold should match"
    
    def test_portfolio_total_pnl_consistency(self):
        """Test that total portfolio P&L calculations are consistent."""
        # Create repositories
        csv_repo = CSVRepository(fund_name="TEST", data_directory=str(self.test_data_dir))
        supabase_repo = SupabaseRepository(fund_name=self.test_fund)
        
        # Create multiple positions
        positions = [
            Position(
                ticker="STOCK1",
                shares=Decimal("100"),
                avg_price=Decimal("50.00"),
                cost_basis=Decimal("5000.00"),
                currency="CAD",
                company="Stock 1",
                current_price=Decimal("55.00"),
                market_value=Decimal("5500.00"),
                unrealized_pnl=Decimal("500.00")
            ),
            Position(
                ticker="STOCK2",
                shares=Decimal("200"),
                avg_price=Decimal("25.00"),
                cost_basis=Decimal("5000.00"),
                currency="CAD",
                company="Stock 2",
                current_price=Decimal("22.50"),
                market_value=Decimal("4500.00"),
                unrealized_pnl=Decimal("-500.00")
            ),
            Position(
                ticker="STOCK3",
                shares=Decimal("50"),
                avg_price=Decimal("100.00"),
                cost_basis=Decimal("5000.00"),
                currency="CAD",
                company="Stock 3",
                current_price=Decimal("120.00"),
                market_value=Decimal("6000.00"),
                unrealized_pnl=Decimal("1000.00")
            )
        ]
        
        # Create portfolio snapshot
        total_value = sum(pos.market_value for pos in positions)
        
        snapshot = PortfolioSnapshot(
            positions=positions,
            timestamp=datetime.now(timezone.utc),
            total_value=total_value
        )
        
        # Save to both repositories
        csv_repo.save_portfolio_snapshot(snapshot)
        supabase_repo.save_portfolio_snapshot(snapshot)
        
        # Get data from both repositories - use date range to include today
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=1)
        date_range = (start_date, end_date)
        
        csv_snapshots = csv_repo.get_portfolio_data(date_range=date_range)
        supabase_snapshots = supabase_repo.get_portfolio_data(date_range=date_range)
        
        assert len(csv_snapshots) >= 1, "CSV should have the snapshot"
        assert len(supabase_snapshots) >= 1, "Supabase should have the snapshot"
        
        csv_snapshot = csv_snapshots[-1]
        supabase_snapshot = supabase_snapshots[-1]
        
        print(f"CSV Total Value: {csv_snapshot.total_value}")
        print(f"Supabase Total Value: {supabase_snapshot.total_value}")
        
        # Total portfolio value should match
        assert csv_snapshot.total_value == supabase_snapshot.total_value, "Total portfolio value should match"
        
        # Calculate totals from positions
        csv_total_cost_basis = sum(pos.cost_basis for pos in csv_snapshot.positions)
        supabase_total_cost_basis = sum(pos.cost_basis for pos in supabase_snapshot.positions)
        csv_total_unrealized_pnl = sum(pos.unrealized_pnl or Decimal('0') for pos in csv_snapshot.positions)
        supabase_total_unrealized_pnl = sum(pos.unrealized_pnl or Decimal('0') for pos in supabase_snapshot.positions)
        
        print(f"CSV Total Cost Basis: {csv_total_cost_basis}")
        print(f"Supabase Total Cost Basis: {supabase_total_cost_basis}")
        print(f"CSV Total Unrealized P&L: {csv_total_unrealized_pnl}")
        print(f"Supabase Total Unrealized P&L: {supabase_total_unrealized_pnl}")
        
        assert csv_total_cost_basis == supabase_total_cost_basis, "Total cost basis should match"
        assert csv_total_unrealized_pnl == supabase_total_unrealized_pnl, "Total unrealized P&L should match"
    
    def test_dual_write_pnl_consistency(self):
        """Test that dual-write operations maintain P&L consistency."""
        # Create dual-write repository
        dual_repo = DualWriteRepository(
            data_directory=str(self.test_data_dir),
            fund_name=self.test_fund
        )
        
        # Create test position
        test_position = Position(
            ticker="DUAL",
            shares=Decimal("75"),
            avg_price=Decimal("80.00"),
            cost_basis=Decimal("6000.00"),
            currency="CAD",
            company="Dual Test Company",
            current_price=Decimal("85.00"),
            market_value=Decimal("6375.00"),
            unrealized_pnl=Decimal("375.00")
        )
        
        snapshot = PortfolioSnapshot(
            positions=[test_position],
            timestamp=datetime.now(timezone.utc),
            total_value=Decimal("6375.00")
        )
        
        # Save using dual-write repository
        dual_repo.save_portfolio_snapshot(snapshot)
        
        # Get data from both underlying repositories - use date range to include today
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=1)
        date_range = (start_date, end_date)
        
        csv_snapshots = dual_repo.csv_repo.get_portfolio_data(date_range=date_range)
        supabase_snapshots = dual_repo.supabase_repo.get_portfolio_data(date_range=date_range)
        
        assert len(csv_snapshots) >= 1, "CSV should have the snapshot"
        assert len(supabase_snapshots) >= 1, "Supabase should have the snapshot"
        
        csv_snapshot = csv_snapshots[-1]
        supabase_snapshot = supabase_snapshots[-1]
        
        # P&L should be consistent between both repositories
        assert csv_snapshot.total_value == supabase_snapshot.total_value, "Dual-write total value should be consistent"
        
        # Calculate totals from positions
        csv_total_cost_basis = sum(pos.cost_basis for pos in csv_snapshot.positions)
        supabase_total_cost_basis = sum(pos.cost_basis for pos in supabase_snapshot.positions)
        csv_total_unrealized_pnl = sum(pos.unrealized_pnl or Decimal('0') for pos in csv_snapshot.positions)
        supabase_total_unrealized_pnl = sum(pos.unrealized_pnl or Decimal('0') for pos in supabase_snapshot.positions)
        
        assert csv_total_cost_basis == supabase_total_cost_basis, "Dual-write cost basis should be consistent"
        assert csv_total_unrealized_pnl == supabase_total_unrealized_pnl, "Dual-write P&L should be consistent"
        
        # Individual position P&L should also be consistent
        csv_position = csv_snapshot.positions[0]
        supabase_position = supabase_snapshot.positions[0]
        
        assert csv_position.unrealized_pnl == supabase_position.unrealized_pnl, "Individual position P&L should be consistent"
        assert csv_position.market_value == supabase_position.market_value, "Individual position market value should be consistent"
        assert csv_position.cost_basis == supabase_position.cost_basis, "Individual position cost basis should be consistent"


class TestPnLCalculationDifferences:
    """Test and document the actual differences in P&L calculations between CSV and Supabase."""
    
    @pytest.fixture(autouse=True)
    def setup_test_environment(self):
        """Set up test environment for difference analysis."""
        # Load Supabase credentials
        load_dotenv("web_dashboard/.env")
        
        # Create temporary directory for CSV tests
        self.test_data_dir = Path(tempfile.mkdtemp(prefix="test_pnl_differences_"))
        
        # Use unique fund name for each test run to avoid data contamination
        import uuid
        self.test_fund = f"TEST_{uuid.uuid4().hex[:8]}"
        
        # Create fund in Supabase if credentials are available
        try:
            from supabase import create_client
            supabase_url = os.getenv("SUPABASE_URL")
            supabase_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            
            if supabase_url and supabase_key:
                supabase = create_client(supabase_url, supabase_key)
                # Create fund
                supabase.table("funds").insert({
                    "name": self.test_fund,
                    "description": "Test fund for PnL difference tests",
                    "currency": "CAD",
                    "fund_type": "investment"
                }).execute()
                # Initialize cash balances
                supabase.table("cash_balances").upsert([
                    {"fund": self.test_fund, "currency": "CAD", "amount": 0},
                    {"fund": self.test_fund, "currency": "USD", "amount": 0}
                ]).execute()
        except Exception:
            pass
        
        yield
        
        # Cleanup - try to delete fund from Supabase
        try:
            from supabase import create_client
            supabase_url = os.getenv("SUPABASE_URL")
            supabase_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            
            if supabase_url and supabase_key:
                supabase = create_client(supabase_url, supabase_key)
                supabase.table("funds").delete().eq("name", self.test_fund).execute()
        except Exception:
            pass
        
        # Cleanup CSV test directory
        if self.test_data_dir.exists():
            try:
                shutil.rmtree(self.test_data_dir)
            except (PermissionError, OSError):
                pass
    
    def test_document_pnl_calculation_differences(self):
        """Document the actual differences in P&L calculations between CSV and Supabase."""
        # Create repositories
        csv_repo = CSVRepository(fund_name="TEST", data_directory=str(self.test_data_dir))
        supabase_repo = SupabaseRepository(fund_name=self.test_fund)
        
        # Create a complex position with various P&L scenarios
        test_position = Position(
            ticker="COMPLEX",
            shares=Decimal("150.5"),  # Fractional shares
            avg_price=Decimal("33.333"),  # Precise decimal
            cost_basis=Decimal("5016.65"),  # Precise calculation
            currency="USD",  # Different currency
            company="Complex Test Company",
            current_price=Decimal("35.789"),  # Precise current price
            market_value=Decimal("5386.35"),  # Calculated value
            unrealized_pnl=Decimal("369.70")  # Calculated P&L
        )
        
        snapshot = PortfolioSnapshot(
            positions=[test_position],
            timestamp=datetime.now(timezone.utc),
            total_value=Decimal("5386.35")
        )
        
        # Save to both repositories
        csv_repo.save_portfolio_snapshot(snapshot)
        supabase_repo.save_portfolio_snapshot(snapshot)
        
        # Retrieve and compare - use date range to include today
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=1)
        date_range = (start_date, end_date)
        
        csv_snapshots = csv_repo.get_portfolio_data(date_range=date_range)
        supabase_snapshots = supabase_repo.get_portfolio_data(date_range=date_range)
        
        assert len(csv_snapshots) >= 1, "CSV should have the snapshot"
        assert len(supabase_snapshots) >= 1, "Supabase should have the snapshot"
        
        csv_snapshot = csv_snapshots[-1]
        supabase_snapshot = supabase_snapshots[-1]
        
        csv_position = csv_snapshot.positions[0]
        supabase_position = supabase_snapshot.positions[0]
        
        # Document the differences
        print("\n=== P&L CALCULATION DIFFERENCES ===")
        print(f"CSV Unrealized P&L: {csv_position.unrealized_pnl}")
        print(f"Supabase Unrealized P&L: {supabase_position.unrealized_pnl}")
        print(f"CSV Market Value: {csv_position.market_value}")
        print(f"Supabase Market Value: {supabase_position.market_value}")
        print(f"CSV Cost Basis: {csv_position.cost_basis}")
        print(f"Supabase Cost Basis: {supabase_position.cost_basis}")
        print(f"CSV Current Price: {csv_position.current_price}")
        print(f"Supabase Current Price: {supabase_position.current_price}")
        print(f"CSV Shares: {csv_position.shares}")
        print(f"Supabase Shares: {supabase_position.shares}")
        print(f"CSV Currency: {csv_position.currency}")
        print(f"Supabase Currency: {supabase_position.currency}")
        
        # Calculate differences
        pnl_diff = csv_position.unrealized_pnl - supabase_position.unrealized_pnl if csv_position.unrealized_pnl and supabase_position.unrealized_pnl else None
        market_value_diff = csv_position.market_value - supabase_position.market_value if csv_position.market_value and supabase_position.market_value else None
        
        print(f"\nP&L Difference: {pnl_diff}")
        print(f"Market Value Difference: {market_value_diff}")
        
        # This test documents the actual differences rather than asserting they're identical
        # The differences help us understand how the field mappers work differently
