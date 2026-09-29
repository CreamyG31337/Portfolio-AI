"""Terminal charts drawn with box-drawing characters.

Pure rendering helpers with no project dependencies beyond the unicode
capability probe in :mod:`display.console_output`. Everything here returns a
list of plain strings so callers decide how (and whether) to colourise.

The line chart uses the classic "asciichart" algorithm: values are quantised to
a row grid and consecutive points are joined with corner glyphs, which reads far
better than a bar chart for a slow-moving series like portfolio value.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence

from display.console_output import _can_handle_unicode

__all__ = [
    "ChartGlyphs",
    "BreakdownEntry",
    "format_compact",
    "format_money_compact",
    "downsample",
    "render_line_chart",
    "render_x_axis",
    "render_breakdown",
    "visible_len",
]

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


@dataclass(frozen=True)
class ChartGlyphs:
    """Characters used to draw a chart, with an ASCII fallback variant."""

    axis_tick: str
    axis_origin: str
    horizontal: str
    vertical: str
    up_right: str
    down_right: str
    up_left: str
    down_left: str
    bullet: str

    @classmethod
    def for_terminal(cls, unicode_ok: Optional[bool] = None) -> "ChartGlyphs":
        """Pick the glyph set the current terminal can actually render."""
        if unicode_ok is None:
            unicode_ok = _can_handle_unicode()
        if unicode_ok:
            return cls(
                axis_tick="┤",      # ┤
                axis_origin="┼",    # ┼
                horizontal="─",     # ─
                vertical="│",       # │
                up_right="╰",       # ╰
                down_right="╭",     # ╭
                up_left="╯",        # ╯
                down_left="╮",      # ╮
                bullet="●",         # ●
            )
        return cls(
            axis_tick="|",
            axis_origin="+",
            horizontal="-",
            vertical="|",
            up_right="\\",
            down_right="/",
            up_left="/",
            down_left="\\",
            bullet="*",
        )


@dataclass
class BreakdownEntry:
    """One item in a multi-column breakdown panel."""

    label: str
    details: List[str] = field(default_factory=list)
    color: str = ""


def visible_len(text: str) -> int:
    """Length of *text* ignoring ANSI colour escapes."""
    return len(_ANSI_RE.sub("", text))


def _pad(text: str, width: int) -> str:
    """Left-justify *text* to *width* counting only visible characters."""
    return text + " " * max(0, width - visible_len(text))


def format_compact(value: float, decimals: int = 1) -> str:
    """Format a number as ``553.1M`` / ``69.1k`` / ``842``.

    Mirrors the compact axis labels used by Claude Code's usage screen.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    sign = "-" if value < 0 else ""
    magnitude = abs(float(value))
    for threshold, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "k")):
        if magnitude >= threshold:
            return f"{sign}{magnitude / threshold:.{decimals}f}{suffix}"
    if magnitude == 0:
        return "0"
    if magnitude < 1:
        return f"{sign}{magnitude:.2f}"
    return f"{sign}{magnitude:.0f}"


def format_money_compact(value: float, symbol: str = "$", decimals: int = 1) -> str:
    """Format a currency amount compactly, e.g. ``$12.3k`` or ``-$412``."""
    sign = "-" if value < 0 else ""
    return f"{sign}{symbol}{format_compact(abs(float(value)), decimals)}"


def downsample(series: Sequence[float], max_points: int) -> List[float]:
    """Average *series* down to at most *max_points* buckets, preserving shape.

    Returns a copy when the series already fits.
    """
    values = [float(v) for v in series]
    if max_points <= 0:
        return []
    if len(values) <= max_points:
        return values
    bucket = len(values) / max_points
    result: List[float] = []
    for i in range(max_points):
        start = int(i * bucket)
        end = max(start + 1, int((i + 1) * bucket))
        chunk = values[start:end]
        result.append(sum(chunk) / len(chunk))
    return result


