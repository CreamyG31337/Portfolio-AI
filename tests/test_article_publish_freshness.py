"""Stale-publish filter for article evidence (Phase K5 follow-up)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

import pit_time
from pit_time import article_fresh_publish_predicate, article_max_publish_age_days
from ticker_analysis_service import TickerAnalysisService


@pytest.fixture(autouse=True)
def _clean_cache(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ARTICLE_EVIDENCE_MAX_PUBLISH_AGE_DAYS", raising=False)
    pit_time.reset_pit_column_cache()
    yield
    pit_time.reset_pit_column_cache()


def _pg(*, has_available_at: bool, published_naive: bool) -> MagicMock:
    def query(sql: str, params=None):
        if "column_name = 'available_at'" in sql:
            return [{"?column?": 1}] if has_available_at else []
        if "data_type" in sql:
            table, column = params
            naive = published_naive if column == "published_at" else True
            return [{"data_type": "timestamp without time zone" if naive else "timestamp with time zone"}]
        raise AssertionError(f"unexpected query: {sql}")

    pg = MagicMock()
    pg.execute_query.side_effect = query
    return pg


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 30), ("", 30), ("45", 45), ("0", 0), ("-1", -1), ("junk", 30)],
)
def test_max_publish_age_env(monkeypatch: pytest.MonkeyPatch, raw, expected) -> None:
    if raw is not None:
        monkeypatch.setenv("ARTICLE_EVIDENCE_MAX_PUBLISH_AGE_DAYS", raw)
    assert article_max_publish_age_days() == expected


def test_predicate_casts_naive_published_at_and_uses_pit_clock() -> None:
    sql = article_fresh_publish_predicate(_pg(has_available_at=True, published_naive=True))
    assert sql == (
        "((published_at AT TIME ZONE 'UTC') IS NULL OR "
        "(published_at AT TIME ZONE 'UTC') >= "
        "COALESCE(available_at, fetched_at AT TIME ZONE 'UTC') - INTERVAL '30 days')"
    )


def test_predicate_leaves_timestamptz_published_at_uncast() -> None:
    sql = article_fresh_publish_predicate(_pg(has_available_at=False, published_naive=False))
    assert sql == "(published_at IS NULL OR published_at >= fetched_at - INTERVAL '30 days')"


@pytest.mark.parametrize("raw", ["0", "-5"])
def test_predicate_disabled(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("ARTICLE_EVIDENCE_MAX_PUBLISH_AGE_DAYS", raw)
    pg = MagicMock()
    assert article_fresh_publish_predicate(pg) == "TRUE"
    pg.execute_query.assert_not_called()


def test_ticker_analysis_articles_apply_freshness_filter() -> None:
    svc = object.__new__(TickerAnalysisService)
    svc.postgres = MagicMock()
    svc.postgres.execute_query.return_value = []
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    with patch("pit_time.article_as_of_expr", return_value="fetched_at"), patch(
        "pit_time.article_fresh_publish_predicate", return_value="FRESH_PREDICATE"
    ):
        svc._get_research_articles("ABCD", start)
    sql = svc.postgres.execute_query.call_args[0][0]
    assert "AND FRESH_PREDICATE" in sql


def test_meta_analysis_articles_apply_freshness_filter() -> None:
    from meta_analysis_service import TickerMetaAnalysisService

    svc = object.__new__(TickerMetaAnalysisService)
    svc.postgres = MagicMock()
    svc.postgres.execute_query.return_value = []
    with patch("pit_time.article_as_of_expr", return_value="fetched_at"), patch(
        "pit_time.article_fresh_publish_predicate", return_value="FRESH_PREDICATE"
    ):
        svc._fetch_article_snippets("ABCD")
    sql = svc.postgres.execute_query.call_args[0][0]
    assert "AND FRESH_PREDICATE" in sql
