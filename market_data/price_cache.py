"""
In-memory price caching with persistence support.

This module provides the PriceCache class for caching market data in memory
with optional persistence to disk. Designed to support both current CSV-based
storage and future database backends, with cache invalidation strategies
suitable for real-time price updates in web dashboards.
"""

import json
import logging
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

import pandas as pd

from config.settings import Settings

logger = logging.getLogger(__name__)


class PriceCache:
    """
    In-memory price cache with persistence and invalidation strategies.
    
    Provides fast access to recently fetched price data while supporting
    both current CSV storage and future database/real-time scenarios.
    """
    
    def __init__(
        self, 
        settings: Optional[Settings] = None,
        max_cache_size: int = 1000,
        default_ttl_minutes: int = 15
    ):
        """
        Initialize the price cache.
        
        Args:
            settings: Optional settings instance for configuration
            max_cache_size: Maximum number of ticker entries to cache
            default_ttl_minutes: Default time-to-live for cache entries in minutes
        """
        self.settings = settings or Settings()
        self.max_cache_size = max_cache_size
        self.default_ttl = timedelta(minutes=default_ttl_minutes)
        
        # Cache structure: {ticker: CacheEntry}
        self._cache: Dict[str, 'CacheEntry'] = {}
        self._access_order: list = []  # For LRU eviction
        
        # Company name cache (from original script)
        self._company_name_cache: Dict[str, str] = {}
        
        # Ticker correction cache (from original script)
        self._ticker_correction_cache: Dict[str, str] = {}
        
        # Load persistent cache if available
        self._load_persistent_cache()
    
    def get_cached_price(
        self, 
        ticker: str, 
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Optional[pd.DataFrame]:
        """
        Retrieve cached price data for a ticker.
        
        Args:
            ticker: Stock ticker symbol
            start_date: Optional start date filter
            end_date: Optional end date filter
            
        Returns:
            Cached DataFrame if available and valid, None otherwise
        """
        ticker = ticker.upper().strip()
        
        if ticker not in self._cache:
            return None
        
        entry = self._cache[ticker]
        
        # Check if cache entry is still valid
        if self._is_expired(entry):
            self._remove_from_cache(ticker)
            return None
        
        # Update access order for LRU
        self._update_access_order(ticker)
        
        # Filter data by date range if specified
        df = entry.data.copy()
        if start_date:
            start_ts = pd.Timestamp(start_date)
            # Make timezone-aware if the index is timezone-aware
            if df.index.tz is not None and start_ts.tz is None:
                start_ts = start_ts.tz_localize(df.index.tz)
            df = df[df.index >= start_ts]
        if end_date:
            end_ts = pd.Timestamp(end_date)
            # Make timezone-aware if the index is timezone-aware
            if df.index.tz is not None and end_ts.tz is None:
                end_ts = end_ts.tz_localize(df.index.tz)
            df = df[df.index <= end_ts]
        
        if df.empty:
            return None
        
        logger.debug(f"Cache hit for {ticker} ({len(df)} rows)")
        return df
    
    def cache_price_data(
        self, 
        ticker: str, 
        data: pd.DataFrame,
        source: str = "unknown",
        ttl_minutes: Optional[int] = None
    ) -> None:
        """
        Cache price data for a ticker.
        
        Args:
            ticker: Stock ticker symbol
            data: Price data DataFrame
            source: Data source identifier
            ttl_minutes: Optional custom TTL in minutes
        """
        if data.empty:
            return
        
        ticker = ticker.upper().strip()
        ttl = timedelta(minutes=ttl_minutes) if ttl_minutes else self.default_ttl
        
        # Create cache entry
        entry = CacheEntry(
            ticker=ticker,
            data=data.copy(),
            source=source,
            timestamp=datetime.now(),
            ttl=ttl
        )
        
        # Add to cache
        self._cache[ticker] = entry
        self._update_access_order(ticker)
        
        # Enforce cache size limit
        self._enforce_cache_limit()
        
        logger.debug(f"Cached {len(data)} rows for {ticker} from {source}")
    
    def invalidate_ticker(self, ticker: str) -> None:
        """
        Invalidate cache entry for a specific ticker.
        
        Args:
            ticker: Stock ticker symbol to invalidate
        """
        ticker = ticker.upper().strip()
        if ticker in self._cache:
            self._remove_from_cache(ticker)
            logger.debug(f"Invalidated cache for {ticker}")
    
    def invalidate_all(self) -> None:
        """Invalidate all cache entries."""
        self._cache.clear()
        self._access_order.clear()
        logger.debug("Invalidated entire price cache")
    
    def invalidate_expired(self) -> int:
        """
        Remove expired cache entries.
        
        Returns:
            Number of entries removed
        """
        expired_tickers = []
        
        for ticker, entry in self._cache.items():
            if self._is_expired(entry):
                expired_tickers.append(ticker)
        
        for ticker in expired_tickers:
            self._remove_from_cache(ticker)
        
        if expired_tickers:
            logger.debug(f"Removed {len(expired_tickers)} expired cache entries")
        
        return len(expired_tickers)
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        total_entries = len(self._cache)
        total_rows = sum(len(entry.data) for entry in self._cache.values())
        
        # Count by source
        sources = {}
        for entry in self._cache.values():
            sources[entry.source] = sources.get(entry.source, 0) + 1
        
        # Find oldest and newest entries
        if self._cache:
            timestamps = [entry.timestamp for entry in self._cache.values()]
            oldest = min(timestamps)
            newest = max(timestamps)
        else:
            oldest = newest = None
        
        return {
            "total_entries": total_entries,
            "total_rows": total_rows,
            "max_cache_size": self.max_cache_size,
            "sources": sources,
            "oldest_entry": oldest,
            "newest_entry": newest,
            "company_names_cached": len(self._company_name_cache),
            "ticker_corrections_cached": len(self._ticker_correction_cache)
        }
    
    def get_company_name(self, ticker: str) -> Optional[str]:
        """
        Get cached company name for a ticker.
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            Company name if cached, None otherwise
        """
        ticker = ticker.upper().strip()
        return self._company_name_cache.get(ticker)
    
    def cache_company_name(self, ticker: str, name: str) -> None:
        """
        Cache company name for a ticker.
        
        Args:
            ticker: Stock ticker symbol
            name: Company name
        """
        ticker = ticker.upper().strip()
        self._company_name_cache[ticker] = name
    
    def clear_company_name_cache(self, ticker: str) -> None:
        """
        Clear cached company name for a ticker.
        
        Args:
            ticker: Stock ticker symbol
        """
        ticker = ticker.upper().strip()
        if ticker in self._company_name_cache:
            del self._company_name_cache[ticker]
    
    def get_ticker_correction(self, ticker: str) -> Optional[str]:
        """
        Get cached ticker correction.
        
        Args:
            ticker: Original ticker symbol
            
        Returns:
            Corrected ticker if cached, None otherwise
        """
        ticker = ticker.upper().strip()
        return self._ticker_correction_cache.get(ticker)
    
    def cache_ticker_correction(self, original: str, corrected: str) -> None:
        """
        Cache ticker correction.
        
        Args:
            original: Original ticker symbol
            corrected: Corrected ticker symbol
        """
        original = original.upper().strip()
        corrected = corrected.upper().strip()
        self._ticker_correction_cache[original] = corrected
    
    def _get_cache_directory(self) -> Optional[Path]:
        """Get cache directory path, or None if no data directory/active fund."""
        try:
            return Path(self.settings.get_data_directory()) / ".cache"
        except ValueError as e:
            if "No data directory specified" in str(e):
                logger.debug("Skipping persistent cache (no data directory or active fund)")
                return None
            raise

    def save_persistent_cache(self) -> None:
        """Save cache to disk for persistence across sessions."""
        cache_dir = self._get_cache_directory()
        if cache_dir is None:
            return
        try:
            cache_dir.mkdir(exist_ok=True)
            
            # Save price cache (using pickle for DataFrame support)
            price_cache_file = cache_dir / "price_cache.pkl"
            with open(price_cache_file, 'wb') as f:
                pickle.dump({
                    'cache': self._cache,
                    'access_order': self._access_order
                }, f)
            
            # Save name caches (using JSON for readability)
            name_cache_file = cache_dir / "name_cache.json"
            with open(name_cache_file, 'w') as f:
                json.dump({
                    'company_names': self._company_name_cache,
                    'ticker_corrections': self._ticker_correction_cache
                }, f, indent=2)
            
            logger.debug("Saved persistent cache to disk")
            
        except Exception as e:
            logger.warning(f"Failed to save persistent cache: {e}")
    
    def _load_persistent_cache(self) -> None:
        """Load cache from disk if available."""
        cache_dir = self._get_cache_directory()
        if cache_dir is None:
            return
        try:
            # Load price cache
            price_cache_file = cache_dir / "price_cache.pkl"
            if price_cache_file.exists():
                with open(price_cache_file, 'rb') as f:
                    data = pickle.load(f)
                    self._cache = data.get('cache', {})
                    self._access_order = data.get('access_order', [])
                
                # Remove expired entries
                self.invalidate_expired()
            
            # Load name caches
            name_cache_file = cache_dir / "name_cache.json"
            if name_cache_file.exists():
                with open(name_cache_file, 'r') as f:
                    data = json.load(f)
                    self._company_name_cache = data.get('company_names', {})
                    self._ticker_correction_cache = data.get('ticker_corrections', {})
            
            if self._cache:
                logger.debug(f"Loaded persistent cache with {len(self._cache)} entries")
                
        except Exception as e:
            logger.warning(f"Failed to load persistent cache: {e}")
            # Reset caches on load failure (e.g. corrupt file)
            self._cache.clear()
            self._access_order.clear()
            self._company_name_cache.clear()
            self._ticker_correction_cache.clear()
    
    def _is_expired(self, entry: 'CacheEntry') -> bool:
        """Check if a cache entry is expired."""
        return datetime.now() - entry.timestamp > entry.ttl
    
    def _update_access_order(self, ticker: str) -> None:
        """Update LRU access order for a ticker."""
        if ticker in self._access_order:
            self._access_order.remove(ticker)
        self._access_order.append(ticker)
    
    def _remove_from_cache(self, ticker: str) -> None:
        """Remove a ticker from cache and access order."""
        if ticker in self._cache:
            del self._cache[ticker]
        if ticker in self._access_order:
            self._access_order.remove(ticker)
    
    def _enforce_cache_limit(self) -> None:
        """Enforce maximum cache size using LRU eviction."""
        while len(self._cache) > self.max_cache_size:
            if not self._access_order:
                break
            
            # Remove least recently used entry
            lru_ticker = self._access_order[0]
            self._remove_from_cache(lru_ticker)
            logger.debug(f"Evicted {lru_ticker} from cache (LRU)")


class CacheEntry:
    """Individual cache entry for price data."""
    
    def __init__(
        self,
        ticker: str,
        data: pd.DataFrame,
        source: str,
        timestamp: datetime,
        ttl: timedelta
    ):
        self.ticker = ticker
        self.data = data
        self.source = source
        self.timestamp = timestamp
        self.ttl = ttl