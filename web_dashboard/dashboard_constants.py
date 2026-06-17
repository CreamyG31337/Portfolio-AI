#!/usr/bin/env python3
"""Shared dashboard constants (Flask + Streamlit; no Streamlit dependency)."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Dict

_startup_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
CACHE_VERSION = os.getenv("BUILD_TIMESTAMP", _startup_timestamp)

SUPPORTED_CURRENCIES: Dict[str, str] = {
    "CAD": "Canadian Dollar",
    "USD": "US Dollar",
}


def get_supported_currencies() -> Dict[str, str]:
    """Return a copy of supported display currencies."""
    return SUPPORTED_CURRENCIES.copy()


def get_cache_ttl() -> int:
    """Cache TTL from market hours: 300s during US session, 3600s otherwise."""
    from datetime import datetime as dt

    try:
        import pytz

        est = pytz.timezone("America/New_York")
        now = dt.now(est)
    except ImportError:
        from zoneinfo import ZoneInfo

        est = ZoneInfo("America/New_York")
        now = dt.now(est)

    if now.weekday() >= 5:
        return 3600

    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)

    if market_open <= now <= market_close:
        return 300
    return 3600
