"""Unit tests for Canadian issuer universe parsing and matching (no network)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "web_dashboard" / "scripts"
for p in (str(_SCRIPTS), str(_ROOT / "web_dashboard"), str(_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from canadian_issuer_universe import (  # noqa: E402
    IssuerRecord,
    alias_candidates,
    build_universe_payload,
    is_equity_issuer,
    parse_cse_daily_summary,
    parse_tsx_directory_payload,
    records_from_payload,
    strip_legal_suffixes,
    targets_from_records,
    yfinance_symbol,
)
from yt_promotion_event_study import matching_tickers, classify_match  # noqa: E402


class TestNameAliases:
    def test_strip_corp_inc(self) -> None:
        assert strip_legal_suffixes("First Phosphate Corp.") == "First Phosphate"
        assert strip_legal_suffixes("Cameco Corporation") == "Cameco"
        assert strip_legal_suffixes("Midnight Sun Mining Corp.") == "Midnight Sun Mining"

    def test_alias_peels_sector_wrapper(self) -> None:
        aliases = alias_candidates("Midnight Sun Mining Corp.")
        assert "Midnight Sun Mining" in aliases
        assert "Midnight Sun" in aliases

    def test_does_not_peel_to_generic_discovery(self) -> None:
        aliases = alias_candidates("Discovery Mining Ltd.")
        assert "Discovery Mining" in aliases
        assert "Discovery" not in aliases

    def test_stopword_exact_alias_rejected(self) -> None:
        # A company whose only alias collapses to "Gold" must not match every gold title.
        assert alias_candidates("Gold Inc.") == []


class TestEquityFilter:
    def test_drops_etf_and_warrants(self) -> None:
        assert is_equity_issuer("Harvest Cameco Enhanced High Income Shares ETF", "CCOE") is False
        assert is_equity_issuer("Some Miner WT", "AAA.WT") is False
        assert is_equity_issuer("First Phosphate Corp.", "PHOS") is True


class TestYfinanceSymbol:
    def test_suffixes(self) -> None:
        assert yfinance_symbol("CCO", "TSX") == "CCO.TO"
        assert yfinance_symbol("MMA", "TSXV") == "MMA.V"
        assert yfinance_symbol("PHOS", "CSE") == "PHOS.CN"
        assert yfinance_symbol("TECK.B", "TSX") == "TECK-B.TO"


class TestTsxParse:
    def test_parses_company_rows_skips_etf(self) -> None:
        payload = {
            "results": [
                {"symbol": "CCO", "name": "Cameco Corporation"},
                {
                    "symbol": "CCOE",
                    "name": "Harvest Cameco Enhanced High Income Shares ETF",
                },
                {"symbol": "OR", "name": "Osisko Gold Royalties Ltd"},
            ]
        }
        rows = parse_tsx_directory_payload(payload, exchange="TSX")
        symbols = {r.symbol for r in rows}
        assert "CCO.TO" in symbols
        assert "CCOE.TO" not in symbols
        assert "OR.TO" in symbols
        cameco = next(r for r in rows if r.symbol == "CCO.TO")
        assert "Cameco" in cameco.aliases


class TestCseParse:
    def test_parses_summary_text(self) -> None:
        text = """CNSX Trading Daily Market Summary July 30 2026 Closing Numbers

