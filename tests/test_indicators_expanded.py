"""
Tests for the expanded technical indicators.

Verifies that each new indicator function:
- Returns correct types and shapes
- Handles edge cases (empty DF, missing columns)
- Produces values in expected ranges for known inputs
"""

import numpy as np
import pandas as pd
import pytest

from web_dashboard.signals.indicators import (
    calculate_adx,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_macd,
    calculate_momentum_returns,
    calculate_roc,
    calculate_rsi,
    calculate_stochastic,
    calculate_volatility,
    calculate_williams_r,
    calculate_z_score,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ohlcv_df() -> pd.DataFrame:
    """150-row synthetic OHLCV DataFrame with a gentle uptrend."""
    np.random.seed(42)
    n = 150
    close = 100 + np.cumsum(np.random.randn(n) * 0.5 + 0.05)
    high = close + np.abs(np.random.randn(n) * 0.3)
    low = close - np.abs(np.random.randn(n) * 0.3)
    open_ = close + np.random.randn(n) * 0.1
    volume = np.random.randint(100_000, 1_000_000, size=n).astype(float)
    return pd.DataFrame({
        "Open": open_,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    })


@pytest.fixture
def empty_df() -> pd.DataFrame:
    return pd.DataFrame()


@pytest.fixture
def short_df() -> pd.DataFrame:
    """Only 5 rows -- too short for most indicators."""
    return pd.DataFrame({
        "Open": [10, 11, 12, 11, 13],
        "High": [11, 12, 13, 12, 14],
        "Low": [9, 10, 11, 10, 12],
        "Close": [10.5, 11.5, 12.5, 11.5, 13.5],
        "Volume": [1000, 1100, 1200, 1300, 1400],
    })


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------

class TestEMA:
    def test_returns_series(self, ohlcv_df: pd.DataFrame) -> None:
        result = calculate_ema(ohlcv_df, period=20)
        assert isinstance(result, pd.Series)
        assert len(result) == len(ohlcv_df)

    def test_last_value_near_close(self, ohlcv_df: pd.DataFrame) -> None:
        result = calculate_ema(ohlcv_df, period=20)
        # EMA should be in the neighborhood of recent prices
        assert abs(result.iloc[-1] - ohlcv_df["Close"].iloc[-1]) < 10

    def test_empty_df(self, empty_df: pd.DataFrame) -> None:
        result = calculate_ema(empty_df, period=20)
        assert result.empty

    def test_missing_column(self, ohlcv_df: pd.DataFrame) -> None:
        result = calculate_ema(ohlcv_df, price_col="Nonexistent")
        assert result.empty


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------

class TestMACD:
    def test_returns_dict_with_keys(self, ohlcv_df: pd.DataFrame) -> None:
        result = calculate_macd(ohlcv_df)
        assert set(result.keys()) == {"macd", "signal", "histogram"}
        for key in result:
            assert isinstance(result[key], pd.Series)
            assert len(result[key]) == len(ohlcv_df)

    def test_histogram_equals_macd_minus_signal(self, ohlcv_df: pd.DataFrame) -> None:
        result = calculate_macd(ohlcv_df)
        diff = result["macd"] - result["signal"]
        np.testing.assert_allclose(
            result["histogram"].dropna().values,
            diff.dropna().values,
            atol=1e-10,
        )

    def test_empty_df(self, empty_df: pd.DataFrame) -> None:
        result = calculate_macd(empty_df)
        assert result["macd"].empty


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

class TestBollingerBands:
    def test_returns_four_series(self, ohlcv_df: pd.DataFrame) -> None:
        result = calculate_bollinger_bands(ohlcv_df)
        assert set(result.keys()) == {"upper", "middle", "lower", "pct_b"}

    def test_upper_above_lower(self, ohlcv_df: pd.DataFrame) -> None:
        result = calculate_bollinger_bands(ohlcv_df)
        valid = result["upper"].dropna()
        np.testing.assert_array_less(
            result["lower"].dropna().values,
            valid.values,
        )

    def test_pct_b_range(self, ohlcv_df: pd.DataFrame) -> None:
        result = calculate_bollinger_bands(ohlcv_df)
        pct_b = result["pct_b"].dropna()
        # Most values should be roughly between -0.5 and 1.5
        assert pct_b.min() > -2.0
        assert pct_b.max() < 3.0


# ---------------------------------------------------------------------------
# ADX
# ---------------------------------------------------------------------------

class TestADX:
    def test_returns_series(self, ohlcv_df: pd.DataFrame) -> None:
        result = calculate_adx(ohlcv_df)
        assert isinstance(result, pd.Series)
        assert len(result) == len(ohlcv_df)

    def test_values_in_range(self, ohlcv_df: pd.DataFrame) -> None:
        result = calculate_adx(ohlcv_df)
        valid = result.dropna()
        assert valid.min() >= 0
        assert valid.max() <= 100

    def test_missing_columns(self, ohlcv_df: pd.DataFrame) -> None:
        df = ohlcv_df.drop(columns=["High"])
        result = calculate_adx(df)
        assert result.empty


# ---------------------------------------------------------------------------
# Stochastic
# ---------------------------------------------------------------------------

class TestStochastic:
    def test_returns_k_and_d(self, ohlcv_df: pd.DataFrame) -> None:
        result = calculate_stochastic(ohlcv_df)
        assert "k" in result and "d" in result
        assert isinstance(result["k"], pd.Series)

    def test_values_in_range(self, ohlcv_df: pd.DataFrame) -> None:
        result = calculate_stochastic(ohlcv_df)
        k = result["k"].dropna()
        assert k.min() >= 0
        assert k.max() <= 100


# ---------------------------------------------------------------------------
# Williams %R
# ---------------------------------------------------------------------------

class TestWilliamsR:
    def test_returns_series(self, ohlcv_df: pd.DataFrame) -> None:
        result = calculate_williams_r(ohlcv_df)
        assert isinstance(result, pd.Series)

    def test_values_in_range(self, ohlcv_df: pd.DataFrame) -> None:
        result = calculate_williams_r(ohlcv_df)
        valid = result.dropna()
        assert valid.min() >= -100
        assert valid.max() <= 0


# ---------------------------------------------------------------------------
# ROC
# ---------------------------------------------------------------------------

class TestROC:
    def test_returns_series(self, ohlcv_df: pd.DataFrame) -> None:
        result = calculate_roc(ohlcv_df)
        assert isinstance(result, pd.Series)

    def test_known_value(self) -> None:
        """If price goes from 100 to 110 in 10 periods, ROC should be ~10%."""
        prices = list(range(100, 111))
        df = pd.DataFrame({"Close": prices})
        result = calculate_roc(df, period=10)
        assert abs(result.iloc[-1] - 10.0) < 0.1


# ---------------------------------------------------------------------------
# Z-Score
# ---------------------------------------------------------------------------

class TestZScore:
    def test_returns_series(self, ohlcv_df: pd.DataFrame) -> None:
        result = calculate_z_score(ohlcv_df, period=50)
        assert isinstance(result, pd.Series)

    def test_centered_around_zero(self, ohlcv_df: pd.DataFrame) -> None:
        result = calculate_z_score(ohlcv_df, period=50)
        valid = result.dropna()
        # Mean of Z-scores over a random walk should be near 0
        assert abs(valid.mean()) < 2.0


# ---------------------------------------------------------------------------
# Momentum Returns
# ---------------------------------------------------------------------------

class TestMomentumReturns:
    def test_returns_dict(self, ohlcv_df: pd.DataFrame) -> None:
        result = calculate_momentum_returns(ohlcv_df)
        assert isinstance(result, dict)
        assert "returns_21d" in result
        assert "returns_63d" in result
        assert "returns_126d" in result

    def test_short_df_zero_for_long_periods(self, short_df: pd.DataFrame) -> None:
        result = calculate_momentum_returns(short_df)
        # 5 rows can't compute 21d, 63d, 126d returns
        assert result["returns_21d"] == 0.0
        assert result["returns_63d"] == 0.0
        assert result["returns_126d"] == 0.0

    def test_custom_periods(self, ohlcv_df: pd.DataFrame) -> None:
        result = calculate_momentum_returns(ohlcv_df, periods=(5, 10))
        assert "returns_5d" in result
        assert "returns_10d" in result
        assert "returns_21d" not in result
