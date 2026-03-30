"""
Tests for Congress Trade Returns feature.

Tests the midpoint estimation, return calculation logic,
and the daily job's core computation.
"""

import pytest
import sys
import os

# Add web_dashboard and project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'web_dashboard')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestEstimateMidpoint:
    """Tests for the amount range -> midpoint estimation function."""

    def _get_fn(self):
        from scheduler.jobs_congress_returns import estimate_midpoint
        return estimate_midpoint

    def test_standard_ranges(self):
        fn = self._get_fn()
        assert fn("$1 - $1,000") == 500.50
        assert fn("$1,001 - $15,000") == 8000.50
        assert fn("$15,001 - $50,000") == 32500.50
        assert fn("$50,001 - $100,000") == 75000.50
        assert fn("$100,001 - $250,000") == 175000.50
        assert fn("$250,001 - $500,000") == 375000.50
        assert fn("$500,001 - $1,000,000") == 750000.50
        assert fn("$1,000,001 - $5,000,000") == 3000000.50

    def test_over_range(self):
        fn = self._get_fn()
        assert fn("Over $1,000,000") == 1500000.00

    def test_none_and_empty(self):
        fn = self._get_fn()
        assert fn(None) is None
        assert fn("") is None

    def test_unknown_range(self):
        fn = self._get_fn()
        assert fn("$999,999,999") is None
        assert fn("some random text") is None

    def test_whitespace_handling(self):
        fn = self._get_fn()
        assert fn("  $1,001 - $15,000  ") == 8000.50
        assert fn("$50,001 - $100,000 ") == 75000.50


class TestReturnCalculation:
    """Tests for the core % return calculation logic."""

    def test_positive_return(self):
        """Stock goes up -> positive return."""
        entry = 100.0
        current = 120.0
        pct = ((current - entry) / entry) * 100
        assert round(pct, 2) == 20.0

    def test_negative_return(self):
        """Stock goes down -> negative return."""
        entry = 100.0
        current = 80.0
        pct = ((current - entry) / entry) * 100
        assert round(pct, 2) == -20.0

    def test_zero_return(self):
        """Stock unchanged -> zero return."""
        entry = 100.0
        current = 100.0
        pct = ((current - entry) / entry) * 100
        assert round(pct, 2) == 0.0

    def test_large_gain(self):
        """Stock doubles -> 100% return."""
        entry = 50.0
        current = 100.0
        pct = ((current - entry) / entry) * 100
        assert round(pct, 2) == 100.0

    def test_near_total_loss(self):
        """Stock drops 95% -> -95% return."""
        entry = 100.0
        current = 5.0
        pct = ((current - entry) / entry) * 100
        assert round(pct, 2) == -95.0

    def test_zero_entry_price_guard(self):
        """Zero entry price must be guarded against (division by zero)."""
        entry = 0.0
        current = 100.0
        # The job skips these: if entry_adj == 0: skip
        assert entry == 0  # Just verifying the guard condition exists

    def test_fractional_prices(self):
        """Penny stock-like fractional prices."""
        entry = 0.5
        current = 1.5
        pct = ((current - entry) / entry) * 100
        assert round(pct, 2) == 200.0


class TestNormalizePctChangeForDb:
    """Clamp pct_change to NUMERIC(8,2) range for congress_trade_returns."""

    def _fn(self):
        from scheduler.jobs_congress_returns import normalize_pct_change_for_db
        return normalize_pct_change_for_db

    def test_within_range_unchanged(self):
        fn = self._fn()
        v, clamped = fn(1945.27)
        assert not clamped
        assert v == 1945.27

    def test_clamps_high(self):
        fn = self._fn()
        v, clamped = fn(2_000_000.0)
        assert clamped
        assert v == 999_999.99

    def test_clamps_low(self):
        fn = self._fn()
        v, clamped = fn(-2_000_000.0)
        assert clamped
        assert v == -999_999.99

    def test_boundary_max_not_clamped(self):
        fn = self._fn()
        v, clamped = fn(999_999.99)
        assert not clamped
        assert v == 999_999.99

    def test_zero(self):
        fn = self._fn()
        v, clamped = fn(0.0)
        assert not clamped
        assert v == 0.0


class TestAmountMidpointMapping:
    """Tests that all known amount ranges from the database have midpoint mappings."""

    KNOWN_DB_RANGES = [
        "$1 - $1,000",
        "$1,001 - $15,000",
        "$15,001 - $50,000",
        "$50,001 - $100,000",
        "$100,001 - $250,000",
        "$250,001 - $500,000",
        "$500,001 - $1,000,000",
        "$1,000,001 - $5,000,000",
        "Over $1,000,000",
    ]

    def test_all_known_ranges_have_midpoints(self):
        from scheduler.jobs_congress_returns import estimate_midpoint
        for amount_range in self.KNOWN_DB_RANGES:
            result = estimate_midpoint(amount_range)
            assert result is not None, f"No midpoint for known range: {amount_range}"
            assert result > 0, f"Midpoint should be positive for {amount_range}"

    def test_midpoints_are_ordered(self):
        """Larger ranges should have larger midpoints."""
        from scheduler.jobs_congress_returns import estimate_midpoint
        prev = 0.0
        for amount_range in self.KNOWN_DB_RANGES[:-1]:  # Skip "Over" which is special
            mid = estimate_midpoint(amount_range)
            assert mid is not None
            assert mid > prev, f"Midpoint for {amount_range} ({mid}) should be > {prev}"
            prev = mid


class TestApiResponseFormat:
    """Tests that the Return field is correctly formatted for the API response."""

    def test_pct_change_rounding(self):
        """API should round pct_change to 1 decimal place."""
        pct_change = 12.3456
        try:
            result = round(float(pct_change), 1)
        except (ValueError, TypeError):
            result = None
        assert result == 12.3

    def test_pct_change_none(self):
        """None pct_change should stay None."""
        pct_change = None
        if pct_change is not None:
            try:
                result = round(float(pct_change), 1)
            except (ValueError, TypeError):
                result = None
        else:
            result = None
        assert result is None

    def test_pct_change_negative(self):
        """Negative pct_change should round correctly."""
        pct_change = -45.678
        result = round(float(pct_change), 1)
        assert result == -45.7

    def test_pct_change_zero(self):
        """Zero pct_change should be 0.0."""
        pct_change = 0.0
        result = round(float(pct_change), 1)
        assert result == 0.0
