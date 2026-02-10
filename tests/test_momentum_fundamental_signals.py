"""
Tests for MomentumSignal and FundamentalSignal classes.
"""

import numpy as np
import pandas as pd
import pytest

from web_dashboard.signals.momentum_signal import MomentumSignal
from web_dashboard.signals.fundamental_signal import FundamentalSignal, _score_metric
from web_dashboard.signals.signal_engine import SignalEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ohlcv_df() -> pd.DataFrame:
    """150-row synthetic OHLCV with gentle uptrend."""
    np.random.seed(42)
    n = 150
    close = 100 + np.cumsum(np.random.randn(n) * 0.5 + 0.05)
    high = close + np.abs(np.random.randn(n) * 0.3)
    low = close - np.abs(np.random.randn(n) * 0.3)
    volume = np.random.randint(100_000, 1_000_000, size=n).astype(float)
    return pd.DataFrame({
        "Open": close + np.random.randn(n) * 0.1,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    })


@pytest.fixture
def strong_fundamentals() -> dict:
    """Good company: profitable, growing, healthy, reasonably valued."""
    return {
        "return_on_equity": 0.22,
        "net_margin": 0.25,
        "operating_margin": 0.18,
        "revenue_growth": 0.15,
        "earnings_growth": 0.20,
        "current_ratio": 2.5,
        "debt_to_equity": 0.3,
        "free_cash_flow": 500_000_000,
        "trailing_pe": 18.0,
        "forward_pe": 15.0,
        "price_to_book": 2.5,
        "price_to_sales": 3.0,
        "peg_ratio": 1.0,
    }


@pytest.fixture
def weak_fundamentals() -> dict:
    """Weak company: low margins, high debt, expensive."""
    return {
        "return_on_equity": 0.03,
        "net_margin": 0.02,
        "operating_margin": 0.05,
        "revenue_growth": -0.05,
        "earnings_growth": -0.10,
        "current_ratio": 0.8,
        "debt_to_equity": 2.0,
        "free_cash_flow": -100_000,
        "trailing_pe": 60.0,
        "forward_pe": 50.0,
        "price_to_book": 8.0,
        "price_to_sales": 12.0,
        "peg_ratio": 3.0,
    }


@pytest.fixture
def sparse_fundamentals() -> dict:
    """Micro-cap: most fields missing (None)."""
    return {
        "return_on_equity": None,
        "net_margin": None,
        "operating_margin": None,
        "trailing_pe": 12.0,
        "price_to_book": None,
        "revenue_growth": 0.30,
    }


# ---------------------------------------------------------------------------
# MomentumSignal
# ---------------------------------------------------------------------------

class TestMomentumSignal:
    def test_evaluate_returns_expected_keys(self, ohlcv_df: pd.DataFrame) -> None:
        signal = MomentumSignal()
        result = signal.evaluate(ohlcv_df)
        assert "trend_following" in result
        assert "momentum" in result
        assert "mean_reversion" in result
        assert "volatility" in result
        assert "oscillators" in result
        assert "composite_score" in result
        assert "bias" in result

    def test_composite_score_in_range(self, ohlcv_df: pd.DataFrame) -> None:
        signal = MomentumSignal()
        result = signal.evaluate(ohlcv_df)
        assert 0.0 <= result["composite_score"] <= 1.0

    def test_bias_is_valid_string(self, ohlcv_df: pd.DataFrame) -> None:
        signal = MomentumSignal()
        result = signal.evaluate(ohlcv_df)
        assert result["bias"] in ("BULLISH", "BEARISH", "NEUTRAL")

    def test_each_category_has_score(self, ohlcv_df: pd.DataFrame) -> None:
        signal = MomentumSignal()
        result = signal.evaluate(ohlcv_df)
        for cat in ["trend_following", "momentum", "mean_reversion", "volatility", "oscillators"]:
            assert "score" in result[cat]
            assert 0.0 <= result[cat]["score"] <= 1.0

    def test_empty_df_returns_neutral(self) -> None:
        signal = MomentumSignal()
        result = signal.evaluate(pd.DataFrame())
        assert result["bias"] == "NEUTRAL"
        assert result["composite_score"] == 0.5
        assert "error" in result

    def test_insufficient_data_returns_neutral(self) -> None:
        short = pd.DataFrame({"Close": [1, 2, 3], "High": [2, 3, 4], "Low": [0, 1, 2], "Volume": [100, 200, 300]})
        signal = MomentumSignal()
        result = signal.evaluate(short)
        assert result["bias"] == "NEUTRAL"
        assert "error" in result


# ---------------------------------------------------------------------------
# FundamentalSignal - score_metric helper
# ---------------------------------------------------------------------------

