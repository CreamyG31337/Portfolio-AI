"""Tests for FearRiskSignal and OHLCV normalization data-quality guards.

Regression coverage for the "phantom EXTREME fear" bug: a single bad price
bar (a $0 / NaN close from a partial, holiday, or glitchy feed row) used to be
coerced to a real $0 price, which the fear/risk signal read as a -100% crash
and flagged as EXTREME fear / AVOID on otherwise healthy stocks (e.g. CMI).
"""

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from web_dashboard.signals.fear_risk_signal import FearRiskSignal
from market_data.data_fetcher import MarketDataFetcher


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def healthy_df() -> pd.DataFrame:
    """130-row boring large-cap: gentle uptrend, ~1% daily noise."""
    rng = np.random.default_rng(1)
    n = 130
    prices = [300.0]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + rng.normal(0.0005, 0.01)))
    idx = pd.bdate_range("2026-01-01", periods=n)
    return pd.DataFrame(
        {
            "Close": [Decimal(str(round(p, 4))) for p in prices],
            "Volume": [Decimal("1000000")] * n,
        },
        index=idx,
    )


# ---------------------------------------------------------------------------
# FearRiskSignal
# ---------------------------------------------------------------------------

def test_healthy_series_is_low_fear(healthy_df):
    result = FearRiskSignal().evaluate(healthy_df)
    assert result["fear_level"] == "LOW"
    assert result["drawdown_pct"] > -10.0


def test_zero_last_bar_does_not_trigger_phantom_extreme(healthy_df):
    """A single $0 last close must NOT read as a -100% crash."""
    df = healthy_df.copy()
    df.iloc[-1, df.columns.get_loc("Close")] = Decimal("0")

    result = FearRiskSignal().evaluate(df)

    assert result["fear_level"] != "EXTREME"
    assert result["recommendation"] != "AVOID"
    assert result["drawdown_pct"] > -50.0
    assert result["daily_change_pct"] > -50.0


def test_nan_last_bar_does_not_trigger_phantom_extreme(healthy_df):
    df = healthy_df.copy()
    df["Close"] = df["Close"].astype(object)
    df.iloc[-1, df.columns.get_loc("Close")] = np.nan

    result = FearRiskSignal().evaluate(df)

    assert result["fear_level"] != "EXTREME"
    assert result["drawdown_pct"] > -50.0


def test_all_invalid_prices_returns_insufficient_data(healthy_df):
    df = healthy_df.copy()
    df["Close"] = [Decimal("0")] * len(df)

    result = FearRiskSignal().evaluate(df)

    assert result["fear_level"] == "LOW"
    assert result.get("error") == "Insufficient data"


# ---------------------------------------------------------------------------
# MarketDataFetcher._normalize_ohlcv
# ---------------------------------------------------------------------------

def _make_fetcher() -> MarketDataFetcher:
    """Build a fetcher without the heavy __init__ (CSV/Supabase cache loads)."""
    return MarketDataFetcher.__new__(MarketDataFetcher)


def test_normalize_ohlcv_drops_zero_close_bars():
    df = pd.DataFrame(
        {
            "Open": [10.0, 11.0, 12.0],
            "High": [10.5, 11.5, 12.5],
            "Low": [9.5, 10.5, 11.5],
            "Close": [10.0, 0.0, 12.0],  # middle bar is bad
            "Volume": [100, 200, 300],
        },
        index=pd.bdate_range("2026-01-01", periods=3),
    )

    out = _make_fetcher()._normalize_ohlcv(df)

    assert len(out) == 2
    assert all(c != Decimal("0") for c in out["Close"])


def test_normalize_ohlcv_drops_nan_close_bars():
    df = pd.DataFrame(
        {
            "Open": [10.0, 11.0, 12.0],
            "High": [10.5, 11.5, 12.5],
            "Low": [9.5, 10.5, 11.5],
            "Close": [10.0, np.nan, 12.0],
            "Volume": [100, 200, 300],
        },
        index=pd.bdate_range("2026-01-01", periods=3),
    )

    out = _make_fetcher()._normalize_ohlcv(df)

    assert len(out) == 2
    assert out["Close"].iloc[-1] == Decimal("12")
