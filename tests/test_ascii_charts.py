"""Tests for the terminal chart primitives in display.ascii_charts."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from display.ascii_charts import (  # noqa: E402
    BreakdownEntry,
    ChartGlyphs,
    downsample,
    format_compact,
    format_money_compact,
    render_breakdown,
    render_line_chart,
    render_x_axis,
    visible_len,
)

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

UNICODE = ChartGlyphs.for_terminal(unicode_ok=True)
ASCII = ChartGlyphs.for_terminal(unicode_ok=False)


class TestFormatCompact:
    def test_scales_to_suffixes(self):
        assert format_compact(553_100_000) == "553.1M"
        assert format_compact(69_100_000) == "69.1M"
        assert format_compact(2_900_000_000) == "2.9B"
        assert format_compact(24_100) == "24.1k"

    def test_small_and_zero_values(self):
        assert format_compact(0) == "0"
        assert format_compact(842) == "842"
        assert format_compact(0.25) == "0.25"

    def test_negative_values_keep_sign(self):
        assert format_compact(-1_500) == "-1.5k"

    def test_money_formatting(self):
        assert format_money_compact(12_345) == "$12.3k"
        assert format_money_compact(-412) == "-$412"


class TestDownsample:
    def test_short_series_passes_through(self):
        assert downsample([1, 2, 3], 10) == [1.0, 2.0, 3.0]

    def test_averages_into_buckets(self):
        assert downsample([0, 10, 20, 30], 2) == [5.0, 25.0]

    def test_never_exceeds_max_points(self):
        assert len(downsample(list(range(1000)), 72)) == 72

    def test_zero_max_points(self):
        assert downsample([1, 2, 3], 0) == []


class TestRenderLineChart:
    def test_empty_series_renders_nothing(self):
        assert render_line_chart([]) == []

    def test_chart_is_height_plus_one_rows(self):
        chart = render_line_chart([1, 5, 3, 8], height=6, glyphs=UNICODE)
        assert len(chart) == 7

    def test_axis_labels_span_min_to_max(self):
        chart = render_line_chart([100, 200], height=4, label_width=6,
                                  format_label=lambda v: f"{v:.0f}", glyphs=UNICODE)
        assert chart[0].startswith("   200")
        assert chart[-1].startswith("   100")

    def test_rising_series_uses_rising_corners(self):
        # A monotonic climb should open with '╭' on top and close with '╯' below,
        # matching the shape Claude Code's usage chart draws.
        chart = "\n".join(render_line_chart([1, 2, 3, 4], height=4, glyphs=UNICODE))
        assert "╭" in chart  # ╭
        assert "╯" in chart  # ╯
        assert "╰" not in chart  # ╰ only appears on falls
        assert "╮" not in chart  # ╮ only appears on falls

    def test_falling_series_uses_falling_corners(self):
        chart = "\n".join(render_line_chart([4, 3, 2, 1], height=4, glyphs=UNICODE))
        assert "╮" in chart  # ╮
        assert "╰" in chart  # ╰
        assert "╭" not in chart
        assert "╯" not in chart

    def test_origin_marker_sits_on_first_value(self):
        chart = render_line_chart([1, 9], height=4, label_width=4, glyphs=UNICODE)
        origin_rows = [i for i, row in enumerate(chart) if UNICODE.axis_origin in row]
        # First value is the minimum, so the origin tick is on the bottom row.
        assert origin_rows == [len(chart) - 1]

    def test_flat_series_still_draws_a_line(self):
        chart = render_line_chart([5, 5, 5, 5], height=4, glyphs=UNICODE)
        assert any(UNICODE.horizontal in row for row in chart)

    def test_ascii_fallback_avoids_box_drawing(self):
        chart = "\n".join(render_line_chart([1, 4, 2], height=4, glyphs=ASCII))
        assert all(ord(char) < 128 for char in chart)

    def test_last_point_is_drawn(self):
        chart = render_line_chart([1, 2, 3], height=4, label_width=4, glyphs=UNICODE)
        last_column = max(len(row) for row in chart) - 1
        assert any(len(row) > last_column and row[last_column] != " " for row in chart)


class TestRenderXAxis:
    def test_first_label_aligns_with_plot_start(self):
        line = render_x_axis(["Jul 14", "Sep 12"], plot_width=40, label_width=8)
        assert line.index("Jul 14") == 9

    def test_labels_do_not_overlap(self):
        line = render_x_axis(["Jan 01", "Jan 02", "Jan 03"], plot_width=8, label_width=4)
        # Only labels that fit without colliding survive.
        assert line.count("Jan") < 3

    def test_empty_input(self):
        assert render_x_axis([], plot_width=10) == ""


class TestRenderBreakdown:
    def test_entries_fill_columns_left_to_right(self):
        lines = render_breakdown(
            [BreakdownEntry("A", ["a1"]), BreakdownEntry("B", ["b1"]),
             BreakdownEntry("C", ["c1"])],
            columns=2,
            column_width=20,
            glyphs=ASCII,
        )
        assert "A" in lines[0] and "B" in lines[0]
        assert "C" in lines[2]

    def test_detail_lines_are_indented_under_the_label(self):
        lines = render_breakdown([BreakdownEntry("A", ["detail"])],
                                 columns=1, column_width=20, glyphs=ASCII)
        assert lines[1].startswith("  detail")

    def test_ragged_details_do_not_break_alignment(self):
        lines = render_breakdown(
            [BreakdownEntry("A", ["a1", "a2"]), BreakdownEntry("B", ["b1"])],
            columns=2,
            column_width=20,
            glyphs=ASCII,
        )
        assert len(lines) == 3
        assert lines[2].strip() == "a2"

    def test_color_codes_do_not_shift_column_alignment(self):
        lines = render_breakdown(
            [BreakdownEntry("A", ["a1"], color="\033[32m"), BreakdownEntry("B", ["b1"])],
            columns=2,
            column_width=20,
            reset="\033[0m",
            glyphs=ASCII,
        )
        plain = _ANSI.sub("", lines[0])
        assert plain.index("* B") == 20
        assert visible_len(lines[0]) == len(plain)

    def test_empty_input(self):
        assert render_breakdown([]) == []
