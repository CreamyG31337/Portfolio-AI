#!/usr/bin/env python3
"""Test DG price fetching to find the bug"""

import sys
from pathlib import Path
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).parent.parent))

from market_data.data_fetcher import MarketDataFetcher
from market_data.price_cache import PriceCache
from config.settings import Settings

print("Testing DG price fetch for 2026-01-19...")
print()

mf = MarketDataFetcher()
target_date = datetime(2026, 1, 19, 0, 0, 0)
end_date = datetime(2026, 1, 19, 23, 59, 59)

result = mf.fetch_price_data('DG', start=target_date, end=end_date)
print(f"Source: {result.source}")
print(f"Data shape: {result.df.shape}")
print()

if not result.df.empty:
    print("DataFrame:")
    print(result.df)
    print()
    
    print("Close column:")
    print(result.df['Close'])
    print()
    
    print(f"Last Close value: {result.df['Close'].iloc[-1]}")
    print(f"Type: {type(result.df['Close'].iloc[-1])}")
    print()
    
    # Test what the scheduled job would do
    latest_price = Decimal(str(result.df['Close'].iloc[-1]))
    print(f"Decimal conversion: {latest_price}")
    print(f"As float: {float(latest_price)}")
    
    # Check cache
    print("\nChecking cache...")
    settings = Settings()
    settings.set('repository.csv.data_directory', str(Path.home() / '.trading_bot_cache'))
    cache = PriceCache(settings=settings)
    cached = cache.get_cached_price('DG')
    if cached is not None and not cached.empty:
        print(f"Cached Close: {cached['Close'].iloc[-1]}")
        print(f"Cached type: {type(cached['Close'].iloc[-1])}")
    else:
        print("No cached data")
else:
    print("EMPTY RESULT!")
    print("Checking cache fallback...")
    settings = Settings()
    settings.set('repository.csv.data_directory', str(Path.home() / '.trading_bot_cache'))
    cache = PriceCache(settings=settings)
    cached = cache.get_cached_price('DG')
    if cached is not None and not cached.empty:
        print(f"Cached data shape: {cached.shape}")
        print(f"Cached Close: {cached['Close'].iloc[-1]}")
        print(f"Cached type: {type(cached['Close'].iloc[-1])}")
        latest_price = Decimal(str(cached['Close'].iloc[-1]))
        print(f"Decimal conversion: {latest_price}")
    else:
        print("No cached data either")
