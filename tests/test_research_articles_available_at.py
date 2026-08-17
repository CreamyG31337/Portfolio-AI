"""Point-in-time available_at for research_articles (AQuA transfer Phase 1)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from research_repository import ResearchRepository

# Imported bare, exactly as research_repository imports it. `pit_time` and
# `web_dashboard.pit_time` are two distinct module objects with two distinct probe
# caches (both directories are importable), so resetting the wrong one leaves the
# real cache populated and the "column absent" branch untestable.
from pit_time import reset_pit_column_cache


class _FakeClient:
    """Postgres double that answers the information_schema probe deterministically.

    A bare MagicMock cannot stand in here: ``pit_time`` decides whether the column
    exists from the truthiness of the probe result, and every MagicMock return is
    truthy, so the "column absent" branch would silently never be exercised.
    """

    def __init__(self, *, has_available_at: bool, fetched_at_naive: bool = True) -> None:
        self.has_available_at = has_available_at
        self.fetched_at_naive = fetched_at_naive
        self.rows: list[dict[str, Any]] = []
        self.calls: list[tuple[str, Any]] = []

    def execute_query(self, query: str, params: Any = None) -> list[Any]:
        if "information_schema.columns" in query:
            if "data_type" in query:
                # Type probe for the fallback column.
                return [
                    {
                        "data_type": (
                            "timestamp without time zone"
                            if self.fetched_at_naive
                            else "timestamp with time zone"
                        )
                    }
                ]
            return [(1,)] if self.has_available_at else []
        self.calls.append((query, params))
        return list(self.rows)

    @property
    def last_sql(self) -> str:
        return self.calls[-1][0].replace("\n", " ")

    @property
    def last_params(self) -> Any:
        return self.calls[-1][1]


@pytest.fixture(autouse=True)
def _clear_pit_cache():
    """pit_time memoizes per process; without this a probe leaks between tests."""
    reset_pit_column_cache()
    yield
    reset_pit_column_cache()


def _repo(
    *,
    available_at: bool = True,
    source_metadata: bool = False,
    fetched_at_naive: bool = True,
) -> ResearchRepository:
    repo = object.__new__(ResearchRepository)  # bypass __init__ DB checks
    repo.client = _FakeClient(
        has_available_at=available_at, fetched_at_naive=fetched_at_naive
    )
    repo._has_tickers_column = True
    repo._has_source_metadata_column = source_metadata
    repo._has_available_at_column = available_at
    return repo


def _repo_with_mock_conn(*, available_at: bool = True) -> ResearchRepository:
    repo = _repo(available_at=available_at)
    repo.client = MagicMock()
    repo._has_available_at_column = available_at
    return repo


def test_as_of_expr_coalesces_onto_the_legacy_clock() -> None:
    """NULL available_at must fall back, not vanish.

    A bare ``available_at`` predicate silently hides every row the migration did not
    reach (pre-migration restores, replicas where the DEFAULT did not replay, writers
    inserting NULL) -- the dashboard showing zero articles with no error.
    """
    repo = _repo(available_at=True)
    assert repo._as_of_time_column() == "COALESCE(available_at, fetched_at AT TIME ZONE 'UTC')"


def test_as_of_expr_falls_back_when_column_absent() -> None:
    repo = _repo(available_at=False)
    assert repo._as_of_time_column() == "fetched_at"


def test_as_of_expr_pins_a_naive_fallback_to_utc() -> None:
    """available_at is TIMESTAMPTZ; research_articles.fetched_at is naive TIMESTAMP.

    A bare COALESCE of the two resolves to timestamptz and reinterprets the naive
    value in the session TimeZone, moving every lookback boundary by the server's UTC
    offset (~8h on a Vancouver-local server). The cast must be explicit.
    """
    repo = _repo(available_at=True, fetched_at_naive=True)
    expr = repo._as_of_time_column()
    assert "AT TIME ZONE 'UTC'" in expr
    assert "COALESCE(available_at, fetched_at)" not in expr


def test_as_of_expr_omits_the_cast_for_a_timestamptz_fallback() -> None:
    """The mirror hazard, and the reason the cast is probed rather than assumed.

    social_metrics.created_at is ALREADY timestamptz in the live Research DB.
    ``AT TIME ZONE 'UTC'`` applied to a timestamptz performs the opposite conversion
    and strips the zone; it round-trips only while the server runs UTC.
    """
    repo = _repo(available_at=True, fetched_at_naive=False)
    assert repo._as_of_time_column() == "COALESCE(available_at, fetched_at)"


def test_save_article_insert_sets_available_at_not_on_conflict() -> None:
    repo = _repo_with_mock_conn(available_at=True)
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
    repo = _repo_with_mock_conn(available_at=False)
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
    repo = _repo(available_at=True)
    repo.get_recent_articles(limit=5, days=30)
    sql = repo.client.last_sql
    assert "WHERE COALESCE(available_at, fetched_at AT TIME ZONE 'UTC') >=" in sql
    assert "ORDER BY COALESCE(available_at, fetched_at AT TIME ZONE 'UTC') DESC" in sql


def test_get_articles_by_date_range_filters_by_available_at() -> None:
    repo = _repo(available_at=True)
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 6, 1, tzinfo=timezone.utc)
    repo.get_articles_by_date_range(start_date=start, end_date=end, limit=10)
    expr = "COALESCE(available_at, fetched_at AT TIME ZONE 'UTC')"
    assert f"WHERE {expr} >= %s AND {expr} <= %s" in repo.client.last_sql


def test_late_ingest_excluded_from_historical_as_of_window() -> None:
    """Success criterion 1: a 2024 story first-known in 2026 stays out of a 2025 lookback.

    This asserts on the *predicate*, not on a canned return value. The previous
    version stubbed the client to return [] and then asserted the result was [] --
    which would have passed just as happily if the query filtered on ``published_at``,
    on ``fetched_at``, or on nothing at all.
    """
    repo = _repo(available_at=True)
    as_of = datetime(2025, 6, 1, tzinfo=timezone.utc)
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo.get_articles_by_date_range(start_date=start, end_date=as_of, limit=50)

    sql = repo.client.last_sql
    params = repo.client.last_params

    # The window is bounded by the first-known clock, never by publication date --
    # publication date is exactly what a back-dated late ingest would sneak in on.
    assert "COALESCE(available_at, fetched_at AT TIME ZONE 'UTC') <= %s" in sql
    assert "published_at <=" not in sql
    # And the upper bound really is the as-of instant.
    assert params[1] == as_of.isoformat()


@pytest.mark.parametrize("has_col,expected", [(True, "COALESCE(available_at"), (False, "fetched_at >=")])
def test_get_recent_fallback_column(has_col: bool, expected: str) -> None:
    repo = _repo(available_at=has_col)
    repo.get_recent_articles(days=7)
    assert expected in repo.client.last_sql
