"""Unit tests for thesis / Insights service."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from web_dashboard.user_insights_service import (
    ThesisNotFoundError,
    ThesisPermissionError,
    _normalize_ticker,
    add_entry,
    archive_thesis,
    create_thesis,
    get_thesis_row,
    list_theses,
)


def test_normalize_ticker_uppercases():
    assert _normalize_ticker(" msft ") == "MSFT"


def test_list_theses_active_only_by_default():
    pg = MagicMock()
    pg.execute_query.return_value = [{"id": uuid4(), "ticker": "MSFT", "status": "active"}]
    rows = list_theses(pg, ticker="msft")
    assert len(rows) == 1
    sql = pg.execute_query.call_args[0][0]
    assert "t.status = 'active'" in sql
    assert pg.execute_query.call_args[0][1] == ("MSFT", 100)


def test_get_thesis_row_not_found():
    pg = MagicMock()
    pg.execute_query.return_value = []
    with pytest.raises(ThesisNotFoundError):
        get_thesis_row(pg, str(uuid4()))


@patch("web_dashboard.user_insights_service._try_embedding", return_value=None)
def test_create_thesis_validates_disposition(mock_embed):
    pg = MagicMock()
    thesis_id = uuid4()
    pg.execute_query.side_effect = [
        [{"id": thesis_id}],
        [{"id": thesis_id, "ticker": "AAPL", "status": "active", "entry_count": 1, "evidence_count": 0}],
    ]
    pg.execute_update.return_value = None

    with pytest.raises(ValueError, match="invalid disposition"):
        create_thesis(
            pg,
            ticker="AAPL",
            title="Test",
            disposition="moon",
            intent="monitor",
            body="note",
            created_by="user@example.com",
        )
    mock_embed.assert_not_called()


@patch("web_dashboard.user_insights_service._try_embedding", return_value=None)
def test_create_thesis_inserts_header_and_opening(mock_embed):
    pg = MagicMock()
    thesis_id = uuid4()
    thesis_row = {
        "id": thesis_id,
        "ticker": "AAPL",
        "status": "active",
        "entry_count": 1,
        "evidence_count": 0,
    }

    def query_side_effect(*_args, **_kwargs):
        sql = (_args[0] if _args else "") or ""
        if "INSERT INTO ticker_theses" in sql:
            return [{"id": thesis_id}]
        if "INSERT INTO thesis_entries" in sql:
            return [{"id": uuid4()}]
        if "FROM ticker_theses" in sql:
            return [thesis_row]
        if "FROM thesis_entries" in sql:
            return [{"id": uuid4(), "entry_kind": "opening", "body": "Strong ecosystem."}]
        if "FROM thesis_evidence" in sql:
            return []
        return []

    pg.execute_query.side_effect = query_side_effect

    detail = create_thesis(
        pg,
        ticker="aapl",
        title="Moat thesis",
        disposition="bullish",
        intent="seek_entry",
        body="Strong ecosystem.",
        created_by="user@example.com",
        source_url="https://example.com/article",
    )
    assert detail["ticker"] == "AAPL"
    assert pg.execute_query.call_count >= 2
    mock_embed.assert_called()


def test_archive_thesis_requires_author_or_admin():
    pg = MagicMock()
    thesis_id = str(uuid4())
    pg.execute_query.return_value = [
        {"id": thesis_id, "created_by": "owner@example.com", "status": "active"}
    ]
    with pytest.raises(ThesisPermissionError):
        archive_thesis(pg, thesis_id=thesis_id, actor="other@example.com", is_admin=False)


@patch("web_dashboard.user_insights_service._try_embedding", return_value=None)
def test_add_entry_review_updates_header(mock_embed):
    pg = MagicMock()
    thesis_id = str(uuid4())
    thesis_row = {
        "id": thesis_id,
        "created_by": "u@x.com",
        "status": "active",
        "disposition": "bullish",
        "intent": "monitor",
        "ticker": "MSFT",
        "entry_count": 2,
        "evidence_count": 0,
    }

    def query_side_effect(*_args, **_kwargs):
        sql = (_args[0] if _args else "") or ""
        if "SELECT t.*" in sql:
            return [thesis_row]
        if "INSERT INTO thesis_entries" in sql:
            return [{"id": uuid4()}]
        if "FROM thesis_entries" in sql:
            return [{"id": uuid4(), "entry_kind": "review", "body": "Still valid after earnings."}]
        if "FROM thesis_evidence" in sql:
            return []
        return []

    pg.execute_query.side_effect = query_side_effect

    result = add_entry(
        pg,
        thesis_id=thesis_id,
        entry_kind="review",
        body="Still valid after earnings.",
        author_id="u@x.com",
        disposition="bearish",
        intent="seek_exit",
    )
    assert result["thesis"]["ticker"] == "MSFT"
    update_calls = [str(c) for c in pg.execute_update.call_args_list]
    assert any("UPDATE ticker_theses" in c for c in update_calls)
