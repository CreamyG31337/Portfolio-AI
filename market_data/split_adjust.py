"""Back-adjust OHLCV when Yahoo records a split but leaves the price cliff.

Yahoo sometimes lists a split on ``ticker.splits`` / the ``Stock Splits`` column
while ``Close`` is still unadjusted (MNST 2:1 on 2026-08-11: ~$90 then ~$45).
``auto_adjust=True`` does not help until Adj Close is populated, and it also
dividend-adjusts.

This helper divides pre-split OHLC by the split ratio **only** when the close
change on the split date (or the next trading bar) matches ``1/ratio - 1``
within a relative tolerance. Real crashes with no matching split are unchanged.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Iterable

import pandas as pd

logger = logging.getLogger(__name__)

PRICE_COLS: tuple[str, ...] = ("Open", "High", "Low", "Close", "Adj Close")
DEFAULT_CLIFF_TOLERANCE = 0.15
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


def _frame_dates(df: pd.DataFrame) -> pd.Series:
    if "Date" in df.columns:
        raw = df["Date"]
    elif "date" in df.columns:
        raw = df["date"]
    else:
        raw = pd.Series(df.index, index=df.index)
    return raw.map(_to_date)


def _close_numeric(df: pd.DataFrame, close_col: str) -> pd.Series:
    if close_col not in df.columns:
        return pd.Series(dtype=float, index=df.index)
    return pd.to_numeric(df[close_col], errors="coerce")


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
        splits: Optional date -> ratio series (e.g. ``ticker.splits``). Merged
            with any ``Stock Splits`` column on ``df``.
        close_col: Column used to detect the cliff.
        price_cols: Columns to divide on pre-split bars.
        cliff_tolerance: Relative tolerance vs ``1/ratio - 1`` (0.15 = 15%).

    Returns:
        A copy with matching cliffs removed. Unchanged when there is no split
        or the move does not match the recorded ratio.
    """
    if df is None or df.empty:
        return df

    combined = merge_split_sources(splits_from_ohlcv(df), splits)
    if combined.empty:
        return df

    dates = _frame_dates(df)
    if dates.isna().all():
        return df

    close = _close_numeric(df, close_col)
    if close.empty:
        return df

    present_price_cols = [col for col in price_cols if col in df.columns]
    if not present_price_cols:
        return df

    result = df.copy()
    # Newest first so a later split is applied against still-unadjusted older bars.
    ordered = combined.sort_index(ascending=False)
    for split_day, ratio in ordered.items():
        expected = (1.0 / ratio) - 1.0
        if abs(expected) < 1e-9:
            continue

        on_or_after = dates.map(lambda d, day=split_day: d is not None and d >= day)
        event_candidates = close.index[on_or_after & close.notna() & (close > 0)]
        if len(event_candidates) == 0:
            continue
        event_idx = event_candidates[0]

        before = dates.map(lambda d, day=split_day: d is not None and d < day)
        prev_candidates = close.index[before & close.notna() & (close > 0)]
        if len(prev_candidates) == 0:
            continue
        prev_idx = prev_candidates[-1]

        prev_close = float(close.loc[prev_idx])
        event_close = float(close.loc[event_idx])
        if prev_close <= 0:
            continue
        actual = (event_close / prev_close) - 1.0
        if abs(actual - expected) > cliff_tolerance * abs(expected):
            continue

        adjust_mask = before
        for col in present_price_cols:
            numeric = pd.to_numeric(result[col], errors="coerce")
            result.loc[adjust_mask, col] = numeric[adjust_mask] / ratio

        close = _close_numeric(result, close_col)
        n_adj = int(adjust_mask.sum())
        logger.info(
            "Applied unadjusted split ratio=%s on %s (%s pre-split bars; cliff %.1f%% vs expected %.1f%%)",
            ratio,
            split_day.isoformat(),
            n_adj,
            actual * 100.0,
            expected * 100.0,
        )

    return result
