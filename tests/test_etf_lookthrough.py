"""
Tests for ETF look-through fundamentals calculation module.
"""

import math
import pytest

from web_dashboard.signals.etf_lookthrough import (
    _METRIC_BOUNDS,
    compute_lookthrough_fundamentals,
)
from web_dashboard.signals.fundamental_signal import FundamentalSignal


# ---------------------------------------------------------------------------
# Harmonic Mean & Ratio-of-Price Tests
# ---------------------------------------------------------------------------

class TestHarmonicMeanRatioOfPrice:
    def test_two_equal_holdings_pe(self) -> None:
        """Two 50% holdings at P/E 10 and 40 must yield exactly 16.0."""
        holdings = [
            {"ticker": "AAPL", "weight_percent": 50.0},
            {"ticker": "MSFT", "weight_percent": 50.0},
        ]
        fundamentals = {
            "AAPL": {"trailing_pe": 10.0},
            "MSFT": {"trailing_pe": 40.0},
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        # 1 / (0.5*(1/10) + 0.5*(1/40)) = 1 / (0.05 + 0.0125) = 1 / 0.0625 = 16.0
        assert result["metrics"]["trailing_pe"] == 16.0
        assert result["coverage"]["trailing_pe"] == 1.0

    def test_unequal_weights_pe(self) -> None:
        """80% at P/E 20 and 20% at P/E 10: yield = 0.8*(1/20) + 0.2*(1/10) = 0.06 -> 16.6667."""
        holdings = [
            {"ticker": "A", "weight_percent": 80.0},
            {"ticker": "B", "weight_percent": 20.0},
        ]
        fundamentals = {
            "A": {"trailing_pe": 20.0},
            "B": {"trailing_pe": 10.0},
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        assert result["metrics"]["trailing_pe"] == pytest.approx(16.6667, abs=1e-4)

    def test_all_ratio_of_price_metrics_use_harmonic_mean(self) -> None:
        """forward_pe, price_to_book, and price_to_sales must all use harmonic mean."""
        holdings = [
            {"ticker": "A", "weight_percent": 50.0},
            {"ticker": "B", "weight_percent": 50.0},
        ]
        fundamentals = {
            "A": {"forward_pe": 10.0, "price_to_book": 2.0, "price_to_sales": 1.0},
            "B": {"forward_pe": 40.0, "price_to_book": 8.0, "price_to_sales": 4.0},
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        assert result["metrics"]["forward_pe"] == 16.0
        # P/B: 1 / (0.5*(1/2) + 0.5*(1/8)) = 1 / (0.25 + 0.0625) = 1 / 0.3125 = 3.2
        assert result["metrics"]["price_to_book"] == 3.2
        # P/S: 1 / (0.5*(1/1) + 0.5*(1/4)) = 1 / (0.5 + 0.125) = 1 / 0.625 = 1.6
        assert result["metrics"]["price_to_sales"] == 1.6


# ---------------------------------------------------------------------------
# Negative P/E & Loss Handling
# ---------------------------------------------------------------------------

class TestNegativePEHandling:
    def test_negative_pe_loss_contributes_zero_yield(self) -> None:
        """Holdings with P/E <= 0 contribute 0 yield and remain in the average."""
        holdings = [
            {"ticker": "PROFIT", "weight_percent": 50.0},
            {"ticker": "LOSS", "weight_percent": 50.0},
        ]
        fundamentals = {
            "PROFIT": {"trailing_pe": 10.0},
            "LOSS": {"trailing_pe": -20.0},
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        # Yield = (0.5 * 0.1 + 0.5 * 0.0) = 0.05 -> 1 / 0.05 = 20.0
        assert result["metrics"]["trailing_pe"] == 20.0
        assert result["coverage"]["trailing_pe"] == 1.0

    def test_zero_pe_contributes_zero_yield(self) -> None:
        """P/E of exactly 0 contributes 0 yield without ZeroDivisionError."""
        holdings = [
            {"ticker": "A", "weight_percent": 50.0},
            {"ticker": "B", "weight_percent": 50.0},
        ]
        fundamentals = {
            "A": {"trailing_pe": 10.0},
            "B": {"trailing_pe": 0.0},
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        assert result["metrics"]["trailing_pe"] == 20.0

    def test_all_negative_or_zero_pe_returns_none(self) -> None:
        """If aggregate yield <= 0, return None."""
        holdings = [
            {"ticker": "A", "weight_percent": 50.0},
            {"ticker": "B", "weight_percent": 50.0},
        ]
        fundamentals = {
            "A": {"trailing_pe": -10.0},
            "B": {"trailing_pe": -5.0},
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        assert result["metrics"]["trailing_pe"] is None
        assert result["coverage"]["trailing_pe"] == 1.0


# ---------------------------------------------------------------------------
# Coverage Threshold Tests
# ---------------------------------------------------------------------------

class TestCoverageThreshold:
    def test_metric_meets_min_coverage(self) -> None:
        """Covered weight 60% with default min_coverage 0.5 is reported."""
        holdings = [
            {"ticker": "A", "weight_percent": 60.0},
            {"ticker": "B", "weight_percent": 40.0},
        ]
        fundamentals = {
            "A": {"return_on_equity": 0.20},
            "B": {"return_on_equity": None},
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        assert result["coverage"]["return_on_equity"] == 0.6
        assert result["metrics"]["return_on_equity"] == 0.20

    def test_metric_below_min_coverage_returns_none(self) -> None:
        """Covered weight 40% with default min_coverage 0.5 returns None."""
        holdings = [
            {"ticker": "A", "weight_percent": 40.0},
            {"ticker": "B", "weight_percent": 60.0},
        ]
        fundamentals = {
            "A": {"return_on_equity": 0.20},
            "B": {"return_on_equity": None},
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        assert result["coverage"]["return_on_equity"] == 0.4
        assert result["metrics"]["return_on_equity"] is None

    def test_custom_min_coverage(self) -> None:
        """Custom min_coverage thresholds alter whether a metric is reported."""
        holdings = [
            {"ticker": "A", "weight_percent": 40.0},
            {"ticker": "B", "weight_percent": 60.0},
        ]
        fundamentals = {
            "A": {"net_margin": 0.15},
            "B": {"net_margin": None},
        }

        # 40% coverage passes 0.35 min_coverage
        res_pass = compute_lookthrough_fundamentals(holdings, fundamentals, min_coverage=0.35)
        assert res_pass["metrics"]["net_margin"] == 0.15

        # 40% coverage fails 0.50 min_coverage
        res_fail = compute_lookthrough_fundamentals(holdings, fundamentals, min_coverage=0.50)
        assert res_fail["metrics"]["net_margin"] is None


# ---------------------------------------------------------------------------
# Weight Renormalization Tests
# ---------------------------------------------------------------------------

class TestWeightRenormalization:
    def test_weights_not_summing_to_100(self) -> None:
        """When total holding weight != 100 (e.g. 60%),
        weights are renormalized over covered weight.
        """
        holdings = [
            {"ticker": "A", "weight_percent": 20.0},
            {"ticker": "B", "weight_percent": 40.0},
        ]
        fundamentals = {
            "A": {"return_on_equity": 0.10},
            "B": {"return_on_equity": 0.25},
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        # Total weight = 60. Both covered -> coverage = 60/60 = 1.0
        assert result["coverage"]["return_on_equity"] == 1.0
        # Renormalized: (20*0.10 + 40*0.25) / 60 = (2 + 10) / 60 = 0.20
        assert result["metrics"]["return_on_equity"] == 0.20

    def test_per_metric_renormalization(self) -> None:
        """Each metric renormalizes only over holdings that have data for that metric."""
        holdings = [
            {"ticker": "A", "weight_percent": 50.0},
            {"ticker": "B", "weight_percent": 50.0},
        ]
        fundamentals = {
            "A": {"return_on_equity": 0.18, "revenue_growth": None},
            "B": {"return_on_equity": None, "revenue_growth": 0.12},
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        assert result["coverage"]["return_on_equity"] == 0.5
        assert result["metrics"]["return_on_equity"] == 0.18
        assert result["coverage"]["revenue_growth"] == 0.5
        assert result["metrics"]["revenue_growth"] == 0.12


# ---------------------------------------------------------------------------
# Skipped Blank Tickers & Invalid Holdings Tests
# ---------------------------------------------------------------------------

class TestSkippedBlankTickers:
    def test_skipped_none_and_empty_tickers(self) -> None:
        """Rows with ticker None or empty string are skipped."""
        holdings = [
            {"ticker": None, "weight_percent": 15.0},
            {"ticker": "", "weight_percent": 10.0},
            {"ticker": "   ", "weight_percent": 5.0},
            {"ticker": "AAPL", "weight_percent": 70.0},
        ]
        fundamentals = {
            "AAPL": {"return_on_equity": 0.25},
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        assert result["holdings_total"] == 1
        assert result["holdings_with_fundamentals"] == 1
        assert result["coverage"]["return_on_equity"] == 1.0
        assert result["metrics"]["return_on_equity"] == 0.25

    def test_skipped_invalid_weights(self) -> None:
        """Rows with invalid, non-positive, NaN, or Inf weights are skipped."""
        holdings = [
            {"ticker": "ZERO", "weight_percent": 0.0},
            {"ticker": "NEG", "weight_percent": -5.0},
            {"ticker": "NAN", "weight_percent": float("nan")},
            {"ticker": "STR", "weight_percent": "invalid"},
            {"ticker": "VALID", "weight_percent": 50.0},
        ]
        fundamentals = {
            "VALID": {"return_on_equity": 0.15},
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        assert result["holdings_total"] == 1
        assert result["coverage"]["return_on_equity"] == 1.0
        assert result["metrics"]["return_on_equity"] == 0.15


# ---------------------------------------------------------------------------
# NaN and Inf Values in Fundamentals Tests
# ---------------------------------------------------------------------------

class TestNaNAndInfValues:
    def test_nan_and_inf_in_fundamentals_skipped(self) -> None:
        """NaN and Inf metric values are skipped and treated as missing."""
        holdings = [
            {"ticker": "A", "weight_percent": 50.0},
            {"ticker": "B", "weight_percent": 50.0},
        ]
        fundamentals = {
            "A": {"current_ratio": 2.0, "debt_to_equity": float("nan")},
            "B": {"current_ratio": float("inf"), "debt_to_equity": 0.4},
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        # current_ratio only valid on A (weight 50%) -> coverage 0.5, value 2.0
        assert result["coverage"]["current_ratio"] == 0.5
        assert result["metrics"]["current_ratio"] == 2.0
        # debt_to_equity only valid on B (weight 50%) -> coverage 0.5, value 0.4
        assert result["coverage"]["debt_to_equity"] == 0.5
        assert result["metrics"]["debt_to_equity"] == 0.4


# ---------------------------------------------------------------------------
# Free Cash Flow & fcf_positive_weight Tests
# ---------------------------------------------------------------------------

class TestFreeCashFlow:
    def test_fcf_not_averaged_and_positive_share_reported(self) -> None:
        """FCF dollar amounts are not averaged;
        fcf_positive_weight reports positive weight share.
        """
        holdings = [
            {"ticker": "A", "weight_percent": 40.0},  # FCF > 0
            {"ticker": "B", "weight_percent": 40.0},  # FCF < 0
            {"ticker": "C", "weight_percent": 20.0},  # FCF missing
        ]
        fundamentals = {
            "A": {"free_cash_flow": 500_000_000},
            "B": {"free_cash_flow": -100_000_000},
            "C": {},
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        # free_cash_flow is never averaged (always None)
        assert result["metrics"]["free_cash_flow"] is None
        # Coverage is 80/100 = 0.8
        assert result["coverage"]["free_cash_flow"] == 0.8
        assert result["coverage"]["fcf_positive_weight"] == 0.8
        # fcf_positive_weight is share of covered weight: 40 / 80 = 0.5
        assert result["metrics"]["fcf_positive_weight"] == 0.5

    def test_fcf_all_positive(self) -> None:
        """All covered holdings FCF > 0 yields fcf_positive_weight = 1.0."""
        holdings = [
            {"ticker": "A", "weight_percent": 50.0},
            {"ticker": "B", "weight_percent": 50.0},
        ]
        fundamentals = {
            "A": {"free_cash_flow": 100.0},
            "B": {"free_cash_flow": 200.0},
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        assert result["metrics"]["fcf_positive_weight"] == 1.0

    def test_fcf_all_negative_or_zero(self) -> None:
        """No holdings with FCF > 0 yields fcf_positive_weight = 0.0."""
        holdings = [
            {"ticker": "A", "weight_percent": 50.0},
            {"ticker": "B", "weight_percent": 50.0},
        ]
        fundamentals = {
            "A": {"free_cash_flow": -50.0},
            "B": {"free_cash_flow": 0.0},
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        assert result["metrics"]["fcf_positive_weight"] == 0.0

    def test_fcf_below_min_coverage_returns_none(self) -> None:
        """When FCF coverage is below min_coverage, fcf_positive_weight is None."""
        holdings = [
            {"ticker": "A", "weight_percent": 30.0},
            {"ticker": "B", "weight_percent": 70.0},
        ]
        fundamentals = {
            "A": {"free_cash_flow": 100.0},
            "B": {},
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals, min_coverage=0.5)
        assert result["coverage"]["free_cash_flow"] == 0.3
        assert result["metrics"]["fcf_positive_weight"] is None


# ---------------------------------------------------------------------------
# PEG Ratio Skipped Tests
# ---------------------------------------------------------------------------

class TestPegRatio:
    def test_peg_ratio_always_none(self) -> None:
        """peg_ratio is skipped and returns None even if all holdings provide it."""
        holdings = [
            {"ticker": "A", "weight_percent": 50.0},
            {"ticker": "B", "weight_percent": 50.0},
        ]
        fundamentals = {
            "A": {"peg_ratio": 1.2},
            "B": {"peg_ratio": 1.8},
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        assert result["metrics"]["peg_ratio"] is None
        assert result["coverage"]["peg_ratio"] == 1.0


# ---------------------------------------------------------------------------
# FundamentalSignal Integration Tests
# ---------------------------------------------------------------------------

class TestFundamentalSignalIntegration:
    def test_output_feeds_fundamental_signal_without_error(self) -> None:
        """The metrics output directly evaluates with FundamentalSignal without error."""
        holdings = [
            {"ticker": "NVDA", "weight_percent": 30.0},
            {"ticker": "AAPL", "weight_percent": 30.0},
            {"ticker": "MSFT", "weight_percent": 40.0},
        ]
        fundamentals = {
            "NVDA": {
                "return_on_equity": 0.40,
                "net_margin": 0.35,
                "operating_margin": 0.30,
                "revenue_growth": 0.50,
                "earnings_growth": 0.60,
                "current_ratio": 2.5,
                "debt_to_equity": 0.2,
                "free_cash_flow": 15_000_000_000,
                "trailing_pe": 35.0,
                "forward_pe": 28.0,
                "price_to_book": 12.0,
                "price_to_sales": 15.0,
                "peg_ratio": 1.5,
            },
            "AAPL": {
                "return_on_equity": 0.30,
                "net_margin": 0.25,
                "operating_margin": 0.25,
                "revenue_growth": 0.10,
                "earnings_growth": 0.12,
                "current_ratio": 1.8,
                "debt_to_equity": 0.8,
                "free_cash_flow": 25_000_000_000,
                "trailing_pe": 28.0,
                "forward_pe": 24.0,
                "price_to_book": 8.0,
                "price_to_sales": 7.0,
                "peg_ratio": 2.0,
            },
            "MSFT": {
                "return_on_equity": 0.25,
                "net_margin": 0.30,
                "operating_margin": 0.28,
                "revenue_growth": 0.15,
                "earnings_growth": 0.18,
                "current_ratio": 2.0,
                "debt_to_equity": 0.4,
                "free_cash_flow": 20_000_000_000,
                "trailing_pe": 30.0,
                "forward_pe": 26.0,
                "price_to_book": 9.0,
                "price_to_sales": 10.0,
                "peg_ratio": 1.8,
            },
        }

        lookthrough = compute_lookthrough_fundamentals(holdings, fundamentals)
        assert lookthrough["method"] == "lookthrough"
        assert lookthrough["holdings_total"] == 3
        assert lookthrough["holdings_with_fundamentals"] == 3

        signal = FundamentalSignal()
        evaluation = signal.evaluate(lookthrough["metrics"])

        assert "error" not in evaluation
        assert evaluation["quality"] in ("STRONG", "GOOD", "FAIR", "WEAK")
        assert 0.0 <= evaluation["composite_score"] <= 1.0
        assert evaluation["metrics_available"] > 0
        for cat in ["profitability", "growth", "health", "valuation"]:
            assert cat in evaluation
            assert evaluation[cat]["score"] is not None

    def test_empty_lookthrough_feeds_fundamental_signal(self) -> None:
        """Empty holdings feed FundamentalSignal safely returning UNKNOWN quality."""
        lookthrough = compute_lookthrough_fundamentals([], {})
        signal = FundamentalSignal()
        evaluation = signal.evaluate(lookthrough["metrics"])
        assert evaluation["quality"] == "UNKNOWN"
        assert evaluation["metrics_available"] == 0


# ---------------------------------------------------------------------------
# General Edge Cases Tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_none_inputs(self) -> None:
        """None holdings or fundamentals handled gracefully."""
        res = compute_lookthrough_fundamentals(None, None)
        assert res["holdings_total"] == 0
        assert res["holdings_with_fundamentals"] == 0
        assert res["weight_with_fundamentals"] == 0.0
        assert res["method"] == "lookthrough"
        for k in res["metrics"]:
            assert res["metrics"][k] is None
        for k in res["coverage"]:
            assert res["coverage"][k] == 0.0

    def test_weight_with_fundamentals_fraction(self) -> None:
        """weight_with_fundamentals is the share of total weight with scored data."""
        holdings = [
            {"ticker": "A", "weight_percent": 60.0},
            {"ticker": "B", "weight_percent": 40.0},
        ]
        fundamentals = {
            "A": {"return_on_equity": 0.2},
            "B": {"fifty_two_week_high": 10.0},  # price-only — not scored
        }
        res = compute_lookthrough_fundamentals(holdings, fundamentals)
        assert res["holdings_with_fundamentals"] == 1
        assert res["weight_with_fundamentals"] == 0.6

    def test_case_insensitive_ticker_lookup(self) -> None:
        """Holdings with lowercase ticker matched to uppercase fundamentals dict."""
        holdings = [{"ticker": "aapl", "weight_percent": 100.0}]
        fundamentals = {"AAPL": {"return_on_equity": 0.22}}

        res = compute_lookthrough_fundamentals(holdings, fundamentals)
        assert res["holdings_total"] == 1
        assert res["holdings_with_fundamentals"] == 1
        assert res["metrics"]["return_on_equity"] == 0.22

    def test_holdings_total_and_fundamentals_count(self) -> None:
        """holdings_total counts valid holdings,
        holdings_with_fundamentals counts those with data.
        """
        holdings = [
            {"ticker": "HAS_DATA", "weight_percent": 30.0},
            {"ticker": "EMPTY_DICT", "weight_percent": 30.0},
            {"ticker": "NOT_IN_DICT", "weight_percent": 40.0},
        ]
        fundamentals = {
            "HAS_DATA": {"return_on_equity": 0.15},
            "EMPTY_DICT": {"return_on_equity": None, "trailing_pe": None},
        }

        res = compute_lookthrough_fundamentals(holdings, fundamentals)
        assert res["holdings_total"] == 3
        assert res["holdings_with_fundamentals"] == 1


class TestRealSecuritiesRowShapes:
    def test_price_only_rows_do_not_count_as_fundamentals(self) -> None:
        """A securities row with only 52-week prices has no scored fundamentals."""
        holdings = [
            {"ticker": "AAA", "weight_percent": 50.0},
            {"ticker": "BBB", "weight_percent": 50.0},
        ]
        fundamentals = {
            "AAA": {"fifty_two_week_high": 41.2, "fifty_two_week_low": 26.9},
            "BBB": {"return_on_equity": 0.2, "fifty_two_week_high": 10.0},
        }
        res = compute_lookthrough_fundamentals(holdings, fundamentals)
        assert res["holdings_with_fundamentals"] == 1

    def test_missing_pe_with_negative_eps_counts_as_loss(self) -> None:
        """yfinance omits trailingPE for losers; negative EPS must still drag the P/E up."""
        holdings = [
            {"ticker": "WIN", "weight_percent": 50.0},
            {"ticker": "LOSS", "weight_percent": 50.0},
        ]
        fundamentals = {
            "WIN": {"trailing_pe": 10.0, "trailing_eps": 2.0},
            "LOSS": {"trailing_pe": None, "trailing_eps": -1.5},
        }
        res = compute_lookthrough_fundamentals(holdings, fundamentals)
        # Yield: 0.5 * 0.1 + 0.5 * 0 = 0.05 -> P/E 20, not 10
        assert res["metrics"]["trailing_pe"] == pytest.approx(20.0)
        assert res["coverage"]["trailing_pe"] == pytest.approx(1.0)

    def test_missing_pe_without_eps_stays_missing(self) -> None:
        holdings = [
            {"ticker": "WIN", "weight_percent": 50.0},
            {"ticker": "UNK", "weight_percent": 50.0},
        ]
        fundamentals = {"WIN": {"trailing_pe": 10.0}, "UNK": {"trailing_pe": None}}
        res = compute_lookthrough_fundamentals(holdings, fundamentals)
        assert res["metrics"]["trailing_pe"] == pytest.approx(10.0)
        assert res["coverage"]["trailing_pe"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Outlier Clamping (Winsorization) Tests
# ---------------------------------------------------------------------------

class TestOutlierClamping:
    def test_metric_bounds_definitions(self) -> None:
        """Verify _METRIC_BOUNDS matches specification exactly."""
        assert _METRIC_BOUNDS == {
            "return_on_equity": (-1.0, 1.0),
            "net_margin": (-1.0, 1.0),
            "operating_margin": (-1.0, 1.0),
            "revenue_growth": (-1.0, 2.0),
            "earnings_growth": (-1.0, 2.0),
            "current_ratio": (0.0, 10.0),
            "debt_to_equity": (0.0, 500.0),
        }

    def test_revenue_growth_extreme_outlier_clamped_to_two(self) -> None:
        """A +2,627% (+26.27) revenue growth holding is clamped to 2.0."""
        holdings = [
            {"ticker": "ASTS", "weight_percent": 50.0},
            {"ticker": "NORM", "weight_percent": 50.0},
        ]
        fundamentals = {
            "ASTS": {"revenue_growth": 26.27},
            "NORM": {"revenue_growth": 0.10},
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        # ASTS clamped to 2.0: (0.5 * 2.0 + 0.5 * 0.10) = 1.05
        assert result["metrics"]["revenue_growth"] == 1.05
        assert result["coverage"]["revenue_growth"] == 1.0
        assert result["clipped"]["revenue_growth"] == 1

    def test_values_inside_bounds_are_untouched(self) -> None:
        """Constituents within bounds are not clamped; clipped count is empty."""
        holdings = [
            {"ticker": "A", "weight_percent": 50.0},
            {"ticker": "B", "weight_percent": 50.0},
        ]
        fundamentals = {
            "A": {
                "return_on_equity": 0.20,
                "revenue_growth": 0.15,
                "debt_to_equity": 40.0,
                "net_margin": 0.10,
                "current_ratio": 2.0,
            },
            "B": {
                "return_on_equity": 0.10,
                "revenue_growth": 0.25,
                "debt_to_equity": 60.0,
                "net_margin": 0.20,
                "current_ratio": 3.0,
            },
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        assert result["metrics"]["return_on_equity"] == 0.15
        assert result["metrics"]["revenue_growth"] == 0.20
        assert result["metrics"]["debt_to_equity"] == 50.0
        assert result["metrics"]["net_margin"] == 0.15
        assert result["metrics"]["current_ratio"] == 2.5
        assert result["clipped"] == {}

    def test_roe_extreme_negative_clamped_to_minus_one(self) -> None:
        """ROE -12.12 (e.g. WULF) clamps to -1.0."""
        holdings = [
            {"ticker": "WULF", "weight_percent": 50.0},
            {"ticker": "CIFR", "weight_percent": 50.0},
        ]
        fundamentals = {
            "WULF": {"return_on_equity": -12.12},
            "CIFR": {"return_on_equity": 0.20},
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        # WULF clamped to -1.0: (0.5 * -1.0 + 0.5 * 0.20) = -0.40
        assert result["metrics"]["return_on_equity"] == -0.40
        assert result["coverage"]["return_on_equity"] == 1.0
        assert result["clipped"]["return_on_equity"] == 1

    def test_debt_to_equity_outlier_clamped_to_five_hundred(self) -> None:
        """D/E 3549.6 (e.g. WULF) clamps to 500.0."""
        holdings = [
            {"ticker": "WULF", "weight_percent": 50.0},
            {"ticker": "CRWV", "weight_percent": 50.0},
        ]
        fundamentals = {
            "WULF": {"debt_to_equity": 3549.6},
            "CRWV": {"debt_to_equity": 100.0},
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        # WULF clamped to 500.0: (0.5 * 500.0 + 0.5 * 100.0) = 300.0
        assert result["metrics"]["debt_to_equity"] == 300.0
        assert result["coverage"]["debt_to_equity"] == 1.0
        assert result["clipped"]["debt_to_equity"] == 1

    def test_pe_ratio_not_clamped(self) -> None:
        """Valuation metrics (e.g. trailing_pe) are not clamped by arithmetic bounds."""
        holdings = [
            {"ticker": "EXPENSIVE", "weight_percent": 50.0},
            {"ticker": "NORMAL", "weight_percent": 50.0},
        ]
        fundamentals = {
            "EXPENSIVE": {"trailing_pe": 1000.0, "forward_pe": 800.0, "price_to_book": 50.0, "price_to_sales": 100.0},
            "NORMAL": {"trailing_pe": 50.0, "forward_pe": 40.0, "price_to_book": 5.0, "price_to_sales": 10.0},
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        # Harmonic mean: 0.5 * (1/1000) + 0.5 * (1/50) = 0.0005 + 0.01 = 0.0105 -> 1/0.0105 = 95.2381
        assert result["metrics"]["trailing_pe"] == pytest.approx(95.2381, abs=1e-4)
        # None of the harmonic-mean valuation metrics should ever appear in clipped
        assert "trailing_pe" not in result["clipped"]
        assert "forward_pe" not in result["clipped"]
        assert "price_to_book" not in result["clipped"]
        assert "price_to_sales" not in result["clipped"]
        assert result["clipped"] == {}

    def test_clipped_counts_multiple_holdings_and_metrics(self) -> None:
        """Multiple holdings clamped across different bounded metrics are tracked accurately."""
        holdings = [
            {"ticker": "ASTS", "weight_percent": 25.0},
            {"ticker": "BMNR", "weight_percent": 25.0},
            {"ticker": "WULF", "weight_percent": 25.0},
            {"ticker": "SAFE", "weight_percent": 25.0},
        ]
        fundamentals = {
            "ASTS": {"revenue_growth": 26.27, "current_ratio": 13.1},
            "BMNR": {"revenue_growth": 21.68, "current_ratio": 36.7},
            "WULF": {"debt_to_equity": 3549.6, "return_on_equity": -12.12},
            "SAFE": {
                "revenue_growth": 0.15,
                "current_ratio": 2.0,
                "debt_to_equity": 50.0,
                "return_on_equity": 0.20,
            },
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        # revenue_growth: ASTS (26.27 -> 2.0) and BMNR (21.68 -> 2.0) are clamped; SAFE (0.15) untouched.
        # covered weight = 25+25+25 = 75 (ASTS, BMNR, SAFE)
        # sum = 25*2.0 + 25*2.0 + 25*0.15 = 50 + 50 + 3.75 = 103.75 -> 103.75 / 75 = 1.3833
        assert result["metrics"]["revenue_growth"] == pytest.approx(1.3833, abs=1e-4)
        assert result["clipped"]["revenue_growth"] == 2

        # current_ratio: ASTS (13.1 -> 10.0) and BMNR (36.7 -> 10.0) are clamped; SAFE (2.0) untouched.
        # covered weight = 75
        # sum = 25*10.0 + 25*10.0 + 25*2.0 = 250 + 250 + 50 = 550 -> 550 / 75 = 7.3333
        assert result["metrics"]["current_ratio"] == pytest.approx(7.3333, abs=1e-4)
        assert result["clipped"]["current_ratio"] == 2

        # debt_to_equity: WULF (3549.6 -> 500.0) is clamped; SAFE (50.0) untouched.
        # covered weight = 50
        # sum = 25*500.0 + 25*50.0 = 12500 + 1250 = 13750 -> 13750 / 50 = 275.0
        assert result["metrics"]["debt_to_equity"] == 275.0
        assert result["clipped"]["debt_to_equity"] == 1

        # return_on_equity: WULF (-12.12 -> -1.0) is clamped; SAFE (0.20) untouched.
        # covered weight = 50
        # sum = 25*(-1.0) + 25*(0.20) = -25 + 5 = -20 -> -20 / 50 = -0.40
        assert result["metrics"]["return_on_equity"] == -0.40
        assert result["clipped"]["return_on_equity"] == 1

    def test_coverage_unchanged_by_clamping(self) -> None:
        """Coverage and covered weights are calculated before clamping and unaffected by bounds."""
        holdings = [
            {"ticker": "ASTS", "weight_percent": 60.0},
            {"ticker": "EMPTY", "weight_percent": 40.0},
        ]
        fundamentals = {
            "ASTS": {"revenue_growth": 26.27},
            "EMPTY": {},
        }

        result = compute_lookthrough_fundamentals(holdings, fundamentals)
        assert result["coverage"]["revenue_growth"] == 0.6
        assert result["holdings_with_fundamentals"] == 1
        assert result["weight_with_fundamentals"] == 0.6
        assert result["metrics"]["revenue_growth"] == 2.0
        assert result["clipped"]["revenue_growth"] == 1

    def test_empty_and_zero_holdings_clipped(self) -> None:
        """Empty holdings inputs return empty clipped dict."""
        res_empty = compute_lookthrough_fundamentals([], {})
        assert res_empty["clipped"] == {}

        res_none = compute_lookthrough_fundamentals(None, None)
        assert res_none["clipped"] == {}

    @pytest.mark.parametrize("metric_key,lower,upper", [
        ("return_on_equity", -1.0, 1.0),
        ("net_margin", -1.0, 1.0),
        ("operating_margin", -1.0, 1.0),
        ("revenue_growth", -1.0, 2.0),
        ("earnings_growth", -1.0, 2.0),
        ("current_ratio", 0.0, 10.0),
        ("debt_to_equity", 0.0, 500.0),
    ])
    def test_each_bounded_metric_clamps_lower_and_upper(
        self, metric_key: str, lower: float, upper: float
    ) -> None:
        """Verify each bounded metric clamps below lower bound and above upper bound."""
        # Below lower bound
        holdings_low = [{"ticker": "LOW", "weight_percent": 100.0}]
        fundamentals_low = {"LOW": {metric_key: lower - 10.0}}
        res_low = compute_lookthrough_fundamentals(holdings_low, fundamentals_low)
        assert res_low["metrics"][metric_key] == lower
        assert res_low["clipped"][metric_key] == 1

        # Above upper bound
        holdings_high = [{"ticker": "HIGH", "weight_percent": 100.0}]
        fundamentals_high = {"HIGH": {metric_key: upper + 10.0}}
        res_high = compute_lookthrough_fundamentals(holdings_high, fundamentals_high)
        assert res_high["metrics"][metric_key] == upper
        assert res_high["clipped"][metric_key] == 1
