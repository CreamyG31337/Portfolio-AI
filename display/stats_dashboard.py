"""The terminal stats dashboard - portfolio charts drawn straight in the console.

Composes :mod:`display.ascii_charts` primitives with the aggregates from
:mod:`portfolio.portfolio_stats` into a single screen: a value-per-day line
chart, a day-over-day change chart, and a two-column holdings breakdown.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Optional

from display.ascii_charts import (
    BreakdownEntry,
    ChartGlyphs,
    downsample,
    format_money_compact,
    render_breakdown,
    render_line_chart,
    render_x_axis,
)
from display.console_output import _can_handle_unicode, _safe_emoji, has_color_support
from display.terminal_utils import detect_terminal_width
from portfolio.portfolio_stats import PortfolioStats

__all__ = ["render_stats_dashboard", "RANGE_CHOICES"]

# Menu key -> (label, days back; None means all time)
RANGE_CHOICES: Dict[str, tuple] = {
    "a": ("All time", None),
    "7": ("Last 7 days", 7),
    "30": ("Last 30 days", 30),
    "90": ("Last 90 days", 90),
}

_LABEL_WIDTH = 9
_MAX_PLOT_WIDTH = 72
_MIN_PLOT_WIDTH = 20
_MAX_HOLDINGS = 12

# Palette for holding bullets, cycled in weight order.
_PALETTE = [
    "\033[38;5;39m",   # blue
    "\033[38;5;208m",  # orange
    "\033[38;5;42m",   # green
    "\033[38;5;170m",  # purple
    "\033[38;5;221m",  # yellow
    "\033[38;5;203m",  # red
]
_RESET = "\033[0m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_GREEN = "\033[32m"
_RED = "\033[31m"


def _money(value: Decimal) -> str:
    """Full-precision money with thousands separators, e.g. ``$12,345.67``."""
    amount = float(value)
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"


def _signed_money(value: Decimal) -> str:
    amount = float(value)
    return f"{'+' if amount >= 0 else '-'}${abs(amount):,.2f}"


def _signed_pct(value: Decimal) -> str:
    amount = float(value)
    return f"{'+' if amount >= 0 else ''}{amount:.1f}%"


def _plot_width() -> int:
    """Chart columns that fit the current terminal, within sane bounds."""
    available = detect_terminal_width() - _LABEL_WIDTH - 2
    return max(_MIN_PLOT_WIDTH, min(_MAX_PLOT_WIDTH, available))


def _colorize(text: str, color: str, use_color: bool) -> str:
    return f"{color}{text}{_RESET}" if use_color and color else text


def _pnl_color(value: Decimal, use_color: bool) -> str:
    if not use_color:
        return ""
    return _GREEN if value >= 0 else _RED


def _date_labels(stats: PortfolioStats, count: int = 4) -> List[str]:
    """Evenly spaced ``Mon D`` labels spanning the series."""
    points = stats.points
    if not points:
        return []
    if len(points) <= count:
        indexes = list(range(len(points)))
    else:
        indexes = [int(i * (len(points) - 1) / (count - 1)) for i in range(count)]
    # %-d/%#d are platform-specific, so strip the leading zero by hand.
    return [points[i].date.strftime("%b %d").replace(" 0", " ") for i in indexes]


def _daily_deltas(stats: PortfolioStats) -> List[float]:
    """Day-over-day market value changes, starting at the second day."""
    points = stats.points
    return [
        float(points[i].market_value - points[i - 1].market_value)
        for i in range(1, len(points))
    ]


def _holding_entries(stats: PortfolioStats, use_color: bool) -> List[BreakdownEntry]:
    entries: List[BreakdownEntry] = []
    for index, holding in enumerate(stats.holdings[:_MAX_HOLDINGS]):
        color = _PALETTE[index % len(_PALETTE)] if use_color else ""
        pnl = _colorize(
            f"{_signed_money(holding.unrealized_pnl)} ({_signed_pct(holding.return_pct)})",
            _pnl_color(holding.unrealized_pnl, use_color),
            use_color,
        )
        entries.append(
            BreakdownEntry(
                label=f"{holding.ticker} ({float(holding.weight_pct):.1f}%)",
                details=[
                    f"{_money(holding.market_value)} · {holding.currency}"
                    if _can_handle_unicode()
                    else f"{_money(holding.market_value)} - {holding.currency}",
                    f"P&L {pnl}",
                ],
                color=color,
            )
        )
    return entries


def render_stats_dashboard(
    stats: PortfolioStats,
    fund_name: str,
    range_label: str,
    *,
    use_color: Optional[bool] = None,
) -> List[str]:
    """Render the whole dashboard as printable lines.

    Returns a list of lines rather than printing so the layout can be tested and
    reused (logs, reports) without capturing stdout.
    """
    if use_color is None:
        use_color = has_color_support()
    glyphs = ChartGlyphs.for_terminal()
    sep = "·" if _can_handle_unicode() else "-"
    width = _plot_width()
    lines: List[str] = []

    header = f"{_safe_emoji('📈')} {fund_name} — Portfolio Stats" if _can_handle_unicode() \
        else f"{_safe_emoji('📈')} {fund_name} - Portfolio Stats"
    lines.append("=" * (width + _LABEL_WIDTH + 1))
    lines.append(_colorize(header, _BOLD, use_color))
    lines.append("=" * (width + _LABEL_WIDTH + 1))
    lines.append("")

    if stats.is_empty:
        lines.append("No portfolio snapshots found for this fund yet.")
        lines.append("Run option [1] View Portfolio to create the first snapshot.")
        return lines

    # --- Portfolio value per day -------------------------------------------
    values = downsample([float(p.market_value) for p in stats.points], width)
    lines.append(_colorize("Portfolio Value per Day (CAD)", _BOLD, use_color))
    chart = render_line_chart(
        values,
        height=8,
        label_width=_LABEL_WIDTH,
        format_label=lambda v: format_money_compact(v),
        glyphs=glyphs,
    )
    lines.extend(chart)
    lines.append(render_x_axis(_date_labels(stats), len(values), _LABEL_WIDTH))
    lines.append("")

    # --- Day-over-day change ------------------------------------------------
    deltas = _daily_deltas(stats)
    if len(deltas) >= 2:
        lines.append(_colorize("Day-over-Day Change (CAD)", _BOLD, use_color))
        lines.extend(
            render_line_chart(
                downsample(deltas, width),
                height=5,
                label_width=_LABEL_WIDTH,
                format_label=lambda v: format_money_compact(v),
                glyphs=glyphs,
            )
        )
        lines.append("")

    # --- Summary line -------------------------------------------------------
    latest = stats.latest
    first = stats.first
    change_color = _pnl_color(stats.change, use_color)
    summary = (
        f"{range_label} {sep} {len(stats.points)} days {sep} "
        f"{_money(first.market_value)} → {_money(latest.market_value)} "
        if _can_handle_unicode()
        else f"{range_label} {sep} {len(stats.points)} days {sep} "
             f"{_money(first.market_value)} -> {_money(latest.market_value)} "
    )
    summary += _colorize(
        f"({_signed_money(stats.change)}, {_signed_pct(stats.change_pct)})",
        change_color,
        use_color,
    )
    lines.append(summary)

    pnl_color = _pnl_color(latest.unrealized_pnl, use_color)
    lines.append(
        f"Cost basis {_money(latest.cost_basis)} {sep} Unrealized "
        + _colorize(
            f"{_signed_money(latest.unrealized_pnl)} ({_signed_pct(latest.return_pct)})",
            pnl_color,
            use_color,
        )
    )

    best, worst = stats.best_day, stats.worst_day
    if best is not None and worst is not None:
        lines.append(
            f"Best day {best.date.strftime('%b %d')} "
            + _colorize(_signed_money(stats.delta_for(best)), _GREEN if use_color else "", use_color)
            + f" {sep} Worst day {worst.date.strftime('%b %d')} "
            + _colorize(_signed_money(stats.delta_for(worst)), _RED if use_color else "", use_color)
        )

    if stats.currency_totals:
        parts = [
            f"{currency} {_money(total)}"
            for currency, total in sorted(stats.currency_totals.items())
        ]
        lines.append(f"By currency (CAD equiv): {f' {sep} '.join(parts)}")
    lines.append("")

    # --- Holdings breakdown -------------------------------------------------
    shown = min(len(stats.holdings), _MAX_HOLDINGS)
    heading = f"Holdings ({shown} of {len(stats.holdings)})" if len(stats.holdings) > shown \
        else f"Holdings ({len(stats.holdings)})"
    lines.append(_colorize(heading, _BOLD, use_color))
    column_width = max(28, (width + _LABEL_WIDTH) // 2)
    lines.extend(
        render_breakdown(
            _holding_entries(stats, use_color),
            columns=2,
            column_width=column_width,
            reset=_RESET if use_color else "",
            glyphs=glyphs,
        )
    )
    return lines


def print_stats_dashboard(stats: PortfolioStats, fund_name: str, range_label: str) -> None:
    """Print the dashboard to stdout."""
    for line in render_stats_dashboard(stats, fund_name, range_label):
        print(line)
