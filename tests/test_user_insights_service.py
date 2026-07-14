"""Unit tests for thesis / Insights service."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from web_dashboard.user_insights_service import (
    ThesisNotFoundError,
    ThesisPermissionError,
    _normalize_ticker,
    add_entry,
    add_llm_reply,
    archive_thesis,
    classify_due_status,
    create_thesis,
    get_thesis_row,
    is_weak_thesis,
    list_theses,
    list_theses_due,
    thesis_reviewed_at,
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


def test_classify_due_status_windows():
    now = datetime(2026, 7, 13, tzinfo=UTC)
    assert classify_due_status(now - timedelta(days=5), now=now) is None
    assert classify_due_status(now - timedelta(days=14), now=now) == "due_for_review"
    assert classify_due_status(now - timedelta(days=20), now=now) == "due_for_review"
    assert classify_due_status(now - timedelta(days=30), now=now) == "stale"
    assert classify_due_status(None, now=now) == "stale"


def test_is_weak_thesis_title_and_tags():
    assert is_weak_thesis(title="[LLM draft][WEAK CONTEXT] COST")
    assert is_weak_thesis(opening_body="[WEAK CONTEXT] Thin sources.")
    assert is_weak_thesis(opening_metadata={"tags": ["llm_draft", "weak_context"]})
    assert not is_weak_thesis(title="Solid moat", opening_body="Scale advantages.")


def test_thesis_reviewed_at_prefers_last_reviewed():
    created = datetime(2026, 1, 1, tzinfo=UTC)
    reviewed = datetime(2026, 6, 1, tzinfo=UTC)
    assert thesis_reviewed_at({"created_at": created, "last_reviewed_at": reviewed}) == reviewed
    assert thesis_reviewed_at({"created_at": created, "last_reviewed_at": None}) == created


def test_list_theses_due_sorts_weak_first():
    pg = MagicMock()
    now = datetime(2026, 7, 13, tzinfo=UTC)
    old = now - timedelta(days=40)
    mid = now - timedelta(days=16)
    fresh = now - timedelta(days=2)
    pg.execute_query.return_value = [
        {
            "id": uuid4(),
            "ticker": "FRESH",
            "title": "Fresh",
            "status": "active",
            "created_at": fresh,
            "last_reviewed_at": fresh,
            "opening_body": "ok",
            "opening_metadata": {},
            "entry_count": 1,
            "evidence_count": 0,
        },
        {
            "id": uuid4(),
            "ticker": "STALE",
            "title": "Stale normal",
            "status": "active",
            "created_at": old,
            "last_reviewed_at": old,
            "opening_body": "ok",
            "opening_metadata": {},
            "entry_count": 1,
            "evidence_count": 0,
        },
        {
            "id": uuid4(),
            "ticker": "WEAK",
            "title": "[LLM draft][WEAK CONTEXT] Weak",
            "status": "active",
            "created_at": mid,
            "last_reviewed_at": mid,
            "opening_body": "thin",
            "opening_metadata": {"tags": ["weak_context"]},
            "entry_count": 1,
            "evidence_count": 0,
        },
    ]
    rows = list_theses_due(pg, now=now, limit=10)
    tickers = [r["ticker"] for r in rows]
    assert "FRESH" not in tickers
    assert tickers[0] == "WEAK"
    assert rows[0]["is_weak"] is True
    assert any(r["ticker"] == "STALE" and r["review_status"] == "stale" for r in rows)


@patch("web_dashboard.user_insights_service._try_embedding", return_value=None)
def test_add_llm_reply_does_not_bump_last_reviewed(mock_embed):
    pg = MagicMock()
    thesis_id = str(uuid4())
    thesis_row = {
        "id": thesis_id,
        "ticker": "MSFT",
        "status": "active",
        "disposition": "bullish",
        "intent": "monitor",
        "last_reviewed_at": datetime(2026, 1, 1, tzinfo=UTC),
        "entry_count": 2,
        "evidence_count": 0,
    }

    def query_side_effect(*_args, **_kwargs):
        sql = (_args[0] if _args else "") or ""
        if "SELECT t.*" in sql or "FROM ticker_theses" in sql:
            return [thesis_row]
        if "INSERT INTO thesis_entries" in sql:
            assert "llm_reply" in sql
            assert "'llm'" in sql or '"llm"' in sql or ", 'llm'," in sql or "llm'," in sql
            return [{"id": uuid4()}]
        if "FROM thesis_entries" in sql:
            return [{"id": uuid4(), "entry_kind": "llm_reply", "body": "HOLDS"}]
        if "FROM thesis_evidence" in sql:
            return []
        return [thesis_row]

    pg.execute_query.side_effect = query_side_effect

    result = add_llm_reply(
        pg,
        thesis_id=thesis_id,
        body="Advisory: HOLDS",
        metadata={"verdict": "HOLDS"},
        model_used="test-model",
    )
    assert result["entry_id"]
    update_sql = pg.execute_update.call_args[0][0]
    assert "last_reviewed_at" not in update_sql
    assert "updated_at" in update_sql


def test_add_entry_rejects_llm_reply():
    pg = MagicMock()
    thesis_id = str(uuid4())
    pg.execute_query.return_value = [
        {"id": thesis_id, "disposition": "bullish", "intent": "monitor", "status": "active"}
    ]
    with pytest.raises(ValueError, match="invalid entry_kind"):
        add_entry(
            pg,
            thesis_id=thesis_id,
            entry_kind="llm_reply",
            body="nope",
            author_id="user@example.com",
        )


def test_format_human_theses_for_meta_bundle_labels_weak():
    from web_dashboard.user_insights_service import format_human_theses_for_meta_bundle

    pg = MagicMock()
    thesis_id = uuid4()
    thesis_row = {
        "id": thesis_id,
        "ticker": "COST",
        "title": "[LLM draft][WEAK CONTEXT] Thin Costco draft",
        "disposition": "neutral",
        "intent": "monitor",
        "status": "active",
        "entry_count": 1,
        "evidence_count": 0,
    }
    opening = {
        "id": uuid4(),
        "entry_kind": "opening",
        "body": "[WEAK CONTEXT] No direct Costco evidence.",
        "metadata": {"tags": ["llm_draft", "moat", "weak_context"]},
    }

    def query_side_effect(*_args, **_kwargs):
        sql = (_args[0] if _args else "") or ""
        if "FROM ticker_theses t" in sql and "WHERE" in sql:
            return [thesis_row]
        if "FROM thesis_entries" in sql:
            return [opening]
        if "FROM thesis_evidence" in sql:
            return []
        if "SELECT t.*" in sql:
            return [thesis_row]
        return [thesis_row]

    pg.execute_query.side_effect = query_side_effect
    block = format_human_theses_for_meta_bundle(pg, "COST")
    assert block is not None
    assert "Human ticker thesis threads" in block
    assert "not fund_thesis" in block
    assert "WEAK CONTEXT" in block
    assert "bootstrap/llm_draft" in block


def test_format_human_theses_for_meta_bundle_none_when_empty():
    from web_dashboard.user_insights_service import format_human_theses_for_meta_bundle

    pg = MagicMock()
    pg.execute_query.return_value = []
    assert format_human_theses_for_meta_bundle(pg, "ZZZZ") is None