class TestScoreMetric:
    def test_none_returns_none(self) -> None:
        assert _score_metric(None, 0.15, "above") is None

    def test_above_at_threshold_gives_half(self) -> None:
        result = _score_metric(0.15, 0.15, "above")
        assert result is not None
        assert abs(result - 0.5) < 0.01

    def test_above_at_double_threshold_gives_one(self) -> None:
        result = _score_metric(0.30, 0.15, "above")
        assert result is not None
        assert abs(result - 1.0) < 0.01

    def test_above_at_zero_gives_zero(self) -> None:
        result = _score_metric(0.0, 0.15, "above")
        assert result is not None
        assert abs(result - 0.0) < 0.01

    def test_below_at_threshold_gives_half(self) -> None:
        result = _score_metric(25.0, 25.0, "below")
        assert result is not None
        assert abs(result - 0.5) < 0.01

    def test_below_at_zero_gives_one(self) -> None:
        result = _score_metric(0.0, 25.0, "below")
        assert result is not None
        assert abs(result - 1.0) < 0.01

    def test_below_at_double_gives_zero(self) -> None:
        result = _score_metric(50.0, 25.0, "below")
        assert result is not None
        assert abs(result - 0.0) < 0.01

    def test_clamped_above(self) -> None:
        result = _score_metric(1.0, 0.15, "above")
        assert result is not None
        assert result <= 1.0

    def test_clamped_below(self) -> None:
        result = _score_metric(100.0, 25.0, "below")
        assert result is not None
        assert result >= 0.0


# ---------------------------------------------------------------------------
# FundamentalSignal
# ---------------------------------------------------------------------------

class TestFundamentalSignal:
    def test_strong_fundamentals_score_high(self, strong_fundamentals: dict) -> None:
        signal = FundamentalSignal()
        result = signal.evaluate(strong_fundamentals)
        assert result["composite_score"] > 0.55
        assert result["quality"] in ("STRONG", "GOOD")

    def test_weak_fundamentals_score_low(self, weak_fundamentals: dict) -> None:
        signal = FundamentalSignal()
        result = signal.evaluate(weak_fundamentals)
        assert result["composite_score"] < 0.4
        assert result["quality"] in ("FAIR", "WEAK")

    def test_sparse_fundamentals_handled(self, sparse_fundamentals: dict) -> None:
        signal = FundamentalSignal()
        result = signal.evaluate(sparse_fundamentals)
        # Should still produce a result with available metrics
        assert result["metrics_available"] > 0
        assert result["quality"] != "UNKNOWN"
        assert "error" not in result

    def test_none_fundamentals(self) -> None:
        signal = FundamentalSignal()
        result = signal.evaluate(None)
        assert result["quality"] == "UNKNOWN"
        assert "error" in result

    def test_empty_dict(self) -> None:
        signal = FundamentalSignal()
        result = signal.evaluate({})
        assert result["quality"] == "UNKNOWN"
        assert "error" in result

    def test_category_details(self, strong_fundamentals: dict) -> None:
        signal = FundamentalSignal()
        result = signal.evaluate(strong_fundamentals)
        for cat in ["profitability", "growth", "health", "valuation"]:
            assert "score" in result[cat]
            assert "metrics_available" in result[cat]
            assert "metrics_total" in result[cat]


# ---------------------------------------------------------------------------
# SignalEngine integration (backward compatibility)
# ---------------------------------------------------------------------------

class TestSignalEngineIntegration:
    def test_evaluate_without_fundamentals(self, ohlcv_df: pd.DataFrame) -> None:
        """Original calling convention still works."""
        engine = SignalEngine()
        result = engine.evaluate("TEST", ohlcv_df)
        assert result["ticker"] == "TEST"
        assert result["overall_signal"] in ("BUY", "SELL", "HOLD", "WATCH")
        assert 0.0 <= result["confidence"] <= 1.0
        # New keys present
        assert "momentum" in result
        assert "fundamental" in result

    def test_evaluate_with_fundamentals(
        self, ohlcv_df: pd.DataFrame, strong_fundamentals: dict
    ) -> None:
        engine = SignalEngine()
        result = engine.evaluate("TEST", ohlcv_df, fundamentals=strong_fundamentals)
        assert result["fundamental"]["quality"] in ("STRONG", "GOOD", "FAIR", "WEAK")
        assert result["fundamental"]["metrics_available"] > 0

    def test_error_returns_hold(self) -> None:
        engine = SignalEngine()
        result = engine.evaluate("BADTICKER", pd.DataFrame())
        assert result["overall_signal"] == "HOLD"
        assert result["confidence"] == 0.0
