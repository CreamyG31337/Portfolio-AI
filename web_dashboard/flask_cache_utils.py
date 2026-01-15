"""
Flask Caching Utilities
=======================

Provides caching functionality for Flask that mirrors Streamlit's @st.cache_data
and @st.cache_resource decorators. This allows easy migration of data-heavy pages
from Streamlit to Flask while maintaining similar caching behavior.

Usage:
    from flask_cache_utils import cache_data, cache_resource
    
    @cache_data(ttl=300)  # Cache for 5 minutes
    def get_expensive_data(param1, param2):
        # Expensive operation here
        return data
    
    @cache_resource  # Cache resource (like DB connections) for app lifetime
    def get_database_client():
        return DatabaseClient()

Features:
    - TTL-based expiration (like Streamlit's ttl parameter)
    - Automatic cache key generation from function arguments
    - Cache version support (for manual invalidation)
    - Multiple backend support (SimpleCache, Redis, Memcached)
    - Thread-safe caching
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Callable, Optional, Dict
from flask import current_app, has_app_context

logger = logging.getLogger(__name__)

# Try to import Flask-Caching, fall back to simple cache if not available
try:
    from flask_caching import Cache
    FLASK_CACHING_AVAILABLE = True
except ImportError:
    FLASK_CACHING_AVAILABLE = False
    logger.warning("Flask-Caching not installed. Using simple in-memory cache. Install with: pip install Flask-Caching")

# Import cache version system for invalidation
try:
    from cache_version import get_cache_version
    CACHE_VERSION_AVAILABLE = True
except ImportError:
    CACHE_VERSION_AVAILABLE = False
    logger.warning("cache_version module not available. Cache versioning disabled.")


class SimpleCache:
    """
    Simple in-memory cache implementation as fallback when Flask-Caching is not available.
    Provides basic TTL-based caching functionality.
    """
    
    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired."""
        if key not in self._cache:
            return None
        
        entry = self._cache[key]
        expires_at = entry.get('expires_at')
        
        # Check if expired
        if expires_at and datetime.now() > expires_at:
            del self._cache[key]
            return None
        
        return entry.get('value')
    
    def set(self, key: str, value: Any, timeout: Optional[int] = None) -> bool:
        """Set value in cache with optional TTL."""
        entry = {'value': value}
        
        if timeout:
            entry['expires_at'] = datetime.now() + timedelta(seconds=timeout)
        
        self._cache[key] = entry
        return True
    
    def delete(self, key: str) -> bool:
        """Delete key from cache."""
        if key in self._cache:
            del self._cache[key]
            return True
        return False
    
    def clear(self) -> bool:
        """Clear all cache entries."""
        self._cache.clear()
        return True
    
    def has(self, key: str) -> bool:
        """Check if key exists and is not expired."""
        if key not in self._cache:
            return False
        
        entry = self._cache[key]
        expires_at = entry.get('expires_at')
        
        if expires_at and datetime.now() > expires_at:
            del self._cache[key]
            return False
        
        return True


# Global cache instance (will be initialized on first use)
_cache_instance: Optional[Any] = None
_simple_cache: Optional[SimpleCache] = None


def _get_cache():
    """Get cache instance, initializing if necessary."""
    global _cache_instance, _simple_cache
    
    if FLASK_CACHING_AVAILABLE:
        try:
            if has_app_context():
                # 1. Try to get from extensions (Standard Flask-Caching way)
                # Flask-Caching stores cache backend in app.extensions['cache'] as a dict
                # where the Cache instance is the key: {Cache_instance: backend}
                cache_ext = current_app.extensions.get('cache')
                
                if cache_ext is not None:
                    # Case A: Standard Flask-Caching dict
                    if hasattr(cache_ext, 'keys'):
                        try:
                            # The Cache object itself is the key
                            # We iterate to find it
                            for key in cache_ext.keys():
                                if isinstance(key, Cache):
                                    return key
                        except (TypeError, AttributeError):
                            pass
                            
                    # Case B: Direct Cache instance (unlikely but possible in some setups)
                    elif isinstance(cache_ext, Cache):
                        return cache_ext

                # 2. Try to get 'cache' attribute from current_app if manually attached
                # Some apps attach it like app.cache = cache
                if hasattr(current_app, 'cache') and isinstance(current_app.cache, Cache):
                    return current_app.cache
                
                # 3. Last resort: Initialize new cache instance attached to current_app
                # This should only happen if cache wasn't initialized in app.py
                logger.warning("Cache not found in extensions, initializing new Flask-Caching instance")
                _cache_instance = Cache(config={'CACHE_TYPE': 'SimpleCache'})
                _cache_instance.init_app(current_app)
                return _cache_instance
            else:
                # Not in app context, use simple cache
                if _simple_cache is None:
                    _simple_cache = SimpleCache()
                return _simple_cache
        except Exception as e:
            logger.warning(f"Failed to get Flask-Caching instance: {e}. Using simple cache.")
            if _simple_cache is None:
                _simple_cache = SimpleCache()
            return _simple_cache
    else:
        # Flask-Caching not available, use simple cache
        if _simple_cache is None:
            _simple_cache = SimpleCache()
        return _simple_cache


