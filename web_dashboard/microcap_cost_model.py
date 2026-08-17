"""Micro-cap round-trip cost model for Learn / stance outcome scoring.

A claim that is "right" by 80 bps on a name that costs 300 bps to trade is a
refutation once costs are applied. Buckets are illustrative ADV proxies using
market_cap when true dollar-ADV is unavailable (nightly scorer already has
securities.market_cap).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from stance_history import BEARISH_STANCES, BULLISH_STANCES

# Round-trip haircut in basis points by liquidity bucket.
BPS_HIGH_LIQUIDITY = 50  # roughly >$5M ADV
BPS_MID_LIQUIDITY = 150  # roughly $1–5M ADV
BPS_LOW_LIQUIDITY = 300  # roughly <$1M ADV

# Market-cap proxies when ADV is unknown (USD).
_MCAP_HIGH = Decimal("2000000000")  # $2B+
_MCAP_MID = Decimal("200000000")  # $200M+

# Below this magnitude an after-cost result is noise, not evidence either way.
# Single definition: track_record_service imports it rather than restating 0.25,
# so the scorer's "refuted" and the aggregate's "miss" can never drift apart.
INCONCLUSIVE_BAND_PP = Decimal("0.25")


def round_trip_cost_bps(
    *,
    avg_dollar_volume: float | Decimal | None = None,
    market_cap: float | Decimal | None = None,
) -> int | None:
    """Return assumed round-trip cost in bps, or None when liquidity is unknown.

    None is not the same as "expensive". Defaulting an unknown-liquidity name to
    the 300 bps bucket manufactures a 3.0 pp haircut out of a missing
    ``securities.market_cap`` row, which is common enough that the scorer already
    tracks it separately -- and because outcomes are inserted ON CONFLICT DO
    NOTHING, the resulting 'refuted' verdict would be frozen permanently the first
    time a row is scored. Callers must treat None as "cannot judge after cost"
    (belief 'inconclusive', cost_bps NULL) so the row can be re-scored once the
    reference data lands.
    """
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

    return None


def excess_after_cost(
    excess_return_pct: Decimal | float | None,
    cost_bps: int | None,
    *,
    stance: str | None = None,
) -> Decimal | None:
    """Directional excess after round-trip cost (percentage points).

    Positive always means the call was still right after the haircut.
    ``excess_return`` is raw ticker−benchmark in percentage points; 100 bps = 1.0 pp.

    Returns None for a non-directional stance or an unknown ``cost_bps`` -- in both
    cases there is no after-cost number to state, and inventing one is what turns a
    data gap into a false refutation.
    """
    if excess_return_pct is None or cost_bps is None:
        return None
    try:
        ex = Decimal(str(excess_return_pct))
    except Exception:
        return None
    if not ex.is_finite():
        return None

    directional = signed_excess(ex, stance)
    if directional is None:
        return None

    haircut = Decimal(cost_bps) / Decimal("100")
    return directional - haircut


def signed_excess(
    excess_return_pct: Decimal | float | None,
    stance: str | None,
) -> Decimal | None:
    """Raw excess signed so positive always means the call was right (pre-cost).

    Shared with the null models in track_record_service, which must re-sign the
    same outcome under a *reassigned* label -- so the sign rule has to live in one
    place or a baseline stops being comparable to the actual rate it is
    differenced against.
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
    if stance_u in BEARISH_STANCES:
        return -ex
    if stance_u in BULLISH_STANCES:
        return ex
    return None


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
    if abs(ex) < INCONCLUSIVE_BAND_PP:
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
