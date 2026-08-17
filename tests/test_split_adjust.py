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
    split_day = df.index[62]
    last_pre = float(adjusted.loc[adjusted.index < split_day, "Close"].iloc[-1])
    assert last_pre == pytest.approx(_last_pre_split_close())
    assert float(adjusted.loc[adjusted.index < split_day, "Close"].max()) < 50.0
    assert float(adjusted["Close"].iloc[-1]) == pytest.approx(45.6)
    assert int(adjusted["Volume"].iloc[0]) == 2_000_000
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
    split_day = df.index[62]
    last_pre = float(adjusted.loc[adjusted.index < split_day, "Close"].iloc[-1])
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


def test_small_ratio_105_dividend_no_adjust() -> None:
    """1.05 stock-dividend marker plus ordinary -3% day must not adjust."""
    idx = pd.bdate_range("2026-06-01", periods=5, freq="C")
    closes = [100.0, 99.5, 99.0, 96.0, 95.5]
    splits = [0.0, 0.0, 1.05, 0.0, 0.0]
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": [500_000] * 5,
            "Stock Splits": splits,
        },
        index=idx,
    )
    adjusted = apply_unadjusted_splits(df)
    pd.testing.assert_series_equal(adjusted["Close"], df["Close"])


def test_crash_with_recorded_split_not_adjusted() -> None:
    """Real ~60% crash with a 2:1 split marker must not match split tolerance."""
    idx = pd.bdate_range("2026-06-01", periods=4, freq="C")
    closes = [90.0, 89.0, 35.6, 35.0]
    splits = [0.0, 0.0, 2.0, 0.0]
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": [1_000_000] * 4,
            "Stock Splits": splits,
        },
        index=idx,
    )
    adjusted = apply_unadjusted_splits(df)
    pd.testing.assert_series_equal(adjusted["Close"], df["Close"])


def test_already_adjusted_series_no_double_adjust() -> None:
    """Continuous post-split prices with a stale 2:1 marker must not adjust."""
    idx = pd.bdate_range("2026-06-01", periods=4, freq="C")
    closes = [22.5, 22.0, 22.5, 22.8]
    splits = [0.0, 0.0, 2.0, 0.0]
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": [1_000_000] * 4,
            "Stock Splits": splits,
        },
        index=idx,
    )
    adjusted = apply_unadjusted_splits(df)
    pd.testing.assert_series_equal(adjusted["Close"], df["Close"])


def test_duplicate_index_no_typeerror() -> None:
    """Repeated timestamps must not raise when detecting cliffs."""
    ts = pd.Timestamp("2026-06-01")
    idx = pd.DatetimeIndex([ts, ts, ts + pd.Timedelta(days=1)])
    closes = [90.0, 90.1, 45.0]
    splits = [0.0, 0.0, 2.0]
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": [100, 100, 100],
            "Stock Splits": splits,
        },
        index=idx,
    )
    adjusted = apply_unadjusted_splits(df)
    assert float(adjusted["Close"].iloc[0]) == pytest.approx(45.0)
    assert float(adjusted["Close"].iloc[1]) == pytest.approx(45.05)


def test_split_on_first_bar_of_short_window_still_adjusts() -> None:
    """5d retry starting on the ex-date must still catch the next-bar cliff."""
    idx = pd.bdate_range("2026-08-11", periods=4, freq="C")
    closes = [90.0, 45.0, 45.2, 45.4]
    splits = [2.0, 0.0, 0.0, 0.0]
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": [1_000_000] * 4,
            "Stock Splits": splits,
        },
        index=idx,
    )
    adjusted = apply_unadjusted_splits(df)
    assert float(adjusted["Close"].iloc[0]) == pytest.approx(45.0)
    assert float(adjusted["Close"].iloc[-1]) == pytest.approx(45.4)
    assert int(adjusted["Volume"].iloc[0]) == 2_000_000


def test_cliff_on_next_trading_bar() -> None:
    """Split-day close still pre-split; cliff appears on T+1."""
    idx = pd.bdate_range("2026-06-01", periods=5, freq="C")
    closes = [90.0, 90.2, 90.0, 90.1, 45.0]
    splits = [0.0, 0.0, 2.0, 0.0, 0.0]
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": [1_000_000] * 5,
            "Stock Splits": splits,
        },
        index=idx,
    )
    adjusted = apply_unadjusted_splits(df)
    split_day = idx[2]
    pre_bars = adjusted.loc[adjusted.index < split_day, "Close"]
    assert float(pre_bars.iloc[-1]) == pytest.approx(45.1)
    assert float(adjusted["Close"].iloc[-1]) == pytest.approx(45.0)


def test_volume_scaled_on_pre_split_bars() -> None:
    df = _ohlcv_with_split_cliff()
    adjusted = apply_unadjusted_splits(df)
    split_day = df.index[62]
    pre_vol = adjusted.loc[adjusted.index < split_day, "Volume"]
    post_vol = adjusted.loc[adjusted.index >= split_day, "Volume"]
    assert int(pre_vol.iloc[0]) == 2_000_000
    assert int(post_vol.iloc[-1]) == 1_000_000


