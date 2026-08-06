"""Unit tests for the scheduled K8 holdings sweep (no network, no DB)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import pytest

# sys.path is set up by tests/conftest.py.
from scheduler.jobs_yt_sweep import (  # noqa: E402
    SweepSummary,
    max_fetches,
    plan_fetches,
    sweep_holdings,
)


def _entry(ticker: str, *video_ids: str) -> dict[str, Any]:
    """One holding's search result, best-scored first."""
    return {
        "ticker": ticker,
        "hits": [
            {"video_id": vid, "score": 10 - i, "title": vid}
            for i, vid in enumerate(video_ids)
        ],
    }


class TestPlanFetches:
    def test_round_robin_spreads_budget_across_holdings(self) -> None:
        """Score-ordering globally would give all 3 fetches to AAA."""
        results = [_entry("AAA", "a1", "a2", "a3"), _entry("BBB", "b1", "b2")]
        queue, skipped = plan_fetches(results, budget=3)
        assert [v["video_id"] for _t, v in queue] == ["a1", "b1", "a2"]
        assert skipped == 0

    def test_deeper_passes_only_after_every_holding_had_one(self) -> None:
        results = [_entry("AAA", "a1", "a2"), _entry("BBB", "b1", "b2")]
        queue, _ = plan_fetches(results, budget=99)
        assert [v["video_id"] for _t, v in queue] == ["a1", "b1", "a2", "b2"]

    def test_known_videos_are_dropped_before_spending_a_fetch(self) -> None:
        """ingest_video fetches captions *before* its own exists check."""
        results = [_entry("AAA", "a1", "a2")]
        queue, skipped = plan_fetches(
            results, budget=5, is_known=lambda url: "a1" in url
        )
        assert [v["video_id"] for _t, v in queue] == ["a2"]
        assert skipped == 1

    def test_holding_fully_landed_drops_out_entirely(self) -> None:
        results = [_entry("AAA", "a1"), _entry("BBB", "b1")]
        queue, skipped = plan_fetches(
            results, budget=5, is_known=lambda url: "a1" in url
        )
        assert [t for t, _v in queue] == ["BBB"]
        assert skipped == 1

    def test_zero_budget_plans_nothing(self) -> None:
        queue, _ = plan_fetches([_entry("AAA", "a1")], budget=0)
        assert queue == []

    def test_a_failing_exists_check_keeps_the_candidate(self) -> None:
        """Losing the DB must not silently skip work; ingest re-checks anyway."""

        def boom(_url: str) -> bool:
            raise RuntimeError("db down")

        queue, skipped = plan_fetches([_entry("AAA", "a1")], budget=5, is_known=boom)
        assert [v["video_id"] for _t, v in queue] == ["a1"]
        assert skipped == 0

    def test_hits_without_a_video_id_are_ignored(self) -> None:
        results = [{"ticker": "AAA", "hits": [{"video_id": "", "score": 9}]}]
        queue, _ = plan_fetches(results, budget=5)
        assert queue == []


class TestMaxFetches:
    def test_default_and_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("YOUTUBE_SWEEP_MAX_FETCHES", raising=False)
        assert max_fetches() == 15
        monkeypatch.setenv("YOUTUBE_SWEEP_MAX_FETCHES", "4")
        assert max_fetches() == 4
        monkeypatch.setenv("YOUTUBE_SWEEP_MAX_FETCHES", "nonsense")
        assert max_fetches() == 15


@dataclass
class FakeCandidate:
    video_id: str
    title: str = "t"
    url: str = "u"
    score: int = 8
    view_count: int | None = 100
    matched: tuple[str, ...] = ()


class FakeRepo:
    def __init__(self, known: Sequence[str] = ()) -> None:
        self.known = set(known)

    def article_exists(self, url: str) -> bool:
        return any(k in url for k in self.known)


@dataclass
class FakeOutcome:
    status: str


@pytest.fixture
def patched_holdings(monkeypatch: pytest.MonkeyPatch):
    import scheduler.jobs_yt_sweep as sweep

    rows = [
        {"ticker": "CCO.TO", "company_name": "Cameco Corporation", "sector": "Energy"},
        {"ticker": "OKLO", "company_name": "Oklo Inc", "sector": "Utilities"},
        {"ticker": "VOO", "company_name": "Vanguard S&P 500 ETF", "sector": None},
    ]
    monkeypatch.setattr(sweep, "holdings_rows", lambda *a, **k: rows)
    monkeypatch.setattr(sweep, "_owned_tickers", lambda: ["CCO.TO", "OKLO"])
    return rows


