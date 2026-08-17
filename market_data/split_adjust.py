"""Back-adjust OHLCV when Yahoo records a split but leaves the price cliff.

Yahoo sometimes lists a split on the ``Stock Splits`` column while the price
history is still unadjusted (MNST 2:1 on 2026-08-11: ~$90 then ~$45). Verified
against the live feed on 2026-08-14: for that window Yahoo returned
``Adj Close == Close == 94.18`` on the pre-split bars, so *neither* column was
back-adjusted and ``auto_adjust=True`` changed nothing. That is why the cliff
has to be detected from the prices themselves rather than read off ``Adj Close``.

Only split-sized ratios (>=1.5 or <=0.667) are considered, so ordinary stock
dividends (1.05) can never trigger an adjustment. The ratio is matched against
the close gap **at the split boundary only** -- the split-date bar, or the bar
after it when Yahoo stamps the split a day before the price actually moves.
Searching further ahead would match any later move of a similar size and rewrite
correct history, so the window is deliberately two bars wide.

Pre-split OHLC is divided by the ratio and ``Volume`` is multiplied by it.
``Adj Close`` is left alone: on the paths that request it, it tracks ``Close``
(above), and callers that want dividend-adjusted prices should use
``auto_adjust=True`` rather than have this helper rescale it.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable

import numpy as np
import pandas as pd

from .ohlcv_quality import PRICE_COLS

logger = logging.getLogger(__name__)

DEFAULT_CLIFF_TOLERANCE = 0.15
# Absolute floor so the accept window never shrinks onto an ordinary day's move.
MIN_CLIFF_TOLERANCE = 0.05
# Below this, a "split" is a stock dividend and its cliff is indistinguishable
# from routine volatility; refuse to act on it at all.
_MIN_SPLIT_RATIO = 1.5
_MAX_SPLIT_RATIO = 1.0 / _MIN_SPLIT_RATIO
# How many bars after the stamped split date the cliff may appear. Yahoo
# occasionally stamps the split before the price actually moves. Kept tiny on
# purpose: widen this and any later move of split-like size starts matching.
_MAX_CLIFF_LAG_BARS = 2
_SPLIT_COL_ALIASES: tuple[str, ...] = ("Stock Splits", "Stock Split", "Splits")

__all__ = [
    "PRICE_COLS",
    "DEFAULT_CLIFF_TOLERANCE",
    "apply_unadjusted_splits",
    "splits_from_ohlcv",
    "merge_split_sources",
]


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
    out = df.copy()
    for col in ("Date", "date"):
        if col in out.columns:
            out["_sort_key"] = pd.to_datetime(out[col], errors="coerce")
            return out.sort_values("_sort_key", kind="stable").drop(columns=["_sort_key"])
    return out.sort_index(kind="stable")


def _frame_dates(df: pd.DataFrame) -> pd.Series:
    """Vectorized calendar dates aligned to ``df`` row order.

    Every branch keeps ``df.index`` so the boolean masks built from the result
    stay alignable with the frame itself.
    """
    for col in ("Date", "date"):
        if col in df.columns:
            return pd.to_datetime(df[col], errors="coerce").dt.date
    idx = pd.to_datetime(df.index, errors="coerce")
    if isinstance(idx, pd.DatetimeIndex):
        return pd.Series(idx.date, index=df.index)
    return pd.Series([_to_date(value) for value in df.index], index=df.index)


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
    ratios = pd.to_numeric(df[col], errors="coerce")
    if not (ratios.fillna(0) != 0).any():
        # Overwhelmingly common case: skip the per-row date conversion entirely.
        return pd.Series(dtype=float)
    dates = _frame_dates(df)
    series = pd.Series(ratios.values, index=pd.Index(dates.values))
    return _nonzero_splits(series)


def merge_split_sources(*sources: pd.Series | None) -> pd.Series:
    """Union of split series; later sources win on duplicate dates."""
    combined = pd.Series(dtype=float)
    for source in sources:
        extra = _nonzero_splits(source)
        if extra.empty:
            continue
        combined = extra if combined.empty else extra.combine_first(combined)
    return combined


def _find_boundary_cliff(
    dates: np.ndarray,
    close: np.ndarray,
    split_day: date,
    ratio: float,
    cliff_tolerance: float,
) -> tuple[int, int] | None:
    """Positions ``(last_pre_split, event)`` of a split cliff at the boundary.

    Considers the gap landing on the split date plus the next
    ``_MAX_CLIFF_LAG_BARS``, since Yahoo sometimes stamps the split before the
    price actually moves. A split stamped on the first in-window bar (common
    for ``period="5d"`` retries) still matches a cliff on the following bars.
    Returns ``None`` when none matches, which is also how an already-adjusted
    series is recognised -- it simply has no cliff there.
    """
    expected = (1.0 / ratio) - 1.0
    tol = max(cliff_tolerance * abs(expected), MIN_CLIFF_TOLERANCE)

    valid = [
        i
        for i in range(len(close))
        if dates[i] is not None
        and not pd.isna(dates[i])
        and not pd.isna(close[i])
        and close[i] > 0
    ]
    first_after = next((k for k, i in enumerate(valid) if dates[i] >= split_day), None)
    if first_after is None:
        return None

    # A 5d Yahoo retry often starts on the ex-date, so the split is stamped on
    # the first in-window bar. Still look at the following bars for a cliff;
    # there is just no earlier bar to treat as pre-split.
    start_k = max(first_after, 1)
    end_k = min(first_after + 1 + _MAX_CLIFF_LAG_BARS, len(valid))
    if start_k >= end_k:
        return None

    for k in range(start_k, end_k):
        prev_pos, event_pos = valid[k - 1], valid[k]
        actual = (float(close[event_pos]) / float(close[prev_pos])) - 1.0
        if abs(actual - expected) <= tol:
            return prev_pos, event_pos
    return None


def _scale_column(
    column: pd.Series,
    mask: np.ndarray,
    factor: float,
    *,
    keep_integer: bool = False,
) -> pd.Series:
    """Multiply masked rows by ``factor`` without corrupting the column dtype.

    ``Decimal`` columns stay ``Decimal`` rather than ending up a mix of
    ``Decimal`` and ``float``. Integer columns are promoted to float so a
    scaled price is never truncated (91/2 must be 45.5, not 45); pass
    ``keep_integer`` for counts like ``Volume``, which are rounded back instead.
    """
    if column.dtype == object:
        values = column.to_numpy(dtype=object, copy=True)
        dec_factor = Decimal(str(factor))
        for i in np.flatnonzero(mask):
            value = values[i]
            if isinstance(value, Decimal):
                try:
                    values[i] = value * dec_factor
                except InvalidOperation:
                    values[i] = value
            elif value is not None and not pd.isna(value):
                try:
                    values[i] = float(value) * factor
                except (TypeError, ValueError):
                    values[i] = value
        return pd.Series(values, index=column.index, name=column.name)

    scaled = pd.to_numeric(column, errors="coerce").to_numpy(dtype="float64", copy=True)
    scaled[mask] = scaled[mask] * factor
    if (
        keep_integer
        and pd.api.types.is_integer_dtype(column.dtype)
        and not np.isnan(scaled).any()
    ):
        return pd.Series(
            np.rint(scaled).astype(column.dtype), index=column.index, name=column.name
        )
    return pd.Series(scaled, index=column.index, name=column.name)


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
        cliff_tolerance: Relative factor vs ``1/ratio - 1`` (0.15 = 15%), floored
            at ``MIN_CLIFF_TOLERANCE`` in absolute terms.

    Returns:
        ``df`` itself when there is no split to act on (the common case, kept
        allocation-free); otherwise a date-sorted copy with matching cliffs
        removed. ``Volume`` on adjusted bars is multiplied by the ratio so it
        stays continuous with the rescaled prices.
    """
    if df is None or df.empty:
        return df

    # Check for splits before copying: most frames have none and this runs on
    # every price fetch.
    frame_splits = splits_from_ohlcv(df)
    extra = _nonzero_splits(splits)
    if frame_splits.empty and extra.empty:
        return df

    combined = merge_split_sources(frame_splits, extra)
    if combined.empty:
        return df

    result = _sort_by_calendar_date(df)
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
    positions = np.arange(len(result))
    scale_volume = "Volume" in result.columns

    # Newest first so a later split is applied against still-unadjusted older bars.
    for split_day, ratio in combined.sort_index(ascending=False).items():
        close_arr = close.to_numpy(dtype=float)
        found = _find_boundary_cliff(dates_arr, close_arr, split_day, ratio, cliff_tolerance)
        if found is None:
            continue
        prev_pos, event_pos = found

        # Mask by position, not by date: when Yahoo stamps the split a bar early
        # the split-date bar is itself still pre-split and must be adjusted too.
        adjust_mask = positions <= prev_pos

        for col in present_price_cols:
            result[col] = _scale_column(result[col], adjust_mask, 1.0 / ratio)
        if scale_volume:
            result["Volume"] = _scale_column(
                result["Volume"], adjust_mask, ratio, keep_integer=True
            )

        close = _close_numeric(result, close_col)
        expected = (1.0 / ratio) - 1.0
        actual = (float(close_arr[event_pos]) / float(close_arr[prev_pos])) - 1.0
        logger.info(
            "Applied unadjusted split ratio=%s on %s (%s pre-split bars; "
            "cliff %.1f%% vs expected %.1f%%)",
            ratio,
            split_day.isoformat(),
            int(adjust_mask.sum()),
            actual * 100.0,
            expected * 100.0,
        )

    return result
