"""Tests for holiday shading and labels on Plotly performance charts."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objs as go
import pytest

from chart_utils import (
    CHART_TRADING_MARKET,
    _add_holiday_shading,
    create_portfolio_value_chart,
)


def _shape_x0_dates(fig: go.Figure) -> list[datetime]:
    dates: list[datetime] = []
    for shape in fig.layout.shapes or []:
        if shape.type != "rect":
            continue
        x0 = shape.x0
        if isinstance(x0, str):
            dates.append(pd.to_datetime(x0).to_pydatetime())
        elif x0 is not None:
            dates.append(pd.to_datetime(x0).to_pydatetime())
    return dates


def _has_holiday_shade(fig: go.Figure, year: int, month: int, day: int) -> bool:
    target = datetime(year, month, day).date()
    return any(d.date() == target for d in _shape_x0_dates(fig))


def _annotation_texts(fig: go.Figure) -> list[str]:
    return [str(a.text) for a in fig.layout.annotations or [] if a.text]


def _annotation_by_text(fig: go.Figure, text: str) -> go.layout.Annotation | None:
    for annotation in fig.layout.annotations or []:
        if annotation.text == text:
            return annotation
    return None


class TestHolidayShadingLabels:
    def test_juneteenth_shaded_but_not_labeled(self) -> None:
        fig = go.Figure()
        _add_holiday_shading(
            fig,
            datetime(2026, 6, 1),
            datetime(2026, 6, 30),
            market=CHART_TRADING_MARKET,
        )

        assert _has_holiday_shade(fig, 2026, 6, 19)
        assert "Juneteenth" not in _annotation_texts(fig)
        assert "Juneteenth National Independence Day" not in _annotation_texts(fig)

    def test_christmas_labeled_vertically(self) -> None:
        fig = go.Figure()
        _add_holiday_shading(
            fig,
            datetime(2026, 12, 1),
            datetime(2026, 12, 31),
            market=CHART_TRADING_MARKET,
        )

        assert _has_holiday_shade(fig, 2026, 12, 25)
        christmas = _annotation_by_text(fig, "Christmas Day")
        assert christmas is not None
        assert christmas.textangle == -90
        assert christmas.yanchor == "top"

    def test_shared_holiday_labels_use_top_position_not_top_left(self) -> None:
        fig = go.Figure()
        _add_holiday_shading(
            fig,
            datetime(2026, 4, 1),
            datetime(2026, 4, 10),
            market=CHART_TRADING_MARKET,
        )

        good_friday = _annotation_by_text(fig, "Good Friday")
        assert good_friday is not None
        assert good_friday.textangle == -90
        assert good_friday.xanchor == "center"


class TestPortfolioChartXAxis:
    @pytest.fixture
    def sample_portfolio_df(self) -> pd.DataFrame:
        dates = pd.date_range("2026-06-01", "2026-12-31", freq="B")
        return pd.DataFrame(
            {
                "date": dates,
                "performance_index": [100.0 + i * 0.1 for i in range(len(dates))],
                "performance_pct": [i * 0.1 for i in range(len(dates))],
                "cost_basis": [1000.0] * len(dates),
            }
        )

    def test_xaxis_range_clamped_to_data(self, sample_portfolio_df: pd.DataFrame) -> None:
        fig = create_portfolio_value_chart(
            sample_portfolio_df,
            show_normalized=True,
            show_benchmarks=None,
            show_weekend_shading=True,
        )

        x_range = fig.layout.xaxis.range
        assert x_range is not None
        assert pd.to_datetime(x_range[0]) == sample_portfolio_df["date"].min()
        assert pd.to_datetime(x_range[1]) == sample_portfolio_df["date"].max()
