"""
Market data module for fetching, caching, and managing market data.

This module provides:
- MarketDataFetcher: Robust data fetching with Yahoo/Stooq fallback
- MarketHours: Market timing and trading day calculations  
- PriceCache: In-memory price caching with persistence support
"""

from .data_fetcher import MarketDataFetcher, FetchResult
from .market_hours import MarketHours
from .ohlcv_quality import drop_invalid_ohlcv_bars, get_last_valid_close
from .price_cache import PriceCache
from .split_adjust import apply_unadjusted_splits

__all__ = [
    'MarketDataFetcher',
    'FetchResult',
    'MarketHours',
    'PriceCache',
    'drop_invalid_ohlcv_bars',
    'get_last_valid_close',
    'apply_unadjusted_splits',
]