"""Tests for shared Yahoo history post-processing."""

from __future__ import annotations

import pandas as pd
import pytest

from market_data.data_fetcher import MarketDataFetcher
from market_data.yahoo_history import flatten_yahoo_columns, prepare_unadjusted_yahoo_history
from web_dashboard.signals.fear_risk_signal import FearRiskSignal


def _mnst_multiindex_frame() -> pd.DataFrame:
    """Yfinance-style MultiIndex with ticker on level 1."""
    idx = pd.bdate_range("2026-05-18", periods=65, freq="C")
    closes = [90.0 + (i % 5) * 0.2 for i in range(62)]
    closes.append(float("nan"))
    closes.extend([45.2, 45.6])
    splits = [0.0] * len(idx)
    splits[62] = 2.0
    flat = pd.DataFrame(
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
    flat.columns = pd.MultiIndex.from_tuples([(col, "MNST") for col in flat.columns])
    return flat


def test_flatten_yahoo_columns_single_ticker() -> None:
    raw = _mnst_multiindex_frame()
    flat = flatten_yahoo_columns(raw)
    assert "Stock Splits" in flat.columns
    assert "Close" in flat.columns
    assert not isinstance(flat.columns, pd.MultiIndex)


def test_prepare_unadjusted_yahoo_history_adjusts_cliff() -> None:
    raw = flatten_yahoo_columns(_mnst_multiindex_frame())
    prepared = prepare_unadjusted_yahoo_history(raw)
    split_day = raw.index[62]
    last_pre = float(prepared.loc[prepared.index < split_day, "Close"].iloc[-1])
    assert last_pre < 50.0
    assert float(prepared["Close"].iloc[-1]) == pytest.approx(45.6)


def test_yahoo_ohlcv_frame_multiindex_not_empty() -> None:
    fetcher = MarketDataFetcher()
    out = fetcher._yahoo_ohlcv_frame(_mnst_multiindex_frame())
    assert not out.empty
    assert "Close" in out.columns


def test_mnst_shaped_frame_fear_low_after_prepare() -> None:
    raw = flatten_yahoo_columns(_mnst_multiindex_frame()).dropna(subset=["Close"])
    prepared = prepare_unadjusted_yahoo_history(_mnst_multiindex_frame()).dropna(subset=["Close"])
    raw_fear = FearRiskSignal().evaluate(raw)
    adj_fear = FearRiskSignal().evaluate(prepared)
    assert raw_fear["fear_level"] in {"HIGH", "EXTREME"}
    assert adj_fear["fear_level"] == "LOW"
