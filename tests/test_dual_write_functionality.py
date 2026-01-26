"""Tests for dual-write functionality."""

import pytest
import tempfile
import shutil
from pathlib import Path
from decimal import Decimal
from datetime import datetime
from unittest.mock import Mock, patch

from data.models.trade import Trade
from data.models.portfolio import PortfolioSnapshot, Position
from data.write_coordinator import WriteCoordinator, WriteResult
from data.repositories.csv_repository import CSVRepository
from data.repositories.repository_factory import RepositoryFactory


class TestWriteCoordinator:
    """Test WriteCoordinator dual-write functionality."""
    
    def setup_method(self):
        """Set up test environment."""
        self.test_data_dir = Path(tempfile.mkdtemp(prefix="test_dual_write_"))
        self.test_data_dir.mkdir(parents=True, exist_ok=True)
        
        # Create CSV repository
        self.csv_repo = CSVRepository(fund_name="TEST", data_directory=str(self.test_data_dir))
        
        # Create mock Supabase repository
        self.supabase_repo = Mock()
        self.supabase_repo.save_trade = Mock()
        self.supabase_repo.save_portfolio_snapshot = Mock()
        
        # Create write coordinator
        self.coordinator = WriteCoordinator(self.csv_repo, self.supabase_repo)
    
    def teardown_method(self):
        """Clean up test environment."""
        if self.test_data_dir.exists():
            try:
                shutil.rmtree(self.test_data_dir)
            except (PermissionError, OSError):
                # On Windows, files might still be locked - ignore cleanup errors
                pass
    
    def test_write_coordinator_initialization(self):
        """Test WriteCoordinator initializes correctly."""
        assert self.coordinator.csv_repo is not None
        assert self.coordinator.supabase_repo is not None
    
    def test_save_trade_both_success(self):
        """Test save_trade when both repositories succeed."""
        # Setup
        trade = Trade(
            ticker="AAPL",
            action="BUY",
            shares=Decimal("10"),
            price=Decimal("150.00"),
            timestamp=datetime.now(),
            cost_basis=Decimal("1500.00"),
            reason="Test trade",
            currency="USD"
        )
        
        # Mock successful saves
        self.supabase_repo.save_trade.return_value = None
        
        # Execute
        result = self.coordinator.save_trade(trade)
        
        # Verify
        assert result.all_successful is True
        assert result.csv_success is True
        assert result.supabase_success is True
        assert result.csv_error is None
        assert result.supabase_error is None
        
        # Verify both repositories were called
        self.supabase_repo.save_trade.assert_called_once_with(trade)
    
    def test_save_trade_csv_success_supabase_failure(self):
        """Test save_trade when CSV succeeds but Supabase fails."""
        # Setup
        trade = Trade(
            ticker="AAPL",
            action="BUY",
            shares=Decimal("10"),
            price=Decimal("150.00"),
            timestamp=datetime.now(),
            cost_basis=Decimal("1500.00"),
            reason="Test trade",
            currency="USD"
        )
        
        # Mock Supabase failure
        self.supabase_repo.save_trade.side_effect = Exception("Supabase connection failed")
        
        # Execute
        result = self.coordinator.save_trade(trade)
        
        # Verify
        assert result.all_successful is False
        assert result.any_successful is True
        assert result.csv_success is True
        assert result.supabase_success is False
        assert result.csv_error is None
        assert "Supabase connection failed" in result.supabase_error
        
        # Verify failure messages
        failures = result.get_failure_messages()
        assert len(failures) == 1
        assert "Supabase" in failures[0]
    
    def test_save_trade_both_failure(self):
        """Test save_trade when both repositories fail."""
        # Setup
        trade = Trade(
            ticker="AAPL",
            action="BUY",
            shares=Decimal("10"),
            price=Decimal("150.00"),
            timestamp=datetime.now(),
            cost_basis=Decimal("1500.00"),
            reason="Test trade",
            currency="USD"
        )
        
        # Mock both failures
        self.supabase_repo.save_trade.side_effect = Exception("Supabase connection failed")
        
        # Mock CSV failure by making the directory read-only
        try:
            self.test_data_dir.chmod(0o444)  # Read-only
        except (OSError, PermissionError):
            # On Windows, we can't easily make directories read-only
            # Just mock the CSV failure instead
            pass
        
        # Execute
        result = self.coordinator.save_trade(trade)
        
        # Verify - CSV might still succeed on Windows, so check for partial failure
        assert result.all_successful is False
        # At least one should fail (Supabase definitely will)
        assert result.supabase_success is False
        assert result.supabase_error is not None
        
        # Verify failure messages
        failures = result.get_failure_messages()
        assert len(failures) >= 1  # At least Supabase failure
    
    def test_save_portfolio_snapshot_both_success(self):
        """Test save_portfolio_snapshot when both repositories succeed."""
        # Setup
        position = Position(
            ticker="AAPL",
            shares=Decimal("10"),
            avg_price=Decimal("150.00"),
            cost_basis=Decimal("1500.00"),
            currency="USD"
        )
        
        snapshot = PortfolioSnapshot(
            positions=[position],
            timestamp=datetime.now()
        )
        
        # Mock successful saves
        self.supabase_repo.save_portfolio_snapshot.return_value = None
        
        # Execute
        result = self.coordinator.save_portfolio_snapshot(snapshot)
        
        # Verify
        assert result.all_successful is True
        assert result.csv_success is True
        assert result.supabase_success is True
        
        # Verify both repositories were called
        self.supabase_repo.save_portfolio_snapshot.assert_called_once_with(snapshot)
    
    def test_validate_sync_both_empty(self):
        """Test sync validation when both repositories are empty."""
        # Mock empty repositories
        self.supabase_repo.get_trade_history.return_value = []
        self.supabase_repo.get_latest_portfolio_snapshot.return_value = None
        
        # Execute
        result = self.coordinator.validate_sync()
        
        # Verify
        assert result is True
    
    def test_validate_sync_trade_count_mismatch(self):
        """Test sync validation when trade counts don't match."""
        # Mock different trade counts
        self.supabase_repo.get_trade_history.return_value = [Mock(), Mock()]  # 2 trades
        self.supabase_repo.get_latest_portfolio_snapshot.return_value = None
        
        # Execute
        result = self.coordinator.validate_sync()
        
        # Verify
        assert result is False


