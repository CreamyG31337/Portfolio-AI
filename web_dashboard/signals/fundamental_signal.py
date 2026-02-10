"""
Fundamental Signal Analysis

Scores a stock's fundamental metrics against research-backed thresholds
(derived from ai-hedge-fund and stock-analysis-with-llm projects).

Categories:
- Profitability: ROE, Net Margin, Operating Margin
- Growth: Revenue Growth, Earnings Growth
- Financial Health: Current Ratio, Debt/Equity, Free Cash Flow
- Valuation: P/E, P/B, P/S, PEG

Missing values are skipped (not penalized). This is critical for micro-cap
stocks where yfinance frequently returns None for many fields.
"""

from typing import Any, Dict, Optional
import logging

logger = logging.getLogger(__name__)

# Thresholds derived from ai-hedge-fund fundamentals.py
# Each tuple: (metric_key, good_threshold, direction)
# direction = "above" means higher is better, "below" means lower is better
PROFITABILITY_THRESHOLDS = [
    ("return_on_equity", 0.15, "above"),    # ROE > 15%
    ("net_margin", 0.20, "above"),           # Net Margin > 20%
    ("operating_margin", 0.15, "above"),     # Operating Margin > 15%
]

GROWTH_THRESHOLDS = [
    ("revenue_growth", 0.10, "above"),       # Revenue Growth > 10%
    ("earnings_growth", 0.10, "above"),      # Earnings Growth > 10%
]

HEALTH_THRESHOLDS = [
    ("current_ratio", 1.5, "above"),         # Current Ratio > 1.5
    ("debt_to_equity", 0.5, "below"),        # Debt/Equity < 0.5
    ("free_cash_flow", 0.0, "above"),        # FCF > 0
]

VALUATION_THRESHOLDS = [
    ("trailing_pe", 25.0, "below"),          # P/E < 25
    ("forward_pe", 20.0, "below"),           # Forward P/E < 20
    ("price_to_book", 3.0, "below"),         # P/B < 3
    ("price_to_sales", 5.0, "below"),        # P/S < 5
    ("peg_ratio", 1.5, "below"),             # PEG < 1.5
]


def _score_metric(value: Optional[float], threshold: float, direction: str) -> Optional[float]:
    """Score a single metric against its threshold.

    Returns a score between 0.0 and 1.0, or None if the value is missing.

    Scoring:
    - Exactly at threshold = 0.5
    - For "above" metrics: double the threshold = 1.0, zero = 0.0
    - For "below" metrics: zero = 1.0, double the threshold = 0.0
    """
    if value is None:
        return None

    try:
        val = float(value)
    except (TypeError, ValueError):
        return None

    if direction == "above":
        if threshold == 0:
            # Special case: just check positive vs negative
            if val > 0:
                return min(1.0, 0.5 + val * 0.5)
            else:
                return max(0.0, 0.5 + val * 0.5)
        # Scale: 0 -> 0.0, threshold -> 0.5, 2*threshold -> 1.0
        score = val / (2.0 * threshold)
    else:  # "below"
        if threshold == 0:
            return 0.5
        # Scale: 0 -> 1.0, threshold -> 0.5, 2*threshold -> 0.0
        score = 1.0 - val / (2.0 * threshold)

    return max(0.0, min(1.0, score))


def _score_category(
    fundamentals: Dict[str, Any],
    thresholds: list[tuple[str, float, str]],
) -> Dict[str, Any]:
    """Score a category of metrics.

    Returns dict with individual metric values, per-metric scores,
    and an aggregate category score (average of available metrics).
    """
    scores: list[float] = []
    details: Dict[str, Any] = {}

    for metric_key, threshold, direction in thresholds:
        raw_value = fundamentals.get(metric_key)
        metric_score = _score_metric(raw_value, threshold, direction)

        if raw_value is not None:
            try:
                details[metric_key] = round(float(raw_value), 4)
            except (TypeError, ValueError):
                details[metric_key] = None
        else:
            details[metric_key] = None

        if metric_score is not None:
            scores.append(metric_score)

    avg_score = sum(scores) / len(scores) if scores else 0.5
    details["score"] = round(avg_score, 3)
    details["metrics_available"] = len(scores)
    details["metrics_total"] = len(thresholds)

    return details


class FundamentalSignal:
    """
    Scores a stock's fundamental quality from a dict of metrics.

    The fundamentals dict is expected to have keys matching the securities
    table columns (e.g. 'return_on_equity', 'trailing_pe', 'debt_to_equity').
    Missing keys are gracefully skipped.
    """

    def evaluate(self, fundamentals: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Evaluate fundamental signal.

        Args:
            fundamentals: Dictionary of fundamental metrics. Keys should match
                          securities table column names. None values and missing
                          keys are handled gracefully.

        Returns:
            Dictionary with per-category scores and a composite quality rating.
        """
        if not fundamentals:
            return self._empty_result("No fundamental data provided")

        try:
            profitability = _score_category(fundamentals, PROFITABILITY_THRESHOLDS)
            growth = _score_category(fundamentals, GROWTH_THRESHOLDS)
            health = _score_category(fundamentals, HEALTH_THRESHOLDS)
            valuation = _score_category(fundamentals, VALUATION_THRESHOLDS)

            total_available = (
                profitability["metrics_available"]
                + growth["metrics_available"]
                + health["metrics_available"]
                + valuation["metrics_available"]
            )

            if total_available == 0:
                return self._empty_result("No fundamental metrics available")

            # Weight categories equally (adjust if you want valuation to matter more)
            category_scores = []
            for cat in [profitability, growth, health, valuation]:
                if cat["metrics_available"] > 0:
                    category_scores.append(cat["score"])

            composite = sum(category_scores) / len(category_scores) if category_scores else 0.5

            if composite >= 0.7:
                quality = "STRONG"
            elif composite >= 0.5:
                quality = "GOOD"
            elif composite >= 0.35:
                quality = "FAIR"
            else:
                quality = "WEAK"

            return {
                "profitability": profitability,
                "growth": growth,
                "health": health,
                "valuation": valuation,
                "composite_score": round(composite, 3),
                "quality": quality,
                "metrics_available": total_available,
            }

        except Exception as e:
            logger.error(f"Error evaluating fundamental signal: {e}", exc_info=True)
            return self._empty_result(str(e))

    @staticmethod
    def _empty_result(reason: str = "") -> Dict[str, Any]:
        empty_cat: Dict[str, Any] = {"score": 0.5, "metrics_available": 0, "metrics_total": 0}
        result: Dict[str, Any] = {
            "profitability": {**empty_cat, "metrics_total": len(PROFITABILITY_THRESHOLDS)},
            "growth": {**empty_cat, "metrics_total": len(GROWTH_THRESHOLDS)},
            "health": {**empty_cat, "metrics_total": len(HEALTH_THRESHOLDS)},
            "valuation": {**empty_cat, "metrics_total": len(VALUATION_THRESHOLDS)},
            "composite_score": 0.5,
            "quality": "UNKNOWN",
            "metrics_available": 0,
        }
        if reason:
            result["error"] = reason
        return result
