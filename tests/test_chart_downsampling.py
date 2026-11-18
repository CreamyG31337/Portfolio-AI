"""LTTB downsampling for long performance charts (web_dashboard/chart_utils.py)."""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web_dashboard"))
)

from chart_utils import (  # noqa: E402
    CHART_MAX_POINTS,
    CHART_MIN_POINTS,
    _downsample_frame,
    chart_point_budget,
    lttb_indices,
)


def test_point_budget_scales_with_width_and_is_clamped():
    assert chart_point_budget(None) is None
    assert chart_point_budget(0) is None
    assert chart_point_budget(100) == CHART_MIN_POINTS
    assert chart_point_budget(1000) == 500
    assert chart_point_budget(10_000) == CHART_MAX_POINTS


def test_lttb_keeps_endpoints_extremes_and_budget():
    rng = np.random.default_rng(7)
    n = 1100
    x = np.arange(n, dtype=float)
    y = np.cumsum(rng.normal(0, 1, n))
    spike = 555
    y[spike] = y.max() + 50  # a one-day spike must survive
    idx = lttb_indices(x, y, 200)

    assert len(idx) <= 200
    assert idx[0] == 0 and idx[-1] == n - 1
    assert np.all(np.diff(idx) > 0)  # sorted, unique
    assert spike in idx
    assert int(np.argmin(y)) in idx


def test_lttb_returns_everything_when_under_budget():
    x = np.arange(50, dtype=float)
    assert list(lttb_indices(x, x, 200)) == list(range(50))


def test_lttb_tolerates_nan():
    x = np.arange(500, dtype=float)
    y = np.sin(x / 20)
    y[10:20] = np.nan
    idx = lttb_indices(x, y, 100)
    assert idx[0] == 0 and idx[-1] == 499


def test_downsample_frame_keeps_real_rows():
    dates = pd.date_range("2022-07-08", periods=1103, freq="B")
    df = pd.DataFrame({"date": dates, "v": np.linspace(100, 214.49, 1103)})
    out = _downsample_frame(df, "date", "v", 300)
    assert len(out) <= 300
    # Every plotted point is an original row (hover values stay exact).
    assert set(out.index) <= set(df.index)
    assert out["v"].iloc[-1] == df["v"].iloc[-1]
    assert _downsample_frame(df, "date", "v", None) is df
