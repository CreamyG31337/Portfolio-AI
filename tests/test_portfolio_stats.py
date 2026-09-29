"""Tests for portfolio.portfolio_stats aggregation."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.models.portfolio import PortfolioSnapshot, Position  # noqa: E402
from portfolio.portfolio_stats import build_portfolio_stats, to_cad  # noqa: E402

RATES = {"2025-09-08": Decimal("1.25"), "2025-09-09": Decimal("1.50")}


def make_position(ticker: str, *, shares="10", value="100", cost="80",
                  currency="CAD", pnl=None) -> Position:
    return Position(
        ticker=ticker,
        shares=Decimal(shares),
        avg_price=Decimal(cost) / Decimal(shares) if Decimal(shares) else Decimal("0"),
        cost_basis=Decimal(cost),
        currency=currency,
        market_value=Decimal(value),
        unrealized_pnl=Decimal(pnl) if pnl is not None else Decimal(value) - Decimal(cost),
    )


def make_snapshot(day: str, positions) -> PortfolioSnapshot:
    return PortfolioSnapshot(positions=positions, timestamp=datetime.fromisoformat(day))


class TestToCad:
    def test_cad_amounts_pass_through(self):
        assert to_cad(Decimal("100"), "CAD", RATES) == Decimal("100")

    def test_usd_uses_the_rate_for_the_date(self):
        converted = to_cad(Decimal("100"), "USD", RATES, datetime(2025, 9, 8))
        assert converted == Decimal("125.00")

    def test_missing_rates_fall_back_to_one_to_one(self):
        assert to_cad(Decimal("100"), "USD", {}) == Decimal("100")

    def test_date_before_history_falls_back_to_latest_rate(self):
        # 2025-09-01 predates every rate we have; don't explode, approximate.
        converted = to_cad(Decimal("100"), "USD", RATES, datetime(2025, 9, 1))
        assert converted == Decimal("150.00")

    def test_none_amount_is_zero(self):
        assert to_cad(None, "USD", RATES) == Decimal("0")


class TestBuildPortfolioStats:
    def test_no_snapshots_gives_empty_stats(self):
        stats = build_portfolio_stats([], RATES)
        assert stats.is_empty
        assert stats.holdings == []

    def test_mixed_currency_totals_are_converted(self):
        snapshot = make_snapshot(
            "2025-09-08",
            [make_position("AAA.TO", value="100", cost="80"),
             make_position("BBB", value="100", cost="80", currency="USD")],
        )
        stats = build_portfolio_stats([snapshot], RATES)
        # 100 CAD + 100 USD at 1.25 = 225 CAD
        assert stats.latest.market_value == Decimal("225.00")
        assert stats.latest.cost_basis == Decimal("180.00")
        assert stats.currency_totals["USD"] == Decimal("125.00")
        assert stats.currency_totals["CAD"] == Decimal("100")

    def test_snapshots_are_sorted_by_timestamp(self):
        late = make_snapshot("2025-09-09", [make_position("AAA", value="200")])
        early = make_snapshot("2025-09-08", [make_position("AAA", value="100")])
        stats = build_portfolio_stats([late, early], RATES)
        assert [float(p.market_value) for p in stats.points] == [100.0, 200.0]

    def test_change_and_pct_across_the_range(self):
        stats = build_portfolio_stats(
            [make_snapshot("2025-09-08", [make_position("AAA", value="100")]),
             make_snapshot("2025-09-09", [make_position("AAA", value="150")])],
            RATES,
        )
        assert stats.change == Decimal("50")
        assert stats.change_pct == Decimal("50")

    def test_single_point_has_no_change(self):
        stats = build_portfolio_stats(
            [make_snapshot("2025-09-08", [make_position("AAA")])], RATES
        )
        assert stats.change == Decimal("0")
        assert stats.change_pct == Decimal("0")
        assert stats.best_day is None

    def test_duplicate_tickers_in_one_day_counted_once(self):
        snapshot = make_snapshot(
            "2025-09-08",
            [make_position("AAA", value="100"), make_position("AAA", value="120")],
        )
        stats = build_portfolio_stats([snapshot], RATES)
        assert stats.latest.market_value == Decimal("120")
        assert len(stats.holdings) == 1

    def test_closed_positions_are_excluded(self):
        snapshot = make_snapshot(
            "2025-09-08",
            [make_position("AAA", value="100", cost="80"),
             make_position("SOLD", shares="0", value="0", cost="5000", pnl="0")],
        )
        stats = build_portfolio_stats([snapshot], RATES)
        assert [h.ticker for h in stats.holdings] == ["AAA"]
        assert stats.latest.cost_basis == Decimal("80")

    def test_holdings_sorted_by_value_with_weights(self):
        snapshot = make_snapshot(
            "2025-09-08",
            [make_position("SMALL", value="25"), make_position("BIG", value="75")],
        )
        stats = build_portfolio_stats([snapshot], RATES)
        assert [h.ticker for h in stats.holdings] == ["BIG", "SMALL"]
        assert stats.holdings[0].weight_pct == Decimal("75")
        assert stats.holdings[1].weight_pct == Decimal("25")

    def test_days_filter_keeps_only_the_recent_tail(self):
        base = datetime(2025, 9, 30)
        snapshots = [
            PortfolioSnapshot(
                positions=[make_position("AAA", value=str(100 + i))],
                timestamp=base - timedelta(days=i),
            )
            for i in range(40)
        ]
        stats = build_portfolio_stats(snapshots, RATES, days=7)
        assert len(stats.points) == 8  # cutoff is inclusive of the boundary day
        assert stats.points[-1].date == base

    def test_days_filter_never_empties_the_series(self):
        stats = build_portfolio_stats(
            [make_snapshot("2020-01-01", [make_position("AAA")])], RATES, days=7
        )
        assert len(stats.points) == 1

    def test_best_and_worst_days(self):
        stats = build_portfolio_stats(
            [make_snapshot("2025-09-08", [make_position("AAA", value="100")]),
             make_snapshot("2025-09-09", [make_position("AAA", value="150")]),
             make_snapshot("2025-09-10", [make_position("AAA", value="120")])],
            RATES,
        )
        assert stats.delta_for(stats.best_day) == Decimal("50")
        assert stats.delta_for(stats.worst_day) == Decimal("-30")

    def test_return_pct_handles_zero_cost_basis(self):
        stats = build_portfolio_stats(
            [make_snapshot("2025-09-08",
                           [make_position("AAA", value="100", cost="0", pnl="100")])],
            RATES,
        )
        assert stats.latest.return_pct == Decimal("0")
        assert stats.holdings[0].return_pct == Decimal("0")