class TestSweepHoldings:
    def test_search_only_run_spends_no_fetches(self, patched_holdings) -> None:
        ingested: list[str] = []
        summary = sweep_holdings(
            research_repo=FakeRepo(),
            search_fn=lambda target, **_k: [FakeCandidate(f"v-{target.ticker}")],
            ingest_fn=lambda vid, **_k: ingested.append(vid),
            ingest=False,
            sleep_fn=lambda _s: None,
        )
        # VOO is a fund and is excluded from pull retrieval.
        assert summary.holdings_searched == 2
        assert summary.with_confirmed_hits == 2
        assert summary.coverage == 1.0
        assert ingested == []

    def test_landed_rows_are_counted(self, patched_holdings) -> None:
        summary = sweep_holdings(
            research_repo=FakeRepo(),
            search_fn=lambda target, **_k: [FakeCandidate(f"v-{target.ticker}")],
            ingest_fn=lambda _vid, **_k: FakeOutcome("saved"),
            budget=5,
            sleep_fn=lambda _s: None,
        )
        assert summary.planned == 2
        assert summary.landed == 2
        assert summary.statuses == {"saved": 2}

    def test_already_ingested_videos_cost_nothing(self, patched_holdings) -> None:
        calls: list[str] = []
        summary = sweep_holdings(
            research_repo=FakeRepo(known=["v-OKLO"]),
            search_fn=lambda target, **_k: [FakeCandidate(f"v-{target.ticker}")],
            ingest_fn=lambda vid, **_k: (calls.append(vid), FakeOutcome("saved"))[1],
            budget=5,
            sleep_fn=lambda _s: None,
        )
        assert calls == ["v-CCO.TO"]
        assert summary.skipped_known == 1
        assert summary.landed == 1

    def test_a_failing_search_does_not_abort_the_sweep(self, patched_holdings) -> None:
        def flaky(target, **_k):
            if target.ticker == "CCO.TO":
                raise RuntimeError("listing blew up")
            return [FakeCandidate("v-OKLO")]

        summary = sweep_holdings(
            research_repo=FakeRepo(),
            search_fn=flaky,
            ingest_fn=lambda _vid, **_k: FakeOutcome("saved"),
            budget=5,
            sleep_fn=lambda _s: None,
        )
        assert summary.holdings_searched == 2
        assert summary.with_confirmed_hits == 1
        assert summary.errors == 1
        assert summary.landed == 1

    def test_a_failing_ingest_does_not_abort_the_sweep(self, patched_holdings) -> None:
        def flaky(vid, **_k):
            if "CCO" in vid:
                raise RuntimeError("nope")
            return FakeOutcome("saved")

        summary = sweep_holdings(
            research_repo=FakeRepo(),
            search_fn=lambda target, **_k: [FakeCandidate(f"v-{target.ticker}")],
            ingest_fn=flaky,
            budget=5,
            sleep_fn=lambda _s: None,
        )
        assert summary.errors == 1
        assert summary.landed == 1

    def test_soft_fails_are_not_errors(self, patched_holdings) -> None:
        """A blocked/no-caption video is a fact, not a job failure."""
        summary = sweep_holdings(
            research_repo=FakeRepo(),
            search_fn=lambda target, **_k: [FakeCandidate(f"v-{target.ticker}")],
            ingest_fn=lambda _vid, **_k: FakeOutcome("soft_fail"),
            budget=5,
            sleep_fn=lambda _s: None,
        )
        assert summary.soft_failed == 2
        assert summary.errors == 0

    def test_search_hits_never_carry_expected_tickers(self, patched_holdings) -> None:
        """§26: a search hit is not an issuer channel, so tickers come from text."""
        seen: list[dict[str, Any]] = []

        def spy(_vid, **kwargs):
            seen.append(kwargs["source_row"])
            return FakeOutcome("saved")

        sweep_holdings(
            research_repo=FakeRepo(),
            search_fn=lambda target, **_k: [FakeCandidate(f"v-{target.ticker}")],
            ingest_fn=spy,
            budget=5,
            sleep_fn=lambda _s: None,
        )
        assert all(row["expected_tickers"] == [] for row in seen)
        assert {row["label"] for row in seen} == {"search:CCO.TO", "search:OKLO"}

    def test_no_holdings_returns_an_empty_summary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import scheduler.jobs_yt_sweep as sweep

        monkeypatch.setattr(sweep, "holdings_rows", lambda *a, **k: [])
        summary = sweep_holdings(research_repo=FakeRepo(), sleep_fn=lambda _s: None)
        assert summary.holdings_searched == 0
        assert summary.coverage == 0.0


class TestSummaryMessage:
    def test_message_reports_coverage_and_outcomes(self) -> None:
        s = SweepSummary(holdings_searched=77, with_confirmed_hits=71, landed=12)
        assert "71/77 holdings covered (92%)" in s.message
        assert "landed 12" in s.message