def render_line_chart(
    series: Sequence[float],
    *,
    height: int = 8,
    label_width: int = 8,
    format_label: Callable[[float], str] = format_compact,
    glyphs: Optional[ChartGlyphs] = None,
) -> List[str]:
    """Render *series* as a line chart.

    Args:
        series: Y values, already downsampled to the desired column count.
        height: Number of value rows (the chart is ``height + 1`` lines tall).
        label_width: Width reserved for the right-aligned axis labels.
        format_label: Formatter for axis tick values.
        glyphs: Glyph set; auto-detected from the terminal when omitted.

    Returns:
        The chart lines, each ``label_width + 1 + len(series)`` characters wide.
        An empty list when there is nothing to plot.
    """
    values = [float(v) for v in series if v is not None]
    if not values:
        return []
    if glyphs is None:
        glyphs = ChartGlyphs.for_terminal()
    height = max(1, height)

    low = min(values)
    high = max(values)
    span = high - low
    if span == 0:
        # A flat series still deserves a line; centre it in the plot area.
        low -= 1.0
        high += 1.0
        span = high - low

    rows = height
    offset = label_width + 1
    width = offset + len(values)
    grid = [[" "] * width for _ in range(rows + 1)]

    def row_for(value: float) -> int:
        """Grid row (0 = top) for a data value."""
        scaled = (value - low) / span * rows
        return rows - int(round(scaled))

    # Axis labels and ticks.
    for row in range(rows + 1):
        tick_value = high - (row / rows) * span
        label = format_label(tick_value).rjust(label_width)[-label_width:]
        for i, char in enumerate(label):
            grid[row][i] = char
        grid[row][offset - 1] = glyphs.axis_tick

    first_row = row_for(values[0])
    grid[first_row][offset - 1] = glyphs.axis_origin

    # The series itself.
    for x in range(len(values) - 1):
        y0 = row_for(values[x])
        y1 = row_for(values[x + 1])
        col = offset + x
        if y0 == y1:
            grid[y0][col] = glyphs.horizontal
        else:
            if y0 > y1:  # rising: y1 is the upper row
                grid[y1][col] = glyphs.down_right
                grid[y0][col] = glyphs.up_left
            else:  # falling: y1 is the lower row
                grid[y1][col] = glyphs.up_right
                grid[y0][col] = glyphs.down_left
            for y in range(min(y0, y1) + 1, max(y0, y1)):
                grid[y][col] = glyphs.vertical

    # Last point has no successor to draw a segment for.
    last_col = offset + len(values) - 1
    if grid[row_for(values[-1])][last_col] == " ":
        grid[row_for(values[-1])][last_col] = glyphs.horizontal

    return ["".join(row).rstrip() for row in grid]


def render_x_axis(labels: Sequence[str], plot_width: int, label_width: int = 8) -> str:
    """Lay out *labels* evenly under a chart of *plot_width* columns.

    Labels that would collide with their neighbour are dropped, so passing a few
    more than will fit is safe.
    """
    if not labels or plot_width <= 0:
        return ""
    line = [" "] * (label_width + 1 + plot_width)
    slots = len(labels)
    for i, label in enumerate(labels):
        if slots == 1:
            col = label_width + 1
        else:
            col = label_width + 1 + int(i * (plot_width - 1) / (slots - 1))
        col = min(col, len(line) - len(label))
        col = max(col, label_width + 1)
        # Skip the label if it would overwrite the previous one.
        if any(c != " " for c in line[max(0, col - 1):col + len(label)]):
            continue
        for j, char in enumerate(label):
            if col + j < len(line):
                line[col + j] = char
    return "".join(line).rstrip()


def render_breakdown(
    entries: Sequence[BreakdownEntry],
    *,
    columns: int = 2,
    column_width: int = 40,
    reset: str = "",
    glyphs: Optional[ChartGlyphs] = None,
) -> List[str]:
    """Render a column layout of bulleted entries with indented detail lines.

    Entries fill left-to-right, row by row, matching the usage-screen layout.
    """
    if not entries:
        return []
    if glyphs is None:
        glyphs = ChartGlyphs.for_terminal()
    columns = max(1, columns)

    lines: List[str] = []
    for start in range(0, len(entries), columns):
        row = entries[start:start + columns]
        detail_count = max(len(entry.details) for entry in row)
        cells: List[List[str]] = []
        for entry in row:
            head = f"{glyphs.bullet} {entry.label}"
            if entry.color:
                head = f"{entry.color}{glyphs.bullet}{reset} {entry.label}"
            cell = [head]
            for i in range(detail_count):
                detail = entry.details[i] if i < len(entry.details) else ""
                cell.append(f"  {detail}" if detail else "")
            cells.append(cell)
        for line_index in range(detail_count + 1):
            parts = [cell[line_index] for cell in cells]
            # Don't pad the final column - avoids trailing whitespace.
            rendered = "".join(
                _pad(part, column_width) if i < len(parts) - 1 else part
                for i, part in enumerate(parts)
            )
            lines.append(rendered.rstrip())
    return lines
