"""Helpers for consistent trade reason/action classification."""

from __future__ import annotations

import re
from typing import Optional

_SELL_PATTERN = re.compile(r"\b(sell|limit sell|market sell)\b", re.IGNORECASE)
_BUY_PATTERN = re.compile(r"\bbuy\b", re.IGNORECASE)
_DIVIDEND_PATTERN = re.compile(r"\b(drip|dividend)\b", re.IGNORECASE)


def normalize_reason_text(reason: Optional[str]) -> str:
    """Normalize nullable reason text into a comparable lowercase string."""
    return str(reason or "").strip().lower()


def is_dividend_reason(reason: Optional[str]) -> bool:
    """Return True when reason indicates a dividend event (cash or DRIP)."""
    return bool(_DIVIDEND_PATTERN.search(normalize_reason_text(reason)))


def is_sell_reason(reason: Optional[str]) -> bool:
    """Return True when reason indicates a sell action."""
    return bool(_SELL_PATTERN.search(normalize_reason_text(reason)))


def infer_trade_action(reason: Optional[str], default: str = "BUY") -> str:
    """Infer canonical action from freeform reason text.

    Returns one of: SELL, DIVIDEND, BUY.
    """
    if is_sell_reason(reason):
        return "SELL"
    if is_dividend_reason(reason):
        return "DIVIDEND"
    text = normalize_reason_text(reason)
    if _BUY_PATTERN.search(text):
        return "BUY"
    return default.upper()
