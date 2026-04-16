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


def test_precious_metals_keep_low_volume_rows() -> None:
    """GC=F / SI=F: Yahoo often reports small positive volume on valid days — do not drop."""
    mod = _load_module()
    assert mod.yahoo_futures_min_reported_volume("GC=F") is None
    assert mod.yahoo_futures_min_reported_volume("SI=F") is None
    df = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-04-14", "2026-04-15"]),
            "Open": [4825.0, 4800.0],
            "High": [4841.6, 4843.6],
            "Low": [4770.1, 4798.0],
            "Close": [4825.0, 4800.0],
            "Volume": [288, 288],
        }
    )
    out = mod.sanitize_yahoo_continuous_futures_df(df, "GC=F", "Gold")
    assert len(out) == 2


def test_sanitize_drops_zero_volume_rows() -> None:
    mod = _load_module()
    df = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]),
            "Open": [10.0, 10.0, 10.0],
            "High": [10.5, 10.2, 10.1],
            "Low": [9.9, 9.9, 9.9],
            "Close": [10.2, 10.1, 10.05],
            "Volume": [5000, 0, 6000],
        }
    )
    out = mod.sanitize_yahoo_continuous_futures_df(df, "SI=F", "Silver")
    assert len(out) == 2
    assert list(out["Volume"]) == [5000, 6000]


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
            "Volume": [15000, 55215, 19729, 2230],
        }
    )
    out = mod.sanitize_yahoo_continuous_futures_df(df, "SI=F", "Silver")
    m = out["Date"].dt.strftime("%Y-%m-%d") == "2024-11-26"
    nov26 = float(out.loc[m, "Close"].iloc[0])
    assert abs(nov26 - (30.0 + 30.111) / 2) < 1e-6


def test_gc_detached_regime_low_run_interpolated() -> None:
    """Multi-day run ~half off stable medians on both sides -> bridge OHLC."""
    mod = _load_module()
    n = 13
    closes = [5000.0] * 5 + [2500.0] * 3 + [5000.0] * 5
    df = pd.DataFrame(
        {
            "Date": pd.date_range("2026-01-01", periods=n, freq="B"),
            "Close": closes,
            "Open": [c * 1.0002 for c in closes],
            "High": [c * 1.002 for c in closes],
            "Low": [c * 0.998 for c in closes],
            "Volume": [1000] * n,
        }
    )
    out = mod.sanitize_yahoo_continuous_futures_df(df, "GC=F", "Gold")
    for j in range(5, 8):
        assert abs(float(out.iloc[j]["Close"]) - 5000.0) < 1.0


def test_gc_detached_regime_high_run_interpolated() -> None:
    mod = _load_module()
    n = 13
    closes = [3000.0] * 5 + [5600.0] * 3 + [3050.0] * 5
    df = pd.DataFrame(
        {
            "Date": pd.date_range("2026-01-01", periods=n, freq="B"),
            "Close": closes,
            "Open": [c * 1.0002 for c in closes],
            "High": [c * 1.002 for c in closes],
            "Low": [c * 0.998 for c in closes],
            "Volume": [1000] * n,
        }
    )
    out = mod.sanitize_yahoo_continuous_futures_df(df, "GC=F", "Gold")
    for j in range(5, 8):
        assert 3000.0 < float(out.iloc[j]["Close"]) < 3200.0


def test_gc_wide_bar_close_repaired() -> None:
    """Interior GC=F day: huge range + body but Close off local trend -> interpolate OHLC."""
    mod = _load_module()
    df = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-01-29", "2026-01-30", "2026-02-02"]),
            "Open": [5415.0, 5376.0, 4807.0],
            "High": [5586.0, 5440.0, 4855.0],
            "Low": [5097.0, 4700.0, 4400.0],
            "Close": [5318.0, 4713.0, 4622.0],
            "Volume": [23709, 8374, 3588],
        }
    )
    out = mod.sanitize_yahoo_continuous_futures_df(df, "GC=F", "Gold")
    assert len(out) == 3
    want = (5318.0 + 4622.0) / 2.0
    assert abs(float(out.iloc[1]["Close"]) - want) < 0.01


def test_sanitize_repairs_si_out_of_band_close() -> None:
    mod = _load_module()
    df = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2025-11-17", "2025-11-18", "2025-11-19", "2025-11-20"]),
            "Open": [50.6, 4000.0, 4080.0, 50.2],
            "High": [50.6, 4000.0, 4080.0, 50.2],
            "Low": [50.6, 4000.0, 4080.0, 50.2],
            "Close": [50.6, 4000.0, 4080.0, 50.2],
            "Volume": [8000, 8000, 8000, 8000],
        }
    )
    out = mod.sanitize_yahoo_continuous_futures_df(df, "SI=F", "Silver")
    assert float(out.iloc[1]["Close"]) < 200
    assert float(out.iloc[2]["Close"]) < 200


def test_sanitize_drops_cl_low_volume_spike_bar() -> None:
    """Rows below the CL=F volume floor are dropped (defense in depth for corrupt cached bars)."""
    mod = _load_module()
    df = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2025-04-08", "2025-04-09", "2025-04-10"]),
            "Open": [61.0, 29.35, 62.7],
            "High": [61.75, 30.323, 63.34],
            "Low": [57.88, 29.255, 58.76],
            "Close": [59.58, 30.323, 60.07],
            "Volume": [557655, 137, 391826],
        }
    )
    out = mod.sanitize_yahoo_continuous_futures_df(df, "CL=F", "Crude Oil")
    assert len(out) == 2
    assert "2025-04-09" not in out["Date"].dt.strftime("%Y-%m-%d").tolist()


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
