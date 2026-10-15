"""
Tests for ETF look-through fundamentals calculation module.
"""

import math
import pytest

from web_dashboard.signals.etf_lookthrough import compute_lookthrough_fundamentals
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