Stock                                                           \tSymbol  \tVol(00s)\tHigh
Avventura Resources Ltd.                                        \tAA      \t170\t0.0850
First Phosphate Corp.                                           \tPHOS    \t500\t0.50
Nevada Organic Phosphate Inc.                                   \tNOP     \t10\t0.10
Stock                                                           \tSymbol  \tVol
"""
        from datetime import date

        rows = parse_cse_daily_summary(text, as_of=date(2026, 7, 30))
        by_sym = {r.raw_symbol: r for r in rows}
        assert "PHOS" in by_sym
        assert by_sym["PHOS"].symbol == "PHOS.CN"
        assert "First Phosphate" in by_sym["PHOS"].aliases
        assert "AA" in by_sym  # short symbol kept; match via name/cashtag only


class TestMatching:
    def test_first_phosphate_and_midnight_sun(self) -> None:
        records = [
            IssuerRecord(
                symbol="PHOS.CN",
                exchange="CSE",
                name="First Phosphate Corp.",
                aliases=tuple(alias_candidates("First Phosphate Corp.")),
                raw_symbol="PHOS",
            ),
            IssuerRecord(
                symbol="MMA.V",
                exchange="TSXV",
                name="Midnight Sun Mining Corp.",
                aliases=tuple(alias_candidates("Midnight Sun Mining Corp.")),
                raw_symbol="MMA",
            ),
            IssuerRecord(
                symbol="CCO.TO",
                exchange="TSX",
                name="Cameco Corporation",
                aliases=tuple(alias_candidates("Cameco Corporation")),
                raw_symbol="CCO",
            ),
        ]
        targets = targets_from_records(records)
        title = "This LFP Supply Chain Story Just Got G7 Backing | John Passalacqua — First Phosphate"
        hits = matching_tickers(title, targets)
        assert classify_match(hits) == "single"
        assert hits == ["PHOS.CN"]

        title2 = "Midnight Sun CEO interview"
        assert matching_tickers(title2, targets) == ["MMA.V"]

        # Short symbol "OR" must not match the English word "or" (cashtag-only for symbols).
        or_rec = IssuerRecord(
            symbol="OR.TO",
            exchange="TSX",
            name="Osisko Gold Royalties Ltd",
            aliases=tuple(alias_candidates("Osisko Gold Royalties Ltd")),
            raw_symbol="OR",
        )
        or_targets = targets_from_records([or_rec])
        assert matching_tickers("Bill Holter: inflation or deflation", or_targets) == []
        assert matching_tickers("Osisko Gold Royalties update", or_targets) == ["OR.TO"]
        assert matching_tickers("$OR drill results", or_targets) == ["OR.TO"]
        # Bare OR without cashtag / name does not match.
        assert matching_tickers("OR drill results", or_targets) == []

        # English-word tickers must not fire on ordinary prose.
        mine = IssuerRecord(
            symbol="MINE.V",
            exchange="TSXV",
            name="Inomin Mines Inc.",
            aliases=tuple(alias_candidates("Inomin Mines Inc.")),
            raw_symbol="MINE",
        )
        mine_t = targets_from_records([mine])
        assert matching_tickers("the mine produced copper", mine_t) == []
        assert matching_tickers("Inomin Mines update", mine_t) == ["MINE.V"]

    def test_payload_roundtrip(self) -> None:
        payload = build_universe_payload(
            retrieved_at=__import__("datetime").date(2026, 7, 30),
            tsx_records=[
                IssuerRecord("CCO.TO", "TSX", "Cameco Corporation", ("Cameco",), "CCO")
            ],
            cse_records=[
                IssuerRecord(
                    "PHOS.CN", "CSE", "First Phosphate Corp.", ("First Phosphate",), "PHOS"
                )
            ],
            source_meta={"CSE": {"as_of": "2026-07-30", "count": 1}},
        )
        assert payload["retrieved_at"] == "2026-07-30"
        assert payload["issuer_count"] == 2
        records = records_from_payload(payload)
        assert {r.symbol for r in records} == {"CCO.TO", "PHOS.CN"}
        # JSON serializable
        json.dumps(payload)


class TestCommittedCacheShape:
    def test_repo_cache_if_present(self) -> None:
        cache = _ROOT / "web_dashboard" / "data" / "canadian_issuers" / "issuers.json"
        if not cache.is_file():
            pytest.skip("issuer cache not committed yet")
        payload = json.loads(cache.read_text(encoding="utf-8"))
        assert payload.get("retrieved_at")
        assert int(payload.get("issuer_count") or 0) > 1000
        assert any(r.get("symbol") == "PHOS.CN" for r in payload["issuers"])
        assert any(r.get("exchange") == "TSX" for r in payload["issuers"])
        assert any(r.get("exchange") == "TSXV" for r in payload["issuers"])
        assert any(r.get("exchange") == "CSE" for r in payload["issuers"])
