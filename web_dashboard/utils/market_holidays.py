"""Compatibility shim for utils.market_holidays imports in Flask runtime."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT_MODULE_PATH = Path(__file__).resolve().parents[2] / "utils" / "market_holidays.py"
_SPEC = importlib.util.spec_from_file_location("_root_market_holidays", _ROOT_MODULE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Could not load market_holidays module from {_ROOT_MODULE_PATH}")

_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

MarketHolidays = _MODULE.MarketHolidays
MARKET_HOLIDAYS = _MODULE.MARKET_HOLIDAYS

__all__ = [
    "MarketHolidays",
    "MARKET_HOLIDAYS",
]
