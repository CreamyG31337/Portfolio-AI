"""Helpers for consistent trade reason/action classification."""

from __future__ import annotations

import re
from typing import Optional

_SELL_PATTERN = re.compile(r"\b(sell|limit sell|market sell)\b", re.IGNORECASE)
_BUY_PATTERN = re.compile(r"\bbuy\b", re.IGNORECASE)
_DIVIDEND_PATTERN = re.compile(r"\b(drip|dividend)\b", re.IGNORECASE)
# Broker / import stubs — not an investment thesis (initial-buy quality checks)
_EMAIL_TRADE_BUY = re.compile(r"^\s*email trade\s*-\s*buy\b", re.IGNORECASE)
_MANUAL_BUY = re.compile(r"\bmanual buy\b", re.IGNORECASE)
_MARKET_BUY_ONLY = re.compile(r"^\s*market buy\s*$", re.IGNORECASE)
_LIMIT_BUY_STUB = re.compile(r"^\s*limit buy\b", re.IGNORECASE)
_BUY_ORDER_ONLY = re.compile(r"^\s*(buy|sell)\s+order\s*$", re.IGNORECASE)


def normalize_reason_text(reason: Optional[str]) -> str:
    """Normalize nullable reason text into a comparable lowercase string."""
    return str(reason or "").strip().lower()


def is_dividend_reason(reason: Optional[str]) -> bool:
    """Return True when reason indicates a dividend event (cash or DRIP)."""
    return bool(_DIVIDEND_PATTERN.search(normalize_reason_text(reason)))


def is_sell_reason(reason: Optional[str]) -> bool:
    """Return True when reason indicates a sell action."""
    return bool(_SELL_PATTERN.search(normalize_reason_text(reason)))


def is_boilerplate_buy_rationale(reason: Optional[str]) -> bool:
    """True when *reason* is generic broker/email/import text, not a written thesis.

    Used for reporting (e.g. initial buys that still need a real rationale). Does not
    judge quality of substantive prose — only filters known non-thesis patterns.
    """
    s = str(reason or "").strip()
    if not s:
        return False
    if _EMAIL_TRADE_BUY.search(s):
        return True
    if _MANUAL_BUY.search(s):
        return True
    if _MARKET_BUY_ONLY.match(s):
        return True
    if _LIMIT_BUY_STUB.match(s):
        return True
    if _BUY_ORDER_ONLY.match(s):
        return True
    return False


def is_trade_sell(trade: dict[str, object]) -> bool:
    """Return True when a trade_log row represents a sell."""
    action = str(trade.get("action") or "").strip().upper()
    if action == "SELL":
        return True
    reason = trade.get("reason")
    return is_sell_reason(reason if isinstance(reason, str) else str(reason or ""))


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