def _make_cache_key(func_name: str, args: tuple, kwargs: dict, cache_version: Optional[str] = None) -> str:
    """
    Generate a cache key from function name and arguments.
    Similar to how Streamlit generates cache keys.
    """
    # Include function name
    key_parts = [func_name]
    
    # Include positional arguments
    if args:
        # Convert args to a hashable format
        args_str = json.dumps(args, sort_keys=True, default=str)
        key_parts.append(f"args:{hashlib.md5(args_str.encode()).hexdigest()}")
    
    # Include keyword arguments (sorted for consistency)
    if kwargs:
        # Filter out kwargs that start with '_' (like Streamlit)
        filtered_kwargs = {k: v for k, v in kwargs.items() if not k.startswith('_')}
        if filtered_kwargs:
            kwargs_str = json.dumps(filtered_kwargs, sort_keys=True, default=str)
            key_parts.append(f"kwargs:{hashlib.md5(kwargs_str.encode()).hexdigest()}")
    
    # Include cache version if available
    if cache_version:
        key_parts.append(f"version:{cache_version}")
    elif CACHE_VERSION_AVAILABLE:
        try:
            cache_version = get_cache_version()
            key_parts.append(f"version:{cache_version}")
        except Exception:
            pass
    
    # Combine all parts
    full_key = "|".join(key_parts)
    
    # Hash the full key to keep it reasonable length
    return hashlib.sha256(full_key.encode()).hexdigest()


def _get_cache_ttl() -> int:
    """Get cache TTL based on market hours (reuses logic from streamlit_utils).
    
    Returns:
        Cache TTL in seconds:
        - 300s (5 min) during market hours (9:30 AM - 4:00 PM EST, Mon-Fri)
        - 3600s (1 hour) outside market hours
    """
    try:
        # Try to import from streamlit_utils first
        from streamlit_utils import get_cache_ttl
        return get_cache_ttl()
    except (ImportError, AttributeError):
        # Fallback implementation if streamlit_utils not available
        from datetime import datetime
        try:
            import pytz
            est = pytz.timezone('America/New_York')
            now = datetime.now(est)
        except ImportError:
            from zoneinfo import ZoneInfo
            est = ZoneInfo('America/New_York')
            now = datetime.now(est)
        
        # Weekend: cache for 1 hour
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            return 3600
        
        # Market hours: 9:30 AM - 4:00 PM EST
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        
        if market_open <= now <= market_close:
            return 300  # 5 minutes during market hours
        else:
            return 3600  # 1 hour outside market hours


