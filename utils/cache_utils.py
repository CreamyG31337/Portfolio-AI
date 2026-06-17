"""Cache clearing utilities for trade entry operations.

This module provides helper functions for clearing caches related to trade entry,
ensuring fresh data is used after trades are added or modified.
"""

import logging
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


def clear_trade_related_caches(data_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Clear all caches related to trade entry operations.
    
    This function clears:
    - Price cache (market data)
    - Exchange rate cache (currency conversions)
    - Flask dashboard cache (when web_dashboard is importable)
    
    Args:
        data_dir: Optional data directory path for currency handler initialization
        
    Returns:
        Dictionary with results of each cache clearing operation:
        {
            "price_cache": {"success": bool, "message": str},
            "exchange_rate_cache": {"success": bool, "message": str},
            "flask_cache": {"success": bool, "message": str}
        }
    """
    results = {
        "price_cache": {"success": False, "message": "Not attempted"},
        "exchange_rate_cache": {"success": False, "message": "Not attempted"},
        "flask_cache": {"success": False, "message": "Not attempted"},
    }
    
    # Clear price cache
    try:
        from market_data.price_cache import PriceCache
        price_cache = PriceCache()
        price_cache.invalidate_all()
        results["price_cache"] = {"success": True, "message": "Price cache cleared"}
        logger.info("Cleared price cache after trade entry")
    except Exception as e:
        results["price_cache"] = {"success": False, "message": f"Failed to clear price cache: {e}"}
        logger.warning(f"Failed to clear price cache: {e}")
    
    # Clear exchange rate cache
    try:
        from financial.currency_handler import CurrencyHandler
        if data_dir:
            currency_handler = CurrencyHandler(data_dir=data_dir)
        else:
            currency_handler = CurrencyHandler()
        currency_handler.clear_exchange_rate_cache()
        results["exchange_rate_cache"] = {"success": True, "message": "Exchange rate cache cleared"}
        logger.info("Cleared exchange rate cache after trade entry")
    except Exception as e:
        results["exchange_rate_cache"] = {"success": False, "message": f"Failed to clear exchange rate cache: {e}"}
        logger.warning(f"Failed to clear exchange rate cache: {e}")
    
    # Clear Flask dashboard caches when available
    try:
        from flask_cache_utils import clear_all_caches

        clear_all_caches()
        results["flask_cache"] = {"success": True, "message": "Flask cache cleared"}
        logger.info("Cleared Flask dashboard cache after trade entry")
    except ImportError:
        results["flask_cache"] = {"success": True, "message": "Flask cache utils not available (skipped)"}
    except Exception as e:
        results["flask_cache"] = {"success": False, "message": f"Failed to clear Flask cache: {e}"}
        logger.warning(f"Failed to clear Flask cache: {e}")
    
    return results

