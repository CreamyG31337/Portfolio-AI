"""Dual-write repository implementation for the CONSOLE APP.

This repository reads from CSV (reliable local source) but writes to both CSV and Supabase.
It provides the best of both worlds - reliable CSV data with Supabase backup.

IMPORTANT - CONSOLE APP ONLY:
    This class is designed for the console trading app (trading_script.py, menu_actions.py)
    which runs locally and has access to CSV files on disk.

    The WEB DASHBOARD (Flask) should NOT use this class because:
    - The web server has no CSV data files (trades live in Supabase only)
    - get_trade_history() reads from CSV and would return empty results
    - get_latest_portfolio_snapshot() reads from CSV and would return stale/empty data
    - CSVRepository.__init__ silently creates empty directories (mkdir exist_ok=True),
      masking misconfiguration errors

    For the web dashboard, use SupabaseRepository directly instead.

See also: SupabaseDualWriteRepository (supabase_dual_write_repository.py) which is
Supabase-primary and was designed as an alternative, though it has a similar caveat
about CSV availability.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Tuple, Dict, Any
import logging

from .base_repository import BaseRepository, RepositoryError, DataValidationError, DataNotFoundError
from .csv_repository import CSVRepository
from .supabase_repository import SupabaseRepository
from ..models.portfolio import Position, PortfolioSnapshot
from ..models.trade import Trade
from ..models.market_data import MarketData

logger = logging.getLogger(__name__)


class DualWriteRepository(BaseRepository):
    """Repository that reads from CSV but writes to both CSV and Supabase.
    
    This provides reliability (CSV as source of truth) while maintaining
    Supabase as a backup and for future features.
    
    WARNING: All read operations (get_trade_history, get_latest_portfolio_snapshot,
    get_portfolio_data) read from CSV files, NOT Supabase. If CSV files don't exist
    or are empty, these methods return empty results -- no error is raised.
    
    For web-only environments without CSV files, use SupabaseRepository directly.
    """
    
    def __init__(self, fund_name: str, data_directory: str = None, **kwargs):
        """Initialize dual-write repository.
        
        Args:
            fund_name: Name of the fund (e.g. "RRSP Lance Webull").
                       IMPORTANT: This must be the fund NAME, not a file path.
                       The fund_name is passed to SupabaseRepository for DB queries.
            data_directory: Optional path to CSV data directory
                           (defaults to trading_data/funds/{fund_name}).
                           IMPORTANT: This must be a directory PATH, not a fund name.
        
        Common mistake (swapped args):
            WRONG: DualWriteRepository("trading_data/funds/MyFund", "MyFund")
            RIGHT: DualWriteRepository(fund_name="MyFund", data_directory="trading_data/funds/MyFund")
        """
        self.fund_name = fund_name
        
        if data_directory:
            self.data_directory = data_directory
            self.data_dir = data_directory  # Alias for compatibility
        else:
            # Default to trading_data/funds/{fund_name}
            self.data_directory = f"trading_data/funds/{fund_name}"
            self.data_dir = self.data_directory
        
        # Initialize CSV repository (primary/read source)
        self.csv_repo = CSVRepository(fund_name=fund_name, data_directory=self.data_directory)
        
        # Initialize Supabase repository (write target)
        self.supabase_repo = SupabaseRepository(fund_name=fund_name)
        
        logger.info(f"Initialized dual-write repository: CSV read, CSV+Supabase write")
    
    def get_portfolio_data(self, date_range: Optional[Tuple[datetime, datetime]] = None) -> List[PortfolioSnapshot]:
        """Get portfolio data from CSV (primary source)."""
        return self.csv_repo.get_portfolio_data(date_range)
    
    def get_latest_portfolio_snapshot(self) -> Optional[PortfolioSnapshot]:
        """Get latest portfolio snapshot from CSV."""
        return self.csv_repo.get_latest_portfolio_snapshot()
    
    def get_latest_portfolio_snapshot_with_pnl(self) -> Optional[PortfolioSnapshot]:
        """Get latest portfolio snapshot with P&L from Supabase view.
        
        This method uses the Supabase 'latest_positions' view which includes
        company names from the securities table (after normalization).
        
        Returns:
            Portfolio snapshot with positions including company names from securities table
        """
        # Delegate to Supabase repository to use the view with company data
        return self.supabase_repo.get_latest_portfolio_snapshot_with_pnl()
    
    def save_portfolio_snapshot(self, snapshot: PortfolioSnapshot, is_trade_execution: bool = False) -> None:
        """Save portfolio snapshot to both CSV and Supabase."""
        try:
            # Save to CSV first (primary)
            self.csv_repo.save_portfolio_snapshot(snapshot)
            logger.info(f"Saved portfolio snapshot to CSV")
            
            # Save to Supabase (backup) - pass is_trade_execution to bypass market-close protection
            self.supabase_repo.save_portfolio_snapshot(snapshot, is_trade_execution=is_trade_execution)
            logger.info(f"Saved portfolio snapshot to Supabase")
            
        except Exception as e:
            logger.error(f"Failed to save portfolio snapshot: {e}")
            raise RepositoryError(f"Failed to save portfolio snapshot: {e}") from e
    
    def get_trade_history(self, ticker: Optional[str] = None, date_range: Optional[Tuple[datetime, datetime]] = None) -> List[Trade]:
        """Get trade history from CSV."""
        return self.csv_repo.get_trade_history(ticker, date_range)
    
    def save_trade(self, trade: Trade) -> None:
        """Save trade to both CSV and Supabase."""
        try:
            # Save to CSV first (primary)
            self.csv_repo.save_trade(trade)
            logger.info(f"Saved trade to CSV: {trade.ticker}")
            
            # Save to Supabase (backup)
            self.supabase_repo.save_trade(trade)
            logger.info(f"Saved trade to Supabase: {trade.ticker}")
            
        except Exception as e:
            logger.error(f"Failed to save trade: {e}")
            raise RepositoryError(f"Failed to save trade: {e}") from e
    
    def get_cash_balance(self, date: Optional[datetime] = None) -> Decimal:
        """Get cash balance from CSV."""
        return self.csv_repo.get_cash_balance(date)
    
    def save_cash_balance(self, balance: Decimal, date: Optional[datetime] = None) -> None:
        """Save cash balance to both CSV and Supabase."""
        try:
            # Save to CSV first (primary)
            self.csv_repo.save_cash_balance(balance, date)
            logger.info(f"Saved cash balance to CSV: {balance}")
            
            # Save to Supabase (backup)
            self.supabase_repo.save_cash_balance(balance, date)
            logger.info(f"Saved cash balance to Supabase: {balance}")
            
        except Exception as e:
            logger.error(f"Failed to save cash balance: {e}")
            raise RepositoryError(f"Failed to save cash balance: {e}") from e
    
    def get_market_data(self, ticker: str, date_range: Optional[Tuple[datetime, datetime]] = None) -> List[MarketData]:
        """Get market data from CSV."""
        return self.csv_repo.get_market_data(ticker, date_range)
    
    def save_market_data(self, market_data: MarketData) -> None:
        """Save market data to both CSV and Supabase."""
        try:
            # Save to CSV first (primary)
            self.csv_repo.save_market_data(market_data)
            logger.info(f"Saved market data to CSV: {market_data.ticker}")
            
            # Save to Supabase (backup)
            self.supabase_repo.save_market_data(market_data)
            logger.info(f"Saved market data to Supabase: {market_data.ticker}")
            
        except Exception as e:
            logger.error(f"Failed to save market data: {e}")
            raise RepositoryError(f"Failed to save market data: {e}") from e
    
    def test_connection(self) -> bool:
        """Test both CSV and Supabase connections."""
        csv_ok = True  # CSV is always available
        supabase_ok = self.supabase_repo.test_connection()
        
        logger.info(f"Connection test - CSV: {csv_ok}, Supabase: {supabase_ok}")
        return csv_ok and supabase_ok
    
    def get_positions_by_ticker(self, ticker: str) -> List[Position]:
        """Get positions for a specific ticker from CSV."""
        return self.csv_repo.get_positions_by_ticker(ticker)
    
    def backup_data(self, backup_path: str) -> bool:
        """Backup data using CSV repository."""
        return self.csv_repo.backup_data(backup_path)
    
    def restore_from_backup(self, backup_path: str) -> bool:
        """Restore data using CSV repository."""
        return self.csv_repo.restore_from_backup(backup_path)
    
    def validate_data_integrity(self) -> bool:
        """Validate data integrity using CSV repository."""
        return self.csv_repo.validate_data_integrity()
    
    def update_ticker_in_future_snapshots(self, ticker: str, trade_timestamp: datetime) -> None:
        """Update ticker in future snapshots for both CSV and Supabase."""
        try:
            # Update CSV (primary)
            self.csv_repo.update_ticker_in_future_snapshots(ticker, trade_timestamp)
            logger.info(f"Updated {ticker} in future CSV snapshots")
            
            # Update Supabase (backup)
            self.supabase_repo.update_ticker_in_future_snapshots(ticker, trade_timestamp)
            logger.info(f"Updated {ticker} in future Supabase snapshots")
        except Exception as e:
            logger.error(f"Failed to update {ticker} in future snapshots: {e}")
            raise RepositoryError(f"Failed to update {ticker} in future snapshots: {e}") from e
