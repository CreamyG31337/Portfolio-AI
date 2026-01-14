"""CSV-based repository implementation."""

from __future__ import annotations

import csv
import os
import shutil
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
import pandas as pd
import logging

from .base_repository import BaseRepository, RepositoryError, DataValidationError, DataNotFoundError
from ..models.portfolio import Position, PortfolioSnapshot
from ..models.trade import Trade
from ..models.market_data import MarketData

logger = logging.getLogger(__name__)


class CSVRepository(BaseRepository):
    """CSV-based implementation of the repository pattern.
    
    This implementation maintains compatibility with the existing CSV file formats
    while providing the repository interface for future database migration.
    """
    
    def __init__(self, fund_name: str, data_directory: str = None):
        """Initialize CSV repository.
        
        Args:
            fund_name: Name of the fund
            data_directory: Optional directory containing CSV files (defaults to trading_data/funds/{fund_name})
        """
        if not fund_name:
            raise ValueError("fund_name is required for CSVRepository")
        
        if data_directory:
            self.data_dir = Path(data_directory)
        else:
            # Default to trading_data/funds/{fund_name}
            self.data_dir = Path(f"trading_data/funds/{fund_name}")
        
        self.fund_name = fund_name
        self.portfolio_file = self.data_dir / "llm_portfolio_update.csv"
        self.trade_log_file = self.data_dir / "llm_trade_log.csv"
        self.cash_balances_file = self.data_dir / "cash_balances.json"
        
        # Cache for portfolio data to avoid repeated reads/parsing
        self._portfolio_cache = None
        self._portfolio_mtime = 0

        # Ensure data directory exists
        self.data_dir.mkdir(exist_ok=True)
    
    def _load_portfolio_cache(self) -> Optional[pd.DataFrame]:
        """Load portfolio data into cache if needed.

        Returns:
            Cached DataFrame or None if file doesn't exist/is empty
        """
        if not self.portfolio_file.exists():
            return None

        current_mtime = os.path.getmtime(self.portfolio_file)

        # If cache is valid and file hasn't changed, return cache
        if self._portfolio_cache is not None and self._portfolio_mtime == current_mtime:
            return self._portfolio_cache

        # Read CSV file
        try:
            df = pd.read_csv(self.portfolio_file)
            if df.empty:
                self._portfolio_cache = df
                self._portfolio_mtime = current_mtime
                return df

            # Parse timestamps with timezone awareness
            # _parse_csv_timestamp returns timezone-aware pandas Timestamps
            parsed_dates = df['Date'].apply(self._parse_csv_timestamp)
            # Convert to datetime64 by extracting components (avoids timezone conversion issues)
            df['Date'] = pd.to_datetime(parsed_dates.apply(lambda x: x.strftime('%Y-%m-%d %H:%M:%S') if hasattr(x, 'strftime') else str(x)))
            # Add timezone info back
            if not parsed_dates.empty and hasattr(parsed_dates.iloc[0], 'tz'):
                df['Date'] = df['Date'].dt.tz_localize(parsed_dates.iloc[0].tz)

            self._portfolio_cache = df
            self._portfolio_mtime = current_mtime
            return df

        except pd.errors.EmptyDataError:
            return None

    def get_portfolio_data(self, date_range: Optional[Tuple[datetime, datetime]] = None) -> List[PortfolioSnapshot]:
        """Retrieve portfolio snapshots from CSV file.
        
        Args:
            date_range: Optional tuple of (start_date, end_date) to filter results
            
        Returns:
            List of PortfolioSnapshot objects
        """
        try:
            if not self.portfolio_file.exists():
                logger.info(f"Portfolio file does not exist: {self.portfolio_file}")
                return []
            
            # Use cached dataframe
            cached_df = self._load_portfolio_cache()
            if cached_df is None or cached_df.empty:
                logger.info("Portfolio CSV file is empty")
                return []

            # Work on a copy to avoid modifying the cache
            df = cached_df.copy()
            
            # Filter by date range if provided
            if date_range:
                start_date, end_date = date_range
                # Ensure date range parameters are timezone-aware for comparison
                from utils.timezone_utils import get_trading_timezone
                trading_tz = get_trading_timezone()
                
                if start_date.tzinfo is None:
                    start_date = start_date.replace(tzinfo=trading_tz)
                if end_date.tzinfo is None:
                    end_date = end_date.replace(tzinfo=trading_tz)
                
                df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]
            
            # Group by date to create snapshots (group by date only, not exact timestamp)
            df['Date_Only'] = df['Date'].dt.date
            snapshots = []
            for date, group in df.groupby('Date_Only'):
                positions = []
                total_value = Decimal('0')
                
                for _, row in group.iterrows():
                    position = Position.from_csv_dict(row.to_dict())
                    positions.append(position)
                    if position.market_value:
                        total_value += position.market_value
                
                # Use the latest timestamp from the group for the snapshot
                latest_timestamp = group['Date'].max()
                snapshot = PortfolioSnapshot(
                    positions=positions,
                    timestamp=latest_timestamp,
                    total_value=total_value
                )
                snapshots.append(snapshot)
            
            return sorted(snapshots, key=lambda x: x.timestamp)
            
        except Exception as e:
            logger.error(f"Failed to load portfolio data: {e}")
            raise RepositoryError(f"Failed to load portfolio data: {e}") from e
    
    def save_portfolio_snapshot(self, snapshot: PortfolioSnapshot, is_trade_execution: bool = False) -> None:
        """Save portfolio snapshot to CSV file.
        
        ARCHITECTURE NOTE: This should receive a COMPLETE snapshot with ALL positions for that date,
        not a partial snapshot with just new positions. For backdated trades, the caller should
        skip calling this and instruct the user to run the rebuild script.
        
        This method handles replacing existing snapshots for the same date (by date-only,
        not exact timestamp) to maintain the rule: ONE snapshot per trading day.
        
        Args:
            snapshot: Complete portfolio snapshot with all positions
            is_trade_execution: Whether this is triggered by a trade execution (bypasses market-close protection)
        """
        try:
            # Prepare data for CSV - use normalized timestamp
            from utils.timezone_utils import get_trading_timezone
            trading_tz = get_trading_timezone()
            
            # Normalize snapshot timestamp to trading timezone
            if snapshot.timestamp.tzinfo is None:
                normalized_timestamp = snapshot.timestamp.replace(tzinfo=trading_tz)
            else:
                normalized_timestamp = snapshot.timestamp.astimezone(trading_tz)
            
            rows = []
            # Use datetime object for DataFrame construction to be compatible with cache
            for position in snapshot.positions:
                row = position.to_csv_dict()
                row['Date'] = normalized_timestamp
                row['Action'] = 'HOLD'  # Default action for portfolio snapshots
                rows.append(row)
            
            # Create DataFrame
            df = pd.DataFrame(rows)
            
            # Ensure proper column order to match existing format
            expected_columns = [
                'Date', 'Ticker', 'Shares', 'Average Price', 'Cost Basis', 
                'Stop Loss', 'Current Price', 'Total Value', 'PnL', 'Action', 
                'Company', 'Currency'
            ]
            
            # Add missing columns with default values
            for col in expected_columns:
                if col not in df.columns:
                    df[col] = ''
            
            # Reorder columns
            df = df[expected_columns]
            
            # Check for duplicates before saving
            existing_df_cache = self._load_portfolio_cache()

            if existing_df_cache is not None and not existing_df_cache.empty:
                # Work on a copy to avoid side effects during processing
                existing_df = existing_df_cache.copy()

                from utils.timezone_utils import get_trading_timezone
                trading_tz = get_trading_timezone()

                # Note: existing_df from cache already has parsed 'Date' as datetime objects

                # Ensure Date column is datetime
                if existing_df['Date'].dtype == 'object':
                     existing_df['Date'] = pd.to_datetime(existing_df['Date'], utc=True).dt.tz_convert(trading_tz)

                # Convert to date-only for comparison
                existing_df['Date_Only'] = existing_df['Date'].dt.date

                # Check if today's data already exists - normalize snapshot to trading timezone
                if snapshot.timestamp.tzinfo is None:
                    normalized_timestamp = snapshot.timestamp.replace(tzinfo=trading_tz)
                else:
                    normalized_timestamp = snapshot.timestamp.astimezone(trading_tz)
                today = normalized_timestamp.date()
                today_data = existing_df[existing_df['Date_Only'] == today]

                if not today_data.empty:
                    # Check if any existing snapshot is at market close (16:00:00)
                    market_close_exists = any(
                        row['Date'].hour == 16 and row['Date'].minute == 0
                        for _, row in today_data.iterrows()
                    )
                    
                    # If we're trying to save a market close snapshot and one already exists
                    if (normalized_timestamp.hour == 16 and normalized_timestamp.minute == 0
                        and market_close_exists):
                        logger.warning(f"Market close snapshot already exists for {today}")
                        # Don't crash, just update the existing one
                        pass
                    
                    # If we're trying to save an intraday snapshot but market close exists
                    elif market_close_exists and not (normalized_timestamp.hour == 16 and normalized_timestamp.minute == 0):
                        logger.warning(f"⚠️  Attempting to save intraday snapshot but market close snapshot already exists for {today}")
                        logger.warning(f"   Skipping save to preserve market close snapshot at 16:00:00")
                        return  # Don't save, preserve market close snapshot
                    
                    logger.debug(f"Portfolio data for {today} already exists. Use update_daily_portfolio_snapshot() instead of save_portfolio_snapshot() to prevent duplicates.")
                    # Remove existing today's data to prevent duplicates
                    existing_df = existing_df[existing_df['Date_Only'] != today]
                    existing_df = existing_df.drop('Date_Only', axis=1)  # Remove helper column

                    # Combine existing data with new data
                    # Both existing_df and df have datetimes now
                    combined_df = pd.concat([existing_df, df], ignore_index=True)

                    # Convert to string for CSV
                    write_df = combined_df.copy()
                    write_df['Date'] = write_df['Date'].apply(
                        lambda x: self._format_timestamp_for_csv(x) if pd.notna(x) else ''
                    )
                    write_df.to_csv(self.portfolio_file, index=False)
                    # Only update cache after successful write to avoid phantom data on write failure
                    self._portfolio_cache = combined_df.copy()
                    self._portfolio_mtime = os.path.getmtime(self.portfolio_file)
                else:
                    # No duplicates, append normally
                    # Write to CSV
                    write_df = df.copy()
                    write_df['Date'] = write_df['Date'].apply(
                        lambda x: self._format_timestamp_for_csv(x) if pd.notna(x) else ''
                    )
                    write_df.to_csv(self.portfolio_file, mode='a', header=False, index=False)
                    # Only update cache after successful write to avoid phantom data on write failure
                    self._portfolio_cache = pd.concat([existing_df_cache, df], ignore_index=True)
                    self._portfolio_mtime = os.path.getmtime(self.portfolio_file)
            else:
                # File doesn't exist or is empty, create new
                # Write to CSV
                write_df = df.copy()
                write_df['Date'] = write_df['Date'].apply(
                    lambda x: self._format_timestamp_for_csv(x) if pd.notna(x) else ''
                )
                write_df.to_csv(self.portfolio_file, index=False)
                # Only update cache after successful write to avoid phantom data on write failure
                self._portfolio_cache = df.copy()
                self._portfolio_mtime = os.path.getmtime(self.portfolio_file)
            
            logger.info(f"Saved portfolio snapshot with {len(snapshot.positions)} positions")
            
        except Exception as e:
            logger.error(f"Failed to save portfolio snapshot: {e}")
            raise RepositoryError(f"Failed to save portfolio snapshot: {e}") from e
    
    def update_daily_portfolio_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        """Update today's portfolio snapshot or create new one if it doesn't exist.
        
        This method follows the rule: only add new rows once per day, update prices in existing rows.
        For new trades added on the same day, it creates HOLD entries with current prices.
        
        Args:
            snapshot: PortfolioSnapshot to save or update
        """
        try:
            from datetime import datetime, timezone
            import pytz
            from utils.timezone_utils import get_trading_timezone
            
            # CRITICAL: Always normalize to trading timezone for consistent date comparison
            trading_tz = get_trading_timezone()
            
            # Convert snapshot timestamp to trading timezone
            if snapshot.timestamp.tzinfo is None:
                # Assume naive timestamps are already in trading timezone
                normalized_timestamp = snapshot.timestamp.replace(tzinfo=trading_tz)
            else:
                # Convert timezone-aware timestamp to trading timezone
                normalized_timestamp = snapshot.timestamp.astimezone(trading_tz)
            
            # Get today's date in trading timezone consistently
            today = normalized_timestamp.date()
            
            # Check if today's snapshot already exists
            existing_df_cache = self._load_portfolio_cache()

            if existing_df_cache is not None and not existing_df_cache.empty:
                # Work on a copy to avoid side effects during processing
                existing_df = existing_df_cache.copy()

                # Note: existing_df from cache already has parsed 'Date' as datetime objects

                # Ensure Date column is datetime
                if existing_df['Date'].dtype == 'object':
                     # We need to handle potential mixed timezones if they were coerced to object
                     # But ideally cache should be clean. If we are here, it means cache has objects.
                     # Force conversion to UTC then to trading TZ
                     existing_df['Date'] = pd.to_datetime(existing_df['Date'], utc=True).dt.tz_convert(trading_tz)

                existing_df['Date_Only'] = existing_df['Date'].dt.date

                # Check if today's data exists
                today_data = existing_df[existing_df['Date_Only'] == today]
                if not today_data.empty:
                    logger.debug(f"Today's portfolio snapshot already exists, updating prices only (no duplicate rows)")

                    # Get list of existing tickers for today
                    existing_tickers = set(today_data['Ticker'].tolist())
                    
                    # Update prices in today's existing rows
                    for _, position_row in today_data.iterrows():
                        ticker = position_row['Ticker']
                        
                        # Find the updated position
                        updated_position = None
                        for pos in snapshot.positions:
                            if pos.ticker == ticker:
                                updated_position = pos
                                break
                        
                        if updated_position:
                            # Update only price-related fields for today's rows only
                            from decimal import ROUND_HALF_UP
                            mask = (existing_df['Date_Only'] == today) & (existing_df['Ticker'] == ticker)
                            # Convert Decimals to float only for CSV storage, maintaining precision
                            current_price_float = float((updated_position.current_price or Decimal('0')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
                            market_value_float = float((updated_position.market_value or Decimal('0')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
                            unrealized_pnl_float = float((updated_position.unrealized_pnl or Decimal('0')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
                            
                            existing_df.loc[mask, 'Current Price'] = current_price_float
                            existing_df.loc[mask, 'Total Value'] = market_value_float
                            existing_df.loc[mask, 'PnL'] = unrealized_pnl_float

                            # Also update position quantities and cost metrics for same-day trades
                            # This ensures average cost and shares are correct when multiple buys happen in a day
                            shares_float = float((updated_position.shares).quantize(Decimal('0.0001')))
                            avg_price_float = float((updated_position.avg_price).quantize(Decimal('0.01')))
                            cost_basis_float = float((updated_position.cost_basis).quantize(Decimal('0.01')))

                            existing_df.loc[mask, 'Shares'] = shares_float
                            existing_df.loc[mask, 'Average Price'] = avg_price_float
                            existing_df.loc[mask, 'Cost Basis'] = cost_basis_float

                            logger.debug(f"Updated position metrics for {ticker}: shares={shares_float}, avg_price={avg_price_float}, cost_basis={cost_basis_float}")

                    # SIMPLIFIED FIX: Only add HOLD rows for tickers that don't have a HOLD row today
                    new_positions = []
                    for pos in snapshot.positions:
                        if pos.ticker not in existing_tickers:
                            # No HOLD row for this ticker today, add one
                            hold_entry = pos.to_csv_dict()
                            hold_entry['Date'] = self._format_timestamp_for_csv(normalized_timestamp)
                            hold_entry['Action'] = 'HOLD'
                            new_positions.append(hold_entry)
                            logger.debug(f"Adding HOLD entry for ticker missing from today: {pos.ticker}")

                    if new_positions:
                        # Add new HOLD entries to the DataFrame
                        new_df = pd.DataFrame(new_positions)
                        existing_df = pd.concat([existing_df, new_df], ignore_index=True)
                        logger.debug(f"Added {len(new_positions)} new HOLD entries for today")
                    else:
                        logger.debug("No new positions to add - only updated existing positions")

                    # Save the updated DataFrame
                    existing_df = existing_df.drop('Date_Only', axis=1)  # Remove helper column

                    # Ensure Date column is formatted as string for CSV
                    existing_df['Date'] = existing_df['Date'].apply(
                        lambda x: self._format_timestamp_for_csv(x) if hasattr(x, 'strftime') else (x if isinstance(x, str) else self._format_timestamp_for_csv(pd.to_datetime(x)))
                    )

                    existing_df.to_csv(self.portfolio_file, index=False)
                    # Invalidate cache
                    self._portfolio_cache = None
                    self._portfolio_mtime = 0

                    logger.debug(f"Updated today's portfolio snapshot with current prices (no duplicates created)")
                    return
            
            # If today's snapshot doesn't exist, create new rows
            logger.info(f"Creating new portfolio snapshot for today")
            self.save_portfolio_snapshot(snapshot)
            
        except Exception as e:
            logger.error(f"Failed to update daily portfolio snapshot: {e}")
            raise RepositoryError(f"Failed to update daily portfolio snapshot: {e}") from e
    
    def get_latest_portfolio_snapshot(self) -> Optional[PortfolioSnapshot]:
        """Get the most recent portfolio snapshot.
        
        Returns:
            Latest PortfolioSnapshot or None if no data exists
        """
        snapshots = self.get_portfolio_data()
        return snapshots[-1] if snapshots else None
    
    def get_trade_history(self, ticker: Optional[str] = None, date_range: Optional[Tuple[datetime, datetime]] = None) -> List[Trade]:
        """Retrieve trade history from CSV file.
        
        Args:
            ticker: Optional ticker symbol to filter by
            date_range: Optional tuple of (start_date, end_date) to filter results
            
        Returns:
            List of Trade objects
        """
        try:
            if not self.trade_log_file.exists():
                logger.info(f"Trade log file does not exist: {self.trade_log_file}")
                return []
            
            # Read CSV file
            df = pd.read_csv(self.trade_log_file)
            if df.empty:
                logger.info("Trade log CSV file is empty")
                return []
            
            # Parse timestamps
            df['Date'] = df['Date'].apply(self._parse_csv_timestamp)
            # Ensure the Date column is properly converted to datetime dtype
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce')

            # Filter by ticker if provided
            if ticker:
                df = df[df['Ticker'] == ticker]
            
            # Filter by date range if provided
            if date_range:
                start_date, end_date = date_range
                # Ensure date range parameters are timezone-aware for comparison
                from utils.timezone_utils import get_trading_timezone
                trading_tz = get_trading_timezone()
                
                if start_date.tzinfo is None:
                    start_date = start_date.replace(tzinfo=trading_tz)
                if end_date.tzinfo is None:
                    end_date = end_date.replace(tzinfo=trading_tz)
                
                df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]
            
            # Convert to Trade objects
            trades = []
            for _, row in df.iterrows():
                trade = Trade.from_csv_dict(row.to_dict(), timestamp=row['Date'])
                trades.append(trade)
            
            return sorted(trades, key=lambda x: x.timestamp)
            
        except Exception as e:
            logger.error(f"Failed to load trade history: {e}")
            raise RepositoryError(f"Failed to load trade history: {e}") from e
    
    def save_trade(self, trade: Trade) -> None:
        """Save a trade record to CSV file.
        
        Args:
            trade: Trade to save
        """
        try:
            # Prepare data for CSV
            row = trade.to_csv_dict()
            
            # Create DataFrame
            new_trade_df = pd.DataFrame([row])
            
            # Ensure proper column order
            expected_columns = [
                'Date', 'Ticker', 'Shares', 'Price', 
                'Cost Basis', 'PnL', 'Reason'
            ]
            
            # Add missing columns with default values
            for col in expected_columns:
                if col not in new_trade_df.columns:
                    new_trade_df[col] = ''
            
            # Reorder columns
            new_trade_df = new_trade_df[expected_columns]
            
            # Read existing trades, append new trade, and sort by date
            if self.trade_log_file.exists():
                # Read existing trades
                existing_df = pd.read_csv(self.trade_log_file)
                
                # Append new trade
                combined_df = pd.concat([existing_df, new_trade_df], ignore_index=True)
                
                # Convert Date column to datetime for proper sorting using timezone-aware parsing
                combined_df['Date'] = combined_df['Date'].apply(self._parse_csv_timestamp)
                
                # Sort by date
                combined_df = combined_df.sort_values('Date')
                
                # Convert Date back to string format for CSV
                from utils.timezone_utils import format_timestamp_for_csv
                combined_df['Date'] = combined_df['Date'].apply(
                    lambda x: format_timestamp_for_csv(x) if pd.notna(x) else ''
                )
                
                # Write sorted trades back to file
                combined_df.to_csv(self.trade_log_file, index=False, lineterminator='\n')
            else:
                # First trade - just write it
                new_trade_df.to_csv(self.trade_log_file, index=False, lineterminator='\n')
            
            logger.info(f"Saved trade: {trade.ticker} {trade.action} {trade.shares} @ {trade.price}")
            
        except Exception as e:
            logger.error(f"Failed to save trade: {e}")
            raise RepositoryError(f"Failed to save trade: {e}") from e
    
    def _ensure_file_ends_with_newline(self, file_path: Path) -> None:
        """Ensure a file ends with exactly one newline before appending.
        
        Args:
            file_path: Path to the file to check
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # If file doesn't end with newline, add one
            if content and not content.endswith('\n'):
                with open(file_path, 'a', encoding='utf-8') as f:
                    f.write('\n')
            # If file ends with multiple newlines, fix it
            elif content.endswith('\n\n'):
                content = content.rstrip('\n') + '\n'
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
        except Exception as e:
            logger.warning(f"Failed to ensure proper newline in {file_path}: {e}")
    
    def get_positions_by_ticker(self, ticker: str) -> List[Position]:
        """Get all positions for a specific ticker across time.
        
        Args:
            ticker: Ticker symbol to search for
            
        Returns:
            List of Position objects for the ticker
        """
        snapshots = self.get_portfolio_data()
        positions = []
        
        for snapshot in snapshots:
            position = snapshot.get_position_by_ticker(ticker)
            if position:
                positions.append(position)
        
        return positions
    
    def get_market_data(self, ticker: str, date_range: Optional[Tuple[datetime, datetime]] = None) -> List[MarketData]:
        """Retrieve market data for a ticker.
        
        Note: CSV repository doesn't store market data separately,
        this is a placeholder for future implementation.
        
        Args:
            ticker: Ticker symbol
            date_range: Optional tuple of (start_date, end_date) to filter results
            
        Returns:
            Empty list (market data not stored in CSV format)
        """
        logger.warning("Market data retrieval not implemented for CSV repository")
        return []
    
    def save_market_data(self, market_data: MarketData) -> None:
        """Save market data.
        
        Note: CSV repository doesn't store market data separately,
        this is a placeholder for future implementation.
        
        Args:
            market_data: MarketData to save
        """
        logger.warning("Market data saving not implemented for CSV repository")
        pass
    
    def backup_data(self, backup_path: str) -> None:
        """Create a backup of all CSV files.
        
        Args:
            backup_path: Path where backup should be created
        """
        try:
            backup_dir = Path(backup_path)
            backup_dir.mkdir(parents=True, exist_ok=True)
            
            # Copy all CSV files
            files_to_backup = [
                self.portfolio_file,
                self.trade_log_file,
                self.cash_balances_file
            ]
            
            for file_path in files_to_backup:
                if file_path.exists():
                    backup_file = backup_dir / file_path.name
                    shutil.copy2(file_path, backup_file)
                    logger.info(f"Backed up {file_path.name}")
            
            logger.info(f"Backup completed to {backup_path}")
            
        except Exception as e:
            logger.error(f"Failed to create backup: {e}")
            raise RepositoryError(f"Failed to create backup: {e}") from e
    
    def restore_from_backup(self, backup_path: str) -> None:
        """Restore data from a backup.
        
        Args:
            backup_path: Path to backup directory
        """
        try:
            backup_dir = Path(backup_path)
            if not backup_dir.exists():
                raise DataNotFoundError(f"Backup directory not found: {backup_path}")
            
            # Restore all CSV files
            files_to_restore = [
                ("llm_portfolio_update.csv", self.portfolio_file),
                ("llm_trade_log.csv", self.trade_log_file),
                ("cash_balances.json", self.cash_balances_file)
            ]
            
            for backup_name, target_path in files_to_restore:
                backup_file = backup_dir / backup_name
                if backup_file.exists():
                    shutil.copy2(backup_file, target_path)
                    logger.info(f"Restored {backup_name}")
            
            logger.info(f"Restore completed from {backup_path}")
            
        except Exception as e:
            logger.error(f"Failed to restore from backup: {e}")
            raise RepositoryError(f"Failed to restore from backup: {e}") from e
    
    def validate_data_integrity(self) -> List[str]:
        """Validate CSV data integrity.
        
        Returns:
            List of validation error messages (empty if no issues)
        """
        issues = []
        
        try:
            # Check portfolio file
            if self.portfolio_file.exists():
                df = pd.read_csv(self.portfolio_file)
                required_columns = ['Date', 'Ticker', 'Shares', 'Average Price']
                missing_columns = [col for col in required_columns if col not in df.columns]
                if missing_columns:
                    issues.append(f"Portfolio file missing columns: {missing_columns}")
                
                # Check for negative shares
                if 'Shares' in df.columns and (df['Shares'] < 0).any():
                    issues.append("Portfolio file contains negative share counts")
            
            # Check trade log file
            if self.trade_log_file.exists():
                df = pd.read_csv(self.trade_log_file)
                required_columns = ['Date', 'Ticker', 'Shares', 'Price']
                missing_columns = [col for col in required_columns if col not in df.columns]
                if missing_columns:
                    issues.append(f"Trade log file missing columns: {missing_columns}")
        
        except Exception as e:
            issues.append(f"Error validating data integrity: {e}")
        
        return issues
    
    def _parse_csv_timestamp(self, timestamp_str: str) -> datetime:
        """Parse timestamp from CSV format with comprehensive timezone handling.

        This function converts timezone abbreviations to pandas-compatible UTC offset formats
        to avoid FutureWarnings and ensure proper timezone handling.

        Args:
            timestamp_str: Timestamp string from CSV

        Returns:
            Parsed datetime object
        """
        if pd.isna(timestamp_str):
            return datetime.now()

        timestamp_str = str(timestamp_str).strip()

        # Handle common timezone abbreviations to prevent pandas FutureWarnings
        # Convert to pandas-compatible UTC offset format

        # Pacific Time (West Coast)
        if " PST" in timestamp_str:
            clean_timestamp = timestamp_str.replace(" PST", "")
            timestamp_with_offset = f"{clean_timestamp}-08:00"
            return pd.to_datetime(timestamp_with_offset)
        elif " PDT" in timestamp_str:
            clean_timestamp = timestamp_str.replace(" PDT", "")
            timestamp_with_offset = f"{clean_timestamp}-07:00"
            return pd.to_datetime(timestamp_with_offset)

        # Mountain Time (Rockies)
        elif " MST" in timestamp_str:
            clean_timestamp = timestamp_str.replace(" MST", "")
            timestamp_with_offset = f"{clean_timestamp}-07:00"
            return pd.to_datetime(timestamp_with_offset)
        elif " MDT" in timestamp_str:
            clean_timestamp = timestamp_str.replace(" MDT", "")
            timestamp_with_offset = f"{clean_timestamp}-06:00"
            return pd.to_datetime(timestamp_with_offset)

        # Central Time (Midwest)
        elif " CST" in timestamp_str:
            clean_timestamp = timestamp_str.replace(" CST", "")
            timestamp_with_offset = f"{clean_timestamp}-06:00"
            return pd.to_datetime(timestamp_with_offset)
        elif " CDT" in timestamp_str:
            clean_timestamp = timestamp_str.replace(" CDT", "")
            timestamp_with_offset = f"{clean_timestamp}-05:00"
            return pd.to_datetime(timestamp_with_offset)

        # Eastern Time (East Coast)
        elif " EST" in timestamp_str:
            clean_timestamp = timestamp_str.replace(" EST", "")
            timestamp_with_offset = f"{clean_timestamp}-05:00"
            return pd.to_datetime(timestamp_with_offset)
        elif " EDT" in timestamp_str:
            clean_timestamp = timestamp_str.replace(" EDT", "")
            timestamp_with_offset = f"{clean_timestamp}-04:00"
            return pd.to_datetime(timestamp_with_offset)

        # Already pandas-compatible formats
        elif " UTC" in timestamp_str or " GMT" in timestamp_str:
            return pd.to_datetime(timestamp_str)

        # Check for ISO format with timezone offset (e.g., "2025-08-25 04:00:00-04:00")
        # Look for pattern like YYYY-MM-DD HH:MM:SS±HH:MM or YYYY-MM-DD HH:MM:SS±HH
        import re
        iso_tz_pattern = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[+-]\d{2}(:\d{2})?$')
        if iso_tz_pattern.match(timestamp_str):
            try:
                return pd.to_datetime(timestamp_str)
            except Exception:
                logger.warning(f"Failed to parse ISO timezone format: {timestamp_str}")
                # Fall through to general parsing

        # UTC offset format already present (general case)
        elif ("+" in timestamp_str or "-" in timestamp_str):
            try:
                return pd.to_datetime(timestamp_str)
            except Exception:
                return pd.to_datetime(timestamp_str, utc=True)

        else:
            # No timezone info, assume local timezone and make it timezone-aware
            try:
                dt = pd.to_datetime(timestamp_str)
                # Convert to timezone-aware using the trading timezone
                from utils.timezone_utils import get_trading_timezone
                trading_tz = get_trading_timezone()
                if dt.tzinfo is None:
                    dt = dt.tz_localize(trading_tz)
                return dt
            except Exception:
                logger.warning(f"Failed to parse timestamp: {timestamp_str}")
                from utils.timezone_utils import get_trading_timezone
                trading_tz = get_trading_timezone()
                return datetime.now(trading_tz)
    
    def _format_timestamp_for_csv(self, timestamp: datetime) -> str:
        """Format timestamp for CSV output with timezone name.

        Uses centralized timezone utilities for consistent formatting.

        Args:
            timestamp: Datetime to format

        Returns:
            Formatted timestamp string with timezone abbreviation
        """
        try:
            from utils.timezone_utils import format_timestamp_for_csv
            return format_timestamp_for_csv(timestamp)
        except ImportError:
            # Fallback to basic formatting if timezone_utils not available
            return timestamp.strftime("%Y-%m-%d %H:%M:%S PST")
    
    def update_ticker_in_future_snapshots(self, ticker: str, trade_timestamp: datetime) -> None:
        """Update a ticker's position in all snapshots after the trade timestamp.
        
        This method rebuilds the ticker's position using FIFO lot tracking from the
        trade date forward, ensuring accurate historical snapshots after backdated trades.
        
        Args:
            ticker: Ticker symbol to update
            trade_timestamp: Timestamp of the backdated trade
            
        Raises:
            RepositoryError: If update operation fails
        """
        try:
            from datetime import timezone
            from portfolio.fifo_trade_processor import FIFOTradeProcessor
            from data.models.lot import LotTracker
            import pandas as pd
            
            logger.info(f"Rebuilding {ticker} positions from {trade_timestamp} forward due to backdated trade")
            
            # Get all trades for this ticker from the trade date forward
            trade_date = trade_timestamp.date()
            start_date = datetime.combine(trade_date, datetime.min.time()).replace(tzinfo=timezone.utc)
            end_date = datetime.now(timezone.utc)
            
            all_trades = self.get_trade_history(ticker=ticker, date_range=(start_date, end_date))
            
            if not all_trades:
                logger.info(f"No trades found for {ticker} from {trade_date} forward")
                return
            
            # Sort trades chronologically
            all_trades.sort(key=lambda x: x.timestamp)
            
            # Get all snapshots from trade date forward
            snapshots = self.get_portfolio_data(date_range=(start_date, end_date))
            
            if not snapshots:
                logger.info(f"No snapshots found from {trade_date} forward")
                return
            
            # For each snapshot, rebuild the ticker's position
            for snapshot in snapshots:
                # Normalize both timestamps to UTC for comparison
                from datetime import timezone as tz
                snapshot_ts = snapshot.timestamp if snapshot.timestamp.tzinfo else snapshot.timestamp.replace(tzinfo=tz.utc)
                trade_ts = trade_timestamp if trade_timestamp.tzinfo else trade_timestamp.replace(tzinfo=tz.utc)
                
                if snapshot_ts < trade_ts:
                    continue  # Skip snapshots before the trade
                
                # Rebuild lots up to this snapshot's timestamp
                tracker = LotTracker(ticker)
                
                # Process all trades up to this snapshot's timestamp
                for trade in all_trades:
                    trade_ts_loop = trade.timestamp if trade.timestamp.tzinfo else trade.timestamp.replace(tzinfo=tz.utc)
                    if trade_ts_loop > snapshot_ts:
                        break
                    
                    if trade.is_buy():
                        tracker.add_lot(
                            shares=trade.shares,
                            price=trade.price,
                            purchase_date=trade.timestamp,
                            currency=trade.currency
                        )
                    elif trade.is_sell():
                        try:
                            tracker.sell_shares_fifo(
                                shares_to_sell=trade.shares,
                                sell_price=trade.price,
                                sell_date=trade.timestamp
                            )
                        except Exception as e:
                            logger.warning(f"Error processing sell trade for {ticker}: {e}")
                
                # Calculate the position at this snapshot time
                total_shares = sum(lot.remaining_shares for lot in tracker.lots)
                total_cost_basis = sum(lot.remaining_cost_basis for lot in tracker.lots)
                avg_price = total_cost_basis / total_shares if total_shares > 0 else Decimal('0')
                
                # Create new position for this ticker
                if total_shares > 0:
                    # Find the original position to get current price and other details
                    original_position = None
                    for pos in snapshot.positions:
                        if pos.ticker == ticker:
                            original_position = pos
                            break
                    
                    new_position = Position(
                        ticker=ticker,
                        shares=total_shares,
                        avg_price=avg_price,
                        cost_basis=total_cost_basis,
                        currency=trade.currency if all_trades else "CAD",
                        company=original_position.company if original_position else None,
                        current_price=original_position.current_price if original_position else None,
                        market_value=original_position.current_price * total_shares if original_position and original_position.current_price else None,
                        unrealized_pnl=None  # Will be calculated
                    )
                    
                    # Remove old position and add new one
                    snapshot.remove_position(ticker)
                    snapshot.add_position(new_position)
                else:
                    # No shares remaining, remove position
                    snapshot.remove_position(ticker)
                
                # Recalculate snapshot totals
                snapshot.total_value = snapshot.calculate_total_value()
                
                # Save the updated snapshot
                self.save_portfolio_snapshot(snapshot)
                logger.info(f"Updated {ticker} position in snapshot {snapshot.timestamp}")
            
            logger.info(f"Successfully rebuilt {ticker} positions from {trade_timestamp} forward")
            
        except Exception as e:
            logger.error(f"Failed to update ticker {ticker} in future snapshots: {e}")
            raise RepositoryError(f"Failed to update ticker {ticker} in future snapshots: {e}") from e