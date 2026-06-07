"""Canonical benchmark futures ingest: validate/repair + structured QC logging (no quarantine table)."""

from __future__ import annotations

import logging
import random
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from scheduler.benchmark_futures_quality import sanitize_yahoo_continuous_futures_df

logger = logging.getLogger(__name__)

BENCHMARK_QC_PREFIX = "[benchmark_qc]"

# CL=F: oil is more volatile than gold; thresholds slightly looser than GC but still catch ~0.5x regime junk.
_CL_DETACHED_LOW_FACTOR = 0.62
_CL_DETACHED_HIGH_FACTOR = 1.58
_CL_DETACHED_ANCHOR_ALIGN = 0.07
_CL_DETACHED_MIN_RUN = 2
_CL_DETACHED_MAX_RUN = 8


def log_benchmark_qc_event(ev: dict[str, Any]) -> None:
    """Emit one grep-friendly line per QC event."""
    parts = [BENCHMARK_QC_PREFIX, f"action={ev.get('action')}"]
    for key in ("ticker", "name", "date", "old_close", "new_close", "db_close", "yahoo_close", "ratio"):
        if key in ev and ev[key] is not None:
            parts.append(f"{key}={ev[key]}")
    logger.warning(" ".join(str(p) for p in parts))


def _repair_cl_detached_regime_runs(
    out: pd.DataFrame, ticker: str, name: str
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Multi-day CL=F closes detached from stable anchors (splice / scale glitches)."""
    events: list[dict[str, Any]] = []
    if len(out) < _CL_DETACHED_MIN_RUN + 2:
        return out, events

    c = pd.to_numeric(out["Close"], errors="coerce").astype(float).to_numpy().copy()
    n = len(c)
    i = 1
    while i < n - _CL_DETACHED_MIN_RUN:
        best_e: int | None = None
        left_a = float(np.nanmedian(c[max(0, i - 5) : i]))
        if left_a <= 0 or np.isnan(left_a):
            i += 1
            continue

        for e in range(i + _CL_DETACHED_MIN_RUN - 1, min(i + _CL_DETACHED_MAX_RUN - 1, n - 2) + 1):
            right_seg = c[e + 1 : min(n, e + 6)]
            if len(right_seg) == 0:
                continue
            right_a = float(np.nanmedian(right_seg))
            if right_a <= 0 or np.isnan(right_a):
                continue
            regime_mid = (left_a + right_a) / 2.0
            if abs(left_a - right_a) / regime_mid > _CL_DETACHED_ANCHOR_ALIGN:
                continue
            seg = c[i : e + 1]
            if np.any(np.isnan(seg)):
                continue
            low_thr = min(left_a, right_a) * _CL_DETACHED_LOW_FACTOR
            high_thr = max(left_a, right_a) * _CL_DETACHED_HIGH_FACTOR
            if np.all(seg < low_thr):
                best_e = e
            elif np.all(seg > high_thr):
                best_e = e

        if best_e is not None:
            right_a = float(np.nanmedian(c[best_e + 1 : min(n, best_e + 6)]))
            left_a = float(np.nanmedian(c[max(0, i - 5) : i]))
            regime_mid = (left_a + right_a) / 2.0
            if (
                left_a > 0
                and right_a > 0
                and not np.isnan(left_a)
                and not np.isnan(right_a)
                and abs(left_a - right_a) / regime_mid <= _CL_DETACHED_ANCHOR_ALIGN
            ):
                new_vals = np.linspace(left_a, right_a, (best_e - i) + 3)[1:-1]
                for k, idx in enumerate(range(i, best_e + 1)):
                    new_c = float(new_vals[k])
                    old_c = float(c[idx])
                    dt = out.iloc[idx]["Date"]
                    d_str = (
                        dt.date().isoformat()
                        if hasattr(dt, "date")
                        else pd.Timestamp(dt).date().isoformat()
                    )
                    events.append(
                        {
                            "action": "repair_cl_detached_regime",
                            "ticker": ticker,
                            "name": name,
                            "date": d_str,
                            "old_close": round(old_c, 6),
                            "new_close": round(new_c, 6),
                        }
                    )
                    c[idx] = new_c
                    for col in ("Open", "High", "Low", "Close"):
                        out.iloc[idx, out.columns.get_loc(col)] = new_c
            i = best_e + 1
        else:
            i += 1

    return out, events


def _repair_cl_interior_wide_bar_closes(
    out: pd.DataFrame, ticker: str, name: str
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Wide-range day with close far from neighbor trend (bad blended bar)."""
    events: list[dict[str, Any]] = []
    if len(out) < 3:
        return out, events

    cl = pd.to_numeric(out["Close"], errors="coerce").astype(float).to_numpy()
    op = pd.to_numeric(out["Open"], errors="coerce").astype(float).to_numpy()
    hi = pd.to_numeric(out["High"], errors="coerce").astype(float).to_numpy()
    lo = pd.to_numeric(out["Low"], errors="coerce").astype(float).to_numpy()

    fix_idx: list[int] = []
    for i in range(1, len(out) - 1):
        c, o, h, l = cl[i], op[i], hi[i], lo[i]
        if any(np.isnan([c, o, h, l])) or c <= 0 or h < l:
            continue
        rng_pct = (h - l) / c
        body_pct = abs(o - c) / c
        prev_c = float(cl[i - 1])
        next_c = float(cl[i + 1])
        if prev_c <= 0 or next_c <= 0 or np.isnan(prev_c) or np.isnan(next_c):
            continue
        med_nb = float(np.median([prev_c, next_c]))
        if med_nb <= 0:
            continue
        dev_nb = abs(c - med_nb) / med_nb
        if rng_pct >= 0.11 and body_pct >= 0.08 and dev_nb >= 0.05:
            fix_idx.append(i)

    if not fix_idx:
        return out, events

    cl_orig = cl.copy()
    for i in fix_idx:
        new_c = float((cl_orig[i - 1] + cl_orig[i + 1]) / 2.0)
        old_c = float(cl_orig[i])
        dt = out.iloc[i]["Date"]
        d_str = dt.date().isoformat() if hasattr(dt, "date") else pd.Timestamp(dt).date().isoformat()
        events.append(
            {
                "action": "repair_cl_wide_bar",
                "ticker": ticker,
                "name": name,
                "date": d_str,
                "old_close": round(old_c, 6),
                "new_close": round(new_c, 6),
            }
        )
        for col in ("Open", "High", "Low", "Close"):
            out.iloc[i, out.columns.get_loc(col)] = new_c

    return out, events


def validate_and_repair_benchmark_df(
    df: pd.DataFrame, ticker: str, name: str
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Single entry for Yahoo OHLCV → cleaned frame for ``benchmark_data`` upsert.

    Runs ``sanitize_yahoo_continuous_futures_df`` for ``*=F``, then CL=F-specific repairs.
    Returns ``(out, events)``; caller may also pass ``events`` to ``emit_benchmark_qc_events``.
    """
    if not str(ticker).endswith("=F"):
        return df.copy(), []

    out = sanitize_yahoo_continuous_futures_df(df, ticker, name)
    all_events: list[dict[str, Any]] = []

    if str(ticker) == "CL=F":
        out, ev1 = _repair_cl_detached_regime_runs(out, ticker, name)
        all_events.extend(ev1)
        out, ev2 = _repair_cl_interior_wide_bar_closes(out, ticker, name)
        all_events.extend(ev2)

    return out, all_events


def emit_benchmark_qc_events(events: list[dict[str, Any]]) -> None:
    for ev in events:
        log_benchmark_qc_event(ev)


def reconcile_benchmark_cache_to_yahoo(
    client: Any,
    ticker: str,
    name: str,
    start_date: datetime,
    end_date: datetime,
    *,
    sample_max: int = 60,
    rel_tol: float = 0.02,
    seed: int = 42,
) -> None:
    """After upsert: compare DB closes to a fresh Yahoo pull run through the same validator."""
    rows = client.get_benchmark_data(ticker, start_date, end_date)
    if not rows:
        return

    try:
        import yfinance as yf
    except ImportError:
        return

    raw = yf.download(
        ticker,
        start=start_date,
        end=end_date,
        progress=False,
        auto_adjust=False,
    )
    if raw.empty:
        return

    raw = raw.reset_index()
    if hasattr(raw.columns, "levels"):
        raw.columns = raw.columns.get_level_values(0)
    raw["Date"] = pd.to_datetime(raw["Date"], errors="coerce")
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col in raw.columns:
            raw[col] = pd.to_numeric(raw[col], errors="coerce")
    raw = raw.dropna(subset=["Date", "Close"]).sort_values("Date").reset_index(drop=True)
    if raw.empty:
        return

    processed, _ = validate_and_repair_benchmark_df(raw, ticker, name)
    if processed.empty:
        return

    processed["Date"] = pd.to_datetime(processed["Date"]).dt.normalize()
    # ⚡ Bolt: Replaced slow .iterrows() with vectorized dict(zip(...)) for O(1) bulk conversion
    y_map = dict(zip(
        processed["Date"].dt.strftime('%Y-%m-%d'),
        processed["Close"].astype(float)
    ))

    db_pairs: list[tuple[str, float]] = []
    for row in rows:
        dv = row.get("date")
        if dv is None:
            continue
        if hasattr(dv, "isoformat"):
            ds = dv.isoformat()[:10]
        else:
            ds = str(dv)[:10]
        cv = row.get("close")
        if cv is None:
            continue
        try:
            db_pairs.append((ds, float(cv)))
        except (TypeError, ValueError):
            continue

    if not db_pairs:
        return

    rng = random.Random(seed)
    if len(db_pairs) > sample_max:
        db_pairs = rng.sample(db_pairs, sample_max)

    for ds, db_close in db_pairs:
        y_close = y_map.get(ds)
        if y_close is None or y_close <= 0 or db_close <= 0:
            continue
        ratio = db_close / y_close
        if abs(ratio - 1.0) > rel_tol:
            log_benchmark_qc_event(
                {
                    "action": "reconcile_mismatch",
                    "ticker": ticker,
                    "name": name,
                    "date": ds,
                    "db_close": round(db_close, 6),
                    "yahoo_close": round(y_close, 6),
                    "ratio": round(ratio, 6),
                }
            )
