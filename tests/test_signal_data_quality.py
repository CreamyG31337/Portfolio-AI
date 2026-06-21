"""End-to-end regression tests: a bad OHLCV bar must not corrupt SignalEngine.

Before the OHLCV data-quality fix, a single zero/NaN price bar (coerced to
Decimal('0')) made the WHOLE signal row wrong -- structure DOWNTREND @ $0,
momentum -100% returns, EXTREME fear, overall SELL. SignalEngine now sanitizes
once at the boundary, so appending a glitchy bar must yield the SAME result as
the clean series.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from web_dashboard.signals.signal_engine import SignalEngine


def _make_ohlcv(n: int = 90, start: float = 100.0, step: float = 0.3) -> pd.DataFrame:
    """Gently rising, healthy OHLCV series (deterministic)."""
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    close = start + np.arange(n) * step
    return pd.DataFrame(
        {
            "Open": close - 0.1,
            "High": close + 0.5,
            "Low": close - 0.5,
            "Close": close,
            "Volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


def _with_extra_bar(df: pd.DataFrame, row: list) -> pd.DataFrame:
    out = df.copy()
    out.loc[df.index[-1] + pd.Timedelta(days=1)] = row
    return out


def test_zero_last_bar_matches_clean_series():
    clean = SignalEngine().evaluate("TEST", _make_ohlcv())
    # glitchy $0 bar appended (Open/High/Low/Close all 0)
    dirty = SignalEngine().evaluate(
        "TEST", _with_extra_bar(_make_ohlcv(), [0.0, 0.0, 0.0, 0.0, 1_000_000.0])
    )
    assert dirty["fear_risk"]["fear_level"] == clean["fear_risk"]["fear_level"]
    assert dirty["overall_signal"] == clean["overall_signal"]
    assert dirty["structure"].get("trend") == clean["structure"].get("trend")
    assert dirty["momentum"].get("composite_score") == clean["momentum"].get("composite_score")


def test_nan_close_last_bar_matches_clean_series():
    clean = SignalEngine().evaluate("TEST", _make_ohlcv())
    dirty = SignalEngine().evaluate(
        "TEST", _with_extra_bar(_make_ohlcv(), [127.0, 127.5, 126.5, np.nan, 1_000_000.0])
    )
    assert dirty["fear_risk"]["fear_level"] == clean["fear_risk"]["fear_level"]
    assert dirty["overall_signal"] == clean["overall_signal"]


def test_zero_bar_does_not_produce_phantom_corruption():
    """Explicit checks: no DOWNTREND@0, no -100% drawdown, not EXTREME/SELL."""
    res = SignalEngine().evaluate(
        "TEST", _with_extra_bar(_make_ohlcv(), [0.0, 0.0, 0.0, 0.0, 1_000_000.0])
    )
    assert res["fear_risk"]["fear_level"] != "EXTREME"
    assert res["fear_risk"]["drawdown_pct"] > -90  # not a phantom -100%
    assert res["structure"].get("trend") != "DOWNTREND"
    assert res["overall_signal"] != "SELL"


def test_all_invalid_returns_error_payload():
    bad = _make_ohlcv(5)
    bad["Close"] = 0.0
    res = SignalEngine().evaluate("TEST", bad)
    assert res["overall_signal"] == "HOLD"
    assert res["confidence"] == 0.0
    assert "error" in res


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
