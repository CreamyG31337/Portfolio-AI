"""Tests for micro-cap cost model."""

from __future__ import annotations

from decimal import Decimal

from microcap_cost_model import (
    belief_from_excess_after_cost,
    excess_after_cost,
    round_trip_cost_bps,
)


def test_adv_buckets() -> None:
    assert round_trip_cost_bps(avg_dollar_volume=6_000_000) == 50
    assert round_trip_cost_bps(avg_dollar_volume=2_000_000) == 150
    assert round_trip_cost_bps(avg_dollar_volume=500_000) == 300


def test_mcap_fallback() -> None:
    assert round_trip_cost_bps(market_cap=3_000_000_000) == 50
    assert round_trip_cost_bps(market_cap=500_000_000) == 150
    assert round_trip_cost_bps(market_cap=50_000_000) == 300


def test_bullish_right_but_costs_eat_edge_is_refuted() -> None:
    # +0.80% excess, 300 bps = 3.0 pp haircut → directional after cost -2.2
    eac = excess_after_cost(Decimal("0.80"), 300, stance="BUY")
    assert eac is not None and eac < 0
    assert belief_from_excess_after_cost(excess_after_cost_pct=eac) == "refuted"


def test_bearish_correct_after_cost() -> None:
    # Raw excess -5% (stock underperformed); bearish directional = +5; cost 1.5 → +3.5
    eac = excess_after_cost(Decimal("-5.0"), 150, stance="SELL")
    assert eac is not None and eac > 0
    assert belief_from_excess_after_cost(excess_after_cost_pct=eac) == "supported"
