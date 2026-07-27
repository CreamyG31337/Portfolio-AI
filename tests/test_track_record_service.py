"""Tests for track_record_service (NaN, excess, domain ROI)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from web_dashboard.track_record_service import (
    _hit_from_row,
    build_track_record_summary,
)


class _FakePg:
    """Returns canned outcomes; optional article-domain map for the second query."""

    def __init__(
        self,
        outcome_rows: list[dict[str, Any]],
        article_domains: dict[str, str] | None = None,
    ) -> None:
        self.outcome_rows = outcome_rows
        self.article_domains = article_domains or {}
        self.queries: list[str] = []

    def execute_query(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> list[dict[str, Any]]:
        self.queries.append(query)
        if "research_articles" in query:
            return [
                {"id": aid, "source": domain}
                for aid, domain in self.article_domains.items()
            ]
        return list(self.outcome_rows)


def test_hit_from_row_rejects_nan_excess() -> None:
    assert _hit_from_row({"stance": "BULLISH", "excess_return": Decimal("NaN")}) is None
    assert _hit_from_row({"stance": "BULLISH", "excess_return": Decimal("1.5")}) is True
    assert _hit_from_row({"stance": "BEARISH", "excess_return": Decimal("-1.0")}) is True
    assert _hit_from_row({"stance": "BEARISH", "excess_return": Decimal("1.0")}) is False


def test_build_track_record_summary_skips_nan_rows() -> None:
    pg = _FakePg(
        [
            {
                "source": "ticker_meta_analysis",
                "stance": "BULLISH",
                "confidence": 0.7,
                "metadata": {},
                "excess_return": Decimal("NaN"),
                "ticker_return": Decimal("NaN"),
                "benchmark_return": Decimal("1.0"),
                "ticker": "BAD",
                "as_of": "2026-06-11",
            },
            {
                "source": "ticker_meta_analysis",
                "stance": "BULLISH",
                "confidence": 0.7,
                "metadata": {},
                "excess_return": Decimal("2.0"),
                "ticker_return": Decimal("3.0"),
                "benchmark_return": Decimal("1.0"),
                "ticker": "GOOD",
                "as_of": "2026-06-11",
            },
        ]
    )
    summary = build_track_record_summary(pg, horizon_days=7)
    assert summary["total_scored"] == 2
    counts = summary["counts_by_source"]["ticker_meta_analysis"]
    assert counts["unscoreable"] == 1
    assert counts["hits"] == 1
    assert counts["scored"] == 1
    assert summary["avg_excess_by_source"]["ticker_meta_analysis"] == 2.0
    assert summary["median_excess_by_source"]["ticker_meta_analysis"] == 2.0


def test_baselines_detect_a_perfect_model() -> None:
    """A model that puts every label on the right row must beat the shuffled null."""
    from web_dashboard.track_record_service import compute_baselines

    rows = [
        ("BULLISH", 5.0, "2026-07-01"),
        ("BULLISH", 3.0, "2026-07-01"),
        ("BEARISH", -4.0, "2026-07-01"),
        ("BEARISH", -2.0, "2026-07-01"),
    ]
    b = compute_baselines(rows)
    # Every call correct: 2 winners called bullish, 2 losers called bearish.
    assert b["always_bullish_hit_rate"] == 0.5
    assert b["always_bearish_hit_rate"] == 0.5
    # Shuffled: each label lands on a matching row half the time.
    assert b["shuffled_hit_rate"] == 0.5


def test_baselines_flat_when_labels_carry_no_information() -> None:
    """Labels uncorrelated with outcomes -> shuffled null equals the real rate."""
    from web_dashboard.track_record_service import compute_baselines

    rows = [
        ("BULLISH", 5.0, "2026-07-01"),
        ("BULLISH", -5.0, "2026-07-01"),
        ("BEARISH", 5.0, "2026-07-01"),
        ("BEARISH", -5.0, "2026-07-01"),
    ]
    b = compute_baselines(rows)
    actual = 2 / 4  # one bullish winner + one bearish loser
    assert b["shuffled_hit_rate"] == actual


def test_baselines_bucket_by_day_to_respect_correlated_moves() -> None:
    """All-up and all-down days must not be pooled: within a day there is nothing to pick.

    Pooling them would let a day where everything rose subsidise a day where
    everything fell, understating the null.
    """
    from web_dashboard.track_record_service import compute_baselines

    rows = [
        ("BULLISH", 2.0, "2026-07-01"),
        ("BEARISH", 3.0, "2026-07-01"),   # everything up that day
        ("BULLISH", -2.0, "2026-07-02"),
        ("BEARISH", -3.0, "2026-07-02"),  # everything down that day
    ]
    b = compute_baselines(rows)
    assert b["day_buckets"] == 2
    # Day 1: any label has a winner under it. Day 2: any label has a loser.
    # So a shuffled model gets exactly one of two right on each day.
    assert b["shuffled_hit_rate"] == 0.5
    assert b["always_bullish_hit_rate"] == 0.5


def test_baselines_empty_input() -> None:
    from web_dashboard.track_record_service import compute_baselines

    b = compute_baselines([])
    assert b["n"] == 0
    assert b["shuffled_hit_rate"] is None


def test_correct_bearish_call_contributes_positive_excess() -> None:
    """The M3 bug: raw excess made a correct BEARISH call score as a bad outcome.

    Prod symptom before the fix: action_queue_ai_review showed hit_rate=68.0%
    alongside mean_excess=-4.24.
    """
    pg = _FakePg(
        [
            {
                "source": "action_queue_ai_review",
                "stance": "SELL",
                "confidence": 0.8,
                "metadata": {},
                # Stock fell 5pp vs benchmark. The SELL call was RIGHT.
                "excess_return": Decimal("-5.0"),
                "ticker_return": Decimal("-4.0"),
                "benchmark_return": Decimal("1.0"),
                "ticker": "AAA",
                "as_of": "2026-07-01",
            },
            {
                "source": "action_queue_ai_review",
                "stance": "BUY",
                "confidence": 0.8,
                "metadata": {},
                "excess_return": Decimal("3.0"),
                "ticker_return": Decimal("4.0"),
                "benchmark_return": Decimal("1.0"),
                "ticker": "BBB",
                "as_of": "2026-07-01",
            },
        ]
    )
    summary = build_track_record_summary(pg, horizon_days=30)
    # Both calls were correct, so both must pull the mean UP: (5.0 + 3.0) / 2.
    assert summary["hit_rate_by_source"]["action_queue_ai_review"] == 1.0
    assert summary["avg_excess_by_source"]["action_queue_ai_review"] == 4.0
    assert summary["excess_metric"] == "directional"
    # The bearish winner is the better call and must rank first.
    assert summary["best_calls"][0]["ticker"] == "AAA"


def test_broad_index_etfs_excluded_from_aggregates() -> None:
    pg = _FakePg(
        [
            {
                "source": "ticker_meta_analysis",
                "stance": "BULLISH",
                "confidence": 0.8,
                "metadata": {},
                "excess_return": Decimal("0.01"),
                "ticker_return": Decimal("1.01"),
                "benchmark_return": Decimal("1.0"),
                "ticker": "VOO",  # tracks ^GSPC: excess ~0 by construction
                "as_of": "2026-07-01",
            },
            {
                "source": "ticker_meta_analysis",
                "stance": "BULLISH",
                "confidence": 0.8,
                "metadata": {},
                "excess_return": Decimal("6.0"),
                "ticker_return": Decimal("7.0"),
                "benchmark_return": Decimal("1.0"),
                "ticker": "ROBO",  # thematic ETF: a genuine call, must be kept
                "as_of": "2026-07-01",
            },
        ]
    )
    summary = build_track_record_summary(pg, horizon_days=30)
    assert summary["broad_index_etf_excluded"] == 1
    assert summary["counts_by_source"]["ticker_meta_analysis"]["scored"] == 1
    assert summary["avg_excess_by_source"]["ticker_meta_analysis"] == 6.0


def test_mean_excess_by_source() -> None:
    pg = _FakePg(
        [
            {
                "source": "ticker_meta_analysis",
                "stance": "BULLISH",
                "confidence": 0.8,
                "metadata": {},
                "excess_return": Decimal("4.0"),
                "ticker_return": Decimal("5.0"),
                "benchmark_return": Decimal("1.0"),
                "ticker": "AAA",
                "as_of": "2026-07-01",
            },
            {
                "source": "ticker_meta_analysis",
                "stance": "BULLISH",
                "confidence": 0.4,
                "metadata": {},
                "excess_return": Decimal("2.0"),
                "ticker_return": Decimal("3.0"),
                "benchmark_return": Decimal("1.0"),
                "ticker": "BBB",
                "as_of": "2026-07-01",
            },
            {
                "source": "action_queue_ai_review",
                "stance": "BUY",
                "confidence": 0.6,
                "metadata": {"verdict": "ALIGNED"},
                "excess_return": Decimal("-1.0"),
                "ticker_return": Decimal("0.0"),
                "benchmark_return": Decimal("1.0"),
                "ticker": "CCC",
                "as_of": "2026-07-01",
            },
        ]
    )
    summary = build_track_record_summary(pg, horizon_days=30)
    assert summary["avg_excess_by_source"]["ticker_meta_analysis"] == 3.0
    assert summary["median_excess_by_source"]["ticker_meta_analysis"] == 3.0
    assert summary["avg_excess_by_source"]["action_queue_ai_review"] == -1.0
    # Confidence bands: 0.8 → gte_0.75 hit; 0.4 → lt_0.5 hit; 0.6 → mid miss
    assert summary["counts_by_confidence_band"]["gte_0.75"]["hits"] == 1
    assert summary["counts_by_confidence_band"]["lt_0.5"]["hits"] == 1
    assert summary["counts_by_confidence_band"]["0.5_to_0.75"]["misses"] == 1


def test_domain_fractional_attribution() -> None:
    """One hit with two domains credits 0.5 scored/hits to each."""
    pg = _FakePg(
        [
            {
                "source": "ticker_meta_analysis",
                "stance": "BULLISH",
                "confidence": 0.7,
                "metadata": {
                    "evidence": {
                        "article_ids": [
                            "11111111-1111-1111-1111-111111111111",
                            "22222222-2222-2222-2222-222222222222",
                        ],
                        "artifact_types": ["articles"],
                    }
                },
                "excess_return": Decimal("10.0"),
                "ticker_return": Decimal("11.0"),
                "benchmark_return": Decimal("1.0"),
                "ticker": "HIT",
                "as_of": "2026-07-01",
            },
        ],
        article_domains={
            "11111111-1111-1111-1111-111111111111": "yahoo.com",
            "22222222-2222-2222-2222-222222222222": "seekingalpha.com",
        },
    )
    summary = build_track_record_summary(pg, horizon_days=30)
    by_domain = {d["domain"]: d for d in summary["by_domain"]}
    assert set(by_domain) == {"yahoo.com", "seekingalpha.com"}
    for domain in ("yahoo.com", "seekingalpha.com"):
        assert by_domain[domain]["scored"] == 0.5
        assert by_domain[domain]["hits"] == 0.5
        assert by_domain[domain]["hit_rate"] == 1.0
        assert by_domain[domain]["mean_excess"] == 10.0
        assert by_domain[domain]["stance_touches"] == 1


def test_missing_evidence_domain_empty_and_coverage() -> None:
    pg = _FakePg(
        [
            {
                "source": "action_queue_ai_review",
                "stance": "BUY",
                "confidence": 0.6,
                "metadata": {"verdict": "TENSION"},
                "excess_return": Decimal("1.0"),
                "ticker_return": Decimal("2.0"),
                "benchmark_return": Decimal("1.0"),
                "ticker": "QQQ",
                "as_of": "2026-07-01",
            },
            {
                "source": "ticker_meta_analysis",
                "stance": "BULLISH",
                "confidence": 0.7,
                "metadata": {"evidence": {"article_ids": [], "artifact_types": ["signals"]}},
                "excess_return": Decimal("3.0"),
                "ticker_return": Decimal("4.0"),
                "benchmark_return": Decimal("1.0"),
                "ticker": "META",
                "as_of": "2026-07-01",
            },
        ]
    )
    summary = build_track_record_summary(pg, horizon_days=30)
    assert summary["by_domain"] == []
    cov_queue = summary["evidence_coverage"]["action_queue_ai_review"]
    assert cov_queue["with_evidence"] == 0
    assert cov_queue["with_article_ids"] == 0
    assert cov_queue["pct_with_article_ids"] == 0.0
    cov_meta = summary["evidence_coverage"]["ticker_meta_analysis"]
    assert cov_meta["with_evidence"] == 1
    assert cov_meta["with_article_ids"] == 0
    assert summary["domain_attribution"]["stances_with_resolved_domain"] == 0


def test_unresolvable_article_ids_not_fake_domain() -> None:
    pg = _FakePg(
        [
            {
                "source": "ticker_analysis",
                "stance": "BEARISH",
                "confidence": 0.55,
                "metadata": {
                    "evidence": {
                        "article_ids": ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"],
                    }
                },
                "excess_return": Decimal("-2.0"),
                "ticker_return": Decimal("-1.0"),
                "benchmark_return": Decimal("1.0"),
                "ticker": "XYZ",
                "as_of": "2026-07-01",
            },
        ],
        article_domains={},  # lookup miss
    )
    summary = build_track_record_summary(pg, horizon_days=7)
    assert summary["by_domain"] == []
    assert summary["domain_attribution"]["unresolved_article_id_lookups"] == 1
    assert summary["evidence_coverage"]["ticker_analysis"]["with_article_ids"] == 1
