"""
Market data fetcher with robust Yahoo Finance -> Stooq fallback logic.

This module provides the MarketDataFetcher class that implements a multi-stage
fallback strategy for fetching OHLCV data:
1. Yahoo Finance via yfinance
2. Stooq via pandas-datareader  
3. Stooq direct CSV
4. Index proxies (e.g., ^GSPC->SPY, ^RUT->IWM) via Yahoo

The fetcher is designed to work with both current CSV storage and future database backends.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, Optional, cast

import pandas as pd
from pathlib import Path

logger = logging.getLogger(__name__)

# Optional pandas-datareader import for Stooq access
try:
    import pandas_datareader.data as pdr
    _HAS_PDR = True
except ImportError:
    _HAS_PDR = False
    # Downgrade to debug to avoid noisy warnings in terminal output
    logger.debug("pandas-datareader not available. Stooq PDR fallback disabled.")

# Known Stooq symbol remaps for common indices
STOOQ_MAP = {
    "^GSPC": "^SPX",  # S&P 500
    "^DJI": "^DJI",   # Dow Jones
    "^IXIC": "^IXIC", # Nasdaq Composite
    # "^RUT": not on Stooq; keep Yahoo
}

# Symbols we should *not* attempt on Stooq
STOOQ_BLOCKLIST = {"^RUT"}

# Index proxy mappings for fallback
PROXY_MAP = {
    "^GSPC": "SPY",   # S&P 500 -> SPDR S&P 500 ETF
    "^RUT": "IWM",    # Russell 2000 -> iShares Russell 2000 ETF
    "^IXIC": "QQQ",   # Nasdaq -> Invesco QQQ Trust
    "^DJI": "DIA",    # Dow Jones -> SPDR Dow Jones Industrial Average ETF
}


@dataclass
class FetchResult:
    """Result of a market data fetch operation."""
    df: pd.DataFrame
    source: str  # "yahoo" | "stooq-pdr" | "stooq-csv" | "yahoo:<proxy>-proxy" | "empty"


class MarketDataFetcher:
    """
    Robust market data fetcher with multi-stage fallback logic.
    
    Supports both current CSV-based storage and future database backends
    through a consistent interface.
    """
    
    def __init__(self, cache_instance: Optional[Any] = None, market_hours: Optional[Any] = None):
        """
        Initialize the market data fetcher.

        Args:
            cache_instance: Optional cache instance for storing/retrieving data
            market_hours: Optional MarketHours instance for market status checking
        """
        self.cache = cache_instance
        self.proxy_map = PROXY_MAP.copy()
        self._portfolio_currency_cache = {}
        self._load_currency_cache()

        # Initialize market hours
        if market_hours is None:
            from market_data.market_hours import MarketHours
            self.market_hours = MarketHours()
        else:
            self.market_hours = market_hours

        # Access global settings for configurable TTL
        try:
            from config.settings import get_settings  # lazy import to avoid cycles
            self.settings = get_settings()
        except Exception:
            self.settings = None

        # In-memory fundamentals cache (TTL-based)
        self._fund_cache: Dict[str, Dict[str, Any]] = {}
        self._fund_cache_meta: Dict[str, Dict[str, Any]] = {}
        ttl_hours = 12
        try:
            if self.settings:
                ttl_hours = int(self.settings.get('market_data.fundamentals_cache_ttl_hours', 12))
        except Exception:
            ttl_hours = 12
        self._fund_cache_ttl = timedelta(hours=ttl_hours)

        # Load fundamentals overrides (one-time load)
        self._fundamentals_overrides: Dict[str, Dict[str, Any]] = {}
        self._load_fundamentals_overrides()

        # Attempt to load fundamentals cache from disk
        try:
            self._load_fundamentals_cache()
        except Exception as e:
            logging.getLogger(__name__).debug(f"Could not load fundamentals cache: {e}")
    
    def _load_currency_cache(self):
        """Load currency information from Supabase and CSV files.
        
        This provides a baseline cache population. The actual source of truth is determined
        by repository mode, and callers will populate the cache from their repository context
        before fetching prices.
        
        Loads from both sources to ensure cache has data even if one source is unavailable.
        """
        try:
            import pandas as pd
            import glob
            import os
            
            # Load from CSV files (source of truth in CSV mode)
            trade_log_files = []
            trade_log_paths = [
                'trading_data/funds/*/llm_trade_log.csv',
                'Scripts and CSV Files/chatgpt_trade_log.csv',
                'data/*/trade_log.csv',
                'data/trade_log.csv'
            ]
            
            for pattern in trade_log_paths:
                trade_log_files.extend(glob.glob(pattern))
            
            # Load currency info from trade logs
            for file_path in trade_log_files:
                try:
                    df = pd.read_csv(file_path)
                    if 'Ticker' in df.columns and 'Currency' in df.columns:
                        # Get the latest entry for each ticker
                        latest_entries = df.groupby('Ticker').last()
                        for ticker, row in latest_entries.iterrows():
                            currency = row['Currency']
                            self._portfolio_currency_cache[ticker] = currency
                            
                            # Handle ticker variants for smart lookup
                            # If ticker has .TO/.V suffix, also cache the base ticker
                            if ticker.endswith('.TO'):
                                base_ticker = ticker[:-3]  # Remove .TO
                                if base_ticker not in self._portfolio_currency_cache:
                                    self._portfolio_currency_cache[base_ticker] = currency
                                    logger.debug(f"Mapped base ticker {base_ticker} -> {currency} from {ticker}")
                            elif ticker.endswith('.V'):
                                base_ticker = ticker[:-2]  # Remove .V
                                if base_ticker not in self._portfolio_currency_cache:
                                    self._portfolio_currency_cache[base_ticker] = currency
                                    logger.debug(f"Mapped base ticker {base_ticker} -> {currency} from {ticker}")
                            # If base ticker is CAD, also try to map to .TO variant
                            elif currency == 'CAD' and not ticker.endswith(('.TO', '.V', '.CN')):
                                to_variant = f"{ticker}.TO"
                                if to_variant not in self._portfolio_currency_cache:
                                    self._portfolio_currency_cache[to_variant] = currency
                                    logger.debug(f"Mapped .TO variant {to_variant} -> {currency} from {ticker}")
                        
                        logger.debug(f"Loaded currency cache from trade log {file_path}: {len(latest_entries)} tickers")
                except Exception as e:
                    logger.debug(f"Could not load currency cache from trade log {file_path}: {e}")
            
            # Then load from portfolio files as fallback/supplement
            portfolio_files = []
            portfolio_paths = [
                'trading_data/funds/*/llm_portfolio_update.csv',
                'Scripts and CSV Files/chatgpt_portfolio_update.csv',
                'data/*/portfolio.csv',
                'data/portfolio.csv'
            ]
            
            for pattern in portfolio_paths:
                portfolio_files.extend(glob.glob(pattern))
            
            for file_path in portfolio_files:
                try:
                    df = pd.read_csv(file_path)
                    if 'Ticker' in df.columns and 'Currency' in df.columns:
                        # Get the latest entry for each ticker
                        latest_entries = df.groupby('Ticker').last()
                        for ticker, row in latest_entries.iterrows():
                            # Only add if not already present (trade log takes precedence)
                            if ticker not in self._portfolio_currency_cache:
                                currency = row['Currency']
                                self._portfolio_currency_cache[ticker] = currency
                                
                                # Handle ticker variants for smart lookup
                                if ticker.endswith('.TO'):
                                    base_ticker = ticker[:-3]
                                    if base_ticker not in self._portfolio_currency_cache:
                                        self._portfolio_currency_cache[base_ticker] = currency
                                elif ticker.endswith('.V'):
                                    base_ticker = ticker[:-2]
                                    if base_ticker not in self._portfolio_currency_cache:
                                        self._portfolio_currency_cache[base_ticker] = currency
                                elif currency == 'CAD' and not ticker.endswith(('.TO', '.V', '.CN')):
                                    to_variant = f"{ticker}.TO"
                                    if to_variant not in self._portfolio_currency_cache:
                                        self._portfolio_currency_cache[to_variant] = currency
                        
                        logger.debug(f"Supplemented currency cache from portfolio {file_path}: {len([t for t in latest_entries.index if t not in self._portfolio_currency_cache])} new tickers")
                except Exception as e:
                    logger.debug(f"Could not load currency cache from portfolio {file_path}: {e}")
            
            # Load from Supabase if available (source of truth in Supabase mode)
            try:
                if os.getenv("SUPABASE_URL"):  # Only try if Supabase is configured
                    from web_dashboard.supabase_client import SupabaseClient
                    client = SupabaseClient(use_service_role=True)  # Bypass RLS for background jobs
                    trades = client.supabase.table("trade_log")\
                        .select("ticker, currency")\
                        .execute()
                    
                    supabase_count = 0
                    for trade in trades.data:
                        ticker = trade['ticker'].upper()
                        currency = trade.get('currency', 'USD').upper()
                        # Add or override (Supabase takes precedence if both exist)
                        self._portfolio_currency_cache[ticker] = currency
                        supabase_count += 1
                        
                        # Handle ticker variants for smart lookup (same logic as CSV loading)
                        # If ticker has .TO/.V suffix, also cache the base ticker
                        if ticker.endswith('.TO'):
                            base_ticker = ticker[:-3]  # Remove .TO
                            if base_ticker not in self._portfolio_currency_cache:
                                self._portfolio_currency_cache[base_ticker] = currency
                                logger.debug(f"Mapped base ticker {base_ticker} -> {currency} from {ticker}")
                        elif ticker.endswith('.V'):
                            base_ticker = ticker[:-2]  # Remove .V
                            if base_ticker not in self._portfolio_currency_cache:
                                self._portfolio_currency_cache[base_ticker] = currency
                                logger.debug(f"Mapped base ticker {base_ticker} -> {currency} from {ticker}")
                        # If base ticker is CAD, also try to map to .TO variant
                        elif currency == 'CAD' and not ticker.endswith(('.TO', '.V', '.CN')):
                            to_variant = f"{ticker}.TO"
                            if to_variant not in self._portfolio_currency_cache:
                                self._portfolio_currency_cache[to_variant] = currency
                                logger.debug(f"Mapped .TO variant {to_variant} -> {currency} from {ticker}")
                    
                    logger.debug(f"Loaded currency cache from Supabase: {supabase_count} tickers")
            except Exception as e:
                logger.debug(f"Could not load currency cache from Supabase: {e}")
                    
        except Exception as e:
            logger.warning(f"Could not load currency cache: {e}")
    
    def _convert_usd_to_cad(self, result: 'FetchResult') -> 'FetchResult':
        """Convert USD prices to CAD prices using current exchange rate."""
        try:
            import yfinance as yf
            from decimal import Decimal
            
            # Get current USD/CAD exchange rate
            usdcad = yf.Ticker('USDCAD=X')
            info = usdcad.info
            exchange_rate = info.get('regularMarketPrice', 1.38)  # Fallback to 1.38
            
            if exchange_rate and exchange_rate > 0:
                # Convert all price columns from USD to CAD
                price_columns = ['Open', 'High', 'Low', 'Close', 'Adj Close']
                converted_df = result.df.copy()
                
                for col in price_columns:
                    if col in converted_df.columns:
                        # Convert Decimal to float, multiply, then convert back to Decimal
                        converted_df[col] = converted_df[col].apply(lambda x: Decimal(str(float(x) * exchange_rate)))
                
                # Update source to indicate conversion
                new_source = f"{result.source} (USD→CAD @ {exchange_rate:.4f})"
                return FetchResult(converted_df, new_source)
            else:
                logger.warning("Could not get USD/CAD exchange rate, using original data")
                return result
                
        except Exception as e:
            logger.warning(f"Could not convert USD to CAD: {e}, using original data")
            return result
    
    def _load_fundamentals_overrides(self) -> None:
        """Load fundamentals overrides from JSON file to correct misleading API data."""
        try:
            # Look for overrides file in config directory
            project_root = Path(__file__).parent.parent
            overrides_path = project_root / "config" / "fundamentals_overrides.json"
            
            if not overrides_path.exists():
                logger.debug(f"Fundamentals overrides file not found: {overrides_path}")
                return
                
            import json
            with open(overrides_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Extract ticker overrides (skip metadata fields starting with _)
            for ticker, overrides in data.items():
                if not ticker.startswith('_'):
                    self._fundamentals_overrides[ticker.upper()] = overrides
                    
            logger.debug(f"Loaded fundamentals overrides for {len(self._fundamentals_overrides)} tickers")
            
        except Exception as e:
            logger.debug(f"Failed to load fundamentals overrides: {e}")
    
    def _apply_fundamentals_overrides(self, ticker_key: str, fundamentals: Dict[str, Any]) -> Dict[str, Any]:
        """Apply overrides to fundamentals data if they exist for the ticker.
        
        Args:
            ticker_key: Uppercase ticker symbol
            fundamentals: Base fundamentals data from API
            
        Returns:
            Fundamentals data with overrides applied
        """
        overrides = self._fundamentals_overrides.get(ticker_key)
        if not overrides:
            return fundamentals
            
        # Create a copy to avoid modifying the original
        result = fundamentals.copy()
        
        # Apply each override field
        for field, value in overrides.items():
            # Skip metadata fields  
            if field.startswith('_') or field == 'description_note':
                continue
                
            # Apply the override value
            result[field] = str(value) if value is not None else 'N/A'
            
        logger.debug(f"Applied {len([k for k in overrides.keys() if not k.startswith('_') and k != 'description_note'])} overrides for {ticker_key}")
        return result
    
    def fetch_price_data(
        self,
        ticker: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        period: str = "1d",
        **kwargs: Any
    ) -> FetchResult:
        """
        Fetch OHLCV data with robust fallback logic and retry mechanisms.

        Args:
            ticker: Stock ticker symbol
            start: Start date for data fetch
            end: End date for data fetch
            period: Period for data (default "1d")
            **kwargs: Additional arguments passed to yfinance

        Returns:
            FetchResult with DataFrame and source information
        """
        # Check cache first if available
        if self.cache:
            cached_data = self.cache.get_cached_price(ticker, start, end)
            if cached_data is not None:
                return FetchResult(cached_data, "cache")

        # Determine date range
        start_date, end_date = self._weekend_safe_range(period, start, end)

        # Try multiple fetch strategies with retries
        # Smart strategy selection based on ticker characteristics
        fetch_strategies = []
        
        # Check if this is a Canadian ticker based on currency in portfolio data
        is_likely_canadian = ticker.endswith(('.TO', '.V', '.CN'))  # Already has Canadian suffix
        
        # If no suffix, check if we have currency info from portfolio
        if not is_likely_canadian and hasattr(self, '_portfolio_currency_cache'):
            currency = self._portfolio_currency_cache.get(ticker.upper())
            if currency == 'CAD':
                is_likely_canadian = True
                logger.debug(f"Detected Canadian ticker from portfolio cache: {ticker} (Currency: {currency})")
            elif currency == 'USD':
                is_likely_canadian = False
        
        # If still no currency info, check fundamentals overrides for Canadian securities
        if not is_likely_canadian and hasattr(self, '_fundamentals_overrides'):
            override_data = self._fundamentals_overrides.get(ticker.upper())
            if override_data:
                country = override_data.get('country', '').upper()
                # Consider Canadian if country is Canada or if it's a Canadian-listed ETF
                if country == 'CANADA' or 'CANADIAN' in override_data.get('industry', '').upper():
                    is_likely_canadian = True
        
        if is_likely_canadian:
            # For likely Canadian tickers, try Canadian suffixes first
            # But don't add suffixes if ticker already has them
            if ticker.endswith(('.TO', '.V', '.CN')):
                # Ticker already has Canadian suffix, use as-is
                fetch_strategies = [
                    ("yahoo", lambda: self._fetch_yahoo_data(ticker, start_date, end_date, **kwargs)),
                    ("stooq-pdr", lambda: self._fetch_stooq_pdr(ticker, start_date, end_date)),
                    ("stooq-csv", lambda: self._fetch_stooq_csv(ticker, start_date, end_date)),
                    ("yahoo-retry-period", lambda: self._fetch_yahoo_data_retry_period(ticker, period)),
                    ("yahoo-retry-simple", lambda: self._fetch_yahoo_data_retry_simple(ticker)),
                    ("yahoo-proxy", lambda: self._fetch_proxy_data(ticker, start_date, end_date, **kwargs)),
                ]
            else:
                # Ticker doesn't have suffix, try adding Canadian suffixes
                fetch_strategies = [
                    ("yahoo-ca-to", lambda: self._fetch_yahoo_data(f"{ticker}.TO", start_date, end_date, **kwargs)),
                    ("yahoo-ca-v", lambda: self._fetch_yahoo_data(f"{ticker}.V", start_date, end_date, **kwargs)),
                    ("yahoo", lambda: self._fetch_yahoo_data(ticker, start_date, end_date, **kwargs)),
                    ("stooq-pdr", lambda: self._fetch_stooq_pdr(ticker, start_date, end_date)),
                    ("stooq-csv", lambda: self._fetch_stooq_csv(ticker, start_date, end_date)),
                    ("yahoo-retry-period", lambda: self._fetch_yahoo_data_retry_period(ticker, period)),
                    ("yahoo-retry-simple", lambda: self._fetch_yahoo_data_retry_simple(ticker)),
                    ("yahoo-proxy", lambda: self._fetch_proxy_data(ticker, start_date, end_date, **kwargs)),
                ]
        else:
            # For likely US tickers, try US first, then Canadian as fallback
            # But don't add suffixes if ticker already has them
            if ticker.endswith(('.TO', '.V', '.CN')):
                # Ticker already has Canadian suffix, use as-is
                fetch_strategies = [
                    ("yahoo", lambda: self._fetch_yahoo_data(ticker, start_date, end_date, **kwargs)),
                    ("stooq-pdr", lambda: self._fetch_stooq_pdr(ticker, start_date, end_date)),
                    ("stooq-csv", lambda: self._fetch_stooq_csv(ticker, start_date, end_date)),
                    ("yahoo-retry-period", lambda: self._fetch_yahoo_data_retry_period(ticker, period)),
                    ("yahoo-retry-simple", lambda: self._fetch_yahoo_data_retry_simple(ticker)),
                    ("yahoo-proxy", lambda: self._fetch_proxy_data(ticker, start_date, end_date, **kwargs)),
                ]
            else:
                # Ticker doesn't have suffix - check if we know it's USD
                # CRITICAL FIX: Don't try Canadian variants for known USD tickers!
                # This prevents fetching wrong data (e.g., DG.TO is a different stock than DG)
                is_known_usd = False
                if hasattr(self, '_portfolio_currency_cache'):
                    currency = self._portfolio_currency_cache.get(ticker.upper())
                    if currency == 'USD':
                        is_known_usd = True
                        logger.debug(f"Skipping Canadian variants for known USD ticker: {ticker}")
                
                if is_known_usd:
                    # Known USD ticker - don't try Canadian variants (they're different stocks!)
                    fetch_strategies = [
                        ("yahoo", lambda: self._fetch_yahoo_data(ticker, start_date, end_date, **kwargs)),
                        ("stooq-pdr", lambda: self._fetch_stooq_pdr(ticker, start_date, end_date)),
                        ("stooq-csv", lambda: self._fetch_stooq_csv(ticker, start_date, end_date)),
                        ("yahoo-retry-period", lambda: self._fetch_yahoo_data_retry_period(ticker, period)),
                        ("yahoo-retry-simple", lambda: self._fetch_yahoo_data_retry_simple(ticker)),
                        ("yahoo-proxy", lambda: self._fetch_proxy_data(ticker, start_date, end_date, **kwargs)),
                    ]
                else:
                    # Unknown currency - try US first then Canadian fallback (for ambiguous cases)
                    fetch_strategies = [
                        ("yahoo", lambda: self._fetch_yahoo_data(ticker, start_date, end_date, **kwargs)),
                        ("stooq-pdr", lambda: self._fetch_stooq_pdr(ticker, start_date, end_date)),
                        ("stooq-csv", lambda: self._fetch_stooq_csv(ticker, start_date, end_date)),
                        ("yahoo-ca-to", lambda: self._fetch_yahoo_data(f"{ticker}.TO", start_date, end_date, **kwargs)),
                        ("yahoo-ca-v", lambda: self._fetch_yahoo_data(f"{ticker}.V", start_date, end_date, **kwargs)),
                        ("yahoo-retry-period", lambda: self._fetch_yahoo_data_retry_period(ticker, period)),
                        ("yahoo-retry-simple", lambda: self._fetch_yahoo_data_retry_simple(ticker)),
                        ("yahoo-proxy", lambda: self._fetch_proxy_data(ticker, start_date, end_date, **kwargs)),
                    ]

        successful_strategy = None
        failed_strategies = []
        
        for strategy_name, fetch_func in fetch_strategies:
            try:
                result = fetch_func()
                if not result.df.empty:
                    # Update source to indicate which strategy worked
                    result = FetchResult(result.df, f"{result.source} ({strategy_name})")
                    self._cache_result(ticker, result)
                    successful_strategy = strategy_name
                    
                    # If we found data using a Canadian suffix, update CSVs to use canonical format
                    self._normalize_ticker_in_csvs(ticker, strategy_name)
                    
                    break
            except Exception as e:
                failed_strategies.append(strategy_name)
                continue

            # Log a summary instead of individual errors
        if successful_strategy:
            if len(failed_strategies) > 0:
                # Provide clear user-visible information about fallbacks
                fallback_msg = f"{ticker}: {', '.join(failed_strategies)} failed, using {successful_strategy}"
                logger.info(fallback_msg)

                # Also provide more detailed technical info at debug level
                if successful_strategy == 'yahoo-retry':
                    logger.debug(f"{ticker}: Yahoo Finance returned 'possibly delisted' warning, but retry with simplified parameters succeeded")
                elif successful_strategy == 'yahoo-period':
                    logger.debug(f"{ticker}: Yahoo Finance with date range failed, but period-based fetch succeeded")
                elif successful_strategy == 'yahoo-simple':
                    logger.debug(f"{ticker}: Yahoo Finance with full parameters failed, but minimal 5-day fetch succeeded")
                elif successful_strategy.startswith('yahoo:'):
                    logger.debug(f"{ticker}: Using proxy ticker {successful_strategy} instead of original ticker")
                elif successful_strategy.startswith('stooq'):
                    logger.debug(f"{ticker}: Yahoo Finance failed, successfully fell back to Stooq data source")
            else:
                logger.debug(f"{ticker}: Successfully fetched from primary source {successful_strategy}")

            # Note: Canadian stocks (.TO, .V, .CN) already return CAD prices from Canadian exchanges
            # Only convert if we're getting US data for Canadian tickers (fallback case)
            if hasattr(self, '_portfolio_currency_cache'):
                currency = self._portfolio_currency_cache.get(ticker)
                # Don't convert if ticker already has Canadian suffix (.TO, .V, .CN) - these are already in CAD
                if currency == 'CAD' and not successful_strategy.startswith('yahoo-ca') and not ticker.endswith(('.TO', '.V', '.CN')):
                    # Only convert if we got data from US exchange, not Canadian, and ticker doesn't have Canadian suffix
                    result = self._convert_usd_to_cad(result)

            return result
        else:
            logger.error(f"{ticker}: All strategies failed ({', '.join(failed_strategies)})")
            return FetchResult(pd.DataFrame(), "failed")
    
    def _weekend_safe_range(
        self,
        period: str,
        start: Optional[datetime],
        end: Optional[datetime]
    ) -> tuple[pd.Timestamp, pd.Timestamp]:
        """
        Calculate weekend-safe date range for data fetching.
        
        Args:
            period: Period string (e.g., "1d", "5d")
            start: Optional start date
            end: Optional end date
            
        Returns:
            Tuple of (start_timestamp, end_timestamp)
        """
        if start and end:
            return pd.Timestamp(start), pd.Timestamp(end)
            
        # Default to recent trading days
        now = pd.Timestamp.now()
        
        # Map period to days
        period_days = {
            "1d": 1, "5d": 5, "1mo": 30, "3mo": 90,
            "6mo": 180, "1y": 365, "2y": 730, "5y": 1825
        }
        
        days = period_days.get(period, 5)
        start_ts = now - timedelta(days=days + 10)  # Extra buffer for weekends
        end_ts = now + timedelta(days=1)  # Include today
        
        return start_ts, end_ts
    
    def _fetch_yahoo_data(
        self,
        ticker: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
        **kwargs: Any
    ) -> FetchResult:
        """Fetch data from Yahoo Finance via yfinance."""
        try:
            import yfinance as yf

            # Suppress yfinance warnings and provide our own clear messaging
            yf_logger = logging.getLogger("yfinance")
            original_level = yf_logger.level
            yf_logger.setLevel(logging.ERROR)

            try:
                # Use Ticker.history() instead of yf.download() for single ticker
                ticker_obj = yf.Ticker(ticker)
                df = ticker_obj.history(
                    start=start,
                    end=end,
                    **kwargs
                )

                if isinstance(df, pd.DataFrame) and not df.empty:
                    # Remove extra columns that aren't OHLCV
                    ohlcv_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
                    df = df[ohlcv_columns]
                    df = self._normalize_ohlcv(self._to_datetime_index(df))
                    return FetchResult(df, "yahoo")
            finally:
                # Restore original logging level
                yf_logger.setLevel(original_level)

        except Exception as e:
            error_msg = str(e).lower()
            # Don't treat "possibly delisted" as a hard failure for ETFs and known tickers
            # These are often false positives from yfinance
            if ("possibly delisted" in error_msg and
                ("no timezone found" in error_msg or "no price data found" in error_msg)):
                # Try a simpler approach - just get recent data without date range
                try:
                    logger.info(f"{ticker}: Yahoo Finance reported 'possibly delisted' - retrying with simplified parameters")
                    import yfinance as yf
                    ticker_obj = yf.Ticker(ticker)
                    # Try with just period instead of explicit dates
                    df = ticker_obj.history(period="5d")

                    if isinstance(df, pd.DataFrame) and not df.empty:
                        ohlcv_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
                        df = df[ohlcv_columns]
                        df = self._normalize_ohlcv(self._to_datetime_index(df))
                        logger.info(f"{ticker}: Successfully retrieved price data via fallback method")
                        return FetchResult(df, "yahoo-retry")
                    else:
                        logger.warning(f"{ticker}: Fallback method also returned no data")
                except Exception as retry_e:
                    logger.warning(f"{ticker}: Both primary and fallback methods failed")

            logger.debug(f"Yahoo fetch failed for {ticker}: {e}")

        return FetchResult(pd.DataFrame(), "empty")

    def _fetch_yahoo_data_retry_period(self, ticker: str, period: str) -> FetchResult:
        """Retry Yahoo Finance fetch using period instead of date range."""
        try:
            import yfinance as yf

            # Suppress yfinance warnings and provide our own clear messaging
            yf_logger = logging.getLogger("yfinance")
            original_level = yf_logger.level
            yf_logger.setLevel(logging.ERROR)

            try:
                ticker_obj = yf.Ticker(ticker)
                df = ticker_obj.history(period=period)

                if isinstance(df, pd.DataFrame) and not df.empty:
                    ohlcv_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
                    df = df[ohlcv_columns]
                    df = self._normalize_ohlcv(self._to_datetime_index(df))
                    logger.info(f"{ticker}: Successfully retrieved price data using period-based approach")
                    return FetchResult(df, "yahoo-period")
            finally:
                # Restore original logging level
                yf_logger.setLevel(original_level)

        except Exception as e:
            logger.debug(f"Yahoo period retry failed for {ticker}: {e}")

        return FetchResult(pd.DataFrame(), "empty")

    def _fetch_yahoo_data_retry_simple(self, ticker: str) -> FetchResult:
        """Retry Yahoo Finance fetch with minimal parameters."""
        try:
            import yfinance as yf

            # Suppress yfinance warnings and provide our own clear messaging
            yf_logger = logging.getLogger("yfinance")
            original_level = yf_logger.level
            yf_logger.setLevel(logging.ERROR)

            try:
                ticker_obj = yf.Ticker(ticker)
                # Try with just 5 days of data, no other parameters
                df = ticker_obj.history(period="5d", interval="1d")

                if isinstance(df, pd.DataFrame) and not df.empty:
                    ohlcv_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
                    df = df[ohlcv_columns]
                    df = self._normalize_ohlcv(self._to_datetime_index(df))
                    logger.info(f"{ticker}: Successfully retrieved price data using minimal parameters approach")
                    return FetchResult(df, "yahoo-simple")
            finally:
                # Restore original logging level
                yf_logger.setLevel(original_level)

        except Exception as e:
            logger.debug(f"Yahoo simple retry failed for {ticker}: {e}")

        return FetchResult(pd.DataFrame(), "empty")

    def _fetch_stooq_pdr(
        self,
        ticker: str,
        start: pd.Timestamp,
        end: pd.Timestamp
    ) -> FetchResult:
        """Fetch data from Stooq via pandas-datareader."""
        if not _HAS_PDR or ticker in STOOQ_BLOCKLIST:
            return FetchResult(pd.DataFrame(), "empty")

        try:
            # Map ticker for Stooq
            stooq_ticker = STOOQ_MAP.get(ticker, ticker)
            if not stooq_ticker.startswith("^"):
                stooq_ticker = stooq_ticker.lower()
                # Handle Canadian tickers (.TO suffix) - keep as is for Stooq
                if not stooq_ticker.endswith(".to") and not stooq_ticker.endswith(".us"):
                    # Default to .us for US tickers if no suffix
                    stooq_ticker += ".us"

            df = cast(pd.DataFrame, pdr.DataReader(
                stooq_ticker, "stooq", start=start, end=end
            ))

            if isinstance(df, pd.DataFrame) and not df.empty:
                df.sort_index(inplace=True)
                df = self._normalize_ohlcv(self._to_datetime_index(df))
                logger.info(f"{ticker}: Successfully retrieved price data from Stooq (pandas-datareader)")
                return FetchResult(df, "stooq-pdr")

        except Exception as e:
            logger.debug(f"Stooq PDR fetch failed for {ticker}: {e}")

        return FetchResult(pd.DataFrame(), "empty")
    
    def _fetch_stooq_csv(
        self,
        ticker: str,
        start: pd.Timestamp,
        end: pd.Timestamp
    ) -> FetchResult:
        """Fetch data from Stooq CSV endpoint."""
        if ticker in STOOQ_BLOCKLIST:
            return FetchResult(pd.DataFrame(), "empty")
            
        try:
            import requests
            import io
            
            # Map ticker for Stooq
            stooq_ticker = STOOQ_MAP.get(ticker, ticker)
            
            # Stooq daily CSV: lowercase; handle different exchanges
            if not stooq_ticker.startswith("^"):
                sym = stooq_ticker.lower()
            else:
                sym = stooq_ticker.lower()
            
            url = f"https://stooq.com/q/d/l/?s={sym}&i=d"
            
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            # Parse CSV
            df = pd.read_csv(io.StringIO(response.text))
            df["Date"] = pd.to_datetime(df["Date"])
            df.set_index("Date", inplace=True)
            df.sort_index(inplace=True)
            
            # Filter to [start, end) (Stooq end is exclusive)
            df = df.loc[(df.index >= start.normalize()) & (df.index < end.normalize())]
            
            # Normalize to Yahoo-like schema
            if "Adj Close" not in df.columns:
                df["Adj Close"] = df["Close"]
                
            if not df.empty:
                df = self._normalize_ohlcv(df)
                logger.info(f"{ticker}: Successfully retrieved price data from Stooq (CSV endpoint)")
                return FetchResult(df, "stooq-csv")

        except Exception as e:
            logger.debug(f"Stooq CSV fetch failed for {ticker}: {e}")

        return FetchResult(pd.DataFrame(), "empty")
    
    def _fetch_proxy_data(
        self,
        ticker: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
        **kwargs: Any
    ) -> FetchResult:
        """Fetch data using proxy ticker (e.g., ^GSPC -> SPY)."""
        proxy = self.proxy_map.get(ticker)
        if not proxy:
            return FetchResult(pd.DataFrame(), "empty")
            
        try:
            result = self._fetch_yahoo_data(proxy, start, end, **kwargs)
            if not result.df.empty:
                logger.info(f"{ticker}: Successfully retrieved price data using proxy ticker {proxy}")
                return FetchResult(result.df, f"yahoo:{proxy}-proxy")

        except Exception as e:
            logger.debug(f"Proxy fetch failed for {ticker} -> {proxy}: {e}")

        return FetchResult(pd.DataFrame(), "empty")
    
    def _to_datetime_index(self, df: pd.DataFrame) -> pd.DataFrame:
        """Convert DataFrame index to datetime if needed."""
        if not isinstance(df.index, pd.DatetimeIndex):
            if "Date" in df.columns:
                df["Date"] = pd.to_datetime(df["Date"])
                df.set_index("Date", inplace=True)
            else:
                df.index = pd.to_datetime(df.index)
        return df
    
    def _normalize_ohlcv(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize OHLCV DataFrame to standard format with Decimal conversion."""
        from decimal import Decimal
        
        # Flatten multiIndex frame so we can lazily lookup values by index.
        if isinstance(df.columns, pd.MultiIndex):
            try:
                # If the second level is the same ticker for all cols, drop it     
                if len(set(df.columns.get_level_values(1))) == 1:
                    df = df.copy()
                    df.columns = df.columns.get_level_values(0)
                else:
                    # multiple tickers: flatten with join
                    df = df.copy()
                    df.columns = ["_".join(map(str, t)).strip("_") for t in df.columns.to_flat_index()]
            except Exception:
                df = df.copy()
                df.columns = ["_".join(map(str, t)).strip("_") for t in df.columns.to_flat_index()]
        
        # Ensure required columns exist
        required_cols = ["Open", "High", "Low", "Close", "Volume"]
        existing_cols = [col for col in required_cols if col in df.columns]
        
        # If we have flattened multi-ticker columns, we can't process them with standard OHLCV logic
        # This typically happens when yfinance returns data for multiple tickers at once
        # In this case, we should return an empty DataFrame as this function expects single-ticker data
        if not existing_cols and any("_" in col for col in df.columns):
            logger.debug("Multi-ticker DataFrame detected, returning empty DataFrame (single-ticker expected)")
            return pd.DataFrame()
        
        # Add Adj Close if missing
        if "Adj Close" not in df.columns and "Close" in df.columns:
            df["Adj Close"] = df["Close"]
            
        # Return only the columns we need
        cols = existing_cols + (["Adj Close"] if "Adj Close" in df.columns else [])
        result_df = df[cols].copy()
        
        # Convert all price columns to Decimal for precision
        price_cols = [col for col in cols if col != "Volume"]
        for col in price_cols:
            if col in result_df.columns:
                # Convert float to Decimal string to avoid precision errors
                result_df[col] = result_df[col].apply(
                    lambda x: Decimal(str(round(x, 6))) if pd.notna(x) and x != 0 else Decimal('0')
                )
        
        # Volume stays as int/float since it's not monetary
        return result_df
    
    def _cache_result(self, ticker: str, result: FetchResult) -> None:
        """Cache the fetch result if cache is available."""
        if self.cache and not result.df.empty:
            self.cache.cache_price_data(ticker, result.df, result.source)
    
    def _normalize_ticker_in_csvs(self, original_ticker: str, successful_strategy: str) -> None:
        """Update CSVs to use canonical ticker format when we discover the correct suffix.
        
        Args:
            original_ticker: The ticker as it appears in CSV (e.g., 'CGL')
            successful_strategy: The strategy that worked (e.g., 'yahoo-ca-to')
        """
        # Determine the canonical ticker format based on successful strategy
        canonical_ticker = None
        
        if successful_strategy == 'yahoo-ca-to':
            canonical_ticker = f"{original_ticker}.TO"
        elif successful_strategy == 'yahoo-ca-v':
            canonical_ticker = f"{original_ticker}.V"
        else:
            # No normalization needed for other strategies
            return
        
        if canonical_ticker == original_ticker:
            # Already in canonical format
            return
        
        try:
            import pandas as pd
            import glob
            from datetime import datetime
            import shutil
            
            logger.info(f"Normalizing ticker {original_ticker} -> {canonical_ticker} in CSV files")
            
            # Update portfolio files
            portfolio_files = glob.glob('trading_data/funds/*/llm_portfolio_update.csv')
            for file_path in portfolio_files:
                try:
                    df = pd.read_csv(file_path)
                    if 'Ticker' in df.columns:
                        # Check if this ticker needs updating
                        ticker_mask = df['Ticker'] == original_ticker
                        if ticker_mask.any():
                            # Create backup
                            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                            backup_file = f"{file_path}.backup_normalize_{timestamp}"
                            shutil.copy2(file_path, backup_file)
                            
                            # Update ticker format
                            df.loc[ticker_mask, 'Ticker'] = canonical_ticker
                            
                            # Save updated file
                            df.to_csv(file_path, index=False)
                            logger.debug(f"Updated {ticker_mask.sum()} entries in {file_path}")
                            
                            # Update currency cache with canonical format
                            currency = self._portfolio_currency_cache.get(original_ticker)
                            if currency:
                                self._portfolio_currency_cache[canonical_ticker] = currency
                                logger.debug(f"Updated currency cache: {canonical_ticker} -> {currency}")
                            
                except Exception as e:
                    logger.warning(f"Failed to normalize ticker in portfolio {file_path}: {e}")
            
            # Update trade log files
            trade_log_files = glob.glob('trading_data/funds/*/llm_trade_log.csv')
            for file_path in trade_log_files:
                try:
                    df = pd.read_csv(file_path)
                    if 'Ticker' in df.columns:
                        # Check if this ticker needs updating
                        ticker_mask = df['Ticker'] == original_ticker
                        if ticker_mask.any():
                            # Create backup
                            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                            backup_file = f"{file_path}.backup_normalize_{timestamp}"
                            shutil.copy2(file_path, backup_file)
                            
                            # Update ticker format
                            df.loc[ticker_mask, 'Ticker'] = canonical_ticker
                            
                            # Save updated file
                            df.to_csv(file_path, index=False)
                            logger.debug(f"Updated {ticker_mask.sum()} entries in trade log {file_path}")
                            
                except Exception as e:
                    logger.warning(f"Failed to normalize ticker in trade log {file_path}: {e}")
            
        except Exception as e:
            logger.error(f"Failed to normalize ticker {original_ticker} -> {canonical_ticker}: {e}")
    
    # -------------------- Fundamentals cache persistence --------------------
    def _get_fund_cache_path(self) -> Optional[Path]:
        """Determine the cache file path for fundamentals."""
        try:
            if self.cache and getattr(self.cache, 'settings', None):
                data_dir = self.cache.settings.get_data_directory()
                cache_dir = Path(data_dir) / ".cache"
            elif getattr(self, 'settings', None):
                data_dir = self.settings.get_data_directory()
                cache_dir = Path(data_dir) / ".cache"
            else:
                # Fallback to current working directory .cache
                cache_dir = Path.cwd() / ".cache"
            cache_dir.mkdir(exist_ok=True)
            return cache_dir / "fundamentals_cache.json"
        except Exception:
            return None
    
    def _load_fundamentals_cache(self) -> None:
        """Load fundamentals cache from disk if available."""
        path = self._get_fund_cache_path()
        if not path or not path.exists():
            return
        import json
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            entries: Dict[str, Dict[str, Any]] = data.get('entries', {})
            ttl_minutes: int = data.get('default_ttl_minutes', int(self._fund_cache_ttl.total_minutes()) if hasattr(self._fund_cache_ttl, 'total_minutes') else int(self._fund_cache_ttl.total_seconds() // 60))
            default_ttl = timedelta(minutes=ttl_minutes)
            for ticker_key, payload in entries.items():
                fund = payload.get('data', {})
                ts_str = payload.get('ts')
                ttl_min = payload.get('ttl_minutes', ttl_minutes)
                try:
                    ts = datetime.fromisoformat(ts_str) if ts_str else None
                except Exception:
                    ts = None
                # Skip expired entries
                if ts and (datetime.now() - ts) < timedelta(minutes=ttl_min):
                    self._fund_cache[ticker_key] = fund
                    self._fund_cache_meta[ticker_key] = {
                        'ts': ts,
                        'ttl': timedelta(minutes=ttl_min) if ttl_min else default_ttl
                    }
        except Exception as e:
            logging.getLogger(__name__).debug(f"Failed to load fundamentals cache: {e}")
    
    def _save_fundamentals_cache(self) -> None:
        """Save fundamentals cache to disk."""
        path = self._get_fund_cache_path()
        if not path:
            return
        import json
        try:
            # Build serializable structure
            entries: Dict[str, Any] = {}
            for ticker_key, fund in self._fund_cache.items():
                meta = self._fund_cache_meta.get(ticker_key, {})
                ts = meta.get('ts')
                ttl = meta.get('ttl', self._fund_cache_ttl)
                entries[ticker_key] = {
                    'data': fund,
                    'ts': ts.isoformat() if isinstance(ts, datetime) else None,
                    'ttl_minutes': int(ttl.total_seconds() // 60) if isinstance(ttl, timedelta) else int(self._fund_cache_ttl.total_seconds() // 60)
                }
            payload = {
                'entries': entries,
                'default_ttl_minutes': int(self._fund_cache_ttl.total_seconds() // 60)
            }
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            logging.getLogger(__name__).debug(f"Failed to save fundamentals cache: {e}")
    
    def fetch_fundamentals(self, ticker: str) -> Dict[str, Any]:
        """Fetch fundamental data for a ticker using yfinance with TTL cache.
        
        Returns:
            Dict with keys: sector, industry, country, marketCap, trailingPE, 
            dividendYield, fiftyTwoWeekHigh, fiftyTwoWeekLow, or "N/A" if unavailable
        """
        ticker_key = ticker.upper().strip()
        
        # Check in-memory TTL cache first
        meta = self._fund_cache_meta.get(ticker_key)
        if meta:
            ts: datetime = meta.get('ts')
            ttl: timedelta = meta.get('ttl', self._fund_cache_ttl)
            if ts and (datetime.now() - ts) < ttl:
                cached = self._fund_cache.get(ticker_key)
                if cached:
                    # Apply overrides to cached data before returning
                    return self._apply_fundamentals_overrides(ticker_key, cached)
            else:
                # Expired
                self._fund_cache.pop(ticker_key, None)
                self._fund_cache_meta.pop(ticker_key, None)
        
        fundamentals = {
            'sector': 'N/A',
            'industry': 'N/A', 
            'country': 'N/A',
            'marketCap': 'N/A',
            'trailingPE': 'N/A',
            'dividendYield': 'N/A',
            'fiftyTwoWeekHigh': 'N/A',
            'fiftyTwoWeekLow': 'N/A'
        }
        
        try:
            import yfinance as yf
            
            # Reduce yfinance noise but keep ERROR level for real failures
            logging.getLogger("yfinance").setLevel(logging.ERROR)
            
            ticker_obj = yf.Ticker(ticker)
            
            # Try new get_info() first, fallback to .info for compatibility
            info = {}
            try:
                get_info = getattr(ticker_obj, 'get_info', None)
                if callable(get_info):
                    info = get_info() or {}
            except Exception:
                info = {}
            if not info:
                try:
                    info = ticker_obj.info or {}
                except Exception:
                    info = {}
            
            # fast_info for performant fields
            try:
                finfo = getattr(ticker_obj, 'fast_info', None)
            except Exception:
                finfo = None
            finfo = finfo or {}
            
            # Current price (for computed dividend yield)
            price = None
            try:
                price = finfo.get('last_price')
            except Exception:
                price = None
            if not price:
                # Fallback to recent close
                try:
                    pr = self.fetch_price_data(ticker, period='5d')
                    if not pr.df.empty and 'Close' in pr.df.columns:
                        # Price is now Decimal from _normalize_ohlcv, convert to float for display only
                        price = float(pr.df['Close'].iloc[-1])
                except Exception:
                    price = None
            
            # Extract available fields with fallbacks
            fundamentals['sector'] = info.get('sector', 'N/A') or 'N/A'
            fundamentals['industry'] = info.get('industry', 'N/A') or 'N/A'
            fundamentals['country'] = info.get('country', 'N/A') or 'N/A'
            
            # Market cap with formatting - check for ETF first
            company_name = info.get('longName', ticker) or ticker
            market_cap = info.get('marketCap')
            if 'ETF' in company_name.upper():
                fundamentals['marketCap'] = 'ETF'
            else:
                if not market_cap and finfo:
                    market_cap = finfo.get('market_cap')
                if market_cap and isinstance(market_cap, (int, float)) and market_cap > 0:
                    if market_cap >= 1e9:
                        fundamentals['marketCap'] = f"${market_cap/1e9:.2f}B"
                    elif market_cap >= 1e6:
                        fundamentals['marketCap'] = f"${market_cap/1e6:.1f}M"
                    else:
                        fundamentals['marketCap'] = f"${market_cap:,.0f}"
            
            # P/E ratio
            pe_ratio = info.get('trailingPE')
            if not pe_ratio and finfo:
                pe_ratio = finfo.get('trailing_pe')
            if pe_ratio and isinstance(pe_ratio, (int, float)) and pe_ratio > 0:
                fundamentals['trailingPE'] = f"{pe_ratio:.1f}"
                
            # Dividend yield (prefer computed from last 365 days of dividends)
            computed_yield = None
            try:
                div_series = ticker_obj.dividends
                if div_series is not None and not div_series.empty and price and price > 0:
                    recent = div_series[div_series.index >= pd.Timestamp.now() - pd.Timedelta(days=365)]
                    if not recent.empty:
                        annual_div = float(recent.sum())
                        if annual_div > 0:
                            computed_yield = (annual_div / float(price)) * 100.0
            except Exception:
                computed_yield = None
            
            if computed_yield is not None:
                fundamentals['dividendYield'] = f"{computed_yield:.1f}%"
            else:
                # Normalize possibly inconsistent API fields
                div_yield = info.get('dividendYield')
                if not div_yield:
                    div_yield = info.get('trailingAnnualDividendYield')
                if div_yield and isinstance(div_yield, (int, float)) and div_yield > 0:
                    if div_yield > 1.0:
                        # Assume already percent
                        fundamentals['dividendYield'] = f"{div_yield:.1f}%"
                    else:
                        fundamentals['dividendYield'] = f"{div_yield*100:.1f}%"
            
            # 52-week high/low
            high_52w = info.get('fiftyTwoWeekHigh')
            low_52w = info.get('fiftyTwoWeekLow')
            # Try fast_info names
            if not high_52w and finfo:
                high_52w = finfo.get('year_high') or finfo.get('fifty_two_week_high')
            if not low_52w and finfo:
                low_52w = finfo.get('year_low') or finfo.get('fifty_two_week_low')
            
            # As a final fallback, compute from last ~1y of history
            if (not high_52w or not low_52w):
                try:
                    hist = self.fetch_price_data(ticker, period='1y')
                    if not hist.df.empty:
                        if not high_52w and 'High' in hist.df.columns:
                            # High/Low are now Decimals from _normalize_ohlcv, convert to float for display only
                            high_52w = float(hist.df['High'].max())
                        if not low_52w and 'Low' in hist.df.columns:
                            # High/Low are now Decimals from _normalize_ohlcv, convert to float for display only
                            low_52w = float(hist.df['Low'].min())
                except Exception:
                    pass
            
            if high_52w and isinstance(high_52w, (int, float)):
                fundamentals['fiftyTwoWeekHigh'] = f"${high_52w:.2f}"
            if low_52w and isinstance(low_52w, (int, float)):
                fundamentals['fiftyTwoWeekLow'] = f"${low_52w:.2f}"
                
            # Normalize country names and apply fallbacks
            country = fundamentals['country']
            if country and country != 'N/A':
                # Normalize common country names to shorter versions
                country_map = {
                    'United States': 'USA',
                    'United States of America': 'USA',
                    'US': 'USA',
                    'Canada': 'Canada',
                    'United Kingdom': 'UK',
                    'Great Britain': 'UK'
                }
                fundamentals['country'] = country_map.get(country, country)
            
            # Country fallback based on ticker suffix
            if fundamentals['country'] == 'N/A':
                if ticker.endswith(('.TO', '.V', '.CN')):
                    fundamentals['country'] = 'Canada'
                else:
                    fundamentals['country'] = 'USA'
                    
        except Exception as e:
            logger.debug(f"Fundamentals fetch failed for {ticker}: {e}")
            
        # Store in cache (even if partial) to avoid repeated calls in same run
        self._fund_cache[ticker_key] = fundamentals
        self._fund_cache_meta[ticker_key] = {
            'ts': datetime.now(),
            'ttl': self._fund_cache_ttl
        }
        
        # Persist to disk (best-effort)
        try:
            self._save_fundamentals_cache()
        except Exception as e:
            logging.getLogger(__name__).debug(f"Could not save fundamentals cache: {e}")
        
        # Apply overrides before returning
        return self._apply_fundamentals_overrides(ticker_key, fundamentals)
    
    def get_current_price(self, ticker: str, allow_after_hours: bool = False) -> Optional[Decimal]:
        """
        Get the current price for a ticker symbol with smart market close logic.
        
        When market is closed, this method efficiently uses cached market close prices
        instead of making expensive API calls for after-hours data.
        
        Args:
            ticker: Stock ticker symbol
            allow_after_hours: If True, fetch after-hours prices when market is closed.
                              If False (default), use cached market close prices.
            
        Returns:
            Current price as Decimal, or None if not available
        """
        try:
            # Check if market is open
            is_market_open = self.market_hours.is_market_open()
            
            if not is_market_open and not allow_after_hours:
                # Market is closed - try to use cached market close prices efficiently
                return self._get_market_close_price(ticker)
            else:
                # Market is open OR after-hours prices are requested
                return self._get_live_price(ticker)
            
        except Exception as e:
            logger.error(f"Error fetching current price for {ticker}: {e}")
            return None
    
    def _get_market_close_price(self, ticker: str) -> Optional[Decimal]:
        """
        Get market close price efficiently using cache when market is closed.
        
        This method tries to use cached data first, only fetching if necessary.
        Much more efficient than the old approach of always fetching 5 days of data.
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            Market close price as Decimal, or None if not available
        """
        try:
            # First, try to get cached data for the previous trading day
            if self.cache:
                # Get data for the last few days to find the most recent trading day
                cached_data = self.cache.get_cached_price(ticker)
                if cached_data is not None and not cached_data.empty:
                    # Get the most recent close price from cache
                    latest_close = cached_data['Close'].iloc[-1]
                    if not pd.isna(latest_close):
                        logger.debug(f"Using cached market close price for {ticker}: {latest_close}")
                        return Decimal(str(latest_close)).quantize(Decimal('0.01'))
            
            # If no cached data, fetch minimal data to get market close price
            # Only fetch 1 day to get the most recent close price
            result = self.fetch_price_data(ticker, period="1d")
            
            if result.df.empty:
                logger.warning(f"No market close price data available for {ticker}")
                return None
            
            # Get the most recent close price
            latest_close = result.df['Close'].iloc[-1]
            
            # Convert to Decimal for precision
            if pd.isna(latest_close):
                logger.warning(f"Latest close price is NaN for {ticker}")
                return None
                
            logger.debug(f"Fetched market close price for {ticker}: {latest_close}")
            return Decimal(str(latest_close)).quantize(Decimal('0.01'))
            
        except Exception as e:
            logger.error(f"Error fetching market close price for {ticker}: {e}")
            return None
    
    def _get_live_price(self, ticker: str) -> Optional[Decimal]:
        """
        Get live price data (for when market is open or after-hours is requested).
        
        This method tries to use cached data first, then fetches minimal data if needed.
        Much more efficient than always fetching 5 days of data.
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            Live price as Decimal, or None if not available
        """
        try:
            # First, try to get cached data
            if self.cache:
                cached_data = self.cache.get_cached_price(ticker)
                if cached_data is not None and not cached_data.empty:
                    # Get the most recent close price from cache
                    latest_close = cached_data['Close'].iloc[-1]
                    if not pd.isna(latest_close):
                        logger.debug(f"Using cached live price for {ticker}: {latest_close}")
                        return Decimal(str(latest_close)).quantize(Decimal('0.01'))
            
            # If no cached data or cache miss, fetch minimal data
            # Try 1 day first, then 2 days if needed (for weekend/holiday handling)
            for period in ["1d", "2d"]:
                result = self.fetch_price_data(ticker, period=period)
                
                if not result.df.empty:
                    # Get the most recent close price
                    latest_close = result.df['Close'].iloc[-1]
                    
                    # Convert to Decimal for precision
                    if pd.isna(latest_close):
                        logger.warning(f"Latest close price is NaN for {ticker}")
                        continue
                        
                    logger.debug(f"Fetched live price for {ticker} using {period}: {latest_close}")
                    return Decimal(str(latest_close)).quantize(Decimal('0.01'))
            
            # If 1d and 2d both fail, fall back to 5d as last resort
            logger.debug(f"Trying 5d fallback for {ticker}")
            result = self.fetch_price_data(ticker, period="5d")
            
            if result.df.empty:
                logger.warning(f"No price data available for {ticker}")
                return None
            
            # Get the most recent close price
            latest_close = result.df['Close'].iloc[-1]
            
            # Convert to Decimal for precision
            if pd.isna(latest_close):
                logger.warning(f"Latest close price is NaN for {ticker}")
                return None
                
            logger.debug(f"Fetched live price for {ticker} using 5d fallback: {latest_close}")
            return Decimal(str(latest_close)).quantize(Decimal('0.01'))
            
        except Exception as e:
            logger.error(f"Error fetching live price for {ticker}: {e}")
            return None