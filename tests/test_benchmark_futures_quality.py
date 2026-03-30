"""Tests for Yahoo continuous futures sanitization (see scheduler/benchmark_futures_quality.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent


def _load_module():
    path = _ROOT / "web_dashboard" / "scheduler" / "benchmark_futures_quality.py"
    spec = importlib.util.spec_from_file_location("benchmark_futures_quality", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sanitize_drops_zero_volume_rows() -> None:
    mod = _load_module()
    df = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]),
            "Open": [10.0, 10.0, 10.0],
            "High": [10.5, 10.2, 10.1],
            "Low": [9.9, 9.9, 9.9],
            "Close": [10.2, 10.1, 10.05],
            "Volume": [100, 0, 200],
        }
    )
    out = mod.sanitize_yahoo_continuous_futures_df(df, "SI=F", "Silver")
    assert len(out) == 2
    assert list(out["Volume"]) == [100, 200]


def test_sanitize_interpolates_zero_range_interior_run() -> None:
    mod = _load_module()
    df = pd.DataFrame(
        {
            "Date": pd.to_datetime(
                ["2024-11-25", "2024-11-26", "2024-11-27", "2024-11-29"]
            ),
            # Only 2024-11-26 is Yahoo-style zero-range; neighbors have real ranges.
            "Open": [30.1, 30.388, 30.2, 30.7],
            "High": [30.5, 30.388, 30.95, 30.8],
            "Low": [29.85, 30.388, 29.9, 30.5],
            "Close": [30.0, 30.388, 30.111, 30.7],
            "Volume": [12, 55215, 19729, 2230],
        }
    )
    out = mod.sanitize_yahoo_continuous_futures_df(df, "SI=F", "Silver")
    m = out["Date"].dt.strftime("%Y-%m-%d") == "2024-11-26"
    nov26 = float(out.loc[m, "Close"].iloc[0])
    assert abs(nov26 - (30.0 + 30.111) / 2) < 1e-6


def test_non_futures_passthrough() -> None:
    mod = _load_module()
    df = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2025-01-01"]),
            "Open": [1.0],
            "High": [1.0],
            "Low": [1.0],
            "Close": [1.0],
            "Volume": [0],
        }
    )
    out = mod.sanitize_yahoo_continuous_futures_df(df, "URA", "Uranium ETF")
    assert len(out) == 1