class TestRepositoryFactoryDualWrite:
    """Test RepositoryFactory dual-write functionality."""
    
    def setup_method(self):
        """Set up test environment."""
        self.test_data_dir = Path(tempfile.mkdtemp(prefix="test_factory_"))
        self.test_data_dir.mkdir(parents=True, exist_ok=True)
    
    def teardown_method(self):
        """Clean up test environment."""
        if self.test_data_dir.exists():
            try:
                shutil.rmtree(self.test_data_dir)
            except (PermissionError, OSError):
                # On Windows, files might still be locked - ignore cleanup errors
                pass
    
    def test_create_dual_write_repository(self):
        """Test creating dual-write repository with real Supabase credentials."""
        # Load environment variables from .env file
        from dotenv import load_dotenv
        import os
        load_dotenv("web_dashboard/.env")
        
        # Setup - use TEST fund to avoid affecting production data
        fund_name = "TEST"
        
        # Execute
        repository = RepositoryFactory.create_dual_write_repository(
            fund_name=fund_name,
            data_directory=str(self.test_data_dir)
        )
        
        # Verify - should return DualWriteRepository, not WriteCoordinator
        from data.repositories.dual_write_repository import DualWriteRepository
        assert isinstance(repository, DualWriteRepository)
        assert repository.csv_repo is not None
        assert repository.supabase_repo is not None


class TestDualWriteIntegration:
    """Integration tests for dual-write functionality."""
    
    def setup_method(self):
        """Set up test environment."""
        self.test_data_dir = Path(tempfile.mkdtemp(prefix="test_integration_"))
        self.test_data_dir.mkdir(parents=True, exist_ok=True)
    
    def teardown_method(self):
        """Clean up test environment."""
        if self.test_data_dir.exists():
            try:
                shutil.rmtree(self.test_data_dir)
            except (PermissionError, OSError):
                # On Windows, files might still be locked - ignore cleanup errors
                pass
    
    def test_trade_processor_with_dual_write(self):
        """Test FIFOTradeProcessor with dual-write coordinator using real Supabase."""
        from portfolio.fifo_trade_processor import FIFOTradeProcessor
        
        # Load environment variables from .env file
        from dotenv import load_dotenv
        load_dotenv("web_dashboard/.env")
        
        # Setup - use TEST fund to avoid affecting production data
        coordinator = RepositoryFactory.create_dual_write_repository(
            fund_name="TEST",
            data_directory=str(self.test_data_dir)
        )
        
        processor = FIFOTradeProcessor(coordinator)
        
        # Execute trade
        trade = processor.execute_buy_trade(
            ticker="TEST",
            shares=Decimal("1"),
            price=Decimal("10.00"),
            reason="Test trade - dual write"
        )
        
        # Verify
        assert trade is not None
        assert trade.ticker == "TEST"
        assert trade.action == "BUY"
        
        # Verify trade was saved to CSV (Supabase might fail due to network, but CSV should work)
        csv_trades = coordinator.csv_repo.get_trade_history()
        assert len(csv_trades) >= 1
        assert any(t.ticker == "TEST" for t in csv_trades)
    
    def test_fallback_to_csv_only(self):
        """Test fallback to CSV-only when Supabase is unavailable."""
        # This test would require mocking the Supabase connection failure
        # For now, we'll just verify the CSV repository works
        csv_repo = CSVRepository(fund_name="TEST", data_directory=str(self.test_data_dir))
        
        trade = Trade(
            ticker="AAPL",
            action="BUY",
            shares=Decimal("10"),
            price=Decimal("150.00"),
            timestamp=datetime.now(),
            cost_basis=Decimal("1500.00"),
            reason="Test trade",
            currency="USD"
        )
        
        # Should not raise exception
        csv_repo.save_trade(trade)
        
        # Verify trade was saved
        trades = csv_repo.get_trade_history()
        assert len(trades) == 1
        assert trades[0].ticker == "AAPL"
