"""Shared OHLCV data-quality helpers.

A single source of truth for rejecting bad price bars (NaN / zero / negative
``Close``/``Open``/``High``/``Low``) so they cannot corrupt downstream signals
or portfolio prices.

Background: glitchy feed rows (a partial in-progress bar, a holiday, a provider
hiccup) sometimes carry a ``0`` or ``NaN`` price. When such a value is coerced to
``Decimal('0')`` it reads as a phantom -100% move -- which previously flagged
healthy large-caps as EXTREME fear / DOWNTREND and zeroed portfolio prices. These
helpers drop those bars (or skip those reads) everywhere price data enters the
system.

Design notes:
- ``drop_invalid_ohlcv_bars`` is a pure function: no Decimal conversion, index
  preserved, returns a copy. Safe to call before *and* after ``_normalize_ohlcv``
  (idempotent), and on cached frames on read.
- ``Volume`` is intentionally NOT treated as a price: zero volume can be real
  (illiquid names, holidays); only a *negative* volume is rejected.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from collections.abc import Sequence

import pandas as pd

logger = logging.getLogger(__name__)

# Columns that represent a price and must be strictly positive to be usable.
PRICE_COLS: tuple[str, ...] = ("Open", "High", "Low", "Close")


def drop_invalid_ohlcv_bars(
    df: pd.DataFrame,
    *,
    price_cols: Sequence[str] = PRICE_COLS,
) -> pd.DataFrame:
    """Drop rows whose any present price column is NaN, zero, or negative.

    Args:
        df: OHLCV DataFrame (DatetimeIndex preserved). Values may be float or
            ``Decimal`` -- both are coerced numerically for the check.
        price_cols: Price columns to validate (defaults to OHLC). Volume is
            never used as a price; only negative volume is rejected.

    Returns:
        A copy with bad rows removed. If ``df`` is empty/None it is returned
        unchanged. Index is preserved (no reset_index).
    """
    if df is None or df.empty:
        return df

    df = df.copy()
    present = [c for c in price_cols if c in df.columns]
    if not present:
        return df

    mask = pd.Series(True, index=df.index)
    for col in present:
        numeric = pd.to_numeric(df[col], errors="coerce")
        mask &= numeric.notna() & (numeric > 0)

    # Reject only *negative* volume; zero/NaN volume can be legitimate.
    if "Volume" in df.columns:
        volume = pd.to_numeric(df["Volume"], errors="coerce")
        mask &= ~(volume < 0)

    if not bool(mask.all()):
        dropped = int((~mask).sum())
        logger.warning(
            "Dropping %d OHLCV bar(s) with missing/zero/negative price", dropped
        )
        df = df[mask]

    return df


def get_last_valid_close(
    df: pd.DataFrame,
    price_col: str = "Close",
) -> Decimal | None:
    """Return the most recent strictly-positive close as a ``Decimal``.

    Walks backward from the last row, skipping NaN / zero / negative closes, so
    a bad trailing bar never yields a ``$0`` price. Returns ``None`` when no
    valid close exists (callers should treat this like missing data).
    """
    if df is None or df.empty or price_col not in df.columns:
        return None

    numeric = pd.to_numeric(df[price_col], errors="coerce")
    valid = (numeric.notna() & (numeric > 0)).to_numpy().nonzero()[0]
    if len(valid) == 0:
        return None

    raw = df[price_col].iloc[int(valid[-1])]
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return None
