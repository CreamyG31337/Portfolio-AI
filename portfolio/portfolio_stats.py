"""Aggregate portfolio snapshots into series and breakdowns for the console.

This is the data half of the terminal stats dashboard; the drawing half lives in
:mod:`display.ascii_charts`. Everything is converted to CAD using the historical
USD/CAD rates for each snapshot date, so a mixed-currency fund still produces a
single meaningful value series.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from data.models.portfolio import Position, PortfolioSnapshot
from utils.currency_converter import convert_usd_to_cad

logger = logging.getLogger(__name__)

__all__ = [
    "DailyPoint",
    "HoldingStat",
    "PortfolioStats",
    "build_portfolio_stats",
    "to_cad",
]

_ZERO = Decimal("0")


def to_cad(amount: Optional[Decimal], currency: str,
           exchange_rates: Dict[str, Decimal],
           on_date: Optional[datetime] = None) -> Decimal:
    """Convert *amount* to CAD, degrading gracefully when rates are missing.

    Falls back to the most recent known rate when the history doesn't reach back
    to *on_date*, and to a 1:1 rate when there are no rates at all. Both
    fallbacks are approximations, so they are logged rather than raised - a
    stats screen should never be the thing that crashes the menu.
    """
    if amount is None:
        return _ZERO
    if (currency or "CAD").upper() != "USD":
        return amount
    if not exchange_rates:
        logger.debug("No exchange rates available; treating USD as CAD 1:1")
        return amount
    try:
        return convert_usd_to_cad(amount, exchange_rates, on_date)
    except ValueError:
        # History doesn't go back far enough - use the earliest rate we do have.
        try:
            return convert_usd_to_cad(amount, exchange_rates, None)
        except ValueError:
            return amount


@dataclass
class DailyPoint:
    """One day of portfolio totals, all in CAD."""

    date: datetime
    market_value: Decimal
    cost_basis: Decimal
    unrealized_pnl: Decimal

    @property
    def return_pct(self) -> Decimal:
        if self.cost_basis == 0:
            return _ZERO
        return self.unrealized_pnl / self.cost_basis * Decimal("100")


@dataclass
class HoldingStat:
    """A single holding in the latest snapshot, valued in CAD."""

    ticker: str
    company: Optional[str]
    currency: str
    shares: Decimal
    market_value: Decimal
    cost_basis: Decimal
    unrealized_pnl: Decimal
    weight_pct: Decimal

    @property
    def return_pct(self) -> Decimal:
        if self.cost_basis == 0:
            return _ZERO
        return self.unrealized_pnl / self.cost_basis * Decimal("100")


@dataclass
class PortfolioStats:
    """Everything the terminal dashboard needs for one time range."""

    points: List[DailyPoint] = field(default_factory=list)
    holdings: List[HoldingStat] = field(default_factory=list)
    currency_totals: Dict[str, Decimal] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.points

    @property
    def latest(self) -> Optional[DailyPoint]:
        return self.points[-1] if self.points else None

    @property
    def first(self) -> Optional[DailyPoint]:
        return self.points[0] if self.points else None

    @property
    def change(self) -> Decimal:
        """Change in market value across the range."""
        if len(self.points) < 2:
            return _ZERO
        return self.points[-1].market_value - self.points[0].market_value

    @property
    def change_pct(self) -> Decimal:
        if len(self.points) < 2 or self.points[0].market_value == 0:
            return _ZERO
        return self.change / self.points[0].market_value * Decimal("100")

    @property
    def best_day(self) -> Optional[DailyPoint]:
        """Day with the largest gain over the previous day."""
        return self._extreme_day(best=True)

    @property
    def worst_day(self) -> Optional[DailyPoint]:
        return self._extreme_day(best=False)

    def _extreme_day(self, best: bool) -> Optional[DailyPoint]:
        if len(self.points) < 2:
            return None
        deltas = [
            (self.points[i].market_value - self.points[i - 1].market_value, self.points[i])
            for i in range(1, len(self.points))
        ]
        chosen = (max if best else min)(deltas, key=lambda pair: pair[0])
        return chosen[1]

    def delta_for(self, point: DailyPoint) -> Decimal:
        """Day-over-day market value change for *point* (0 on the first day)."""
        index = self.points.index(point)
        if index == 0:
            return _ZERO
        return point.market_value - self.points[index - 1].market_value


def _latest_positions(snapshot: PortfolioSnapshot) -> List[Position]:
    """Open positions in *snapshot*, deduped by ticker keeping the last row.

    CSV snapshots are grouped by calendar date, so a ticker written twice in one
    day would otherwise be counted twice. Fully sold positions stay in the CSV
    with zero shares but keep their original cost basis, so they are dropped -
    otherwise they inflate the cost basis of every day after the sale.
    """
    by_ticker: Dict[str, Position] = {}
    for position in snapshot.positions:
        by_ticker[position.ticker] = position
    return [position for position in by_ticker.values() if position.shares != 0]


def build_portfolio_stats(
    snapshots: Sequence[PortfolioSnapshot],
    exchange_rates: Optional[Dict[str, Decimal]] = None,
    days: Optional[int] = None,
) -> PortfolioStats:
    """Turn raw snapshots into a CAD-normalised series plus a holdings breakdown.

    Args:
        snapshots: Portfolio snapshots, in any order.
        exchange_rates: USD/CAD rates keyed by ``YYYY-MM-DD``.
        days: Keep only the last *days* calendar days; ``None`` means all time.

    Returns:
        A :class:`PortfolioStats`; empty when there is nothing to show.
    """
    rates = exchange_rates or {}
    ordered = sorted(
        (s for s in snapshots if s.timestamp is not None),
        key=lambda s: s.timestamp,
    )
    if not ordered:
        return PortfolioStats()

    if days is not None and days > 0:
        cutoff = ordered[-1].timestamp - timedelta(days=days)
        ordered = [s for s in ordered if s.timestamp >= cutoff] or ordered[-1:]

    points: List[DailyPoint] = []
    for snapshot in ordered:
        market_value = _ZERO
        cost_basis = _ZERO
        unrealized = _ZERO
        for position in _latest_positions(snapshot):
            currency = position.currency or "CAD"
            when = snapshot.timestamp
            market_value += to_cad(position.market_value, currency, rates, when)
            cost_basis += to_cad(position.cost_basis, currency, rates, when)
            unrealized += to_cad(position.calculated_unrealized_pnl, currency, rates, when)
        points.append(
            DailyPoint(
                date=snapshot.timestamp,
                market_value=market_value,
                cost_basis=cost_basis,
                unrealized_pnl=unrealized,
            )
        )

    latest_snapshot = ordered[-1]
    latest_positions = _latest_positions(latest_snapshot)
    total_value = points[-1].market_value

    holdings: List[HoldingStat] = []
    currency_totals: Dict[str, Decimal] = {}
    for position in latest_positions:
        currency = (position.currency or "CAD").upper()
        when = latest_snapshot.timestamp
        value = to_cad(position.market_value, currency, rates, when)
        cost = to_cad(position.cost_basis, currency, rates, when)
        pnl = to_cad(position.calculated_unrealized_pnl, currency, rates, when)
        weight = (value / total_value * Decimal("100")) if total_value else _ZERO
        holdings.append(
            HoldingStat(
                ticker=position.ticker,
                company=position.company,
                currency=currency,
                shares=position.shares,
                market_value=value,
                cost_basis=cost,
                unrealized_pnl=pnl,
                weight_pct=weight,
            )
        )
        currency_totals[currency] = currency_totals.get(currency, _ZERO) + value

    holdings.sort(key=lambda h: h.market_value, reverse=True)
    return PortfolioStats(points=points, holdings=holdings, currency_totals=currency_totals)
