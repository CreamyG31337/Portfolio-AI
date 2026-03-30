"""Yahoo Finance continuous futures (``*=F``) data quality helpers.

**Empirical check (yfinance ``SI=F``):**

- **2024-11-26:** Volume ~55k but ``(High-Low)/Close`` ≈ 0 (O=H=L=C) — not a trustworthy bar.
- **2025-11-03:** Volume 0 / missing.
- Many 2024 sessions combine **flat OHLC** with **single-digit volume**.

These rows skew normalized commodity charts. Sanitize **before** upserting ``benchmark_data``.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Inclusive USD/oz (or contract-native) closes for Yahoo *continuous* symbols. Values outside
# are almost always contract/multiplier glitches (e.g. SI=F at ~4000 while neighbors ~50).
_YAHOO_FUTURES_CLOSE_BOUNDS: dict[str, tuple[float, float]] = {
    "SI=F": (10.0, 160.0),
    "GC=F": (800.0, 9000.0),
    "CL=F": (10.0, 220.0),
    "NG=F": (0.2, 40.0),
    "HG=F": (1.5, 8.5),
    "ZW=F": (300.0, 1100.0),
}


def sanitize_yahoo_continuous_futures_df(df: pd.DataFrame, ticker: str, name: str) -> pd.DataFrame:
    """Drop zero-volume rows; linearly interpolate closes for zero-range OHLC runs.

    Only tickers ending in ``=F`` are modified (GC=F, SI=F, CL=F, …). Others returned as-is.
    """
    if not str(ticker).endswith("=F"):
        return df

    out = df.sort_values("Date").reset_index(drop=True).copy()

    if "Volume" in out.columns:
        out["Volume"] = pd.to_numeric(out["Volume"], errors="coerce").fillna(0)
        bad_vol = out["Volume"] <= 0
        if bad_vol.any():
            n_drop = int(bad_vol.sum())
            logger.warning(
                "Dropping %d row(s) with missing/zero volume for futures %s (%s)",
                n_drop,
                ticker,
                name,
            )
            out = out.loc[~bad_vol].reset_index(drop=True)

    if len(out) < 3:
        return out

    if not all(c in out.columns for c in ("Open", "High", "Low", "Close")):
        return out

    hi = pd.to_numeric(out["High"], errors="coerce")
    lo = pd.to_numeric(out["Low"], errors="coerce")
    cl = pd.to_numeric(out["Close"], errors="coerce")
    rng_pct = (hi - lo) / cl.replace(0, pd.NA)
    bad_flat = (rng_pct < 1e-4) & cl.notna() & (cl > 0)
    bad_flat = bad_flat.fillna(False).to_numpy()

    closes = cl.astype(float).to_numpy().copy()
    n = len(closes)
    i = 0
    while i < n:
        if not bad_flat[i]:
            i += 1
            continue
        j = i
        while j < n and bad_flat[j]:
            j += 1
        left = closes[i - 1] if i > 0 else None
        right = closes[j] if j < n else None
        run_len = j - i
        if left is not None and right is not None:
            for k in range(run_len):
                alpha = (k + 1) / (run_len + 1)
                new_c = float(left * (1.0 - alpha) + right * alpha)
                idx = i + k
                dt = out.iloc[idx]["Date"]
                logger.warning(
                    "Repaired zero-range Yahoo bar for %s (%s) on %s: interpolated close to %.6f",
                    name,
                    ticker,
                    dt.date() if hasattr(dt, "date") else dt,
                    new_c,
                )
                closes[idx] = new_c
                for col in ("Open", "High", "Low", "Close"):
                    out.iloc[idx, out.columns.get_loc(col)] = new_c
        elif left is not None:
            for k in range(run_len):
                idx = i + k
                dt = out.iloc[idx]["Date"]
                logger.warning(
                    "Repaired leading zero-range bar for %s (%s) on %s: set to %.6f",
                    name,
                    ticker,
                    dt.date() if hasattr(dt, "date") else dt,
                    left,
                )
                closes[idx] = float(left)
                for col in ("Open", "High", "Low", "Close"):
                    out.iloc[idx, out.columns.get_loc(col)] = float(left)
        elif right is not None:
            for k in range(run_len):
                idx = i + k
                dt = out.iloc[idx]["Date"]
                logger.warning(
                    "Repaired trailing zero-range bar for %s (%s) on %s: set to %.6f",
                    name,
                    ticker,
                    dt.date() if hasattr(dt, "date") else dt,
                    right,
                )
                closes[idx] = float(right)
                for col in ("Open", "High", "Low", "Close"):
                    out.iloc[idx, out.columns.get_loc(col)] = float(right)
        i = j

    bounds: Optional[tuple[float, float]] = _YAHOO_FUTURES_CLOSE_BOUNDS.get(str(ticker))
    if bounds is not None:
        lo_b, hi_b = bounds
        cl2 = pd.to_numeric(out["Close"], errors="coerce").astype(float).to_numpy()
        bad_scale = (cl2 < lo_b) | (cl2 > hi_b) | np.isnan(cl2)
        n2 = len(cl2)
        i = 0
        while i < n2:
            if not bad_scale[i]:
                i += 1
                continue
            j = i
            while j < n2 and bad_scale[j]:
                j += 1
            left = float(out.iloc[i - 1]["Close"]) if i > 0 else None
            right = float(out.iloc[j]["Close"]) if j < n2 else None
            run_len = j - i
            if left is not None and right is not None and lo_b <= left <= hi_b and lo_b <= right <= hi_b:
                for k in range(run_len):
                    alpha = (k + 1) / (run_len + 1)
                    new_c = float(left * (1.0 - alpha) + right * alpha)
                    idx = i + k
                    dt = out.iloc[idx]["Date"]
                    logger.warning(
                        "Repaired out-of-band close for %s (%s) on %s (bounds [%.1f,%.1f]): "
                        "interpolated to %.6f",
                        name,
                        ticker,
                        dt.date() if hasattr(dt, "date") else dt,
                        lo_b,
                        hi_b,
                        new_c,
                    )
                    for col in ("Open", "High", "Low", "Close"):
                        out.iloc[idx, out.columns.get_loc(col)] = new_c
            elif left is not None and lo_b <= left <= hi_b:
                for k in range(run_len):
                    idx = i + k
                    dt = out.iloc[idx]["Date"]
                    logger.warning(
                        "Repaired out-of-band close for %s (%s) on %s: set to left anchor %.6f",
                        name,
                        ticker,
                        dt.date() if hasattr(dt, "date") else dt,
                        left,
                    )
                    for col in ("Open", "High", "Low", "Close"):
                        out.iloc[idx, out.columns.get_loc(col)] = left
            elif right is not None and lo_b <= right <= hi_b:
                for k in range(run_len):
                    idx = i + k
                    dt = out.iloc[idx]["Date"]
                    logger.warning(
                        "Repaired out-of-band close for %s (%s) on %s: set to right anchor %.6f",
                        name,
                        ticker,
                        dt.date() if hasattr(dt, "date") else dt,
                        right,
                    )
                    for col in ("Open", "High", "Low", "Close"):
                        out.iloc[idx, out.columns.get_loc(col)] = right
            i = j

    return out