def test_adj_close_unchanged_when_present() -> None:
    idx = pd.bdate_range("2026-06-01", periods=4, freq="C")
    closes = [90.0, 90.0, 45.0, 45.5]
    adj_close = [45.0, 45.0, 45.0, 45.5]
    splits = [0.0, 0.0, 2.0, 0.0]
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Adj Close": adj_close,
            "Volume": [1_000_000] * 4,
            "Stock Splits": splits,
        },
        index=idx,
    )
    adjusted = apply_unadjusted_splits(df)
    pd.testing.assert_series_equal(adjusted["Adj Close"], df["Adj Close"])
    assert float(adjusted.loc[adjusted.index < idx[2], "Close"].iloc[-1]) == pytest.approx(45.0)


# --- Regression coverage for the PR review findings -------------------------


def _flat_series_frame(closes, splits, volume=1_000_000) -> pd.DataFrame:
    idx = pd.bdate_range("2026-01-01", periods=len(closes), freq="C")
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": [volume] * len(closes),
            "Stock Splits": splits,
        },
        index=idx,
    )


def test_already_adjusted_series_survives_a_later_decline() -> None:
    """A slow drift to half price months later must not be read as the split cliff."""
    n = 200
    closes = [45.0] * 60 + [45.0 - 21.0 * (i / (n - 61)) for i in range(n - 60)]
    splits = [0.0] * n
    splits[60] = 2.0
    adjusted = apply_unadjusted_splits(_flat_series_frame(closes, splits))
    assert float(adjusted["Close"].iloc[0]) == pytest.approx(45.0)


def test_reverse_split_then_legitimate_double_is_untouched() -> None:
    n = 200
    closes = [10.0] * 60 + [10.0 + 10.0 * (i / (n - 61)) for i in range(n - 60)]
    splits = [0.0] * n
    splits[60] = 0.5
    adjusted = apply_unadjusted_splits(_flat_series_frame(closes, splits))
    assert float(adjusted["Close"].iloc[0]) == pytest.approx(10.0)


def test_split_day_bar_is_adjusted_when_the_cliff_lags() -> None:
    """No phantom spike: the stamped bar is pre-split too and must be scaled."""
    closes = [90.0] * 61 + [45.0] * 59
    splits = [0.0] * 120
    splits[60] = 2.0
    adjusted = apply_unadjusted_splits(_flat_series_frame(closes, splits))
    window = [float(v) for v in adjusted["Close"].iloc[58:63]]
    assert window == pytest.approx([45.0] * 5)


def test_int64_price_columns_are_not_truncated() -> None:
    df = _flat_series_frame([91, 91, 45, 45], [0.0, 0.0, 2.0, 0.0])
    for col in ("Open", "High", "Low", "Close"):
        df[col] = df[col].astype("int64")
    adjusted = apply_unadjusted_splits(df)
    assert float(adjusted["Close"].iloc[0]) == pytest.approx(45.5)


def test_decimal_price_columns_stay_decimal() -> None:
    from decimal import Decimal

    values = [Decimal("90.10"), Decimal("90.10"), Decimal("45.05"), Decimal("45.05")]
    df = _flat_series_frame(values, [0.0, 0.0, 2.0, 0.0])
    adjusted = apply_unadjusted_splits(df)
    assert all(isinstance(v, Decimal) for v in adjusted["Close"])
    assert adjusted["Close"].iloc[0] == pytest.approx(Decimal("45.05"))


def test_int64_volume_survives_a_lossy_reverse_split() -> None:
    df = _flat_series_frame([1.0, 1.0, 10.0, 10.0], [0.0, 0.0, 0.1, 0.0])
    df["Volume"] = pd.Series([1234567, 2345678, 3456789, 4567890], index=df.index).astype("int64")
    adjusted = apply_unadjusted_splits(df)
    assert float(adjusted["Close"].iloc[0]) == pytest.approx(10.0)
    assert int(adjusted["Volume"].iloc[0]) == 123457
    assert int(adjusted["Volume"].iloc[-1]) == 4567890


def test_adj_close_is_never_rescaled() -> None:
    df = _flat_series_frame([90.0, 90.0, 45.0, 45.0], [0.0, 0.0, 2.0, 0.0])
    df["Adj Close"] = df["Close"]
    adjusted = apply_unadjusted_splits(df)
    assert float(adjusted["Adj Close"].iloc[0]) == pytest.approx(90.0)
    assert float(adjusted["Close"].iloc[0]) == pytest.approx(45.0)


def test_frame_without_splits_is_returned_unchanged() -> None:
    """Hot path: no split means no sort and no copy."""
    df = _flat_series_frame([90.0, 90.5, 91.0, 90.2], [0.0, 0.0, 0.0, 0.0])
    assert apply_unadjusted_splits(df) is df


def test_stock_dividend_ratio_never_triggers() -> None:
    closes = [100.0, 100.0, 95.5, 95.0]
    df = _flat_series_frame(closes, [0.0, 0.0, 1.05, 0.0])
    adjusted = apply_unadjusted_splits(df)
    assert float(adjusted["Close"].iloc[0]) == pytest.approx(100.0)


def test_unsorted_frame_with_date_column_is_handled() -> None:
    closes = [90.0, 90.0, 45.0, 45.0]
    df = pd.DataFrame(
        {
            "Date": pd.bdate_range("2026-01-01", periods=4, freq="C"),
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": [1_000_000] * 4,
            "Stock Splits": [0.0, 0.0, 2.0, 0.0],
        }
    ).iloc[::-1]
    adjusted = apply_unadjusted_splits(df)
    assert float(adjusted["Close"].iloc[0]) == pytest.approx(45.0)
    assert float(adjusted["Close"].iloc[-1]) == pytest.approx(45.0)
