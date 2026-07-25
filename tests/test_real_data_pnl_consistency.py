"""
Test P&L calculation consistency between CSV and Supabase with realistic trade data.

Uses isolated temp CSV dirs and unique Supabase fund names per run so repeated
executions cannot accumulate trades and falsely diverge the two backends.
"""

import os
import tempfile
import shutil
import uuid
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


class TestRealDataPnLConsistency:
    """Test P&L calculations are consistent across CSV and Supabase backends."""
    
    @pytest.fixture(autouse=True)
    def setup_test_environment(self):
        """Set up isolated CSV + Supabase fund (no shared TEST fund pollution)."""
        load_dotenv("web_dashboard/.env")
        
        self.test_data_dir = Path(tempfile.mkdtemp(prefix="test_real_data_pnl_"))
        self.test_fund = f"TEST_REAL_{uuid.uuid4().hex[:8]}"
        
        try:
            from supabase import create_client
            supabase_url = os.getenv("SUPABASE_URL")
            supabase_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            
            if supabase_url and supabase_key:
                supabase = create_client(supabase_url, supabase_key)
                supabase.table("funds").insert({
                    "name": self.test_fund,
                    "description": "Isolated fund for real-data PnL consistency tests",
                    "currency": "CAD",
                    "fund_type": "investment"
                }).execute()
                supabase.table("cash_balances").upsert([
                    {"fund": self.test_fund, "currency": "CAD", "amount": 0},
                    {"fund": self.test_fund, "currency": "USD", "amount": 0}
                ]).execute()
        except Exception:
            pass
        
        yield
        
        try:
            from supabase import create_client
            supabase_url = os.getenv("SUPABASE_URL")
            supabase_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            
            if supabase_url and supabase_key:
                supabase = create_client(supabase_url, supabase_key)
                supabase.table("funds").delete().eq("name", self.test_fund).execute()
        except Exception:
            pass
        
        if self.test_data_dir.exists():
            try:
                shutil.rmtree(self.test_data_dir)
            except (PermissionError, OSError):
                pass
    
    def test_real_data_basic_pnl_consistency(self):
        """Test basic P&L calculations with real data."""
        # Create repositories
        csv_repo = CSVRepository(fund_name="TEST", data_directory=str(self.test_data_dir))
        supabase_repo = SupabaseRepository(fund_name=self.test_fund)
        
        # Create test position with real data
        test_position = Position(
            ticker="REAL",
            shares=Decimal("100"),
            avg_price=Decimal("50.00"),
            cost_basis=Decimal("5000.00"),
            currency="CAD",
            company="Real Test Company",
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
        
        # Get data from both repositories - use date range to include today
        # Also ensure we wait a moment for writes to complete
        import time
        time.sleep(0.5)
        
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
    
    def test_real_data_fifo_consistency(self):
        """Test FIFO P&L calculations with real data."""
        # Create repositories
        csv_repo = CSVRepository(fund_name="TEST", data_directory=str(self.test_data_dir))
        supabase_repo = SupabaseRepository(fund_name=self.test_fund)
        
        # Create FIFO trade processor for both repositories
        csv_processor = FIFOTradeProcessor(csv_repo)
        supabase_processor = FIFOTradeProcessor(supabase_repo)
        
        # Create a sequence of trades to test FIFO P&L
        trades = [
            {
                "ticker": "REAL_FIFO",
                "action": "BUY",
                "shares": Decimal("100"),
                "price": Decimal("50.00"),
                "currency": "CAD",
                "timestamp": datetime.now(timezone.utc) - timedelta(days=3)
            },
            {
                "ticker": "REAL_FIFO",
                "action": "BUY", 
                "shares": Decimal("50"),
                "price": Decimal("60.00"),
                "currency": "CAD",
                "timestamp": datetime.now(timezone.utc) - timedelta(days=2)
            },
            {
                "ticker": "REAL_FIFO",
                "action": "SELL",
                "shares": Decimal("75"),
                "price": Decimal("70.00"),
                "currency": "CAD",
                "timestamp": datetime.now(timezone.utc) - timedelta(days=1)
            }
        ]
        
        # Execute trades in both repositories
        for trade_data in trades:
            if trade_data['action'] == "BUY":
                csv_processor.execute_buy_trade(
                    ticker=trade_data['ticker'],
                    shares=trade_data['shares'],
                    price=trade_data['price'],
                    currency=trade_data['currency']
                )
                supabase_processor.execute_buy_trade(
                    ticker=trade_data['ticker'],
                    shares=trade_data['shares'],
                    price=trade_data['price'],
                    currency=trade_data['currency']
                )
            elif trade_data['action'] == "SELL":
                csv_processor.execute_sell_trade(
                    ticker=trade_data['ticker'],
                    shares=trade_data['shares'],
                    price=trade_data['price'],
                    currency=trade_data['currency']
                )
                supabase_processor.execute_sell_trade(
                    ticker=trade_data['ticker'],
                    shares=trade_data['shares'],
                    price=trade_data['price'],
                    currency=trade_data['currency']
                )
        
        # Get realized P&L summary from both processors
        csv_pnl_summary = csv_processor.get_realized_pnl_summary("REAL_FIFO")
        supabase_pnl_summary = supabase_processor.get_realized_pnl_summary("REAL_FIFO")
        
        print(f"CSV Realized P&L: {csv_pnl_summary['total_realized_pnl']}")
        print(f"Supabase Realized P&L: {supabase_pnl_summary['total_realized_pnl']}")
        print(f"CSV Shares Sold: {csv_pnl_summary['total_shares_sold']}")
        print(f"Supabase Shares Sold: {supabase_pnl_summary['total_shares_sold']}")
        
        # Isolated backends must agree on FIFO realized P&L and shares sold
        assert csv_pnl_summary['total_shares_sold'] == supabase_pnl_summary['total_shares_sold'], "FIFO shares sold should match"
        assert csv_pnl_summary['total_realized_pnl'] == supabase_pnl_summary['total_realized_pnl'], "FIFO realized P&L should match"
        assert csv_pnl_summary['total_shares_sold'] == Decimal("75"), "Expected one isolated sell of 75 shares"
        assert csv_pnl_summary['total_realized_pnl'] == Decimal("1500.0"), "Expected FIFO PnL of (70-50)*75"
    
    def test_real_data_dual_write_consistency(self):
        """Test dual-write operations with real data."""
        # Create dual-write repository
        dual_repo = DualWriteRepository(
            fund_name=self.test_fund,
            data_directory=str(self.test_data_dir),
        )
        
        # Create test position
        test_position = Position(
            ticker="DUAL_REAL",
            shares=Decimal("75"),
            avg_price=Decimal("80.00"),
            cost_basis=Decimal("6000.00"),
            currency="CAD",
            company="Dual Real Test Company",
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
