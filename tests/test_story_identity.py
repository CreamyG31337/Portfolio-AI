"""Tests for Phase I1 story identity / corroboration boost."""

from __future__ import annotations

import pytest

from story_identity import (
    apply_corroboration_boost,
    containment_match,
    find_matching_story,
    same_story,
    source_key,
    tokenize_words,
    try_corroborate_incoming_story,
    vectorize_title,
)


def test_tokenize_words_basic() -> None:
    assert tokenize_words("Apple's Q2 Earnings Beat Estimates") == [
        "apple's",
        "q2",
        "earnings",
        "beat",
        "estimates",
    ]


def test_source_key_prefers_host() -> None:
    assert source_key("Yahoo Finance", "https://www.finance.yahoo.com/news/x") == "finance.yahoo.com"
    assert source_key("CNBC", None) == "cnbc"


def test_same_story_near_duplicate_wire_copy() -> None:
    a = "Microcap XYZ beats earnings estimates, raises full-year guidance"
    b = "XYZ beats earnings estimates and raises full year guidance"
    assert same_story(a, b) is True


def test_different_entities_not_same_story() -> None:
    # Dual-view entity boost should separate same template, different country.
    a = "Turkey hikes interest rates to 50 percent amid inflation crisis"
    b = "Argentina hikes interest rates to 50 percent amid inflation crisis"
    assert same_story(a, b) is False


def test_containment_rescue_for_truncated_title() -> None:
    long_title = "Acme Corp announces strategic acquisition of rival Beta Industries for $2B cash"
    short = "Acme Corp announces strategic acquisition of rival Beta Industries"
    assert containment_match(tokenize_words(long_title), tokenize_words(short)) is True
    assert same_story(long_title, short) is True


def test_find_matching_story_picks_best() -> None:
    candidates = [
        {"id": "1", "title": "Unrelated weather report hits midwest farms", "url": "u1"},
        {
            "id": "2",
            "title": "NanoChip Inc reports surprise profit surge on AI chip demand",
            "url": "u2",
        },
    ]
    match = find_matching_story(
        "NanoChip reports surprise profit surge driven by AI chip demand",
        candidates,
    )
    assert match is not None
    assert match.article_id == "2"


def test_apply_corroboration_boost_caps() -> None:
    assert apply_corroboration_boost(0.7, 1) == 0.7
    assert apply_corroboration_boost(0.7, 2) == 0.75
    assert apply_corroboration_boost(0.7, 10) == 0.85  # +0.15 cap
    assert apply_corroboration_boost(0.95, 5) == 1.0


def test_calculate_relevance_score_includes_corroboration() -> None:
    from scheduler.jobs_common import calculate_relevance_score

    base = calculate_relevance_score(["ABC"], None, owned_tickers=None, corroboration_count=1)
    boosted = calculate_relevance_score(["ABC"], None, owned_tickers=None, corroboration_count=3)
    assert base == 0.7
    assert boosted == pytest.approx(0.8)


def test_try_corroborate_respects_feature_flag(monkeypatch) -> None:
    monkeypatch.setenv("STORY_DEDUP_ENABLED", "false")

    class Repo:
        def fetch_recent_story_candidates(self, **kwargs):
            raise AssertionError("should not fetch when disabled")

    assert try_corroborate_incoming_story(Repo(), title="Anything here") is None


def test_try_corroborate_records_match(monkeypatch) -> None:
    monkeypatch.setenv("STORY_DEDUP_ENABLED", "true")
    calls: list[tuple[str, str]] = []

    class Repo:
        def fetch_recent_story_candidates(self, **kwargs):
            return [
                {
                    "id": "art-1",
                    "title": "Gamma Bio posts strong Phase 2 trial results for rare disease drug",
                    "url": "https://example.com/a",
                    "source": "Example Wire",
                }
            ]

        def record_story_corroboration(self, article_id, source_key, **kwargs):
            calls.append((article_id, source_key))
            return {"matched": True, "incremented": True, "corroboration_count": 2}

    match = try_corroborate_incoming_story(
        Repo(),
        title="Gamma Bio posts strong Phase 2 trial results for rare disease therapy",
        source="Other Outlet",
        url="https://other.example/news/1",
    )
    assert match is not None
    assert match.article_id == "art-1"
    assert calls == [("art-1", "other.example")]


def test_vectorize_title_is_normalized() -> None:
    vec = vectorize_title("Hello World Markets Rally")
    assert abs(sum(v * v for v in vec.uniform) - 1.0) < 1e-6
    assert abs(sum(v * v for v in vec.entity) - 1.0) < 1e-6
