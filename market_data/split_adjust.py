"""Back-adjust OHLCV when Yahoo records a split but leaves the price cliff.

Yahoo sometimes lists a split on the ``Stock Splits`` column while ``Close`` is
still unadjusted (MNST 2:1 on 2026-08-11: ~$90 then ~$45). ``auto_adjust=True``
does not help until Adj Close is populated, and it also dividend-adjusts.

Split-only ratios (≥1.5 or ≤0.667) are matched against close cliffs on the split
date or the next trading bar using relative + absolute tolerance. Pre-split OHLC
is divided by the ratio and ``Volume`` is multiplied. ``Adj Close`` is never
adjusted (Yahoo already split-adjusts it under ``auto_adjust=False``).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Iterable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

PRICE_COLS: tuple[str, ...] = ("Open", "High", "Low", "Close")
DEFAULT_CLIFF_TOLERANCE = 0.15
_MIN_EXPECTED_MOVE = 0.20
_MIN_SPLIT_RATIO = 1.5
_MAX_SPLIT_RATIO = 1.0 / _MIN_SPLIT_RATIO
_SPLIT_COL_ALIASES: tuple[str, ...] = ("Stock Splits", "Stock Split", "Splits")


def _to_date(value: object) -> date | None:
    """Calendar date of a timestamp, keeping the original wall date (no UTC shift)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(ts):
        return None
    return ts.date()


