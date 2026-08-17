"""Point-in-time available_at for research_articles (AQuA transfer Phase 1)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from research_repository import ResearchRepository


def _repo_with_flags(*, available_at: bool = True, source_metadata: bool = False) -> ResearchRepository:
    client = MagicMock()
    # Bypass __init__ DB checks
    repo = object.__new__(ResearchRepository)
    repo.client = client
    repo._has_tickers_column = True
    repo._has_source_metadata_column = source_metadata
    repo._has_available_at_column = available_at
    return repo


def test_as_of_time_column_prefers_available_at() -> None:
    repo = _repo_with_flags(available_at=True)
    assert repo._as_of_time_column() == "available_at"
    repo._has_available_at_column = False
    assert repo._as_of_time_column() == "fetched_at"


def test_save_article_insert_sets_available_at_not_on_conflict() -> None:
    repo = _repo_with_flags(available_at=True)
    cursor = MagicMock()
    cursor.fetchone.return_value = ["11111111-1111-1111-1111-111111111111"]
    conn = MagicMock()
    conn.cursor.return_value = cursor
    repo.client.get_connection.return_value.__enter__.return_value = conn
    repo.client.get_connection.return_value.__exit__.return_value = None

    article_id = repo.save_article(
        title="Late scrape of old story",
        url="https://example.com/old-story",
        published_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
        tickers=["ABCD"],
    )
    assert article_id == "11111111-1111-1111-1111-111111111111"

    sql = cursor.execute.call_args[0][0]
    assert "available_at" in sql
    assert "ON CONFLICT (url) DO UPDATE SET" in sql
    # Immutable PIT clock + no lookback bump on re-ingest
    conflict_clause = sql.split("ON CONFLICT (url) DO UPDATE SET", 1)[1]
    assert "available_at" not in conflict_clause
    assert "fetched_at" not in conflict_clause
    assert "ticker_validated_at = NOW()" in conflict_clause


def test_save_article_without_available_at_column_omits_it() -> None:
    repo = _repo_with_flags(available_at=False)
    cursor = MagicMock()
    cursor.fetchone.return_value = ["22222222-2222-2222-2222-222222222222"]
    conn = MagicMock()
    conn.cursor.return_value = cursor
    repo.client.get_connection.return_value.__enter__.return_value = conn
    repo.client.get_connection.return_value.__exit__.return_value = None

    repo.save_article(title="t", url="https://example.com/x")
    sql = cursor.execute.call_args[0][0]
    assert "available_at" not in sql
    assert "fetched_at = CURRENT_TIMESTAMP" not in sql


def test_get_recent_articles_filters_by_available_at() -> None:
    repo = _repo_with_flags(available_at=True)
    repo.client.execute_query.return_value = []

    repo.get_recent_articles(limit=5, days=30)
    sql = repo.client.execute_query.call_args[0][0]
    assert "WHERE available_at >=" in sql.replace("\n", " ")
    assert "ORDER BY available_at DESC" in sql.replace("\n", " ")


def test_get_articles_by_date_range_filters_by_available_at() -> None:
    repo = _repo_with_flags(available_at=True)
    repo.client.execute_query.return_value = []

    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 6, 1, tzinfo=timezone.utc)
    repo.get_articles_by_date_range(start_date=start, end_date=end, limit=10)
    sql = repo.client.execute_query.call_args[0][0]
    assert "WHERE available_at >= %s AND available_at <= %s" in sql.replace("\n", " ")


def test_late_ingest_excluded_from_historical_as_of_window() -> None:
    """A 2024 story first-known in 2026 must not appear in a mid-2025 lookback."""
    repo = _repo_with_flags(available_at=True)
    # Simulate DB returning nothing when filtered by available_at <= 2025-06-01
    # for an article with available_at=2026-01-01
    repo.client.execute_query.return_value = []

    as_of = datetime(2025, 6, 1, tzinfo=timezone.utc)
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = repo.get_articles_by_date_range(start_date=start, end_date=as_of, limit=50)
    assert rows == []
    params: Any = repo.client.execute_query.call_args[0][1]
    assert params[1] == as_of.isoformat()


@pytest.mark.parametrize(
    "has_col,expected_fragment",
    [
        (True, "available_at"),
        (False, "fetched_at"),
    ],
)
def test_get_recent_fallback_column(has_col: bool, expected_fragment: str) -> None:
    repo = _repo_with_flags(available_at=has_col)
    repo.client.execute_query.return_value = []
    repo.get_recent_articles(days=7)
    sql = repo.client.execute_query.call_args[0][0]
    assert f"WHERE {expected_fragment} >=" in sql.replace("\n", " ")
