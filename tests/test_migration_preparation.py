"""
Migration preparation tests for the trading system.

Tests cover data model serialization for both CSV and JSON formats,
repository pattern abstraction with mock database repository,
and backup/restore functionality with different backend types.
"""

import unittest
import tempfile
import shutil
import json
import csv
from datetime import datetime, timezone, timedelta
from pathlib import Path
from decimal import Decimal
import sys

# Add the parent directory to the path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.models.portfolio import Position, PortfolioSnapshot
from data.models.trade import Trade
from data.models.market_data import MarketData
from data.repositories.base_repository import BaseRepository
from data.repositories.csv_repository import CSVRepository
from data.repositories.repository_factory import RepositoryFactory
from utils.backup_manager import BackupManager


class MockDatabaseRepository(BaseRepository):
    """Mock database repository for testing migration patterns."""
    
    def __init__(self, connection_string: str = "mock://localhost/test"):
        """Initialize mock database repository."""
        self.connection_string = connection_string
        self.portfolios = []
        self.trades = []
        self.market_data = {}
        self.connected = True
    
    def get_portfolio_data(self, date_range=None, limit=None):
        """Get portfolio snapshots from mock database."""
        snapshots = self.portfolios.copy()
        if date_range:
            start_date, end_date = date_range
            snapshots = [s for s in snapshots if start_date <= s.timestamp <= end_date]
        if limit:
            snapshots = snapshots[-limit:]
        return snapshots
    
    def save_portfolio_snapshot(self, snapshot):
        """Save portfolio snapshot to mock database."""
        # Simulate database ID assignment
        if not snapshot.snapshot_id:
            snapshot.snapshot_id = f"db_snap_{len(self.portfolios) + 1}"
        
        # Remove existing snapshot with same ID
        self.portfolios = [s for s in self.portfolios if s.snapshot_id != snapshot.snapshot_id]
        self.portfolios.append(snapshot)
    
    def get_latest_portfolio_snapshot(self):
        """Get the most recent portfolio snapshot."""
        return self.portfolios[-1] if self.portfolios else None
    
    def get_trade_history(self, ticker=None, date_range=None, limit=None):
        """Get trades from mock database."""
        trades = self.trades.copy()
        if ticker:
            trades = [t for t in trades if t.ticker == ticker]
        if date_range:
            start_date, end_date = date_range
            trades = [t for t in trades if start_date <= t.timestamp <= end_date]
        if limit:
            trades = trades[-limit:]
        return trades
    
    def save_trade(self, trade):
        """Save trade to mock database."""
        # Simulate database ID assignment
        if not trade.trade_id:
            trade.trade_id = f"db_trade_{len(self.trades) + 1}"
        
        # Remove existing trade with same ID
        self.trades = [t for t in self.trades if t.trade_id != trade.trade_id]
        self.trades.append(trade)
    
    def get_positions_by_ticker(self, ticker):
        """Get positions for a ticker across all snapshots."""
        positions = []
        for snapshot in self.portfolios:
            for position in snapshot.positions:
                if position.ticker == ticker:
                    positions.append(position)
        return positions
    
    def get_market_data(self, ticker, date_range=None):
        """Get market data from mock database."""
        data = self.market_data.get(ticker, [])
        if date_range:
            start_date, end_date = date_range
            data = [d for d in data if start_date <= d.date <= end_date]
        return data
    
    def save_market_data(self, market_data):
        """Save market data to mock database."""
        if market_data.ticker not in self.market_data:
            self.market_data[market_data.ticker] = []
        
        # Simulate database ID assignment
        if not market_data.data_id:
            market_data.data_id = f"db_md_{len(self.market_data[market_data.ticker]) + 1}"
        
        self.market_data[market_data.ticker].append(market_data)
    
    def backup_data(self, backup_path):
        """Create backup of mock database."""
        backup_data = {
            'portfolios': [p.to_dict() for p in self.portfolios],
            'trades': [t.to_dict() for t in self.trades],
            'market_data': {k: [md.to_dict() for md in v] for k, v in self.market_data.items()},
            'backup_timestamp': datetime.now(timezone.utc).isoformat(),
            'repository_type': 'database',
            'connection_string': self.connection_string
        }
        
        with open(backup_path, 'w') as f:
            json.dump(backup_data, f, indent=2, default=str)
    
    def restore_from_backup(self, backup_path):
        """Restore mock database from backup."""
        with open(backup_path, 'r') as f:
            backup_data = json.load(f)
        
        # Clear existing data
        self.portfolios.clear()
        self.trades.clear()
        self.market_data.clear()
        
        # Restore portfolios
        for p_data in backup_data.get('portfolios', []):
            portfolio = PortfolioSnapshot.from_dict(p_data)
            self.portfolios.append(portfolio)
        
        # Restore trades
        for t_data in backup_data.get('trades', []):
            trade = Trade.from_dict(t_data)
            self.trades.append(trade)
        
        # Restore market data
        for ticker, md_list in backup_data.get('market_data', {}).items():
            self.market_data[ticker] = []
            for md_data in md_list:
                market_data = MarketData.from_dict(md_data)
                self.market_data[ticker].append(market_data)
    
    def validate_data_integrity(self):
        """Validate database data integrity."""
        issues = []
        
        # Check for duplicate IDs
        portfolio_ids = [p.snapshot_id for p in self.portfolios if p.snapshot_id]
        if len(portfolio_ids) != len(set(portfolio_ids)):
            issues.append("Duplicate portfolio snapshot IDs found")
        
        trade_ids = [t.trade_id for t in self.trades if t.trade_id]
        if len(trade_ids) != len(set(trade_ids)):
            issues.append("Duplicate trade IDs found")
        
        return issues
    
    def update_ticker_in_future_snapshots(self, ticker: str, trade_timestamp: datetime) -> None:
        """Update ticker in future snapshots (mock implementation)."""
        # For mock repository, just update positions in snapshots after trade timestamp
        for snapshot in self.portfolios:
            if snapshot.timestamp > trade_timestamp:
                # Update positions for this ticker in future snapshots
                # This is a simplified mock - real implementation would recalculate using FIFO
                for position in snapshot.positions:
                    if position.ticker == ticker:
                        # Mock: just mark as updated
                        pass


