"""
ETF Look-Through Fundamentals Module

Calculates holdings-weighted ("look-through") fundamental metrics for ETFs from
their underlying constituents, producing an aggregate profile directly evaluable
by FundamentalSignal.
"""

from typing import Any, Dict, List, Optional
import logging
import math

from .fundamental_signal import (
    GROWTH_THRESHOLDS,
    HEALTH_THRESHOLDS,
    PROFITABILITY_THRESHOLDS,
    VALUATION_THRESHOLDS,
)

logger = logging.getLogger(__name__)

# Key lists imported from FundamentalSignal
PROFITABILITY_METRICS: List[str] = [m[0] for m in PROFITABILITY_THRESHOLDS]
GROWTH_METRICS: List[str] = [m[0] for m in GROWTH_THRESHOLDS]
HEALTH_METRICS: List[str] = [m[0] for m in HEALTH_THRESHOLDS]
VALUATION_METRICS: List[str] = [m[0] for m in VALUATION_THRESHOLDS]

ALL_THRESHOLD_METRICS: List[str] = (
    PROFITABILITY_METRICS + GROWTH_METRICS + HEALTH_METRICS + VALUATION_METRICS
)

# Valuation ratios priced per share/market value where weighted harmonic mean is required
RATIO_OF_PRICE_METRICS: set[str] = {
    "trailing_pe",
    "forward_pe",
    "price_to_book",
    "price_to_sales",
}

# Fixed bounds (winsorization) applied to individual holding metrics before computing
# the holdings-weighted arithmetic mean. A few extreme small-cap holdings (e.g. ASTS
# revenue growth +2627%, WULF ROE -1212%, WULF D/E 3549%) would otherwise dominate
# and distort the aggregate fund-level profile.
# Note: debt_to_equity is in percent units as reported by yfinance (100 = 1.0x D/E),
# so 500.0 corresponds to 5.0x leverage.
_METRIC_BOUNDS: Dict[str, tuple[float, float]] = {
    "return_on_equity": (-1.0, 1.0),
    "net_margin": (-1.0, 1.0),
    "operating_margin": (-1.0, 1.0),
    "revenue_growth": (-1.0, 2.0),
    "earnings_growth": (-1.0, 2.0),
    "current_ratio": (0.0, 10.0),
    "debt_to_equity": (0.0, 500.0),
}


def _extract_finite_float(val: Any) -> Optional[float]:
    """Convert input to float, rejecting None, NaN, and Inf."""
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _get_ticker_fundamentals(
    fundamentals_by_ticker: Dict[str, Dict[str, Any]], ticker: str
) -> Optional[Dict[str, Any]]:
    """Look up fundamentals for a ticker, case-insensitively if needed."""
    if not isinstance(fundamentals_by_ticker, dict):
        return None
    if ticker in fundamentals_by_ticker:
        res = fundamentals_by_ticker[ticker]
        return res if isinstance(res, dict) else None
    ticker_upper = ticker.upper()
    if ticker_upper in fundamentals_by_ticker:
        res = fundamentals_by_ticker[ticker_upper]
        return res if isinstance(res, dict) else None
    ticker_lower = ticker.lower()
    if ticker_lower in fundamentals_by_ticker:
        res = fundamentals_by_ticker[ticker_lower]
        return res if isinstance(res, dict) else None
    return None


def _holding_has_fundamentals(fundamentals: Optional[Dict[str, Any]]) -> bool:
    """Check if a fundamentals dictionary has a finite value for any scored metric.

    Only scored metrics count: a securities row nearly always carries price fields
    like fifty_two_week_high, which would make every holding look covered.
    """
    if not fundamentals or not isinstance(fundamentals, dict):
        return False
    return any(
        _extract_finite_float(fundamentals.get(k)) is not None
        for k in ALL_THRESHOLD_METRICS
    )


def _metric_value(fund_data: Optional[Dict[str, Any]], metric_key: str) -> Optional[float]:
    """A holding's value for one metric.

    yfinance omits trailingPE for loss-making companies instead of making it
    negative. Treat missing P/E with trailing EPS <= 0 as a loss (P/E 0, which
    contributes zero earnings yield), or the losers silently drop out and bias
    the aggregate P/E low.
    """
    if not fund_data:
        return None
    val = _extract_finite_float(fund_data.get(metric_key))
    if val is None and metric_key == "trailing_pe":
        eps = _extract_finite_float(fund_data.get("trailing_eps"))
        if eps is not None and eps <= 0.0:
            return 0.0
    return val


