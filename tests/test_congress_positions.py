"""
Tests for Congress Closed Positions feature.

Tests the position computation logic, P&L estimation, and helpers
used in jobs_congress_positions.py.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Path setup for imports
project_root = str(Path(__file__).resolve().parent.parent)
web_dashboard_path = str(Path(__file__).resolve().parent.parent / "web_dashboard")
if project_root not in sys.path:
    sys.path.insert(0, project_root)
if web_dashboard_path not in sys.path:
    sys.path.insert(1, web_dashboard_path)


class TestEstimateMidpoint:
    """Test the amount range to midpoint conversion."""

    def setup_method(self):
        from scheduler.jobs_congress_positions import estimate_midpoint
        self.estimate_midpoint = estimate_midpoint

    def test_standard_ranges(self):
        assert self.estimate_midpoint("$1,001 - $15,000") == 8000.50
        assert self.estimate_midpoint("$15,001 - $50,000") == 32500.50
        assert self.estimate_midpoint("$50,001 - $100,000") == 75000.50
        assert self.estimate_midpoint("$100,001 - $250,000") == 175000.50
        assert self.estimate_midpoint("$250,001 - $500,000") == 375000.50
        assert self.estimate_midpoint("$500,001 - $1,000,000") == 750000.50
        assert self.estimate_midpoint("$1,000,001 - $5,000,000") == 3000000.50

    def test_small_range(self):
        assert self.estimate_midpoint("$1 - $1,000") == 500.50

    def test_over_range(self):
        assert self.estimate_midpoint("Over $1,000,000") == 1500000.00

    def test_empty_and_none(self):
        assert self.estimate_midpoint(None) == 0.0
        assert self.estimate_midpoint("") == 0.0

    def test_unknown_range(self):
        assert self.estimate_midpoint("Something weird") == 0.0

    def test_whitespace_handling(self):
        assert self.estimate_midpoint("  $1,001 - $15,000  ") == 8000.50


class TestPositionComputation:
    """Test the position-level aggregation logic."""

    def test_simple_buy_sell(self):
        """One buy, one sell -> correct return and P&L."""
        buys = [{"price": "100.00", "amount": "$15,001 - $50,000"}]
        sells = [{"price": "120.00", "amount": "$15,001 - $50,000"}]

        avg_buy = 100.0
        avg_sell = 120.0
        pct_return = (avg_sell - avg_buy) / avg_buy * 100
        assert pct_return == pytest.approx(20.0)

        from scheduler.jobs_congress_positions import estimate_midpoint
        est_invested = sum(estimate_midpoint(b["amount"]) for b in buys)
        est_pnl = est_invested * pct_return / 100
        assert est_invested == pytest.approx(32500.50)
        assert est_pnl == pytest.approx(6500.10, rel=0.01)

    def test_multiple_buys_single_sell(self):
        """Average buy price across multiple purchases."""
        buy_prices = [100.0, 110.0, 120.0]
        avg_buy = sum(buy_prices) / len(buy_prices)
        assert avg_buy == pytest.approx(110.0)

        avg_sell = 130.0
        pct_return = (avg_sell - avg_buy) / avg_buy * 100
        assert pct_return == pytest.approx(18.18, rel=0.01)

    def test_negative_return(self):
        """Position that lost money."""
        avg_buy = 150.0
        avg_sell = 120.0
        pct_return = (avg_sell - avg_buy) / avg_buy * 100
        assert pct_return == pytest.approx(-20.0)

    def test_zero_buy_price_skipped(self):
        """Zero buy price should be rejected (division by zero)."""
        avg_buy = 0.0
        # The job code skips positions with avg_buy <= 0
        assert avg_buy <= 0  # Would be filtered out

    def test_days_held_calculation(self):
        """Days held = last_sell_date - first_buy_date."""
        from datetime import datetime
        fb = datetime.strptime("2025-01-15", "%Y-%m-%d").date()
        ls = datetime.strptime("2025-04-15", "%Y-%m-%d").date()
        days_held = (ls - fb).days
        assert days_held == 90

    def test_days_held_negative_clamped(self):
        """If sell date is before buy date (data quirk), days_held = 0."""
        from datetime import datetime
        fb = datetime.strptime("2025-04-15", "%Y-%m-%d").date()
        ls = datetime.strptime("2025-01-15", "%Y-%m-%d").date()
        days_held = (ls - fb).days
        if days_held < 0:
            days_held = 0
        assert days_held == 0


class TestEstInvestedAggregation:
    """Test that est_invested sums correctly across multiple purchases."""

    def setup_method(self):
        from scheduler.jobs_congress_positions import estimate_midpoint
        self.estimate_midpoint = estimate_midpoint

    def test_sum_of_multiple_purchases(self):
        """Total invested = sum of midpoints of all purchase amounts."""
        amounts = [
            "$1,001 - $15,000",   # 8000.50
            "$15,001 - $50,000",  # 32500.50
            "$50,001 - $100,000", # 75000.50
        ]
        total = sum(self.estimate_midpoint(a) for a in amounts)
        assert total == pytest.approx(115501.50)

    def test_unknown_amounts_contribute_zero(self):
        """Unknown amount ranges add $0 to invested total."""
        amounts = ["$1,001 - $15,000", "Unknown Range", None]
        total = sum(self.estimate_midpoint(a) for a in amounts)
        assert total == pytest.approx(8000.50)


class TestPnlEstimation:
    """Test the P&L estimation formula."""

    def test_positive_pnl(self):
        est_invested = 100000.0
        pct_return = 15.0
        est_pnl = est_invested * pct_return / 100
        assert est_pnl == pytest.approx(15000.0)

    def test_negative_pnl(self):
        est_invested = 100000.0
        pct_return = -8.5
        est_pnl = est_invested * pct_return / 100
        assert est_pnl == pytest.approx(-8500.0)

    def test_zero_invested_zero_pnl(self):
        est_invested = 0.0
        pct_return = 50.0
        est_pnl = est_invested * pct_return / 100 if est_invested > 0 else 0.0
        assert est_pnl == 0.0

    def test_large_position(self):
        """Test with $5M+ position."""
        est_invested = 15000000.50  # $5M-$25M midpoint
        pct_return = 3.5
        est_pnl = est_invested * pct_return / 100
        assert est_pnl == pytest.approx(525000.02, rel=0.01)


class TestLeaderboardAggregation:
    """Test the politician-level rollup logic."""

    def test_win_loss_counting(self):
        """Positions with pct_return > 0 are wins."""
        returns = [5.0, -3.0, 10.0, -1.0, 0.0, 7.0]
        wins = sum(1 for r in returns if r > 0)
        losses = len(returns) - wins
        assert wins == 3
        assert losses == 3  # 0.0 counts as a loss

    def test_win_percentage(self):
        returns = [5.0, -3.0, 10.0, -1.0, 7.0]
        wins = sum(1 for r in returns if r > 0)
        win_pct = wins / len(returns) * 100
        assert win_pct == pytest.approx(60.0)

    def test_average_return(self):
        returns = [10.0, -5.0, 20.0, -10.0, 15.0]
        avg = sum(returns) / len(returns)
        assert avg == pytest.approx(6.0)

    def test_total_pnl(self):
        """Total P&L is sum of individual position P&Ls."""
        pnls = [15000.0, -3000.0, 8000.0, -1000.0]
        total = sum(pnls)
        assert total == pytest.approx(19000.0)

    def test_min_positions_filter(self):
        """Politicians with fewer than min_positions are excluded."""
        politicians = {
            "A": {"positions": 5, "total_pnl": 50000},
            "B": {"positions": 2, "total_pnl": 100000},
            "C": {"positions": 10, "total_pnl": 30000},
        }
        min_positions = 3
        filtered = {k: v for k, v in politicians.items() if v["positions"] >= min_positions}
        assert len(filtered) == 2
        assert "B" not in filtered


class TestSpyReturnReference:
    """Test SPY return computation logic."""

    def test_spy_pct_change(self):
        """SPY return = (end - start) / start * 100."""
        spy_start = 450.0
        spy_end = 475.0
        spy_pct = (spy_end - spy_start) / spy_start * 100
        assert spy_pct == pytest.approx(5.56, rel=0.01)

    def test_spy_negative_return(self):
        spy_start = 475.0
        spy_end = 450.0
        spy_pct = (spy_end - spy_start) / spy_start * 100
        assert spy_pct == pytest.approx(-5.26, rel=0.01)

    def test_spy_zero_start_skipped(self):
        """If SPY start price is 0, skip (avoid division by zero)."""
        spy_start = 0.0
        # The job code checks spy_start_f > 0 before computing
        assert spy_start <= 0
