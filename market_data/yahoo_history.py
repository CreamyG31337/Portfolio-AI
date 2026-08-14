"""Shared post-processing for unadjusted Yahoo ``history()`` frames."""

from __future__ import annotations

import logging

import pandas as pd

from .split_adjust import apply_unadjusted_splits

logger = logging.getLogger(__name__)


def flatten_yahoo_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten MultiIndex columns from yfinance download/history responses."""
    if not isinstance(df.columns, pd.MultiIndex):
        return df
    try:
        if len(set(df.columns.get_level_values(1))) == 1:
            out = df.copy()
            out.columns = out.columns.get_level_values(0)
            return out
        out = df.copy()
        out.columns = ["_".join(map(str, t)).strip("_") for t in out.columns.to_flat_index()]
        return out
    except Exception:
        out = df.copy()
        out.columns = ["_".join(map(str, t)).strip("_") for t in out.columns.to_flat_index()]
        return out


def prepare_unadjusted_yahoo_history(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten MultiIndex columns, sort, and back-adjust unadjusted split cliffs.

    Uses only ``Stock Splits`` already on the ``history()`` frame — no extra
    ``ticker.splits`` network round-trip.
    """
    if df is None or df.empty:
        return df
    flat = flatten_yahoo_columns(df)
    return apply_unadjusted_splits(flat)
