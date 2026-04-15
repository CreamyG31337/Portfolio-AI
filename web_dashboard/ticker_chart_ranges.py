"""Shared ticker price-chart range keys and day spans for Flask, Streamlit, and clients."""

from __future__ import annotations

from typing import FrozenSet

# Calendar-day lookback for date filters (congress trades, ETF trades, portfolio_positions).
# "max" uses a long window for DB filters; Yahoo Finance uses period="max" when enabled.
TICKER_CHART_RANGE_DAYS: dict[str, int] = {
    "3m": 90,
    "6m": 180,
    "1y": 365,
    "2y": 730,
    "5y": 1825,
    "10y": 3650,
    "20y": 7300,
    "max": 365 * 75,
}

VALID_TICKER_CHART_RANGES: FrozenSet[str] = frozenset(TICKER_CHART_RANGE_DAYS.keys())


def normalize_ticker_chart_range(chart_range: str | None, default: str = "3m") -> str:
    """Return a valid range key or default."""
    if not chart_range:
        return default
    key = str(chart_range).strip().lower()
    return key if key in VALID_TICKER_CHART_RANGES else default


def ticker_chart_range_days(chart_range: str) -> int:
    """Calendar days for auxiliary date windows (not always equal to Yahoo history length for max)."""
    return TICKER_CHART_RANGE_DAYS[normalize_ticker_chart_range(chart_range)]


def use_yfinance_max_period(chart_range: str) -> bool:
    """True when the UI range should pull full available history from Yahoo Finance."""
    return normalize_ticker_chart_range(chart_range) == "max"
