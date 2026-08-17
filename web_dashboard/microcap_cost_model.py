"""Micro-cap round-trip cost model for Learn / stance outcome scoring.

A claim that is "right" by 80 bps on a name that costs 300 bps to trade is a
refutation once costs are applied. Buckets are illustrative ADV proxies using
market_cap when true dollar-ADV is unavailable (nightly scorer already has
securities.market_cap).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

# Round-trip haircut in basis points by liquidity bucket.
BPS_HIGH_LIQUIDITY = 50  # roughly >$5M ADV
BPS_MID_LIQUIDITY = 150  # roughly $1–5M ADV
BPS_LOW_LIQUIDITY = 300  # roughly <$1M ADV

# Market-cap proxies when ADV is unknown (USD).
_MCAP_HIGH = Decimal("2000000000")  # $2B+
_MCAP_MID = Decimal("200000000")  # $200M+


def round_trip_cost_bps(
    *,
    avg_dollar_volume: float | Decimal | None = None,
    market_cap: float | Decimal | None = None,
) -> int:
    """Return assumed round-trip cost in basis points."""
    adv = _to_decimal(avg_dollar_volume)
    if adv is not None and adv > 0:
        if adv >= Decimal("5000000"):
            return BPS_HIGH_LIQUIDITY
        if adv >= Decimal("1000000"):
            return BPS_MID_LIQUIDITY
        return BPS_LOW_LIQUIDITY

    mcap = _to_decimal(market_cap)
    if mcap is not None and mcap > 0:
        if mcap >= _MCAP_HIGH:
            return BPS_HIGH_LIQUIDITY
        if mcap >= _MCAP_MID:
            return BPS_MID_LIQUIDITY
        return BPS_LOW_LIQUIDITY

    return BPS_LOW_LIQUIDITY


def excess_after_cost(
    excess_return_pct: Decimal | float | None,
    cost_bps: int,
    *,
    stance: str | None = None,
) -> Decimal | None:
    """Directional excess after round-trip cost (percentage points).

    Positive always means the call was still right after the haircut.
    ``excess_return`` is raw ticker−benchmark in percentage points; 100 bps = 1.0 pp.
    """
    if excess_return_pct is None:
        return None
    try:
        ex = Decimal(str(excess_return_pct))
    except Exception:
        return None
    if not ex.is_finite():
        return None

    stance_u = (stance or "").strip().upper()
    if stance_u in {
        "SELL",
        "BEARISH",
        "VERY_BEARISH",
        "STRONG_BEARISH",
        "AVOID",
    }:
        directional = -ex
    elif stance_u in {
        "BUY",
        "BULLISH",
        "VERY_BULLISH",
        "STRONG_BULLISH",
    }:
        directional = ex
    else:
        return None

    haircut = Decimal(cost_bps) / Decimal("100")
    return directional - haircut


def belief_from_excess_after_cost(
    *,
    excess_after_cost_pct: Decimal | float | None,
    stance: str | None = None,
) -> str:
    """Map after-cost directional excess to supported / refuted / inconclusive.

    ``excess_after_cost_pct`` must already be directional (positive = call was right).
    """
    del stance  # reserved for future asymmetric bands
    if excess_after_cost_pct is None:
        return "inconclusive"
    try:
        ex = Decimal(str(excess_after_cost_pct))
    except Exception:
        return "inconclusive"
    if not ex.is_finite():
        return "inconclusive"
    if abs(ex) < Decimal("0.25"):
        return "inconclusive"
    return "supported" if ex > 0 else "refuted"


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        d = Decimal(str(value))
    except Exception:
        return None
    if not d.is_finite():
        return None
    return d
