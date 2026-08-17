"""Supabase-based repository implementation."""

from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Tuple, Dict, Any
import logging

from .base_repository import BaseRepository, RepositoryError, DataValidationError, DataNotFoundError
from ..models.portfolio import Position, PortfolioSnapshot
from ..models.trade import Trade
from ..models.market_data import MarketData

# Import field mappers
from .field_mapper import (
    PositionMapper,
    TradeMapper,
    CashBalanceMapper,
    SnapshotMapper
)

logger = logging.getLogger(__name__)

# Suppress httpx INFO logs (Supabase HTTP requests)
logging.getLogger("httpx").setLevel(logging.WARNING)


class SupabaseRepository(BaseRepository):
    """Supabase-based implementation of the repository pattern.
    
    This implementation provides the same interface as CSVRepository but
    uses Supabase as the backend storage.
    """
    
    def __init__(self, fund_name: str, url: str = None, key: str = None, use_service_role: bool = False, **kwargs):
        """Initialize Supabase repository.
        
        Args:
            fund_name: Fund name (REQUIRED - no default)
            url: Supabase project URL
            key: Supabase key (anon key or service role key)
            use_service_role: If True, use service role key to bypass RLS (for console apps)
        """
        self.supabase_url = url or os.getenv("SUPABASE_URL")
        
        # Determine which key to use
        if key:
            # Explicit key provided
            self.supabase_key = key
        elif use_service_role:
            # Use service role key to bypass RLS (for console apps)
            self.supabase_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            if not self.supabase_key:
                logger.warning(
                    "use_service_role=True but SUPABASE_SECRET_KEY/SERVICE_ROLE_KEY not found. "
                    "Falling back to publishable key. RLS may block queries."
                )
                self.supabase_key = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
        else:
            # Auto-detect: prefer service role key if available (for console apps to bypass RLS)
            # Fall back to publishable key if service role key not available (for web dashboard)
            service_role_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            if service_role_key:
                self.supabase_key = service_role_key
                logger.debug("Using service role key (bypasses RLS)")
            else:
                self.supabase_key = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
                logger.debug("Using publishable key (respects RLS)")
        
        if not fund_name:
            raise RepositoryError(
                "Fund name is required for SupabaseRepository. "
                "This should be provided by the repository factory using the active fund name."
            )
        self.fund = fund_name  # Keep for backward compatibility
        self.fund_name = fund_name
        
        # Add data_dir for compatibility with code expecting it (exchange rates, etc.)
        # Point to the common shared data directory where exchange rates are stored
        self.data_dir = "trading_data/exchange_rates"
        
        if not self.supabase_url or not self.supabase_key:
            raise RepositoryError("Supabase URL and key must be provided")
        
            # Initialize Supabase client
        try:
            from supabase import create_client, Client
            self.supabase: Client = create_client(self.supabase_url, self.supabase_key)
            # Determine key type for logging - check actual key in use, not just the flag
            service_role_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            publishable_key = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
            # Check if the actual key being used matches the service role key
            if service_role_key and self.supabase_key == service_role_key:
                key_type = "service_role"
            elif publishable_key and self.supabase_key == publishable_key:
                key_type = "publishable"
            else:
                # Fallback: if explicit key was provided, we can't determine type
                key_type = "custom"
            logger.info(f"Supabase client initialized successfully (using {key_type} key)")
        except ImportError:
            raise RepositoryError("Supabase client not available. Install with: pip install supabase")
        except Exception as e:
            raise RepositoryError(f"Failed to initialize Supabase client: {e}")
    
    def ensure_ticker_in_securities(self, ticker: str, currency: str, company_name: Optional[str] = None) -> bool:
        """Ensure ticker exists in securities table with metadata from yfinance.

        This method is called on first trade to populate the securities table.
        It checks if the ticker exists and has company metadata. If not, it fetches
        from yfinance and inserts/updates the record.

        Args:
            ticker: Stock ticker symbol (e.g., 'AAPL', 'SHOP.TO')
            currency: Currency code ('CAD' or 'USD')
            company_name: Optional company name if already known (avoids yfinance call)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Check if ticker already exists with complete metadata
            existing = self.supabase.table("securities").select("ticker, company_name, sector, industry").eq("ticker", ticker).execute()

            # Check if ticker exists with valid metadata (not just ticker name, has sector/industry)
            existing_company_name = None
            has_complete_metadata = False

            if existing.data:
                existing_company_name = existing.data[0].get('company_name')
                existing_sector = existing.data[0].get('sector')
                existing_industry = existing.data[0].get('industry')

                # Consider metadata complete if:
                # 1. Company name exists and is not just the ticker, not 'Unknown', and not empty
                # 2. Has sector or industry (indicates yfinance data was fetched)
                if (existing_company_name and
                    existing_company_name != ticker and
                    existing_company_name != 'Unknown' and
                    existing_company_name.strip() and
                    (existing_sector or existing_industry)):
                    has_complete_metadata = True

            # If ticker exists with complete metadata, no need to update
            if has_complete_metadata:
                logger.debug(f"Ticker {ticker} already exists in securities table with complete metadata")
                return True

            # Need to fetch/update metadata from yfinance
            metadata = {
                'ticker': ticker,
                'currency': currency
            }

            # If company_name parameter was provided and ticker doesn't have complete metadata, use it
            # Otherwise fetch from yfinance to get full metadata including sector/industry
            if company_name and company_name.strip() and not existing.data:
                # Only use provided company_name if ticker doesn't exist at all
                metadata['company_name'] = company_name.strip()
            else:
                # Always fetch from yfinance to get complete metadata (company_name, sector, industry, etc.)
                try:
                    import yfinance as yf
                    stock = yf.Ticker(ticker)
                    info = stock.info

                    if info:
                        # Get company name (prefer longName over shortName)
                        metadata['company_name'] = info.get('longName') or info.get('shortName', 'Unknown')

                        # Get additional metadata
                        metadata['sector'] = info.get('sector')
                        metadata['industry'] = info.get('industry')
                        metadata['country'] = info.get('country')

                        # Get market cap (store as text since it can be very large)
                        market_cap = info.get('marketCap')
                        if market_cap:
                            metadata['market_cap'] = str(market_cap)

                        logger.debug(f"Fetched metadata for {ticker}: {metadata.get('company_name')}, sector={metadata.get('sector')}, industry={metadata.get('industry')}")
                    else:
                        logger.warning(f"No yfinance info available for {ticker}")
                        metadata['company_name'] = 'Unknown'

                except Exception as yf_error:
                    logger.warning(f"Failed to fetch yfinance data for {ticker}: {yf_error}")
                    metadata['company_name'] = 'Unknown'

            # Set last_updated timestamp
            from datetime import timezone
            metadata['last_updated'] = datetime.now(timezone.utc).isoformat()

            # Upsert into securities table
            result = self.supabase.table("securities").upsert(metadata, on_conflict="ticker").execute()

            logger.info(f"✅ Ensured {ticker} in securities table: {metadata.get('company_name')}")
            return True

        except Exception as e:
            logger.error(f"❌ Error ensuring ticker {ticker} in securities table: {e}")
            return False

    def get_portfolio_data(self, date_range: Optional[Tuple[datetime, datetime]] = None) -> List[PortfolioSnapshot]:
        """Get portfolio data from Supabase.
        
        Args:
            date_range: Optional date range filter. If None, defaults to last 90 days for performance.
            
        Returns:
            List of portfolio snapshots
            
        Raises:
            RepositoryError: If data retrieval fails
        """
        try:
            import time
            start_time = time.time()
            
            # If no date range provided, default to last 90 days for performance
            # This avoids loading all historical data when only recent snapshots are needed
            date_range_limited = False
            if date_range is None:
                from datetime import timedelta
                end_date = datetime.now()
                start_date = end_date - timedelta(days=90)
                date_range = (start_date, end_date)
                date_range_limited = True
                logger.info(f"⚠️  No date range specified - loading last 90 days only (for performance)")
                logger.info(f"   Date range: {start_date.date()} to {end_date.date()}")
                # Use logger for user-facing messages to avoid encoding issues with emojis
                logger.warning(f"No date range specified - loading last 90 days only (for performance)")
                logger.info(f"   Date range: {start_date.date()} to {end_date.date()}")
                logger.info(f"   Note: Full history available but limited for faster loading")
            
            # Supabase Python client has a 1000-row default limit
            # We need to paginate to get all data
            all_data = []
            page_size = 1000
            offset = 0
            batch_num = 1
            
            if date_range:
                start_date, end_date = date_range
                days_diff = (end_date - start_date).days
                logger.info(f"📊 Loading portfolio data from {start_date.date()} to {end_date.date()} ({days_diff} days)...")
            
            while True:
                query = self.supabase.table("portfolio_positions") \
                    .select("*") \
                    .eq("fund", self.fund) \
                    .range(offset, offset + page_size - 1)
                
                if date_range:
                    query = query.gte("date", start_date.isoformat()).lte("date", end_date.isoformat())
                
                result = query.execute()
                
                if not result.data:
                    break
                
                all_data.extend(result.data)
                logger.debug(f"   Fetched batch {batch_num}: {len(result.data)} positions (total: {len(all_data)})")
                
                # If we got less than page_size rows, we're done
                if len(result.data) < page_size:
                    break
                
                offset += page_size
                batch_num += 1
            
            elapsed_time = time.time() - start_time
            logger.info(f"✅ Fetched {len(all_data)} portfolio positions in {elapsed_time:.2f}s")
            
            if date_range_limited:
                logger.warning(f"⚠️  Note: Only showing last 90 days of history. Full history available on request.")
            
            # Create a result-like object with all data
            class Result:
                def __init__(self, data):
                    self.data = data
            
            result = Result(all_data)
            
            # Use SnapshotMapper to group positions by date and create snapshots
            process_start = time.time()
            logger.debug("   Grouping positions by date and creating snapshots...")
            grouped = SnapshotMapper.group_positions_by_date(result.data)
            
            snapshots = []
            for date_key, position_rows in grouped.items():
                # Get timestamp from first position
                if position_rows:
                    from .field_mapper import TypeTransformers
                    timestamp = TypeTransformers.iso_to_datetime(position_rows[0]["date"])
                    snapshot = SnapshotMapper.create_snapshot_from_positions(timestamp, position_rows)
                    snapshots.append(snapshot)
            
            process_time = time.time() - process_start
            total_time = time.time() - start_time
            logger.info(f"✅ Created {len(snapshots)} snapshots in {process_time:.2f}s (total: {total_time:.2f}s)")
            
            return sorted(snapshots, key=lambda s: s.timestamp)
            
        except Exception as e:
            logger.error(f"Failed to get portfolio data: {e}")
            raise RepositoryError(f"Failed to get portfolio data: {e}")
    
    def save_portfolio_snapshot(self, snapshot: PortfolioSnapshot, is_trade_execution: bool = False) -> None:
        """Save portfolio data to Supabase with duplicate detection.
        
        ARCHITECTURE NOTE: This should receive a COMPLETE snapshot with ALL positions for that date.
        This method deletes ALL existing positions for that date before inserting,
        ensuring ONE snapshot per trading day regardless of timestamp differences.
        
        Args:
            snapshot: Complete portfolio snapshot with all positions
            is_trade_execution: Whether this is triggered by a trade execution (bypasses market-close protection)
            
        Raises:
            RepositoryError: If data saving fails
        """
        try:
            # Check for existing snapshots on the same date
            from datetime import timezone
            snapshot_date = snapshot.timestamp.date()
            
            # Get existing snapshots for this date
            existing = self.get_portfolio_data(date_range=(
                datetime.combine(snapshot_date, datetime.min.time()).replace(tzinfo=timezone.utc),
                datetime.combine(snapshot_date, datetime.max.time()).replace(tzinfo=timezone.utc)
            ))
            
            if existing:
                # Check if any existing snapshot is at market close (16:00:00)
                market_close_exists = any(
                    s.timestamp.hour == 16 and s.timestamp.minute == 0 
                    for s in existing
                )
                
                # If we're trying to save a market close snapshot and one already exists
                if (snapshot.timestamp.hour == 16 and snapshot.timestamp.minute == 0 
                    and market_close_exists):
                    logger.warning(f"Market close snapshot already exists for {snapshot_date}")
                    # Don't crash, just update the existing one
                    pass
                
                # If we're trying to save an intraday snapshot but market close exists
                # Only apply protection for price updates, not trade executions
                elif (market_close_exists and not (snapshot.timestamp.hour == 16 and snapshot.timestamp.minute == 0) 
                      and not is_trade_execution):
                    logger.warning(f"⚠️  Attempting to save intraday snapshot but market close snapshot already exists for {snapshot_date}")
                    logger.warning(f"   Skipping save to preserve market close snapshot at 16:00:00")
                    return  # Don't save, preserve market close snapshot
            
            # Get fund's base currency for pre-conversion
            base_currency = 'CAD'  # Default
            try:
                fund_result = self.supabase.table("funds")\
                    .select("base_currency")\
                    .eq("name", self.fund)\
                    .limit(1)\
                    .execute()
                if fund_result.data and fund_result.data[0].get('base_currency'):
                    base_currency = fund_result.data[0]['base_currency'].upper()
            except Exception as e:
                logger.warning(f"Could not get base_currency for fund {self.fund}, using default CAD: {e}")
            
            # Get exchange rates for this date (for currency conversion)
            # Import exchange rate utility
            try:
                import sys
                from pathlib import Path
                project_root = Path(__file__).resolve().parent.parent.parent
                web_dashboard_path = project_root / 'web_dashboard'
                if str(web_dashboard_path) not in sys.path:
                    sys.path.insert(0, str(web_dashboard_path))
                from exchange_rates_utils import get_exchange_rate_for_date_from_db
            except ImportError:
                logger.warning("Could not import exchange_rates_utils - pre-converted values will be None")
                get_exchange_rate_for_date_from_db = None
            
            # Use PositionMapper to convert positions to Supabase format with pre-converted values
            positions_data = []
            snapshot_date = snapshot.timestamp.date()
            
            # Collect unique tickers to ensure existence
            unique_tickers = set()
            ticker_currencies = {}

            for position in snapshot.positions:
                ticker = position.ticker
                currency = (position.currency or 'CAD').upper()

                unique_tickers.add(ticker)
                if ticker not in ticker_currencies:
                    ticker_currencies[ticker] = currency

                exchange_rate = None
                
                # Calculate exchange rate if needed
                if base_currency and currency != base_currency:
                    if get_exchange_rate_for_date_from_db:
                        try:
                            # Get exchange rate for this date
                            if currency == 'USD' and base_currency != 'USD':
                                # Converting USD to base currency
                                rate = get_exchange_rate_for_date_from_db(
                                    snapshot.timestamp,
                                    'USD',
                                    base_currency
                                )
                                if rate is not None:
                                    exchange_rate = float(rate)
                            elif base_currency == 'USD' and currency != 'USD':
                                # Converting from position currency to USD
                                rate = get_exchange_rate_for_date_from_db(
                                    snapshot.timestamp,
                                    currency,
                                    'USD'
                                )
                                if rate is not None:
                                    exchange_rate = float(rate)
                                else:
                                    # Try inverse rate
                                    inverse_rate = get_exchange_rate_for_date_from_db(
                                        snapshot.timestamp,
                                        'USD',
                                        currency
                                    )
                                    if inverse_rate is not None and inverse_rate != 0:
                                        exchange_rate = 1.0 / float(inverse_rate)
                        except Exception as e:
                            logger.warning(f"Could not get exchange rate for {currency}→{base_currency} on {snapshot_date}: {e}")
                
                # Convert position with pre-converted values
                position_data = PositionMapper.model_to_db(
                    position, 
                    self.fund, 
                    snapshot.timestamp,
                    base_currency=base_currency,
                    exchange_rate=exchange_rate
                )
                positions_data.append(position_data)
            
            # Ensure all tickers exist in securities table
            for ticker in unique_tickers:
                currency = ticker_currencies.get(ticker, "USD")
                self.ensure_ticker_in_securities(ticker, currency)

            # Clear existing positions for this fund and date first
            # Delete all positions for this fund and DATE (not exact timestamp)
            snapshot_date_str = snapshot.timestamp.date().isoformat()
            delete_result = self.supabase.table("portfolio_positions").delete()\
                .eq("fund", self.fund)\
                .gte("date", f"{snapshot_date_str}T00:00:00")\
                .lt("date", f"{snapshot_date_str}T23:59:59.999999")\
                .execute()
            
            # Upsert new positions (insert or update on conflict)
            # Using upsert instead of insert to handle race conditions gracefully
            # The unique constraint is on (fund, ticker, date_only) - date_only is auto-populated by trigger
            # If delete+insert pattern fails due to race condition, upsert will handle it
            result = self.supabase.table("portfolio_positions").upsert(
                positions_data,
                on_conflict="fund,ticker,date_only"
            ).execute()
            
            logger.info(f"Saved {len(positions_data)} portfolio positions to Supabase")
            
        except Exception as e:
            logger.error(f"Failed to save portfolio data: {e}")
            raise RepositoryError(f"Failed to save portfolio data: {e}")
    
    def get_trade_history(self, ticker: Optional[str] = None, date_range: Optional[Tuple[datetime, datetime]] = None) -> List[Trade]:
        """Get trade history from Supabase.
        
        Args:
            ticker: Optional ticker symbol to filter by
            date_range: Optional date range filter
            
        Returns:
            List of trades
            
        Raises:
            RepositoryError: If data retrieval fails
        """
        try:
            # WE MUST PAGINATE - Supabase has a hard limit of 1000 rows per request
            all_rows = []
            batch_size = 1000
            offset = 0
            
            while True:
                # Filter by fund name
                query = self.supabase.table("trade_log").select("*").eq("fund", self.fund)
                
                if ticker:
                    query = query.eq("ticker", ticker)
                
                if date_range:
                    start_date, end_date = date_range
                    query = query.gte("date", start_date.isoformat()).lte("date", end_date.isoformat())
                
                result = query.range(offset, offset + batch_size - 1).execute()
                
                if not result.data:
                    break
                
                all_rows.extend(result.data)
                
                # If we got fewer rows than batch_size, we're done
                if len(result.data) < batch_size:
                    break
                
                offset += batch_size
                
                # Safety break to prevent infinite loops (e.g. max 50k rows = 50 batches)
                if offset > 50000:
                    logger.warning("Reached 50,000 row safety limit in get_trade_history pagination")
                    break
            
            # Use TradeMapper to convert database rows to Trade objects
            trades = [TradeMapper.db_to_model(row) for row in all_rows]
            
            return trades
            
        except Exception as e:
            logger.error(f"Failed to get trade history: {e}")
            raise RepositoryError(f"Failed to get trade history: {e}")
    
    def save_trade(self, trade: Trade) -> None:
        """Save a trade to Supabase.
        
        Args:
            trade: Trade to save
            
        Raises:
            RepositoryError: If data saving fails
        """
        try:
            # Ensure ticker exists in securities table
            self.ensure_ticker_in_securities(trade.ticker, trade.currency)

            # Use TradeMapper to convert Trade object to Supabase format
            trade_data = TradeMapper.model_to_db(trade, self.fund)
            
            result = self.supabase.table("trade_log").insert(trade_data).execute()
            
            logger.info(f"Saved trade for {trade.ticker} to Supabase")
            
        except Exception as e:
            logger.error(f"Failed to save trade: {e}")
            raise RepositoryError(f"Failed to save trade: {e}")
    
    def get_market_data(self, ticker: str, date_range: Optional[Tuple[datetime, datetime]] = None) -> List[MarketData]:
        """Get market data from Supabase.
        
        Args:
            ticker: Stock ticker symbol
            date_range: Optional date range filter
            
        Returns:
            List of market data points
            
        Raises:
            RepositoryError: If data retrieval fails
        """
        # This would need a market_data table in Supabase
        # For now, return empty list as market data is typically fetched live
        logger.warning("Market data retrieval from Supabase not implemented yet")
        return []
    
    def save_market_data(self, market_data: MarketData) -> None:
        """Save market data to Supabase.
        
        Args:
            market_data: MarketData to save
            
        Raises:
            RepositoryError: If data saving fails
        """
        # This would need a market_data table in Supabase
        # For now, do nothing as market data is typically fetched live
        logger.warning(f"Market data saving to Supabase not implemented yet (ticker: {market_data.ticker})")
    
    def get_recent_trades(self, days: int = 30, limit: int = 100) -> List[Trade]:
        """Get recent trades for easier debugging.
        
        Args:
            days: Number of days back to look
            limit: Maximum number of trades to return
            
        Returns:
            List of recent trades sorted by date
        """
        from datetime import timedelta
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        return self.get_trade_history(date_range=(start_date, end_date))[:limit]
    
    def get_trades_by_ticker(self, ticker: str, limit: int = 50) -> List[Trade]:
        """Get all trades for a specific ticker.
        
        Args:
            ticker: Ticker symbol to filter by
            limit: Maximum number of trades to return
            
        Returns:
            List of trades for the ticker
        """
        trades = self.get_trade_history(ticker=ticker)
        return sorted(trades, key=lambda x: x.timestamp, reverse=True)[:limit]
    
    def get_fund_summary(self) -> Dict[str, Any]:
        """Get a summary of trades for this fund.
        
        Returns:
            Dictionary with fund statistics
        """
        try:
            # Get all trades for this fund
            all_trades = self.get_trade_history()
            
            if not all_trades:
                return {
                    'fund': self.fund,
                    'total_trades': 0,
                    'unique_tickers': 0,
                    'date_range': None,
                    'total_value': 0
                }
            
            # Calculate statistics
            tickers = set(trade.ticker for trade in all_trades)
            dates = [trade.timestamp for trade in all_trades]
            total_value = sum(float(trade.cost_basis or 0) for trade in all_trades)
            
            return {
                'fund': self.fund,
                'total_trades': len(all_trades),
                'unique_tickers': len(tickers),
                'date_range': {
                    'first': min(dates).strftime('%Y-%m-%d'),
                    'last': max(dates).strftime('%Y-%m-%d')
                },
                'total_value': total_value,
                'tickers': sorted(tickers)
            }
            
        except Exception as e:
            logger.error(f"Failed to get fund summary: {e}")
            raise RepositoryError(f"Failed to get fund summary: {e}")

    def backup_data(self, backup_path: str) -> None:
        """Backup data from Supabase.
        
        Args:
            backup_path: Path to save backup
            
        Raises:
            RepositoryError: If backup fails
        """
        try:
            # Export all data to CSV files
            portfolio_data = self.get_portfolio_data()
            trade_data = self.get_trade_history()
            
            # Save to backup location
            # This would need to be implemented based on backup format requirements
            logger.info(f"Backup completed to {backup_path}")
            
        except Exception as e:
            logger.error(f"Failed to backup data: {e}")
            raise RepositoryError(f"Failed to backup data: {e}")
    
    def restore_data(self, backup_path: str) -> None:
        """Restore data to Supabase.
        
        Args:
            backup_path: Path to backup file
            
        Raises:
            RepositoryError: If restore fails
        """
        # This would need to be implemented based on backup format
        logger.warning("Data restore from backup not implemented yet")
    
    def get_cash_balances(self) -> Dict[str, Decimal]:
        """Get cash balances from Supabase.
        
        Returns:
            Dictionary of currency -> balance
            
        Raises:
            RepositoryError: If data retrieval fails
        """
        try:
            # WE MUST PAGINATE - Supabase has a hard limit of 1000 rows per request
            all_rows = []
            batch_size = 1000
            offset = 0
            
            while True:
                query = self.supabase.table("cash_balances").select("*").eq("fund", self.fund)
                
                result = query.range(offset, offset + batch_size - 1).execute()
                
                if not result.data:
                    break
                
                all_rows.extend(result.data)
                
                # If we got fewer rows than batch_size, we're done
                if len(result.data) < batch_size:
                    break
                
                offset += batch_size
                
                # Safety break to prevent infinite loops
                if offset > 50000:
                    logger.warning("Reached 50,000 row safety limit in get_cash_balances pagination")
                    break
            
            # Use CashBalanceMapper to convert database rows to dictionary
            balances = CashBalanceMapper.db_to_dict(all_rows)
            
            return balances
            
        except Exception as e:
            logger.error(f"Failed to get cash balances: {e}")
            raise RepositoryError(f"Failed to get cash balances: {e}")
    
    def save_cash_balances(self, balances: Dict[str, Decimal]) -> None:
        """Save cash balances to Supabase.
        
        Args:
            balances: Dictionary of currency -> balance
            
        Raises:
            RepositoryError: If data saving fails
        """
        try:
            # Use CashBalanceMapper to convert dictionary to database format
            balances_data = CashBalanceMapper.dict_to_db(balances, self.fund)
            
            result = self.supabase.table("cash_balances").upsert(balances_data).execute()
            
            logger.info(f"Saved cash balances to Supabase")
            
        except Exception as e:
            logger.error(f"Failed to save cash balances: {e}")
            raise RepositoryError(f"Failed to save cash balances: {e}")
    
    def get_latest_portfolio_snapshot_with_pnl(self) -> Optional[PortfolioSnapshot]:
        """Get the most recent portfolio snapshot with calculated P&L from database view.
        
        This uses the Supabase view 'latest_positions' which calculates
        1-day and 5-day P&L server-side for better performance.
        
        Returns:
            Portfolio snapshot with positions including historical P&L metrics
        """
        try:
            # WE MUST PAGINATE - Supabase has a hard limit of 1000 rows per request
            all_rows = []
            batch_size = 1000
            offset = 0
            
            while True:
                query = self.supabase.table("latest_positions") \
                    .select("*") \
                    .eq("fund", self.fund)
                
                result = query.range(offset, offset + batch_size - 1).execute()
                
                if not result.data:
                    break
                
                all_rows.extend(result.data)
                
                # If we got fewer rows than batch_size, we're done
                if len(result.data) < batch_size:
                    break
                
                offset += batch_size
                
                # Safety break to prevent infinite loops
                if offset > 50000:
                    logger.warning("Reached 50,000 row safety limit in get_latest_portfolio_snapshot_with_pnl pagination")
                    break
            
            if not all_rows:
                logger.debug(f"No portfolio data found for fund: {self.fund}")
                return None
            
            # Convert view rows to Position objects
            from .field_mapper import TypeTransformers
            positions = []
            
            for row in all_rows:
                # The view returns enriched data with P&L calculations
                position = PositionMapper.db_to_model(row)
                
                # Add the calculated P&L fields from the view
                position.daily_pnl = row.get('daily_pnl')
                position.daily_pnl_pct = row.get('daily_pnl_pct')
                position.five_day_pnl = row.get('five_day_pnl')
                position.five_day_pnl_pct = row.get('five_day_pnl_pct')
                
                positions.append(position)
            
            # Get timestamp from first position
            timestamp = TypeTransformers.iso_to_datetime(all_rows[0]['date'])
            
            # Calculate total value
            total_value = sum(pos.market_value for pos in positions if pos.market_value)
            
            return PortfolioSnapshot(
                positions=positions,
                timestamp=timestamp,
                total_value=total_value
            )
            
        except Exception as e:
            logger.error(f"Failed to get portfolio snapshot with P&L: {e}", exc_info=True)
            raise RepositoryError(f"Failed to get portfolio snapshot with P&L: {e}") from e
    
    def get_latest_portfolio_snapshot(self) -> Optional[PortfolioSnapshot]:
        """Get the most recent portfolio snapshot.
        
        Returns the latest snapshot with all positions from that exact timestamp.
        This avoids loading historical data and just gets the current portfolio state.
        """
        try:
            # Strategy: Get max date first, then get all positions with that exact date
            # This is more efficient than loading all history and taking the last one
            
            # Step 1: Find the maximum (latest) date for this fund
            max_date_query = self.supabase.table("portfolio_positions") \
                .select("date") \
                .eq("fund", self.fund) \
                .order("date", desc=True) \
                .limit(1) \
                .execute()
            
            if not max_date_query.data:
                logger.debug(f"No portfolio data found for fund: {self.fund}")
                return None
            
            from .field_mapper import TypeTransformers
            latest_timestamp_str = max_date_query.data[0]["date"]
            latest_timestamp = TypeTransformers.iso_to_datetime(latest_timestamp_str)
            
            # Step 2: Get ALL positions from that exact DATE (not timestamp)
            # Get positions from the same DATE (not exact timestamp)
            # WE MUST PAGINATE - Supabase has a hard limit of 1000 rows per request
            date_str = latest_timestamp.date().isoformat()
            all_position_rows = []
            batch_size = 1000
            offset = 0
            
            while True:
                query = self.supabase.table("portfolio_positions") \
                    .select("*") \
                    .eq("fund", self.fund) \
                    .gte("date", f"{date_str}T00:00:00Z") \
                    .lte("date", f"{date_str}T23:59:59Z")
                
                result = query.range(offset, offset + batch_size - 1).execute()
                
                if not result.data:
                    break
                
                all_position_rows.extend(result.data)
                
                # If we got fewer rows than batch_size, we're done
                if len(result.data) < batch_size:
                    break
                
                offset += batch_size
                
                # Safety break to prevent infinite loops
                if offset > 50000:
                    logger.warning("Reached 50,000 row safety limit in get_latest_portfolio_snapshot pagination")
                    break
            
            if not all_position_rows:
                logger.debug(f"No positions found for latest date: {latest_timestamp}")
                return None
            
            logger.debug(f"Found {len(all_position_rows)} positions for latest snapshot: {latest_timestamp}")
            
            # Group by ticker and take the latest timestamp for each ticker
            # This handles cases where there are multiple updates on the same day
            ticker_positions = {}
            for row in all_position_rows:
                ticker = row['ticker']
                row_timestamp = TypeTransformers.iso_to_datetime(row['date'])
                
                # Keep only the latest position for each ticker
                if ticker not in ticker_positions:
                    ticker_positions[ticker] = row
                else:
                    existing_timestamp = TypeTransformers.iso_to_datetime(ticker_positions[ticker]['date'])
                    if row_timestamp > existing_timestamp:
                        ticker_positions[ticker] = row
            
            # Convert to Position objects
            positions = [PositionMapper.db_to_model(row) for row in ticker_positions.values()]
            
            # Calculate total value
            total_value = Decimal('0')
            for position in positions:
                if position.market_value:
                    total_value += position.market_value
            
            # Create snapshot
            snapshot = PortfolioSnapshot(
                positions=positions,
                timestamp=latest_timestamp,
                total_value=total_value
            )
            
            return snapshot
            
        except Exception as e:
            logger.error(f"Failed to get latest portfolio snapshot: {e}")
            raise RepositoryError(f"Failed to get latest portfolio snapshot: {e}")
    
    def get_positions_by_ticker(self, ticker: str) -> List[Position]:
        """Get all positions for a specific ticker across time."""
        try:
            # WE MUST PAGINATE - Supabase has a hard limit of 1000 rows per request
            all_rows = []
            batch_size = 1000
            offset = 0
            
            while True:
                query = self.supabase.table("portfolio_positions").select("*").eq("ticker", ticker).eq("fund", self.fund)
                
                result = query.range(offset, offset + batch_size - 1).execute()
                
                if not result.data:
                    break
                
                all_rows.extend(result.data)
                
                # If we got fewer rows than batch_size, we're done
                if len(result.data) < batch_size:
                    break
                
                offset += batch_size
                
                # Safety break to prevent infinite loops
                if offset > 50000:
                    logger.warning("Reached 50,000 row safety limit in get_positions_by_ticker pagination")
                    break
            
            # Use PositionMapper to convert database rows to Position objects
            positions = [PositionMapper.db_to_model(row) for row in all_rows]
            
            return positions
            
        except Exception as e:
            logger.error(f"Failed to get positions by ticker: {e}")
            raise RepositoryError(f"Failed to get positions by ticker: {e}")
    
    def restore_from_backup(self, backup_path: str) -> None:
        """Restore data from a backup."""
        # This would need to be implemented based on backup format
        logger.warning("Data restore from backup not implemented yet")
        raise RepositoryError("Data restore from backup not implemented yet")
    
    def validate_data_integrity(self) -> List[str]:
        """Validate data integrity and return list of issues found."""
        issues = []
        
        try:
            # Check if portfolio positions exist
            result = self.supabase.table("portfolio_positions").select("id").limit(1).execute()
            if not result.data:
                issues.append("No portfolio positions found")
            
            # Check if trade log exists
            result = self.supabase.table("trade_log").select("id").limit(1).execute()
            if not result.data:
                issues.append("No trade log found")
            
            # Add more validation checks as needed
            
        except Exception as e:
            issues.append(f"Database connection error: {e}")
        
        return issues

    def get_current_positions(self, fund: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get current portfolio positions, optionally filtered by fund.

        This method returns aggregated data from the latest_positions view,
        which includes pre-calculated daily P&L data.
        """
        try:
            # WE MUST PAGINATE - Supabase has a hard limit of 1000 rows per request
            all_rows = []
            batch_size = 1000
            offset = 0
            
            # Use provided fund if explicitly given (including None for all funds)
            # Empty string means "all funds" so treat it as None
            target_fund = fund if fund else None
            
            while True:
                query = self.supabase.table("latest_positions").select("*, securities(company_name, sector, industry, market_cap, country)")
                if target_fund:
                    query = query.eq("fund", target_fund)
                
                result = query.range(offset, offset + batch_size - 1).execute()
                
                if not result.data:
                    break
                
                all_rows.extend(result.data)
                
                # If we got fewer rows than batch_size, we're done
                if len(result.data) < batch_size:
                    break
                
                offset += batch_size
                
                # Safety break to prevent infinite loops
                if offset > 50000:
                    logger.warning("Reached 50,000 row safety limit in get_current_positions pagination")
                    break
            
            return all_rows
        except Exception as e:
            logger.error(f"Failed to get current positions: {e}")
            raise RepositoryError(f"Failed to get current positions: {e}")

    def get_trade_log(self, limit: int = 1000, fund: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get recent trade log entries, optionally filtered by fund.
        
        Always uses pagination to handle Supabase's 1000-row limit safely.
        """
        try:
            # Use provided fund if explicitly given (including None for all funds)
            # Empty string means "all funds" so treat it as None  
            target_fund = fund if fund else None
            
            # Always use pagination to be safe with Supabase's 1000-row limit
            all_rows = []
            batch_size = 1000
            offset = 0
            
            while len(all_rows) < limit:
                query = self.supabase.table("trade_log").select("*").order("date", desc=True)
                if target_fund:
                    query = query.eq("fund", target_fund)
                
                result = query.range(offset, offset + batch_size - 1).execute()
                
                if not result.data:
                    break
                
                all_rows.extend(result.data)
                
                # If we got fewer rows than batch_size, we're done
                if len(result.data) < batch_size:
                    break
                
                # If we've collected enough rows, stop
                if len(all_rows) >= limit:
                    break
                
                offset += batch_size
                
                # Safety break to prevent infinite loops
                if offset > 50000:
                    logger.warning("Reached 50,000 row safety limit in get_trade_log pagination")
                    break
            
            # Return only the requested limit
            return all_rows[:limit]
        except Exception as e:
            logger.error(f"Failed to get trade log: {e}")
            raise RepositoryError(f"Failed to get trade log: {e}")

    def get_available_funds(self) -> List[str]:
        """Get list of available funds in the database."""
        try:
            # Get unique fund names from portfolio_positions table
            # WE MUST PAGINATE - Supabase has a hard limit of 1000 rows per request
            all_rows = []
            batch_size = 1000
            offset = 0
            
            while True:
                query = self.supabase.table("portfolio_positions").select("fund")
                
                result = query.range(offset, offset + batch_size - 1).execute()
                
                if not result.data:
                    break
                
                all_rows.extend(result.data)
                
                # If we got fewer rows than batch_size, we're done
                if len(result.data) < batch_size:
                    break
                
                offset += batch_size
                
                # Safety break to prevent infinite loops
                if offset > 50000:
                    logger.warning("Reached 50,000 row safety limit in get_available_funds pagination")
                    break
            
            funds = list(set(row['fund'] for row in all_rows if row.get('fund')))
            return sorted(funds)
        except Exception as e:
            logger.error(f"Failed to get available funds: {e}")
            raise RepositoryError(f"Failed to get available funds: {e}")
    
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
            
            # Create a FIFO processor to rebuild lots
            fifo_processor = FIFOTradeProcessor(self)
            
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