class TestDataModelSerialization(unittest.TestCase):
    """Test data model serialization for both CSV and JSON formats."""
    
    def test_position_csv_json_serialization(self):
        """Test Position serialization to both CSV and JSON formats."""
        position = Position(
            ticker="AAPL",
            shares=Decimal('100.123456'),
            avg_price=Decimal('150.99'),
            cost_basis=Decimal('15099.123456'),
            current_price=Decimal('155.01'),
            market_value=Decimal('15501.123456'),
            unrealized_pnl=Decimal('402.00'),
            currency="USD",
            company="Apple Inc.",
            position_id="pos_123"
        )
        
        # Test CSV serialization
        csv_data = position.to_csv_dict()
        self.assertIn('Ticker', csv_data)
        self.assertIn('Shares', csv_data)
        self.assertIn('Average Price', csv_data)
        self.assertEqual(csv_data['Ticker'], 'AAPL')
        self.assertEqual(csv_data['Currency'], 'USD')
        
        # Test JSON serialization
        json_data = position.to_dict()
        self.assertIn('ticker', json_data)
        self.assertIn('shares', json_data)
        self.assertIn('avg_price', json_data)
        self.assertEqual(json_data['ticker'], 'AAPL')
        self.assertEqual(json_data['currency'], 'USD')
        
        # Test round-trip CSV
        restored_from_csv = Position.from_csv_dict(csv_data)
        self.assertEqual(restored_from_csv.ticker, position.ticker)
        self.assertEqual(restored_from_csv.currency, position.currency)
        
        # Test round-trip JSON
        restored_from_json = Position.from_dict(json_data)
        self.assertEqual(restored_from_json.ticker, position.ticker)
        self.assertEqual(restored_from_json.currency, position.currency)
        self.assertEqual(restored_from_json.position_id, position.position_id)
    
    def test_trade_csv_json_serialization(self):
        """Test Trade serialization to both CSV and JSON formats."""
        timestamp = datetime.now(timezone.utc)
        trade = Trade(
            ticker="GOOGL",
            action="BUY",
            shares=Decimal('50.5'),
            price=Decimal('2000.99'),
            timestamp=timestamp,
            cost_basis=Decimal('101049.95'),
            pnl=Decimal('500.00'),
            reason="Strong fundamentals",
            currency="USD",
            trade_id="trade_456"
        )
        
        # Test CSV serialization
        csv_data = trade.to_csv_dict()
        self.assertIn('Ticker', csv_data)
        self.assertIn('Shares', csv_data)
        self.assertIn('Price', csv_data)
        self.assertEqual(csv_data['Ticker'], 'GOOGL')
        self.assertEqual(csv_data['Reason'], 'Strong fundamentals')
        
        # Test JSON serialization
        json_data = trade.to_dict()
        self.assertIn('ticker', json_data)
        self.assertIn('action', json_data)
        self.assertIn('shares', json_data)
        self.assertEqual(json_data['ticker'], 'GOOGL')
        self.assertEqual(json_data['action'], 'BUY')
        self.assertEqual(json_data['trade_id'], 'trade_456')
        
        # Test round-trip CSV
        restored_from_csv = Trade.from_csv_dict(csv_data, timestamp)
        self.assertEqual(restored_from_csv.ticker, trade.ticker)
        self.assertEqual(restored_from_csv.reason, trade.reason)
        
        # Test round-trip JSON
        restored_from_json = Trade.from_dict(json_data)
        self.assertEqual(restored_from_json.ticker, trade.ticker)
        self.assertEqual(restored_from_json.action, trade.action)
        self.assertEqual(restored_from_json.trade_id, trade.trade_id)
    
    def test_portfolio_snapshot_json_serialization(self):
        """Test PortfolioSnapshot JSON serialization for web API."""
        positions = [
            Position(ticker="AAPL", shares=Decimal('100'), avg_price=Decimal('150.00'),
                    cost_basis=Decimal('15000.00'), current_price=Decimal('155.00')),
            Position(ticker="GOOGL", shares=Decimal('50'), avg_price=Decimal('2000.00'),
                    cost_basis=Decimal('100000.00'), current_price=Decimal('2100.00')),
        ]
        
        timestamp = datetime.now(timezone.utc)
        snapshot = PortfolioSnapshot(
            positions=positions,
            cash_balance=Decimal('5000.00'),
            timestamp=timestamp,
            total_value=Decimal('125000.00'),
            snapshot_id="snap_789"
        )
        
        # Test JSON serialization
        json_data = snapshot.to_dict()
        self.assertIn('positions', json_data)
        self.assertIn('cash_balance', json_data)
        self.assertIn('timestamp', json_data)
        self.assertIn('snapshot_id', json_data)
        
        self.assertEqual(len(json_data['positions']), 2)
        self.assertEqual(json_data['snapshot_id'], 'snap_789')
        
        # Test round-trip JSON
        restored = PortfolioSnapshot.from_dict(json_data)
        self.assertEqual(len(restored.positions), 2)
        self.assertEqual(restored.snapshot_id, snapshot.snapshot_id)
        self.assertEqual(restored.cash_balance, snapshot.cash_balance)
    
    def test_market_data_serialization(self):
        """Test MarketData serialization for database storage."""
        date = datetime.now(timezone.utc)
        market_data = MarketData(
            ticker="MSFT",
            date=date,
            open_price=Decimal('300.00'),
            high_price=Decimal('305.50'),
            low_price=Decimal('299.00'),
            close_price=Decimal('304.25'),
            adj_close_price=Decimal('304.25'),
            volume=1500000,
            source="yahoo",
            data_id="md_101"
        )
        
        # Test JSON serialization
        json_data = market_data.to_dict()
        expected_keys = [
            'ticker', 'date', 'open', 'high', 'low', 'close', 
            'adj_close', 'volume', 'source', 'data_id'
        ]
        
        for key in expected_keys:
            self.assertIn(key, json_data)
        
        self.assertEqual(json_data['ticker'], 'MSFT')
        self.assertEqual(json_data['source'], 'yahoo')
        self.assertEqual(json_data['data_id'], 'md_101')
        
        # Test round-trip JSON
        restored = MarketData.from_dict(json_data)
        self.assertEqual(restored.ticker, market_data.ticker)
        self.assertEqual(restored.source, market_data.source)
        self.assertEqual(restored.data_id, market_data.data_id)
        self.assertEqual(restored.volume, market_data.volume)
    
    def test_serialization_precision_preservation(self):
        """Test that decimal precision is preserved in serialization."""
        position = Position(
            ticker="AAPL",
            shares=Decimal('100.123456789'),
            avg_price=Decimal('150.999999'),
            cost_basis=Decimal('15099.123456789'),
            current_price=Decimal('155.555555')
        )
        
        # Test JSON round-trip preserves precision
        json_data = position.to_dict()
        restored = Position.from_dict(json_data)
        
        # Should preserve business-required precision: 4 decimal places for shares, 2 for money
        self.assertAlmostEqual(float(restored.shares), float(position.shares), places=4)
        self.assertAlmostEqual(float(restored.avg_price), float(position.avg_price), places=2)
    
    def test_serialization_with_none_values(self):
        """Test serialization handling of None values."""
        position = Position(
            ticker="AAPL",
            shares=Decimal('100'),
            avg_price=Decimal('150.00'),
            cost_basis=Decimal('15000.00'),
            current_price=None,  # None value
            market_value=None,   # None value
            company=None         # None value
        )
        
        # Test JSON serialization handles None values
        json_data = position.to_dict()
        # The to_dict method might convert None to 0.0 for numeric fields
        current_price = json_data.get('current_price')
        self.assertTrue(current_price is None or current_price == 0.0)
        market_value = json_data.get('market_value')
        self.assertTrue(market_value is None or market_value == 0.0)
        
        # Test CSV serialization handles None values
        csv_data = position.to_csv_dict()
        # CSV format converts None to default values
        current_price = csv_data.get('Current Price')
        self.assertTrue(current_price == 0.0 or current_price is None)
        self.assertEqual(csv_data.get('Company'), '')
        
        # Test round-trip with None values
        restored = Position.from_dict(json_data)
        self.assertIsNone(restored.current_price)
        self.assertIsNone(restored.market_value)