def _sort_by_calendar_date(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy sorted ascending by calendar date (callers may pass unsorted frames)."""
    if df.empty:
        return df.copy()
    out = df.copy()
    if "Date" in out.columns:
        out["_sort_key"] = pd.to_datetime(out["Date"], errors="coerce")
        out = out.sort_values("_sort_key", kind="stable").drop(columns=["_sort_key"])
    elif "date" in out.columns:
        out["_sort_key"] = pd.to_datetime(out["date"], errors="coerce")
        out = out.sort_values("_sort_key", kind="stable").drop(columns=["_sort_key"])
    else:
        out = out.sort_index(kind="stable")
    return out


def _frame_dates(df: pd.DataFrame) -> pd.Series:
    """Vectorized calendar dates aligned to ``df`` row order."""
    if "Date" in df.columns:
        raw = pd.to_datetime(df["Date"], errors="coerce")
        return raw.dt.date
    if "date" in df.columns:
        raw = pd.to_datetime(df["date"], errors="coerce")
        return raw.dt.date
    idx = pd.to_datetime(df.index, errors="coerce")
    if isinstance(idx, pd.DatetimeIndex):
        return pd.Series(idx.date, index=df.index)
    return pd.Series(idx).dt.date


def _close_numeric(df: pd.DataFrame, close_col: str) -> pd.Series:
    if close_col not in df.columns:
        return pd.Series(dtype=float, index=df.index)
    return pd.to_numeric(df[close_col], errors="coerce")


def _is_split_only_ratio(ratio: float) -> bool:
    """Exclude ordinary stock-dividend noise (e.g. 1.05)."""
    return ratio >= _MIN_SPLIT_RATIO or ratio <= _MAX_SPLIT_RATIO


def _nonzero_splits(splits: pd.Series | None) -> pd.Series:
    if splits is None or splits.empty:
        return pd.Series(dtype=float)
    out: dict[date, float] = {}
    for idx, raw in splits.items():
        split_day = _to_date(idx)
        try:
            ratio = float(raw)
        except (TypeError, ValueError):
            continue
        if split_day is None or pd.isna(ratio) or ratio <= 0 or abs(ratio - 1.0) < 1e-9:
            continue
        if not _is_split_only_ratio(ratio):
            continue
        out[split_day] = ratio
    if not out:
        return pd.Series(dtype=float)
    return pd.Series(out)


def splits_from_ohlcv(df: pd.DataFrame) -> pd.Series:
    """Non-zero split ratios keyed by calendar date from a Yahoo history frame."""
    col = next((name for name in _SPLIT_COL_ALIASES if name in df.columns), None)
    if col is None:
        return pd.Series(dtype=float)
    dates = _frame_dates(df)
    ratios = pd.to_numeric(df[col], errors="coerce")
    series = pd.Series(ratios.values, index=pd.Index(dates.values))
    return _nonzero_splits(series)


def merge_split_sources(*sources: pd.Series | None) -> pd.Series:
    """Union of split series; later sources win on duplicate dates."""
    combined = pd.Series(dtype=float)
    for source in sources:
        extra = _nonzero_splits(source)
        if extra.empty:
            continue
        if combined.empty:
            combined = extra
        else:
            combined = extra.combine_first(combined)
    return combined


def _cliff_tolerance(expected: float, cliff_tolerance: float) -> float:
    return max(cliff_tolerance * abs(expected), 0.05)


def _find_prev_position(
    dates: np.ndarray,
    close: np.ndarray,
    split_day: date,
) -> int | None:
    """Last valid close strictly before split day."""
    for i in range(len(close) - 1, -1, -1):
        day = dates[i]
        c = close[i]
        if pd.isna(day) or pd.isna(c) or c <= 0:
            continue
        if day < split_day:
            return i
    return None


def _find_matching_event_position(
    dates: np.ndarray,
    close: np.ndarray,
    split_day: date,
    prev_pos: int,
    ratio: float,
    cliff_tolerance: float,
) -> int | None:
    """First on/after split-day bar whose cliff vs ``prev_pos`` matches the ratio."""
    expected = (1.0 / ratio) - 1.0
    if abs(expected) < _MIN_EXPECTED_MOVE:
        return None

    prev_close = float(close[prev_pos])
    if prev_close <= 0:
        return None

    tol = _cliff_tolerance(expected, cliff_tolerance)
    n = len(close)
    for i in range(n):
        day = dates[i]
        c = close[i]
        if pd.isna(day) or pd.isna(c) or c <= 0 or day < split_day:
            continue

        event_close = float(c)

        actual = (event_close / prev_close) - 1.0
        if abs(actual - expected) <= tol:
            return i
    return None


def apply_unadjusted_splits(
    df: pd.DataFrame,
    splits: pd.Series | None = None,
    *,
    close_col: str = "Close",
    price_cols: Iterable[str] = PRICE_COLS,
    cliff_tolerance: float = DEFAULT_CLIFF_TOLERANCE,
) -> pd.DataFrame:
    """Divide pre-split OHLC by ``ratio`` when a matching unadjusted cliff exists.

    Args:
        df: OHLCV frame with a DatetimeIndex or a Date/date column.
        splits: Optional date -> ratio series merged with ``Stock Splits`` on ``df``.
        close_col: Column used to detect the cliff.
        price_cols: OHLC columns to divide on pre-split bars (not Adj Close).
        cliff_tolerance: Relative factor vs ``1/ratio - 1`` (0.15 = 15%).

    Returns:
        A copy sorted by date with matching cliffs removed.
    """
    if df is None or df.empty:
        return df

    result = _sort_by_calendar_date(df)
    frame_splits = splits_from_ohlcv(result)
    extra = _nonzero_splits(splits)
    if frame_splits.empty and extra.empty:
        return result

    combined = merge_split_sources(frame_splits, extra)
    if combined.empty:
        return result

    dates = _frame_dates(result)
    if dates.isna().all():
        return result

    close = _close_numeric(result, close_col)
    if close.empty:
        return result

    present_price_cols = [col for col in price_cols if col in result.columns]
    if not present_price_cols:
        return result

    dates_arr = dates.to_numpy()
    # Newest first so a later split is applied against still-unadjusted older bars.
    ordered = combined.sort_index(ascending=False)
    scale_volume = "Volume" in result.columns

    for split_day, ratio in ordered.items():
        if not _is_split_only_ratio(ratio):
            continue

        expected = (1.0 / ratio) - 1.0
        if abs(expected) < _MIN_EXPECTED_MOVE:
            continue

        close_arr = close.to_numpy(dtype=float)
        prev_pos = _find_prev_position(dates_arr, close_arr, split_day)
        if prev_pos is None:
            continue

        event_pos = _find_matching_event_position(
            dates_arr, close_arr, split_day, prev_pos, ratio, cliff_tolerance
        )
        if event_pos is None:
            continue

        prev_close = float(close_arr[prev_pos])
        event_close = float(close_arr[event_pos])

        adjust_mask = dates < split_day
        for col in present_price_cols:
            numeric = pd.to_numeric(result[col], errors="coerce").astype(float)
            result.loc[adjust_mask, col] = numeric.loc[adjust_mask] / ratio

        if scale_volume:
            vol = pd.to_numeric(result["Volume"], errors="coerce").astype(float)
            result.loc[adjust_mask, "Volume"] = vol.loc[adjust_mask] * ratio

        close = _close_numeric(result, close_col)
        n_adj = int(adjust_mask.sum())
        actual = (event_close / prev_close) - 1.0
        logger.info(
            "Applied unadjusted split ratio=%s on %s (%s pre-split bars; cliff %.1f%% vs expected %.1f%%)",
            ratio,
            split_day.isoformat(),
            n_adj,
            actual * 100.0,
            expected * 100.0,
        )

    return result
