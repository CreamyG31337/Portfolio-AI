"""Unit tests for the shared OHLCV data-quality helpers."""
from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from market_data.ohlcv_quality import drop_invalid_ohlcv_bars, get_last_valid_close


def _make_df(n: int = 5) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    base = np.linspace(100.0, 104.0, n)
    return pd.DataFrame(
        {
            "Open": base,
            "High": base + 1,
            "Low": base - 1,
            "Close": base,
            "Volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


# ---------------------------------------------------------------------------
# drop_invalid_ohlcv_bars
# ---------------------------------------------------------------------------

def test_healthy_series_unchanged():
    df = _make_df()
    out = drop_invalid_ohlcv_bars(df)
    assert len(out) == len(df)
    pd.testing.assert_index_equal(out.index, df.index)


def test_drops_zero_close_last_bar():
    df = _make_df()
    df.iloc[-1, df.columns.get_loc("Close")] = 0.0
    out = drop_invalid_ohlcv_bars(df)
    assert len(out) == len(df) - 1
    assert df.index[-1] not in out.index


def test_drops_nan_close_bar():
    df = _make_df()
    df.iloc[2, df.columns.get_loc("Close")] = np.nan
    out = drop_invalid_ohlcv_bars(df)
    assert len(out) == len(df) - 1
    assert df.index[2] not in out.index


def test_drops_row_when_low_bad_but_close_ok():
    """The fetcher's old Close-only filter missed bad Open/High/Low; helper catches it."""
    df = _make_df()
    df.iloc[1, df.columns.get_loc("Low")] = 0.0
    out = drop_invalid_ohlcv_bars(df)
    assert len(out) == len(df) - 1
    assert df.index[1] not in out.index


def test_negative_price_dropped():
    df = _make_df()
    df.iloc[0, df.columns.get_loc("Open")] = -5.0
    out = drop_invalid_ohlcv_bars(df)
    assert df.index[0] not in out.index


def test_zero_volume_kept():
    df = _make_df()
    df.iloc[-1, df.columns.get_loc("Volume")] = 0.0
    out = drop_invalid_ohlcv_bars(df)
    assert len(out) == len(df)  # zero volume is legitimate


def test_negative_volume_dropped():
    df = _make_df()
    df.iloc[-1, df.columns.get_loc("Volume")] = -1.0
    out = drop_invalid_ohlcv_bars(df)
    assert len(out) == len(df) - 1


def test_empty_df_returned_as_is():
    df = pd.DataFrame()
    out = drop_invalid_ohlcv_bars(df)
    assert out.empty


def test_handles_decimal_values():
    df = _make_df(3)
    df["Close"] = [Decimal("100"), Decimal("0"), Decimal("102")]
    out = drop_invalid_ohlcv_bars(df)
    assert len(out) == 2


# ---------------------------------------------------------------------------
# get_last_valid_close
# ---------------------------------------------------------------------------

def test_last_valid_close_simple():
    df = _make_df(3)  # linspace(100, 104, 3) -> [100, 102, 104]
    assert get_last_valid_close(df) == Decimal("104.0")


def test_last_valid_close_skips_trailing_zero():
    df = _make_df(4)
    df.iloc[-1, df.columns.get_loc("Close")] = 0.0
    # should return the prior bar's close, not 0
    assert get_last_valid_close(df) == Decimal(str(df["Close"].iloc[-2]))


def test_last_valid_close_skips_trailing_nan():
    df = _make_df(4)
    df.iloc[-1, df.columns.get_loc("Close")] = np.nan
    assert get_last_valid_close(df) == Decimal(str(df["Close"].iloc[-2]))


def test_last_valid_close_all_invalid_returns_none():
    df = _make_df(3)
    df["Close"] = [0.0, np.nan, -1.0]
    assert get_last_valid_close(df) is None


def test_last_valid_close_empty_returns_none():
    assert get_last_valid_close(pd.DataFrame()) is None


def test_last_valid_close_preserves_decimal_precision():
    df = _make_df(2)
    df["Close"] = [Decimal("210.69"), Decimal("0")]
    assert get_last_valid_close(df) == Decimal("210.69")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