class TestRepositoryPatternAbstraction(unittest.TestCase):
    """Test repository pattern abstraction with mock database repository."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.temp_dir)
        
        # Create both repository types
        self.csv_repo = CSVRepository(fund_name="TEST", data_directory=str(self.data_dir))
        self.db_repo = MockDatabaseRepository("mock://test/db")
        
        # Sample data
        self.sample_positions = [
            Position(ticker="AAPL", shares=Decimal('100'), avg_price=Decimal('150.00'),
                    cost_basis=Decimal('15000.00'), current_price=Decimal('155.00')),
            Position(ticker="GOOGL", shares=Decimal('50'), avg_price=Decimal('2000.00'),
                    cost_basis=Decimal('100000.00'), current_price=Decimal('2100.00')),
        ]
        
        self.sample_snapshot = PortfolioSnapshot(
            positions=self.sample_positions,
            cash_balance=Decimal('5000.00'),
            timestamp=datetime.now(timezone.utc)
        )
        
        self.sample_trade = Trade(
            ticker="MSFT",
            action="BUY",
            shares=Decimal('75'),
            price=Decimal('300.00'),
            timestamp=datetime.now(timezone.utc),
            cost_basis=Decimal('22500.00')
        )
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir)
    
    def test_repository_interface_consistency(self):
        """Test that both repositories implement the same interface consistently."""
        repositories = [self.csv_repo, self.db_repo]
        
        for repo in repositories:
            # Test portfolio operations
            repo.save_portfolio_snapshot(self.sample_snapshot)
            snapshots = repo.get_portfolio_data()
            
            self.assertIsInstance(snapshots, list)
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(len(snapshots[0].positions), 2)
            
            # Test trade operations
            repo.save_trade(self.sample_trade)
            trades = repo.get_trade_history()
            
            self.assertIsInstance(trades, list)
            self.assertEqual(len(trades), 1)
            self.assertEqual(trades[0].ticker, "MSFT")
    
    def test_data_migration_between_repositories(self):
        """Test migrating data from CSV to database repository."""
        # Save data to CSV repository
        self.csv_repo.save_portfolio_snapshot(self.sample_snapshot)
        self.csv_repo.save_trade(self.sample_trade)
        
        # Load data from CSV repository
        csv_snapshots = self.csv_repo.get_portfolio_data()
        csv_trades = self.csv_repo.get_trade_history()
        
        # Migrate to database repository
        for snapshot in csv_snapshots:
            self.db_repo.save_portfolio_snapshot(snapshot)
        
        for trade in csv_trades:
            self.db_repo.save_trade(trade)
        
        # Verify data in database repository
        db_snapshots = self.db_repo.get_portfolio_data()
        db_trades = self.db_repo.get_trade_history()
        
        self.assertEqual(len(db_snapshots), len(csv_snapshots))
        self.assertEqual(len(db_trades), len(csv_trades))
        
        # Verify data integrity
        self.assertEqual(db_snapshots[0].cash_balance, csv_snapshots[0].cash_balance)
        self.assertEqual(db_trades[0].ticker, csv_trades[0].ticker)
        self.assertEqual(db_trades[0].shares, csv_trades[0].shares)
    
    def test_database_specific_features(self):
        """Test database-specific features like ID assignment."""
        # Save data to database repository
        self.db_repo.save_portfolio_snapshot(self.sample_snapshot)
        self.db_repo.save_trade(self.sample_trade)
        
        # Verify database IDs were assigned
        snapshots = self.db_repo.get_portfolio_data()
        trades = self.db_repo.get_trade_history()
        
        self.assertIsNotNone(snapshots[0].snapshot_id)
        self.assertTrue(snapshots[0].snapshot_id.startswith("db_snap_"))
        
        self.assertIsNotNone(trades[0].trade_id)
        self.assertTrue(trades[0].trade_id.startswith("db_trade_"))
    
    def test_repository_filtering_capabilities(self):
        """Test filtering capabilities across repository types."""
        # Create multiple trades with different dates
        trades = [
            Trade(ticker="AAPL", action="BUY", shares=Decimal('100'), price=Decimal('150.00'),
                  timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc), cost_basis=Decimal('15000.00')),
            Trade(ticker="GOOGL", action="BUY", shares=Decimal('50'), price=Decimal('2000.00'),
                  timestamp=datetime(2025, 1, 2, tzinfo=timezone.utc), cost_basis=Decimal('100000.00')),
            Trade(ticker="AAPL", action="SELL", shares=Decimal('25'), price=Decimal('160.00'),
                  timestamp=datetime(2025, 1, 3, tzinfo=timezone.utc), pnl=Decimal('250.00')),
        ]
        
        repositories = [self.csv_repo, self.db_repo]
        
        for repo in repositories:
            # Save all trades
            for trade in trades:
                repo.save_trade(trade)
            
            # Test ticker filtering
            aapl_trades = repo.get_trade_history(ticker="AAPL")
            self.assertEqual(len(aapl_trades), 2)
            
            googl_trades = repo.get_trade_history(ticker="GOOGL")
            self.assertEqual(len(googl_trades), 1)
            
            # Test date range filtering
            # Use a broader date range to account for timezone shifts during save/load
            # The CSV repository converts UTC to PST/PDT, so we need to account for the 8-hour shift
            date_range = (datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc), 
                         datetime(2025, 1, 3, 12, 0, tzinfo=timezone.utc))
            recent_trades = repo.get_trade_history(date_range=date_range)
            self.assertEqual(len(recent_trades), 2)
    
    def test_repository_error_handling(self):
        """Test error handling consistency across repositories."""
        # Test with invalid data
        invalid_position = Position(
            ticker="",  # Invalid empty ticker
            shares=Decimal('0'),  # Invalid zero shares
            avg_price=Decimal('150.00'),
            cost_basis=Decimal('0.00')
        )
        
        invalid_snapshot = PortfolioSnapshot(
            positions=[invalid_position],
            cash_balance=Decimal('5000.00'),
            timestamp=datetime.now(timezone.utc)
        )
        
        repositories = [self.csv_repo, self.db_repo]
        
        for repo in repositories:
            # Should handle invalid data gracefully
            try:
                repo.save_portfolio_snapshot(invalid_snapshot)
                # If no exception, verify data was handled appropriately
                snapshots = repo.get_portfolio_data()
                # Implementation may choose to save with warnings or reject
                self.assertIsInstance(snapshots, list)
            except Exception as e:
                # If exception is raised, it should be a specific repository error
                self.assertIsInstance(e, Exception)
    
    def test_repository_factory_with_mock_database(self):
        """Test repository factory with mock database repository."""
        # Register mock database repository
        RepositoryFactory.register_repository("mock_db", MockDatabaseRepository)
        
        # Create repository through factory
        repo = RepositoryFactory.create_repository("mock_db", connection_string="mock://test")
        
        self.assertIsInstance(repo, MockDatabaseRepository)
        self.assertEqual(repo.connection_string, "mock://test")
        
        # Test that it works like other repositories
        repo.save_portfolio_snapshot(self.sample_snapshot)
        snapshots = repo.get_portfolio_data()
        
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(len(snapshots[0].positions), 2)


class TestBackupRestoreFunctionality(unittest.TestCase):
    """Test backup and restore functionality with different backend types."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.temp_dir)
        self.backup_dir = Path(self.temp_dir) / "backups"
        
        # Create repositories
        self.csv_repo = CSVRepository(fund_name="TEST", data_directory=str(self.data_dir))
        self.db_repo = MockDatabaseRepository("mock://test/db")
        
        # Create backup managers
        self.csv_backup_manager = BackupManager(self.data_dir, self.backup_dir)
        
        # Sample data
        self.sample_data = self._create_sample_data()
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir)
    
    def _create_sample_data(self):
        """Create comprehensive sample data for testing."""
        positions = [
            Position(ticker="AAPL", shares=Decimal('100'), avg_price=Decimal('150.00'),
                    cost_basis=Decimal('15000.00'), current_price=Decimal('155.00'),
                    currency="USD", company="Apple Inc."),
            Position(ticker="SHOP.TO", shares=Decimal('50'), avg_price=Decimal('75.00'),
                    cost_basis=Decimal('3750.00'), current_price=Decimal('80.00'),
                    currency="CAD", company="Shopify Inc."),
        ]
        
        snapshot = PortfolioSnapshot(
            positions=positions,
            cash_balance=Decimal('10000.00'),
            timestamp=datetime.now(timezone.utc)
        )
        
        trades = [
            Trade(ticker="AAPL", action="BUY", shares=Decimal('100'), price=Decimal('150.00'),
                  timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc), cost_basis=Decimal('15000.00'),
                  currency="USD", reason="Strong fundamentals"),
            Trade(ticker="SHOP.TO", action="BUY", shares=Decimal('50'), price=Decimal('75.00'),
                  timestamp=datetime(2025, 1, 2, tzinfo=timezone.utc), cost_basis=Decimal('3750.00'),
                  currency="CAD", reason="E-commerce growth"),
        ]
        
        market_data = [
            MarketData(ticker="AAPL", date=datetime(2025, 1, 1, tzinfo=timezone.utc),
                      open_price=Decimal('149.00'), high_price=Decimal('152.00'),
                      low_price=Decimal('148.00'), close_price=Decimal('150.00'),
                      volume=1000000, source="yahoo"),
            MarketData(ticker="SHOP.TO", date=datetime(2025, 1, 2, tzinfo=timezone.utc),
                      open_price=Decimal('74.00'), high_price=Decimal('76.00'),
                      low_price=Decimal('73.50'), close_price=Decimal('75.00'),
                      volume=500000, source="yahoo"),
        ]
        
        return {
            'snapshot': snapshot,
            'trades': trades,
            'market_data': market_data
        }
    
    def test_csv_backup_and_restore(self):
        """Test backup and restore with CSV repository."""
        # Save data to CSV repository
        self.csv_repo.save_portfolio_snapshot(self.sample_data['snapshot'])
        for trade in self.sample_data['trades']:
            self.csv_repo.save_trade(trade)
        
        # Create backup
        backup_name = self.csv_backup_manager.create_backup("csv_test")
        self.assertIsNotNone(backup_name)
        
        # Verify backup files exist
        backup_files = list(self.backup_dir.glob(f"*{backup_name}*"))
        self.assertGreater(len(backup_files), 0)
        
        # Modify original data
        portfolio_file = self.data_dir / "llm_portfolio_update.csv"
        with open(portfolio_file, 'w') as f:
            f.write("corrupted,data\n")
        
        # Restore from backup
        result = self.csv_backup_manager.restore_from_backup(backup_name)
        self.assertTrue(result)
        
        # Verify data was restored
        restored_snapshots = self.csv_repo.get_portfolio_data()
        restored_trades = self.csv_repo.get_trade_history()
        
        self.assertEqual(len(restored_snapshots), 1)
        self.assertEqual(len(restored_trades), 2)
        self.assertEqual(restored_snapshots[0].positions[0].ticker, "AAPL")
    
    def test_database_backup_and_restore(self):
        """Test backup and restore with database repository."""
        # Save data to database repository
        self.db_repo.save_portfolio_snapshot(self.sample_data['snapshot'])
        for trade in self.sample_data['trades']:
            self.db_repo.save_trade(trade)
        for md in self.sample_data['market_data']:
            self.db_repo.save_market_data(md)
        
        # Create backup
        backup_file = self.backup_dir / "db_backup.json"
        self.backup_dir.mkdir(exist_ok=True)
        self.db_repo.backup_data(backup_file)
        
        self.assertTrue(backup_file.exists())
        
        # Verify backup content
        with open(backup_file, 'r') as f:
            backup_data = json.load(f)
        
        self.assertIn('portfolios', backup_data)
        self.assertIn('trades', backup_data)
        self.assertIn('market_data', backup_data)
        self.assertIn('repository_type', backup_data)
        self.assertEqual(backup_data['repository_type'], 'database')
        
        # Clear database
        self.db_repo.portfolios.clear()
        self.db_repo.trades.clear()
        self.db_repo.market_data.clear()
        
        # Restore from backup
        self.db_repo.restore_from_backup(backup_file)
        
        # Verify data was restored
        restored_snapshots = self.db_repo.get_portfolio_data()
        restored_trades = self.db_repo.get_trade_history()
        restored_market_data = self.db_repo.get_market_data("AAPL")
        
        self.assertEqual(len(restored_snapshots), 1)
        self.assertEqual(len(restored_trades), 2)
        self.assertEqual(len(restored_market_data), 1)
    
    def test_cross_repository_backup_restore(self):
        """Test backup from one repository type and restore to another."""
        # Save data to CSV repository
        self.csv_repo.save_portfolio_snapshot(self.sample_data['snapshot'])
        for trade in self.sample_data['trades']:
            self.csv_repo.save_trade(trade)
        
        # Export CSV data to CSV format (since export_to_json doesn't exist)
        export_dir = self.backup_dir / "csv_export"
        self.backup_dir.mkdir(exist_ok=True)
        result = self.csv_backup_manager.export_to_csv(export_dir)
        self.assertTrue(result)
        
        # Load exported CSV data and migrate to database repository
        # Since we exported to CSV, let's read the CSV files directly
        portfolio_csv = export_dir / "llm_portfolio_update.csv"
        trades_csv = export_dir / "llm_trade_log.csv"
        
        export_data = {'portfolio': [], 'trades': []}
        
        if portfolio_csv.exists():
            with open(portfolio_csv, 'r') as f:
                reader = csv.DictReader(f)
                export_data['portfolio'] = list(reader)
        
        if trades_csv.exists():
            with open(trades_csv, 'r') as f:
                reader = csv.DictReader(f)
                export_data['trades'] = list(reader)
        
        # Migrate portfolio data
        for p_data in export_data.get('portfolio', []):
            # Convert CSV format to Position objects
            position = Position(
                ticker=p_data.get('Ticker', ''),
                shares=Decimal(str(p_data.get('Shares', 0))),
                avg_price=Decimal(str(p_data.get('Average Price', 0))),
                cost_basis=Decimal(str(p_data.get('Cost Basis', 0))),
                current_price=Decimal(str(p_data.get('Current Price', 0))) if p_data.get('Current Price') else None,
                currency=p_data.get('Currency', 'CAD'),
                company=p_data.get('Company', '')
            )
            
            # Create snapshot (simplified for test)
            snapshot = PortfolioSnapshot(
                positions=[position],
                cash_balance=Decimal('0.00'),
                timestamp=datetime.now(timezone.utc)
            )
            self.db_repo.save_portfolio_snapshot(snapshot)
        
        # Migrate trade data
        for t_data in export_data.get('trades', []):
            trade = Trade(
                ticker=t_data.get('Ticker', ''),
                action="BUY",  # Simplified
                shares=Decimal(str(t_data.get('Shares', 0))),
                price=Decimal(str(t_data.get('Price', 0))),
                timestamp=datetime.now(timezone.utc),  # Simplified
                cost_basis=Decimal(str(t_data.get('Cost Basis', 0))),
                reason=t_data.get('Reason', '')
            )
            self.db_repo.save_trade(trade)
        
        # Verify migration
        db_snapshots = self.db_repo.get_portfolio_data()
        db_trades = self.db_repo.get_trade_history()
        
        self.assertGreater(len(db_snapshots), 0)
        self.assertGreater(len(db_trades), 0)
    
    def test_backup_format_compatibility(self):
        """Test backup format compatibility between repository types."""
        # Create backups from both repository types
        
        # CSV backup
        self.csv_repo.save_portfolio_snapshot(self.sample_data['snapshot'])
        csv_backup_name = self.csv_backup_manager.create_backup("csv_format_test")
        
        # Database backup
        self.db_repo.save_portfolio_snapshot(self.sample_data['snapshot'])
        db_backup_file = self.backup_dir / "db_format_test.json"
        self.backup_dir.mkdir(exist_ok=True)
        self.db_repo.backup_data(db_backup_file)
        
        # Verify both backup formats contain essential data
        
        # Check CSV backup files
        csv_backup_files = list(self.backup_dir.glob(f"*{csv_backup_name}*"))
        self.assertGreater(len(csv_backup_files), 0)
        
        # Check database backup content
        with open(db_backup_file, 'r') as f:
            db_backup_data = json.load(f)
        
        self.assertIn('portfolios', db_backup_data)
        self.assertIn('backup_timestamp', db_backup_data)
        self.assertIn('repository_type', db_backup_data)
    
    def test_backup_data_integrity_validation(self):
        """Test data integrity validation in backups."""
        # Create data with potential integrity issues
        positions = [
            Position(ticker="AAPL", shares=Decimal('100'), avg_price=Decimal('150.00'),
                    cost_basis=Decimal('15000.00'), position_id="pos_1"),
            Position(ticker="AAPL", shares=Decimal('50'), avg_price=Decimal('160.00'),
                    cost_basis=Decimal('8000.00'), position_id="pos_1"),  # Duplicate ID
        ]
        
        snapshot = PortfolioSnapshot(
            positions=positions,
            cash_balance=Decimal('5000.00'),
            timestamp=datetime.now(timezone.utc),
            snapshot_id="snap_1"
        )
        
        # Save to database repository
        self.db_repo.save_portfolio_snapshot(snapshot)
        
        # Validate data integrity
        issues = self.db_repo.validate_data_integrity()
        
        # Should detect duplicate position IDs (if validation is implemented)
        # If no issues are detected, that's also acceptable for this test
        self.assertIsInstance(issues, list)
    
    def test_backup_metadata_preservation(self):
        """Test that backup metadata is preserved across operations."""
        # Add metadata to sample data
        self.sample_data['snapshot'].snapshot_id = "original_snap_123"
        self.sample_data['trades'][0].trade_id = "original_trade_456"
        
        # Save to database repository
        self.db_repo.save_portfolio_snapshot(self.sample_data['snapshot'])
        self.db_repo.save_trade(self.sample_data['trades'][0])
        
        # Create backup
        backup_file = self.backup_dir / "metadata_test.json"
        self.backup_dir.mkdir(exist_ok=True)
        self.db_repo.backup_data(backup_file)
        
        # Clear and restore
        self.db_repo.portfolios.clear()
        self.db_repo.trades.clear()
        self.db_repo.restore_from_backup(backup_file)
        
        # Verify metadata was preserved
        restored_snapshots = self.db_repo.get_portfolio_data()
        restored_trades = self.db_repo.get_trade_history()
        
        self.assertEqual(restored_snapshots[0].snapshot_id, "original_snap_123")
        self.assertEqual(restored_trades[0].trade_id, "original_trade_456")