def cache_data(ttl: Optional[int] = None, show_spinner: bool = False, use_market_hours: bool = False):
    """
    Decorator for caching function results (similar to @st.cache_data).
    
    Args:
        ttl: Time to live in seconds. None means cache forever (until manually cleared).
             If use_market_hours=True, this parameter is ignored and TTL is calculated dynamically.
        show_spinner: Not used in Flask (no UI spinner), kept for API compatibility.
        use_market_hours: If True, use market-hours-aware TTL (300s during market hours, 3600s outside).
    
    Usage:
        @cache_data(ttl=300)  # Cache for 5 minutes (static)
        def get_expensive_data(param1, param2):
            return expensive_operation()
        
        @cache_data(use_market_hours=True)  # Dynamic TTL based on market hours
        def get_portfolio_data(fund: str):
            return fetch_portfolio(fund)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Extract cache_version from kwargs if present (for manual invalidation)
            cache_version = kwargs.pop('_cache_version', None)
            
            # Determine TTL
            if use_market_hours:
                effective_ttl = _get_cache_ttl()
            else:
                effective_ttl = ttl
            
            # Generate cache key
            cache_key = _make_cache_key(func.__name__, args, kwargs, cache_version)
            
            # Try to get from cache
            cache = _get_cache()
            # Flask-Caching: use cache.get() which returns None if not found
            try:
                cached_value = cache.get(cache_key)
            except Exception as cache_error:
                logger.warning(f"Cache get error for {func.__name__}: {cache_error}", exc_info=True)
                cached_value = None
            
            if cached_value is not None:
                logger.debug(f"Cache hit for {func.__name__} with key {cache_key[:16]}...")
                return cached_value
            
            # Cache miss - execute function
            logger.debug(f"Cache miss for {func.__name__} with key {cache_key[:16]}...")
            result = func(*args, **kwargs)
            
            # Store in cache
            try:
                cache.set(cache_key, result, timeout=effective_ttl)
            except Exception as cache_error:
                logger.warning(f"Cache set error for {func.__name__}: {cache_error}", exc_info=True)
                # Continue without caching if cache.set fails
            
            return result
        
        # Add cache clearing method to function
        def clear_cache(*args, **kwargs):
            """Clear cache for this function with specific arguments."""
            cache_version = kwargs.pop('_cache_version', None)
            cache_key = _make_cache_key(func.__name__, args, kwargs, cache_version)
            cache = _get_cache()
            cache.delete(cache_key)
        
        def clear_all_cache():
            """Clear all cache entries for this function."""
            cache = _get_cache()
            cache.clear()
        
        wrapper.clear_cache = clear_cache
        wrapper.clear_all_cache = clear_all_cache
        
        return wrapper
    
    return decorator


def cache_resource(func: Optional[Callable] = None):
    """
    Decorator for caching resources (similar to @st.cache_resource).
    Resources are cached for the application lifetime (no TTL).
    
    Usage:
        @cache_resource
        def get_database_client():
            return DatabaseClient()
    """
    # Support both @cache_resource and @cache_resource() syntax
    if func is None:
        # Called as @cache_resource() - return decorator factory
        def decorator_factory(f: Callable) -> Callable:
            return _cache_resource_impl(f)
        return decorator_factory
    else:
        # Called as @cache_resource - apply decorator directly
        return _cache_resource_impl(func)

def _cache_resource_impl(func: Callable) -> Callable:
    """Internal implementation of cache_resource decorator."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Extract cache_version from kwargs if present
        cache_version = kwargs.pop('_cache_version', None)
        
        # Generate cache key
        cache_key = _make_cache_key(func.__name__, args, kwargs, cache_version)
        
        # Try to get from cache
        cache = _get_cache()
        try:
            cached_value = cache.get(cache_key)
        except Exception as cache_error:
            logger.warning(f"Cache get error for {func.__name__}: {cache_error}", exc_info=True)
            cached_value = None
        
        if cached_value is not None:
            logger.debug(f"Resource cache hit for {func.__name__} with key {cache_key[:16]}...")
            return cached_value
        
        # Cache miss - execute function
        logger.debug(f"Resource cache miss for {func.__name__} with key {cache_key[:16]}...")
        result = func(*args, **kwargs)
        
        # Store in cache without TTL (cached forever until manually cleared)
        # Flask-Caching: timeout=None means no expiration
        try:
            cache.set(cache_key, result, timeout=None)
        except Exception as cache_error:
            logger.warning(f"Cache set error for {func.__name__}: {cache_error}", exc_info=True)
            # Continue without caching if cache.set fails
        
        return result
    
    # Add cache clearing methods
    def clear_cache(*args, **kwargs):
        """Clear cache for this resource with specific arguments."""
        cache_version = kwargs.pop('_cache_version', None)
        cache_key = _make_cache_key(func.__name__, args, kwargs, cache_version)
        cache = _get_cache()
        cache.delete(cache_key)
    
    def clear_all_cache():
        """Clear all cache entries for this resource."""
        cache = _get_cache()
        cache.clear()
    
    wrapper.clear_cache = clear_cache
    wrapper.clear_all_cache = clear_all_cache
    
    return wrapper


def clear_all_caches():
    """Clear all cached data (useful for manual cache invalidation)."""
    cache = _get_cache()
    cache.clear()
    logger.info("All caches cleared")


def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics (if supported by backend)."""
    cache = _get_cache()
    
    if hasattr(cache, 'cache'):
        # Flask-Caching with SimpleCache
        if hasattr(cache.cache, '_cache'):
            cache_dict = cache.cache._cache
            return {
                'total_keys': len(cache_dict),
                'backend': 'SimpleCache',
                'keys': list(cache_dict.keys())[:10]  # First 10 keys as sample
            }
    
    # Simple cache stats
    if isinstance(cache, SimpleCache):
        return {
            'total_keys': len(cache._cache),
            'backend': 'SimpleCache',
            'keys': list(cache._cache.keys())[:10]
        }
    
    return {
        'total_keys': 'unknown',
        'backend': 'unknown',
        'keys': []
    }
