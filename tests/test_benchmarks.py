"""Tests for per-ticker benchmark resolution (measurement rig M2a)."""

from web_dashboard.benchmarks import (
    BENCHMARK_CANADA,
    BENCHMARK_US_BROAD,
    BENCHMARK_US_SMALL,
    is_canadian_listing,
    resolve_benchmark,
)


def test_canadian_listing_detected_from_ticker_suffix() -> None:
    assert is_canadian_listing("GMIN.TO")
    assert is_canadian_listing("HURA.TO")
    assert is_canadian_listing("SOME.V")
    assert not is_canadian_listing("MSFT")


def test_canadian_listing_detected_from_resolved_price_symbol() -> None:
    """TECK.B looks US-shaped but resolves to TECK-B.TO.

    The stored ticker carries no exchange suffix, so suffix-matching on `ticker`
    alone would score a TSX miner against the S&P 500.
    """
    assert is_canadian_listing("TECK.B", price_symbol="TECK-B.TO")
    assert not is_canadian_listing("BRK.B", price_symbol="BRK-B")


def test_canadian_listing_falls_back_to_currency() -> None:
    assert is_canadian_listing("XYZ", currency="CAD")
    assert not is_canadian_listing("XYZ", currency="USD")


def test_us_large_cap_uses_broad_index() -> None:
    symbol, fallback = resolve_benchmark("MSFT", market_cap=3_000_000_000_000)
    assert symbol == BENCHMARK_US_BROAD
    assert fallback is False


def test_us_small_cap_uses_small_index() -> None:
    symbol, fallback = resolve_benchmark("RAIL", market_cap=150_000_000)
    assert symbol == BENCHMARK_US_SMALL
    assert fallback is False


def test_canadian_beats_cap_band() -> None:
    """Geography is resolved before size: a small TSX name still scores vs TSX."""
    symbol, fallback = resolve_benchmark("GLO.TO", market_cap=50_000_000)
    assert symbol == BENCHMARK_CANADA
    assert fallback is False


def test_unknown_market_cap_defaults_but_flags_fallback() -> None:
    """51 stance tickers have no securities row; those must be visible, not silent."""
    symbol, fallback = resolve_benchmark("FTXL")
    assert symbol == BENCHMARK_US_BROAD
    assert fallback is True

    # NaN / zero / junk caps are "unknown", not "tiny" -- otherwise a bad data point
    # would silently move a megacap onto the small-cap index.
    for bad in (float("nan"), 0, -1, "not a number", None):
        symbol, fallback = resolve_benchmark("AAPL", market_cap=bad)
        assert symbol == BENCHMARK_US_BROAD
        assert fallback is True


def test_override_wins_over_every_rule() -> None:
    symbol, fallback = resolve_benchmark(
        "GMIN.TO", market_cap=100, override="qqq"
    )
    assert symbol == "QQQ"
    assert fallback is False