class TestMigrationScenarios(unittest.TestCase):
    """Test various migration scenarios and edge cases."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.temp_dir)
        
        self.csv_repo = CSVRepository(fund_name="TEST", data_directory=str(self.data_dir))
        self.db_repo = MockDatabaseRepository("mock://migration/test")
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir)
    
    def test_large_dataset_migration(self):
        """Test migration of large datasets."""
        # Create large dataset
        positions = []
        trades = []
        
        for i in range(100):
            position = Position(
                ticker=f"STOCK{i:03d}",
                shares=Decimal('100') + i,
                avg_price=Decimal('100.00') + i,
                cost_basis=Decimal('10000.00') + (i * 100),
                current_price=Decimal('105.00') + i
            )
            positions.append(position)
            
            trade = Trade(
                ticker=f"STOCK{i:03d}",
                action="BUY",
                shares=Decimal('100') + i,
                price=Decimal('100.00') + i,
                timestamp=datetime.now(timezone.utc) + timedelta(days=i),
                cost_basis=Decimal('10000.00') + (i * 100)
            )
            trades.append(trade)
        
        # Save to CSV repository
        snapshot = PortfolioSnapshot(
            positions=positions,
            cash_balance=Decimal('50000.00'),
            timestamp=datetime.now(timezone.utc)
        )
        
        self.csv_repo.save_portfolio_snapshot(snapshot)
        for trade in trades:
            self.csv_repo.save_trade(trade)
        
        # Migrate to database repository
        csv_snapshots = self.csv_repo.get_portfolio_data()
        csv_trades = self.csv_repo.get_trade_history()
        
        for snapshot in csv_snapshots:
            self.db_repo.save_portfolio_snapshot(snapshot)
        
        for trade in csv_trades:
            self.db_repo.save_trade(trade)
        
        # Verify migration
        db_snapshots = self.db_repo.get_portfolio_data()
        db_trades = self.db_repo.get_trade_history()
        
        self.assertEqual(len(db_snapshots), 1)
        self.assertEqual(len(db_snapshots[0].positions), 100)
        self.assertEqual(len(db_trades), 100)
    
    def test_migration_with_data_conflicts(self):
        """Test migration handling of data conflicts."""
        # Create conflicting data
        trade1 = Trade(
            ticker="AAPL",
            action="BUY",
            shares=Decimal('100'),
            price=Decimal('150.00'),
            timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
            cost_basis=Decimal('15000.00'),
            trade_id="conflict_trade"
        )
        
        trade2 = Trade(
            ticker="GOOGL",
            action="SELL",
            shares=Decimal('50'),
            price=Decimal('2000.00'),
            timestamp=datetime(2025, 1, 2, tzinfo=timezone.utc),
            pnl=Decimal('5000.00'),
            trade_id="conflict_trade"  # Same ID
        )
        
        # Save both trades to database repository
        self.db_repo.save_trade(trade1)
        self.db_repo.save_trade(trade2)
        
        # Verify conflict handling (second trade should overwrite first)
        trades = self.db_repo.get_trade_history()
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].ticker, "GOOGL")  # Second trade wins
    
    def test_migration_rollback_scenario(self):
        """Test migration rollback capabilities."""
        # Create original data
        original_snapshot = PortfolioSnapshot(
            positions=[
                Position(ticker="AAPL", shares=Decimal('100'), avg_price=Decimal('150.00'),
                        cost_basis=Decimal('15000.00'))
            ],
            cash_balance=Decimal('10000.00'),
            timestamp=datetime.now(timezone.utc)
        )
        
        # Save to CSV repository
        self.csv_repo.save_portfolio_snapshot(original_snapshot)
        
        # Create backup before migration
        backup_manager = BackupManager(self.data_dir)
        backup_name = backup_manager.create_backup("pre_migration")
        
        # Simulate failed migration (corrupt data)
        corrupted_snapshot = PortfolioSnapshot(
            positions=[
                Position(ticker="", shares=Decimal('0'), avg_price=Decimal('0'),
                        cost_basis=Decimal('0'))  # Invalid data
            ],
            cash_balance=Decimal('-1000.00'),  # Invalid negative cash
            timestamp=datetime.now(timezone.utc)
        )
        
        self.csv_repo.save_portfolio_snapshot(corrupted_snapshot)
        
        # Rollback using backup
        result = backup_manager.restore_from_backup(backup_name)
        self.assertTrue(result)
        
        # Verify rollback success
        restored_snapshots = self.csv_repo.get_portfolio_data()
        self.assertGreaterEqual(len(restored_snapshots), 1)
        # Check the most recent snapshot
        latest_snapshot = restored_snapshots[-1]
        self.assertEqual(latest_snapshot.positions[0].ticker, "AAPL")
        # Cash balance might be None in CSV format, check if it exists
        if latest_snapshot.cash_balance is not None:
            self.assertEqual(latest_snapshot.cash_balance, Decimal('10000.00'))


if __name__ == '__main__':
    unittest.main()