def compute_lookthrough_fundamentals(
    holdings: Optional[List[Dict[str, Any]]],
    fundamentals_by_ticker: Optional[Dict[str, Dict[str, Any]]],
    min_coverage: float = 0.5,
) -> Dict[str, Any]:
    """
    Computes holdings-weighted ("look-through") fundamental metrics for an ETF.

    Args:
        holdings: List of dicts with {"ticker": str, "weight_percent": float}.
                  Weights are percentages (e.g. 4.2). Blank/empty tickers or
                  invalid weights are skipped.
        fundamentals_by_ticker: Dict mapping ticker symbol to dictionary of
                                fundamental metric values (column names matching
                                the securities table).
        min_coverage: Minimum fraction of total holding weight (0.0 to 1.0)
                      required to report a metric. Defaults to 0.5 (50%).

    Returns:
        Dict with:
            - metrics: Dict mapping metric_key to aggregated float or None.
                       Usable as input to FundamentalSignal().evaluate(...).
            - coverage: Dict mapping metric_key to fraction of total weight with data (0..1).
            - holdings_total: Total count of valid holdings.
            - holdings_with_fundamentals: Count of valid holdings with available fundamental data.
            - weight_with_fundamentals: Fraction (0..1) of total holding weight with scored data.
            - method: "lookthrough"
            - clipped: Dict mapping metric_key to count of holdings clamped to bounds
                       (only metrics with count > 0 are included; empty if none clamped).
    """
    if holdings is None:
        holdings = []
    if fundamentals_by_ticker is None:
        fundamentals_by_ticker = {}

    # 1. Filter and clean holdings (skip cash/odd rows with ticker None or "")
    valid_holdings: List[Dict[str, Any]] = []
    for h in holdings:
        if not isinstance(h, dict):
            continue
        ticker = h.get("ticker")
        if ticker is None or not isinstance(ticker, str):
            continue
        ticker_clean = ticker.strip()
        if not ticker_clean:
            continue

        raw_weight = h.get("weight_percent")
        weight = _extract_finite_float(raw_weight)
        if weight is None or weight <= 0.0:
            continue

        valid_holdings.append({
            "ticker": ticker_clean,
            "weight_percent": weight,
        })

    holdings_total = len(valid_holdings)
    total_weight = sum(h["weight_percent"] for h in valid_holdings)

    # 2. Track holdings with fundamentals (count + weight fraction)
    holdings_with_fundamentals = 0
    weight_covered = 0.0
    for h in valid_holdings:
        fund_data = _get_ticker_fundamentals(fundamentals_by_ticker, h["ticker"])
        if _holding_has_fundamentals(fund_data):
            holdings_with_fundamentals += 1
            weight_covered += h["weight_percent"]

    weight_with_fundamentals = (
        round(weight_covered / total_weight, 4) if total_weight > 0.0 else 0.0
    )

    # Initialize results
    metrics: Dict[str, Optional[float]] = {}
    coverage: Dict[str, float] = {}
    clipped: Dict[str, int] = {}

    for metric_key in ALL_THRESHOLD_METRICS:
        metrics[metric_key] = None
        coverage[metric_key] = 0.0

    metrics["fcf_positive_weight"] = None
    coverage["fcf_positive_weight"] = 0.0

    if total_weight <= 0.0 or holdings_total == 0:
        return {
            "metrics": metrics,
            "coverage": coverage,
            "holdings_total": holdings_total,
            "holdings_with_fundamentals": holdings_with_fundamentals,
            "weight_with_fundamentals": weight_with_fundamentals,
            "method": "lookthrough",
            "clipped": clipped,
        }

    for metric_key in ALL_THRESHOLD_METRICS:
        covered_holdings: List[tuple[float, float]] = []
        for h in valid_holdings:
            fund_data = _get_ticker_fundamentals(fundamentals_by_ticker, h["ticker"])
            val = _metric_value(fund_data, metric_key)
            if val is not None:
                covered_holdings.append((h["weight_percent"], val))

        covered_weight = sum(w for w, _ in covered_holdings)
        cov = covered_weight / total_weight
        coverage[metric_key] = round(cov, 4)

        # Rule: peg_ratio: skip it (return None); it can't be averaged meaningfully.
        if metric_key == "peg_ratio":
            metrics["peg_ratio"] = None
            continue

        # Rule: free_cash_flow is an absolute dollar amount — do NOT average it.
        # Instead report fcf_positive_weight: share of covered weight with FCF > 0 (0..1).
        if metric_key == "free_cash_flow":
            metrics["free_cash_flow"] = None
            coverage["fcf_positive_weight"] = round(cov, 4)
            if cov >= min_coverage and covered_weight > 0:
                pos_weight = sum(w for w, val in covered_holdings if val > 0.0)
                metrics["fcf_positive_weight"] = round(pos_weight / covered_weight, 4)
            else:
                metrics["fcf_positive_weight"] = None
            continue

        # Rule: A metric is reported only if its covered weight is >= min_coverage; otherwise None.
        if cov < min_coverage or covered_weight <= 0:
            metrics[metric_key] = None
            continue

        if metric_key in RATIO_OF_PRICE_METRICS:
            # Weighted harmonic mean:
            # Holdings with value <= 0 contribute 0 yield and are kept in the average.
            # If aggregate yield <= 0, return None.
            weighted_yield_sum = sum(
                (w * (1.0 / val)) if val > 0.0 else 0.0
                for w, val in covered_holdings
            )
            agg_yield = weighted_yield_sum / covered_weight
            if agg_yield <= 0.0:
                metrics[metric_key] = None
            else:
                metrics[metric_key] = round(1.0 / agg_yield, 4)
        else:
            # Weighted arithmetic mean:
            bounds = _METRIC_BOUNDS.get(metric_key)
            if bounds is not None:
                lower, upper = bounds
                clamped_count = 0
                weighted_val_sum = 0.0
                for w, val in covered_holdings:
                    if val < lower:
                        weighted_val_sum += w * lower
                        clamped_count += 1
                    elif val > upper:
                        weighted_val_sum += w * upper
                        clamped_count += 1
                    else:
                        weighted_val_sum += w * val
                if clamped_count > 0:
                    clipped[metric_key] = clamped_count
            else:
                weighted_val_sum = sum(w * val for w, val in covered_holdings)
            agg_val = weighted_val_sum / covered_weight
            metrics[metric_key] = round(agg_val, 4)

    return {
        "metrics": metrics,
        "coverage": coverage,
        "holdings_total": holdings_total,
        "holdings_with_fundamentals": holdings_with_fundamentals,
        "weight_with_fundamentals": weight_with_fundamentals,
        "method": "lookthrough",
        "clipped": clipped,
    }
