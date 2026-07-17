"""Tests for congress trade field normalization and cross-source dedupe keys."""

from __future__ import annotations

from web_dashboard.utils.congress_trade_normalize import (
    CONGRESS_TRADE_UPSERT_ON_CONFLICT,
    build_congress_trade_record,
    congress_trade_dedupe_key,
    normalize_amount,
    normalize_owner,
    normalize_ticker,
    normalize_trade_type,
)
from web_dashboard.utils.politician_mapping import resolve_politician_name


class TestNormalizeAmount:
    def test_collapses_hyphen_spacing(self) -> None:
        assert normalize_amount("$1,001-$15,000") == "$1,001 - $15,000"
        assert normalize_amount("$1,001 - $15,000") == "$1,001 - $15,000"
        assert normalize_amount("$1,001  -  $15,000") == "$1,001 - $15,000"

    def test_empty_and_none(self) -> None:
        assert normalize_amount(None) == ""
        assert normalize_amount("") == ""
        assert normalize_amount("  ") == ""


class TestNormalizeOwner:
    def test_known_aliases(self) -> None:
        assert normalize_owner("not disclosed") == "Not-Disclosed"
        assert normalize_owner("Not-Disclosed") == "Not-Disclosed"
        assert normalize_owner("undisclosed") == "Not-Disclosed"
        assert normalize_owner("spouse") == "Spouse"
        assert normalize_owner("dependent") == "Child"

    def test_default_unknown(self) -> None:
        assert normalize_owner(None) == "Unknown"
        assert normalize_owner("") == "Unknown"


class TestNormalizeTradeType:
    def test_preserves_exchange_and_received(self) -> None:
        assert normalize_trade_type("exchange") == "Exchange"
        assert normalize_trade_type("Received") == "Received"
        assert normalize_trade_type("buy") == "Purchase"
        assert normalize_trade_type("S (partial)") == "Sale"


class TestDedupeKey:
    def test_fmp_and_scraper_amount_variants_collide(self) -> None:
        fmp_key = congress_trade_dedupe_key(
            425, "eqt", "2026-06-01", "$1,001-$15,000", "Purchase", "Unknown"
        )
        scraper_key = congress_trade_dedupe_key(
            425, "EQT", "2026-06-01", "$1,001 - $15,000", "purchase", None
        )
        assert fmp_key == scraper_key

    def test_owner_variants_collide(self) -> None:
        a = congress_trade_dedupe_key(1, "AAPL", "2026-01-01", "$1,001 - $15,000", "Sale", "not disclosed")
        b = congress_trade_dedupe_key(1, "AAPL", "2026-01-01", "$1,001-$15,000", "Sale", "Not-Disclosed")
        assert a == b

    def test_upsert_conflict_target_matches_db_constraint(self) -> None:
        assert CONGRESS_TRADE_UPSERT_ON_CONFLICT == (
            "politician_id,ticker,transaction_date,amount,type,owner"
        )


class TestBuildRecord:
    def test_omits_politician_name_column(self) -> None:
        record = build_congress_trade_record(
            politician_id=425,
            ticker="eqt",
            transaction_date="2026-06-01",
            amount="$1,001-$15,000",
            trade_type="Purchase",
            owner=None,
            disclosure_date="2026-06-18",
            chamber="House",
        )
        assert "politician" not in record
        assert record["politician_id"] == 425
        assert record["ticker"] == "EQT"
        assert record["amount"] == "$1,001 - $15,000"
        assert record["owner"] == "Unknown"
        assert record["type"] == "Purchase"


class TestKeanAlias:
    def test_kean_variants_resolve_to_bioguide_form(self) -> None:
        for name in (
            "Thomas Kean Jr",
            "Thomas Kean",
            "Thomas H. Kean Jr.",
            "thomas h. kean, jr.",
        ):
            canonical, bioguide = resolve_politician_name(name)
            assert canonical == "Thomas H. Kean, Jr."
            assert bioguide == "K000398"

    def test_normalize_ticker(self) -> None:
        assert normalize_ticker(" eqt ") == "EQT"
