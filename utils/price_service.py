"""Centralized price fetching and portfolio update service.

This module provides a unified interface for all price-related operations,
replacing scattered logic across multiple files. It handles:
- Fetching historical price data (for graphs and analysis)
- Fetching current prices (for portfolio display)
- Updating Position objects with new prices
- Market hours awareness
- Cache management
- Currency conversion

The service does NOT handle storage - it only works with in-memory Position
objects. Storage is delegated to the repository layer for proper separation
of concerns.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd

from data.models.portfolio import Position, PortfolioSnapshot
from market_data.market_hours import MarketHours
from market_data.data_fetcher import MarketDataFetcher
from market_data.ohlcv_quality import get_last_valid_close
from market_data.price_cache import PriceCache
from portfolio.portfolio_manager import PortfolioManager

logger = logging.getLogger(__name__)


class PriceService:
    """Centralized service for price fetching and portfolio updates.
    
    This service provides a unified interface for all price-related operations
    throughout the application. It handles both historical data (for graphs)
    and current prices (for display), with smart caching and market hours
    awareness.
    
    Key Features:
    - Cache-first strategy to minimize API calls
    - Market hours awareness (respects trading days and close times)
    - Support for both historical and current price fetching
    - Currency conversion support
    - Fallback to existing prices when API fails
    - Reports cache efficiency metrics
    
    Separation of Concerns:
    - This service handles ONLY business logic (fetch, calculate, validate)
    - Storage operations (save/load) are delegated to repository layer
    - No knowledge of CSV, Supabase, or any storage implementation
    """
    
    def __init__(
        self,
        market_data_fetcher: MarketDataFetcher,
        price_cache: PriceCache,
        market_hours: MarketHours
    ):
        """Initialize the price service.
        
        Args:
            market_data_fetcher: Service for fetching market data from APIs
            price_cache: Cache for storing and retrieving price data
            market_hours: Service for market hours and trading day logic
        """
        self.fetcher = market_data_fetcher
        self.cache = price_cache
        self.market_hours = market_hours
    
    def get_historical_prices(
        self,
        tickers: List[str],
        start_date: datetime,
        end_date: datetime,
        verbose: bool = True
    ) -> Tuple[Dict[str, pd.DataFrame], int, int]:
        """Fetch historical price data for multiple tickers.
        
        This method is used when you need historical OHLCV data, such as for
        generating graphs or calculating 7-day/30-day P&L. It returns full
        DataFrames with Open, High, Low, Close, and Volume data.
        
        Cache Strategy:
        - Checks cache first for each ticker
        - Only fetches from API if cache miss
        - Caches results for future use
        - Reports cache efficiency (hits vs API calls)
        
        Args:
            tickers: List of ticker symbols to fetch
            start_date: Start date for historical data
            end_date: End date for historical data
            verbose: If True, log progress and cache metrics
            
        Returns:
            Tuple of:
            - Dict mapping ticker to DataFrame (empty DataFrame if fetch fails)
            - Number of cache hits
            - Number of API calls made
            
        Example:
            >>> market_data, hits, calls = service.get_historical_prices(
            ...     ['AAPL', 'MSFT'],
            ...     datetime(2024, 1, 1),
            ...     datetime(2024, 10, 1)
            ... )
            >>> aapl_data = market_data['AAPL']  # Full DataFrame
            >>> latest_price = get_last_valid_close(aapl_data)
        """
        market_data = {}
        cache_hits = 0
        api_calls = 0
        
        if verbose:
            logger.info(f"Fetching historical prices for {len(tickers)} tickers")
        
        for ticker in tickers:
            try:
                # Cache-first approach: Check cache first
                cached_data = self.cache.get_cached_price(ticker, start_date, end_date)
                
                if cached_data is not None and not cached_data.empty:
                    # Use cached data
                    market_data[ticker] = cached_data
                    cache_hits += 1
                    logger.debug(f"Cache hit for {ticker}: {len(cached_data)} rows")
                else:
                    # Cache miss - fetch fresh data from API
                    result = self.fetcher.fetch_price_data(ticker, start_date, end_date)
                    if not result.df.empty:
                        market_data[ticker] = result.df
                        # Update cache with fresh data
                        self.cache.cache_price_data(ticker, result.df, result.source)
                        api_calls += 1
                        logger.debug(f"API fetch for {ticker}: {len(result.df)} rows from {result.source}")
                    else:
                        market_data[ticker] = pd.DataFrame()
                        logger.warning(f"No data returned for {ticker}")
            
            except Exception as e:
                logger.warning(f"Failed to fetch data for {ticker}: {e}")
                market_data[ticker] = pd.DataFrame()
        
        # Report cache efficiency
        if verbose and cache_hits > 0:
            logger.info(f"Cache efficiency: {cache_hits} hits, {api_calls} API calls")
        
        return market_data, cache_hits, api_calls
    
    def get_current_prices(
        self,
        tickers: List[str],
        verbose: bool = True
    ) -> Dict[str, Optional[Decimal]]:
        """Fetch current prices for multiple tickers.
        
        This method is used when you only need the latest price for each ticker,
        such as for portfolio display. It returns single price values, not
        full historical DataFrames.
        
        Note: This method does NOT cache prices to disk. Prices are only
        cached in memory for the session. This is intentional - during market
        hours, prices change frequently, and we want fresh data on next run.
        Only market close prices should be persisted to storage.
        
        Args:
            tickers: List of ticker symbols to fetch
            verbose: If True, log progress
            
        Returns:
            Dict mapping ticker to current price (None if fetch fails)
            
        Example:
            >>> prices = service.get_current_prices(['AAPL', 'MSFT'])
            >>> aapl_price = prices['AAPL']  # Decimal('150.25')
        """
        prices = {}
        
        if verbose:
            logger.info(f"Fetching current prices for {len(tickers)} tickers")
        
        for ticker in tickers:
            try:
                price = self.fetcher.get_current_price(ticker)
                prices[ticker] = price
                if price:
                    logger.debug(f"Fetched current price for {ticker}: ${price}")
                else:
                    logger.warning(f"No current price available for {ticker}")
            except Exception as e:
                logger.warning(f"Failed to fetch current price for {ticker}: {e}")
                prices[ticker] = None
        
        return prices
    
    def update_positions_with_prices(
        self,
        positions: List[Position],
        use_historical: bool = True,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        verbose: bool = True
    ) -> Tuple[List[Position], int, int]:
        """Update Position objects with current/historical prices.
        
        This is the main method for updating portfolio positions with fresh
        prices. It handles fetching, caching, fallback logic, and creating
        new Position objects with updated values.
        
        Logic:
        1. Fetch prices (historical or current based on use_historical flag)
        2. For each position:
           - Extract price from fetched data
           - Calculate market_value = shares * price
           - Calculate unrealized_pnl = (price - avg_price) * shares
           - Create new Position object with updates
           - Fallback to existing CSV price if fetch fails
        
        Args:
            positions: List of Position objects to update
            use_historical: If True, use historical data (for graphs)
                          If False, use current prices (for display)
            start_date: Start date for historical fetch (required if use_historical=True)
            end_date: End date for historical fetch (required if use_historical=True)
            verbose: If True, log progress and metrics
            
        Returns:
            Tuple of:
            - List of updated Position objects
            - Number of cache hits (if use_historical=True)
            - Number of API calls made
            
        Example:
            >>> updated, hits, calls = service.update_positions_with_prices(
            ...     positions,
            ...     use_historical=True,
            ...     start_date=week_ago,
            ...     end_date=today
            ... )
            >>> # Now save via repository:
            >>> repository.save_portfolio_snapshot(PortfolioSnapshot(positions=updated))
        """
        if not positions:
            return [], 0, 0
        
        tickers = [pos.ticker for pos in positions]
        updated_positions = []
        cache_hits = 0
        api_calls = 0
        
        # Fetch prices based on mode
        if use_historical:
            if not start_date or not end_date:
                raise ValueError("start_date and end_date required for historical mode")
            
            market_data, cache_hits, api_calls = self.get_historical_prices(
                tickers, start_date, end_date, verbose
            )
            
            # Extract prices from DataFrames
            prices = {}
            for ticker, df in market_data.items():
                if not df.empty and 'Close' in df.columns:
                    prices[ticker] = get_last_valid_close(df)
                else:
                    prices[ticker] = None
        else:
            # Fetch current prices
            price_dict = self.get_current_prices(tickers, verbose)
            prices = price_dict
            api_calls = len([p for p in price_dict.values() if p is not None])
        
        # Update each position
        for position in positions:
            price = prices.get(position.ticker)
            
            if price and price > 0:
                # Create updated position with new price
                updated_position = Position(
                    ticker=position.ticker,
                    shares=position.shares,
                    avg_price=position.avg_price,
                    cost_basis=position.cost_basis,
                    currency=position.currency,
                    company=position.company,
                    current_price=price,
                    market_value=position.shares * price,
                    unrealized_pnl=(price - position.avg_price) * position.shares,
                    stop_loss=position.stop_loss,
                    position_id=position.position_id
                )
                updated_positions.append(updated_position)
                logger.debug(f"Updated {position.ticker} with price: ${price}")
        else:
            # Price fetch failed - don't use fallback prices, fail clearly
            # CRITICAL: We never use fallback prices (old prices, average prices, etc.)
            # This prevents silent insertion of garbage data that would corrupt P&L calculations
            logger.error(f"Failed to fetch price for {position.ticker} - no fallback available")
            logger.error(f"  Position will not be included in updated positions")
            logger.error(f"  This ensures data integrity - no stale prices will be saved")
            # Don't append - skip this position entirely
        
        if verbose:
            logger.info(f"Updated {len(updated_positions)} positions")
        
        return updated_positions, cache_hits, api_calls
    
    def should_update_portfolio(
        self,
        portfolio_manager: PortfolioManager,
        target_date: Optional[datetime] = None
    ) -> Tuple[bool, str]:
        """Determine if portfolio prices should be updated.
        
        This method implements smart logic for deciding when to update prices:
        - Checks if today is a trading day
        - Checks if portfolio was already updated today
        - Checks for missing trading days
        - Respects market hours (don't overwrite close with after-hours)
        
        This delegates to the existing portfolio_update_logic module to
        preserve all the smart market hours logic.
        
        Args:
            portfolio_manager: Portfolio manager for checking last update
            target_date: Optional specific date to check (defaults to today)
            
        Returns:
            Tuple of (should_update: bool, reason: str)
            
        Example:
            >>> should_update, reason = service.should_update_portfolio(pm)
            >>> if should_update:
            ...     print(f"Updating: {reason}")
            ...     positions = service.update_positions_with_prices(...)
            ... else:
            ...     print(f"Skipping: {reason}")
        """
        from utils.portfolio_update_logic import should_update_portfolio
        return should_update_portfolio(self.market_hours, portfolio_manager, target_date)
    
    def apply_currency_conversion(
        self,
        positions: List[Position],
        data_dir: Path,
        target_currency: str = 'CAD'
    ) -> Dict[str, Any]:
        """Apply currency conversion to positions for accurate totals.
        
        This method converts position values to a common currency (typically CAD
        for Canadian portfolios) to calculate accurate total portfolio value.
        
        Args:
            positions: List of Position objects
            data_dir: Data directory for loading exchange rates
            target_currency: Target currency for conversion (default: CAD)
            
        Returns:
            Dict containing:
            - 'positions': List of positions (unchanged)
            - 'total_cad': Total portfolio value in CAD
            - 'total_usd': Total portfolio value in USD
            - 'exchange_rate': USD to CAD exchange rate used
            
        Example:
            >>> result = service.apply_currency_conversion(positions, data_dir)
            >>> print(f"Total portfolio value: ${result['total_cad']:.2f} CAD")
        """
        from utils.currency_converter import load_exchange_rates, convert_usd_to_cad
        
        # Load exchange rates
        exchange_rates = load_exchange_rates(data_dir)
        
        # Calculate totals by currency
        total_cad = Decimal('0')
        total_usd = Decimal('0')
        
        for position in positions:
            if position.market_value is not None:
                if position.currency == 'USD':
                    # Convert USD to CAD
                    cad_value = convert_usd_to_cad(position.market_value, exchange_rates)
                    total_cad += cad_value
                    total_usd += position.market_value
                else:
                    # Assume CAD
                    total_cad += position.market_value
        
        # Get exchange rate (default to 1.35 if not available)
        exchange_rate = exchange_rates.get('USDCAD', Decimal('1.35'))
        
        return {
            'positions': positions,
            'total_cad': total_cad,
            'total_usd': total_usd,
            'exchange_rate': exchange_rate
        }
    
    def format_cache_stats(self, cache_hits: int, api_calls: int) -> str:
        """Format cache statistics for display.
        
        Args:
            cache_hits: Number of cache hits
            api_calls: Number of API calls made
            
        Returns:
            Formatted string for display
            
        Example:
            >>> stats = service.format_cache_stats(8, 2)
            >>> print(stats)  # "8 from cache, 2 fresh fetches"
        """
        if cache_hits > 0:
            return f"{cache_hits} from cache, {api_calls} fresh fetches"
        else:
            return f"{api_calls} API calls"

