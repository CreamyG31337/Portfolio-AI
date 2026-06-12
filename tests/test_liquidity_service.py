"""Tests for liquidity / exit-risk math (ROADMAP §4.3)."""

import pandas as pd

from web_dashboard.liquidity_service import PARTICIPATION_RATE, build_liquidity_panel


def _positions(rows):
    return pd.DataFrame(rows)


def test_days_to_exit_math():
    df = _positions([{"ticker": "AAA", "shares": 5_000, "market_value": 25_000.0}])
    volumes = {"AAA": {"avg_daily_volume": 10_000.0}}

    (row,) = build_liquidity_panel(df, volumes=volumes)

    # 5000 shares at 10% of 10k daily volume -> 5 days.
    assert row["days_to_exit"] == round(5_000 / (PARTICIPATION_RATE * 10_000), 2)
    assert row["pct_of_adv"] == 50.0
    assert row["risk_bucket"] == "elevated"


def test_risk_buckets():
    df = _positions([
        {"ticker": "LIQ", "shares": 500, "market_value": 1.0},     # 0.5 d -> low
        {"ticker": "MID", "shares": 5_000, "market_value": 1.0},   # 5 d -> elevated
        {"ticker": "BAD", "shares": 50_000, "market_value": 1.0},  # 50 d -> high
        {"ticker": "UNK", "shares": 100, "market_value": 1.0},     # no volume data
    ])
    volumes = {t: {"avg_daily_volume": 10_000.0} for t in ("LIQ", "MID", "BAD")}

    rows = {r["ticker"]: r for r in build_liquidity_panel(df, volumes=volumes)}

    assert rows["LIQ"]["risk_bucket"] == "low"
    assert rows["MID"]["risk_bucket"] == "elevated"
    assert rows["BAD"]["risk_bucket"] == "high"
    assert rows["UNK"]["risk_bucket"] == "unknown"
    assert rows["UNK"]["days_to_exit"] is None


def test_worst_risk_sorts_first_unknown_last():
    df = _positions([
        {"ticker": "UNK", "shares": 100, "market_value": 1.0},
        {"ticker": "LIQ", "shares": 500, "market_value": 1.0},
        {"ticker": "BAD", "shares": 50_000, "market_value": 1.0},
    ])
    volumes = {t: {"avg_daily_volume": 10_000.0} for t in ("LIQ", "BAD")}

    rows = build_liquidity_panel(df, volumes=volumes)

    assert [r["ticker"] for r in rows] == ["BAD", "LIQ", "UNK"]


def test_same_ticker_across_funds_is_summed():
    """Exit risk is the book's total footprint in the name, not one fund's slice."""
    df = _positions([
        {"ticker": "AAA", "shares": 3_000, "market_value": 9_000.0, "fund": "TFSA"},
        {"ticker": "AAA", "shares": 2_000, "market_value": 6_000.0, "fund": "RRSP"},
    ])
    volumes = {"AAA": {"avg_daily_volume": 10_000.0}}

    (row,) = build_liquidity_panel(df, volumes=volumes)

    assert row["shares"] == 5_000
    assert row["market_value"] == 15_000.0
    assert row["days_to_exit"] == 5.0


def test_zero_and_negative_share_rows_skipped():
    df = _positions([
        {"ticker": "AAA", "shares": 0, "market_value": 0.0},
        {"ticker": "BBB", "shares": None, "market_value": 0.0},
    ])
    assert build_liquidity_panel(df, volumes={}) == []


def test_empty_and_malformed_frames():
    assert build_liquidity_panel(None, volumes={}) == []
    assert build_liquidity_panel(pd.DataFrame(), volumes={}) == []
    assert build_liquidity_panel(pd.DataFrame([{"foo": 1}]), volumes={}) == []
