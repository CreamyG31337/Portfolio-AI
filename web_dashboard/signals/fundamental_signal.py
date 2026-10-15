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
import math
import re

logger = logging.getLogger(__name__)

# Below these, a composite score is mostly the 0.5 defaults and says nothing
# (e.g. one P/E value alone rating an ETF "GOOD"), so report UNKNOWN instead.
MIN_METRICS_FOR_RATING = 3
MIN_CATEGORIES_FOR_RATING = 2

_ETF_NAME_RE = re.compile(r"\b(ETF|ETN)\b", re.IGNORECASE)


def _looks_like_etf(fundamentals: Dict[str, Any]) -> bool:
    """True if the securities row names an ETF/ETN rather than an operating company."""
    return bool(_ETF_NAME_RE.search(fundamentals.get("company_name") or ""))

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

    # val is always a float here (from float() above); reject NaN/Inf
    if math.isnan(val) or math.isinf(val):
        return None

    if direction == "above":
        if threshold == 0:
            # Special case: just check positive vs negative
            if val > 0:
                return 1.0
            elif val < 0:
                return 0.0
            else:
                return 0.5
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
            lookthrough_meta = fundamentals.get("_lookthrough")
            is_lookthrough = isinstance(lookthrough_meta, dict)
            # Score metrics only; _lookthrough is metadata for the API contract.
            score_input = (
                {k: v for k, v in fundamentals.items() if k != "_lookthrough"}
                if is_lookthrough
                else fundamentals
            )

            profitability = _score_category(score_input, PROFITABILITY_THRESHOLDS)
            growth = _score_category(score_input, GROWTH_THRESHOLDS)
            health = _score_category(score_input, HEALTH_THRESHOLDS)
            valuation = _score_category(score_input, VALUATION_THRESHOLDS)

            total_available = (
                profitability["metrics_available"]
                + growth["metrics_available"]
                + health["metrics_available"]
                + valuation["metrics_available"]
            )

            # Look-through with zero scored metrics still uses the insufficient path
            # so callers get method/lookthrough meta (not a bare empty error).
            if total_available == 0 and not is_lookthrough:
                return self._empty_result("No fundamental metrics available")

            # Weight categories equally (adjust if you want valuation to matter more)
            category_scores = []
            for cat in [profitability, growth, health, valuation]:
                if cat["metrics_available"] > 0:
                    category_scores.append(cat["score"])

            # Look-through payloads have no company_name; skip the ETF name gate.
            is_etf = True if is_lookthrough else _looks_like_etf(fundamentals)
            insufficient = (
                total_available < MIN_METRICS_FOR_RATING
                or len(category_scores) < MIN_CATEGORIES_FOR_RATING
            )
            if not is_lookthrough and is_etf:
                insufficient = True

            if insufficient:
                # Keep the raw metric values for display, but don't rate.
                # Neutral 0.5 so the signal engine's blend is unaffected.
                if is_lookthrough:
                    pct = float(lookthrough_meta.get("weight_with_fundamentals") or 0.0) * 100.0
                    reason = f"Holdings data covers only {pct:.0f}% of fund weight"
                elif is_etf:
                    reason = "ETF: company fundamentals do not apply"
                else:
                    reason = (
                        f"Only {total_available} metric(s) in {len(category_scores)} "
                        f"categor{'y' if len(category_scores) == 1 else 'ies'} available"
                    )
                result: Dict[str, Any] = {
                    "profitability": profitability,
                    "growth": growth,
                    "health": health,
                    "valuation": valuation,
                    "composite_score": 0.5,
                    "quality": "UNKNOWN",
                    "metrics_available": total_available,
                    "insufficient_data": True,
                    "is_etf": is_etf,
                    "reason": reason,
                }
                return self._attach_lookthrough(result, lookthrough_meta, score_input)

            composite = sum(category_scores) / len(category_scores)

            if composite >= 0.7:
                quality = "STRONG"
            elif composite >= 0.5:
                quality = "GOOD"
            elif composite >= 0.35:
                quality = "FAIR"
            else:
                quality = "WEAK"

            result = {
                "profitability": profitability,
                "growth": growth,
                "health": health,
                "valuation": valuation,
                "composite_score": round(composite, 3),
                "quality": quality,
                "metrics_available": total_available,
            }
            return self._attach_lookthrough(result, lookthrough_meta, score_input)

        except Exception as e:
            logger.error(f"Error evaluating fundamental signal: {e}", exc_info=True)
            return self._empty_result(str(e))

    @staticmethod
    def _attach_lookthrough(
        result: Dict[str, Any],
        lookthrough_meta: Optional[Dict[str, Any]],
        score_input: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Attach look-through contract fields when present; no-op otherwise."""
        if not isinstance(lookthrough_meta, dict):
            return result
        result["method"] = "lookthrough"
        result["is_etf"] = True
        result["lookthrough"] = {
            "etf_ticker": str(lookthrough_meta.get("etf_ticker") or ""),
            "as_of": str(lookthrough_meta.get("as_of") or ""),
            "holdings_total": int(lookthrough_meta.get("holdings_total") or 0),
            "holdings_with_fundamentals": int(
                lookthrough_meta.get("holdings_with_fundamentals") or 0
            ),
            "weight_with_fundamentals": float(
                lookthrough_meta.get("weight_with_fundamentals") or 0.0
            ),
        }
        fcf_w = score_input.get("fcf_positive_weight")
        if fcf_w is not None:
            result.setdefault("health", {})["fcf_positive_weight"] = fcf_w
        return result

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
