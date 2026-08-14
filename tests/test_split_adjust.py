"""Tests for unadjusted-split OHLCV back-adjustment."""

from __future__ import annotations

import pandas as pd
import pytest

from market_data.split_adjust import apply_unadjusted_splits
from web_dashboard.signals.fear_risk_signal import FearRiskSignal
from web_dashboard.signals.structure_signal import StructureSignal


def _ohlcv_with_split_cliff() -> pd.DataFrame:
    """MNST-shaped 2:1: ~90 then ~45, split marked on a NaN gap day."""
    idx = pd.bdate_range("2026-05-18", periods=65, freq="C")
    closes = [90.0 + (i % 5) * 0.2 for i in range(62)]
    closes.append(float("nan"))
    closes.extend([45.2, 45.6])
    splits = [0.0] * len(idx)
    splits[62] = 2.0
    return pd.DataFrame(
        {
            "Open": [c * 0.995 if c == c else float("nan") for c in closes],
            "High": [c * 1.01 if c == c else float("nan") for c in closes],
            "Low": [c * 0.99 if c == c else float("nan") for c in closes],
            "Close": closes,
            "Volume": [1_000_000] * len(idx),
            "Stock Splits": splits,
        },
        index=idx,
    )


def _last_pre_split_close(closes_unadjusted: float = 90.0 + (61 % 5) * 0.2) -> float:
    return closes_unadjusted / 2.0


def test_two_for_one_cliff_is_back_adjusted() -> None:
    df = _ohlcv_with_split_cliff()
    adjusted = apply_unadjusted_splits(df)
    last_pre = float(adjusted.loc[adjusted.index < df.index[62], "Close"].iloc[-1])
    assert last_pre == pytest.approx(_last_pre_split_close())
    assert float(adjusted.loc[adjusted.index < df.index[62], "Close"].max()) < 50.0
    assert float(adjusted["Close"].iloc[-1]) == pytest.approx(45.6)
    assert int(adjusted["Volume"].iloc[0]) == 1_000_000
    assert int(adjusted["Volume"].iloc[-1]) == 1_000_000


def test_real_crash_without_split_is_unchanged() -> None:
    idx = pd.bdate_range("2026-05-18", periods=64, freq="C")
    closes = [90.0] * 62 + [45.0, 44.5]
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": [1_000_000] * len(idx),
        },
        index=idx,
    )
    adjusted = apply_unadjusted_splits(df)
    pd.testing.assert_frame_equal(adjusted, df)


def test_recorded_split_without_cliff_is_noop() -> None:
    """Yahoo already adjusted: split row exists but price only moves ~1%."""
    idx = pd.bdate_range("2026-05-18", periods=64, freq="C")
    closes = [45.0] * 62 + [45.4, 45.6]
    splits = [0.0] * 64
    splits[62] = 2.0
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": [1_000_000] * len(idx),
            "Stock Splits": splits,
        },
        index=idx,
    )
    adjusted = apply_unadjusted_splits(df)
    assert float(adjusted["Close"].iloc[0]) == 45.0
    assert float(adjusted["Close"].iloc[-1]) == 45.6


def test_explicit_splits_series_matches_column() -> None:
    df = _ohlcv_with_split_cliff().drop(columns=["Stock Splits"])
    splits = pd.Series([2.0], index=pd.DatetimeIndex([df.index[62]]))
    adjusted = apply_unadjusted_splits(df, splits)
    last_pre = float(adjusted.loc[adjusted.index < df.index[62], "Close"].iloc[-1])
    assert last_pre == pytest.approx(_last_pre_split_close())


def test_date_column_frame_is_supported() -> None:
    raw = _ohlcv_with_split_cliff().reset_index().rename(columns={"index": "Date"})
    adjusted = apply_unadjusted_splits(raw)
    split_day = raw["Date"].iloc[62]
    last_pre = float(adjusted.loc[adjusted["Date"] < split_day, "Close"].iloc[-1])
    assert last_pre == pytest.approx(_last_pre_split_close())


def test_fear_and_trend_recover_after_split_adjust() -> None:
    df = _ohlcv_with_split_cliff().dropna(subset=["Close"])
    raw_fear = FearRiskSignal().evaluate(df)
    assert raw_fear["fear_level"] in {"HIGH", "EXTREME"}
    assert raw_fear["drawdown_pct"] < -10.0

    adjusted = apply_unadjusted_splits(_ohlcv_with_split_cliff()).dropna(subset=["Close"])
    adj_fear = FearRiskSignal().evaluate(adjusted)
    assert adj_fear["drawdown_pct"] > -10.0
    assert adj_fear["fear_level"] != "EXTREME"

    raw_structure = StructureSignal().evaluate(df)
    adj_structure = StructureSignal().evaluate(adjusted)
    assert raw_structure["trend"] == "DOWNTREND"
    assert adj_structure["trend"] != "DOWNTREND"
