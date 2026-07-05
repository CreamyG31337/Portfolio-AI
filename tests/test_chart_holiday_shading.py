"""Tests for holiday shading and labels on Plotly performance charts."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objs as go

from chart_utils import CHART_TRADING_MARKET, _add_holiday_shading


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
    def test_juneteenth_shaded_and_labeled_vertically(self) -> None:
        fig = go.Figure()
        _add_holiday_shading(
            fig,
            datetime(2026, 6, 1),
            datetime(2026, 6, 30),
            market=CHART_TRADING_MARKET,
        )

        assert _has_holiday_shade(fig, 2026, 6, 19)
        juneteenth = _annotation_by_text(fig, "Juneteenth")
        assert juneteenth is not None
        assert juneteenth.textangle == -90

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

    def test_holiday_labels_use_top_center_not_top_left(self) -> None:
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
