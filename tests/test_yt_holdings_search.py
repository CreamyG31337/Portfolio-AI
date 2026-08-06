"""Unit tests for Phase K8 pull retrieval (no network, no DB).

The junk titles here are **real** — every one was returned by the §26.2 probe against
production holdings. They are the reason this module exists, so they are the fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

# sys.path is set up by tests/conftest.py.
from yt_holdings_search import (  # noqa: E402
    Candidate,
    HoldingTarget,
    evaluate_listing,
    is_fund,
    normalize_company_name,
    rank,
    score_title,
    search_holding,
    targets_from_holdings,
    title_junk_reason,
)


@dataclass
class FakeListing:
    """Shaped like ``yt_captions.VideoListing`` (only the fields K8 reads)."""

    video_id: str
    title: str
    url: str = ""
    view_count: int | None = None
    duration_s: int | None = None
    channel_name: str | None = None


CAMECO = HoldingTarget("CCO.TO", "Cameco Corporation", "Energy")
GMIN = HoldingTarget("GMIN.TO", "G Mining Ventures Corp.", "Basic Materials")
VERTIV = HoldingTarget("VRT", "VERTIV HOLDINGS CLASS A", "Industrials")
TECK = HoldingTarget("TECK.B", "Teck Resources Limited", "Basic Materials")


class TestNameNormalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Cameco Corporation", "Cameco"),
            ("G Mining Ventures Corp.", "G Mining Ventures"),
            ("VERTIV HOLDINGS CLASS A", "Vertiv"),
            ("Teck Resources Limited", "Teck Resources"),
            ("Oklo Inc", "Oklo"),
            ("Westbridge Renewable Energy Corp.", "Westbridge Renewable Energy"),
        ],
    )
    def test_strips_corporate_suffixes(self, raw: str, expected: str) -> None:
        assert normalize_company_name(raw) == expected

    def test_empty_input_is_empty(self) -> None:
        assert normalize_company_name("") == ""
        assert normalize_company_name("   ") == ""

    def test_bare_symbol_drops_exchange_suffix(self) -> None:
        assert CAMECO.bare_symbol == "CCO"
        assert GMIN.bare_symbol == "GMIN"
        assert VERTIV.bare_symbol == "VRT"

    def test_aliases_include_two_word_prefix_for_long_names(self) -> None:
        assert "G Mining Ventures" in GMIN.aliases
        assert "G Mining" in GMIN.aliases
        # Short names do not generate a redundant prefix.
        assert CAMECO.aliases == ("Cameco",)


class TestFundsAreSkipped:
    """Searching a basket returns index explainers, never issuer news."""

    @pytest.mark.parametrize(
        "ticker,name",
        [
            ("XEQT.TO", "iShares Core Equity ETF Portfolio"),
            ("URNM", "SPROTT URANIUM MINERS ETF"),
            ("VOO", "Vanguard S&P 500 ETF"),
            ("SMH", "VanEck Semiconductor ETF"),
            # The three the marker list missed: no "ETF" anywhere in the name.
            ("FXD", "First Trust Consumer Staples AlphaDEX Fund"),
            ("FXG", "First Trust Consumer Discretionary AlphaDEX Fund"),
            ("FXL", "First Trust Technology AlphaDEX Fund"),
        ],
    )
    def test_detects_funds(self, ticker: str, name: str) -> None:
        assert is_fund(ticker, name) is True

    @pytest.mark.parametrize(
        "ticker,name",
        [
            ("CCO.TO", "Cameco Corporation"),
            ("OKLO", "Oklo Inc"),
            ("TECK.B", "Teck Resources Limited"),
            # A REIT ends in "Trust" and is a real issuer: the ending test must
            # not swallow it, which is why "trust" is not a fund ending.
            ("REI.UN", "RioCan Real Estate Investment Trust"),
            # "Fund" mid-name is an operating company, not a basket.
            ("BX", "Blackstone Fund Services Inc"),
        ],
    )
    def test_operating_companies_are_not_funds(self, ticker: str, name: str) -> None:
        assert is_fund(ticker, name) is False

    def test_targets_from_holdings_drops_funds(self) -> None:
        rows = [
            {"ticker": "CCO.TO", "company_name": "Cameco Corporation", "sector": "Energy"},
            {"ticker": "XEQT.TO", "company_name": "iShares Core Equity ETF Portfolio"},
            {"ticker": "", "company_name": "No Ticker"},
            {"ticker": "OKLO", "company_name": "Oklo Inc", "sector": "Utilities"},
        ]
        targets = targets_from_holdings(rows)
        assert [t.ticker for t in targets] == ["CCO.TO", "OKLO"]
        assert targets_from_holdings(rows, include_funds=True)[1].ticker == "XEQT.TO"


class TestRealJunkTitlesFromTheProbe:
    """§26.3: ranking company-name hits by views returns these. All must be rejected."""

    @pytest.mark.parametrize(
        "title,reason",
        [
            ("How It's Made - Uranium Part 1", "manufacturing_show"),
            ("Earth's Two-Billion-Year-Old Nuclear Reactor", "documentary"),
            ("How a gas turbine works | GE Vernova", "explainer"),
            ("Shopify Tutorial For Beginners 2026 - Set up Your Store", "tutorial"),
            ("I Tried AI Dropshipping For 7 Days, Here's How You Can Copy Me", "get_rich"),
            ("VERTICAL | LEV vs NRG - VCT Americas Etappe 2", "esports"),
        ],
    )
    def test_junk_is_rejected(self, title: str, reason: str) -> None:
        assert title_junk_reason(title) == reason

    def test_bare_brand_mention_is_rejected_for_lacking_issuer_signal(self) -> None:
        """'Reading electrical one line drawings | Eaton PSEC' names Eaton and is
        vendor training. No keyword catches it — the rule is that a name alone is
        not confirmation."""
        eaton = HoldingTarget("ETN", "Eaton Corporation plc", "Industrials")
        listing = FakeListing("e", "Reading electrical one line drawings | Eaton PSEC")
        cand = evaluate_listing(listing, eaton)
        assert cand.reject_reason == "no_issuer_signal"
        assert cand.confirmed is False

    @pytest.mark.parametrize(
        "title",
        [
            "Teck Resources and Anglo American announce $70 billion tie-up",
            "Centrus Energy CEO talks about its role as nuclear energy grows",
            "Enbridge CEO on Tariffs Impact on Steel & Pipeline Costs",
            "G Mining (TSX:GMIN) - G2 Acquisition Builds Tier-1 Gold Hub",
        ],
    )
    def test_real_hits_survive(self, title: str) -> None:
        assert title_junk_reason(title) is None


class TestScoring:
    def test_name_is_mandatory(self) -> None:
        """Issuer vocabulary without the company name proves nothing."""
        score, matched = score_title("CEO discusses Q4 earnings and guidance", CAMECO)
        assert score == 0
        assert matched == ()

    def test_exchange_tag_and_symbol_rank_highest(self) -> None:
        tagged, _ = score_title("G Mining (TSX:GMIN) - G2 Acquisition Builds Gold Hub", GMIN)
        plain, _ = score_title("G Mining Ventures gives a corporate update", GMIN)
        assert tagged > plain

    def test_issuer_vocabulary_adds_signal(self) -> None:
        with_ceo, matched = score_title("Cameco CEO on uranium contracting", CAMECO)
        bare, _ = score_title("Cameco mentioned in passing", CAMECO)
        assert with_ceo > bare
        assert "executive" in matched

    def test_mining_operations_vocabulary_scores(self) -> None:
        _, matched = score_title("G Mining Ventures drill results and resource estimate", GMIN)
        assert "mining_ops" in matched


class TestViewsNeverLeadRanking:
    """The §26.3 finding, locked in: a 3M-view documentary must not outrank a 4k CEO hit."""

    def test_low_view_confirmed_hit_beats_high_view_junk(self) -> None:
        junk = FakeListing("a", "How It's Made - Uranium Part 1", view_count=5_251_091)
        real = FakeListing("b", "Cameco CEO on Q4 results and guidance", view_count=4_604)
        ranked = rank([evaluate_listing(junk, CAMECO), evaluate_listing(real, CAMECO)])
        assert [c.video_id for c in ranked] == ["b"]

    def test_views_only_break_ties_between_equal_scores(self) -> None:
        low = Candidate("low", "t", "", "CCO.TO", view_count=100, score=9)
        high = Candidate("high", "t", "", "CCO.TO", view_count=9_000, score=9)
        assert [c.video_id for c in rank([low, high])] == ["high", "low"]

    def test_a_high_score_still_wins_against_more_views(self) -> None:
        strong = Candidate("strong", "t", "", "CCO.TO", view_count=10, score=12)
        weak = Candidate("weak", "t", "", "CCO.TO", view_count=1_000_000, score=4)
        assert [c.video_id for c in rank([strong, weak])] == ["strong", "weak"]


class TestEvaluateListing:
    def test_unrelated_title_rejected_as_name_absent(self) -> None:
        cand = evaluate_listing(FakeListing("x", "Nvidia earnings preview"), CAMECO)
        assert cand.reject_reason == "name_absent"
        assert cand.confirmed is False

    def test_confirmed_candidate_carries_view_count_and_matches(self) -> None:
        listing = FakeListing(
            "y", "Cameco CEO talks uranium contracts", view_count=4_604, duration_s=612
        )
        cand = evaluate_listing(listing, CAMECO)
        assert cand.confirmed is True
        assert cand.view_count == 4_604
        assert cand.duration_s == 612
        assert any(m.startswith("name:") for m in cand.matched)

    def test_brand_collision_rejected_before_scoring(self) -> None:
        """Vertiv/VCT: the esports match names the brand but is not about the issuer."""
        listing = FakeListing("z", "VERTICAL | LEV vs NRG - VCT Americas", view_count=111_027)
        assert evaluate_listing(listing, VERTIV).reject_reason == "esports"


class TestSearchHolding:
    def test_filters_and_ranks_a_search_page(self) -> None:
        page = [
            FakeListing("1", "How It's Made - Uranium Part 1", view_count=5_251_091),
            FakeListing("2", "Cameco (TSX:CCO) Q4 earnings beat", view_count=3_100),
            FakeListing("3", "Best gaming laptops 2026 review headset", view_count=800_000),
            FakeListing("4", "Cameco CEO interview on contracting", view_count=12_000),
        ]
        got = search_holding(CAMECO, search_fn=lambda *_a, **_k: page)
        assert [c.video_id for c in got] == ["2", "4"]
        assert all(c.confirmed for c in got)

    def test_search_failure_returns_empty_not_raises(self) -> None:
        def boom(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError("429 rate limited")

        assert search_holding(TECK, search_fn=boom) == []

    def test_query_uses_company_name_not_symbol(self) -> None:
        seen: dict[str, Any] = {}

        def capture(q: str, **kwargs: Any) -> list[Any]:
            seen["q"] = q
            return []

        search_holding(CAMECO, search_fn=capture)
        assert "Cameco" in seen["q"]
        assert "CCO.TO" not in seen["q"]


class TestNameCollisionDefences:
    """Both cases were false results from the first full sweep against the real book."""

    def test_adf_no_longer_matches_adf_foods(self) -> None:
        """DRX.TO normalizes to 'ADF', which matched the unrelated 'ADF Foods'.
        Three characters cannot identify an issuer without the symbol."""
        drx = HoldingTarget("DRX.TO", "ADF Group Inc.", "Industrials")
        listing = FakeListing("f", "ADF Foods Reports Strong Q4 Earnings, EBITDA Up")
        cand = evaluate_listing(listing, drx)
        assert cand.reject_reason == "short_name_unconfirmed"
        assert cand.confirmed is False

    def test_adf_group_still_matches_its_own_news(self) -> None:
        drx = HoldingTarget("DRX.TO", "ADF Group Inc.", "Industrials")
        listing = FakeListing("g", "ADF Group (DRX) Q1 2026 Earnings - Full Coverage")
        assert evaluate_listing(listing, drx).confirmed is True

    def test_short_name_requires_symbol_corroboration(self) -> None:
        oklo = HoldingTarget("OKLO", "Oklo Inc", "Utilities")
        doc = FakeListing("h", "Oklo and the story of natural nuclear fission reactors")
        assert evaluate_listing(doc, oklo).reject_reason == "short_name_unconfirmed"
        real = FakeListing("i", "Oklo (OKLO) Q3 earnings and reactor guidance")
        assert evaluate_listing(real, oklo).confirmed is True


class TestSectorHintFallback:
    """A sector hint must not cost us a holding when the plain query would find it."""

    def test_falls_back_to_unhinted_query(self) -> None:
        seen: list[str] = []

        def fake(query: str, **_k: Any) -> list[Any]:
            seen.append(query)
            if "basic materials" in query:
                return []
            return [FakeListing("j", "G Mining Ventures (TSX:GMIN) drill results", view_count=8349)]

        hits = search_holding(GMIN, search_fn=fake)
        assert len(seen) == 2
        assert [c.video_id for c in hits] == ["j"]

    def test_no_second_call_when_first_query_succeeds(self) -> None:
        seen: list[str] = []

        def fake(query: str, **_k: Any) -> list[Any]:
            seen.append(query)
            return [FakeListing("k", "Cameco (TSX:CCO) Q4 earnings beat", view_count=3100)]

        assert len(search_holding(CAMECO, search_fn=fake)) == 1
        assert len(seen) == 1
