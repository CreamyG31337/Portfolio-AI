#!/usr/bin/env python3
"""Tests for AI Assistant server-side chat session helpers + routes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ai_assistant_session import (
    MAX_STORED_TURNS,
    append_turns,
    clear_chat,
    load_chat,
    _normalize_messages,
)


class TestNormalizeMessages:
    def test_filters_roles_and_caps(self) -> None:
        raw = (
            [{"role": "system", "content": "nope"}]
            + [{"role": "user", "content": f"u{i}"} for i in range(50)]
            + [{"role": "assistant", "content": "a"}]
        )
        out = _normalize_messages(raw)
        assert all(m["role"] in ("user", "assistant") for m in out)
        assert len(out) == MAX_STORED_TURNS
        assert out[-1]["content"] == "a"


class TestSessionHelpers:
    def test_load_empty_when_missing(self) -> None:
        table = MagicMock()
        chain = table.select.return_value.eq.return_value.eq.return_value.limit.return_value
        chain.execute.return_value = MagicMock(data=[])
        sb = MagicMock()
        sb.supabase.table.return_value = table
        with patch("ai_assistant_session._supabase", return_value=sb):
            out = load_chat("user-1", "TEST")
        assert out["messages"] == []
        assert out["fund"] == "TEST"

    def test_replace_and_append(self) -> None:
        table = MagicMock()
        select_chain = table.select.return_value.eq.return_value.eq.return_value.limit.return_value
        select_chain.execute.return_value = MagicMock(
            data=[{"messages": [{"role": "user", "content": "hi"}], "model": None}]
        )
        upsert_chain = table.upsert.return_value
        upsert_chain.execute.return_value = MagicMock(data=[])
        sb = MagicMock()
        sb.supabase.table.return_value = table
        with patch("ai_assistant_session._supabase", return_value=sb):
            out = append_turns(
                "user-1",
                "TEST",
                [{"role": "assistant", "content": "hello"}],
                model="glm-5.2",
            )
        assert len(out["messages"]) == 2
        assert out["messages"][0]["content"] == "hi"
        assert out["messages"][1]["content"] == "hello"
        assert out["model"] == "glm-5.2"
        table.upsert.assert_called()

    def test_clear_deletes_row(self) -> None:
        table = MagicMock()
        delete_chain = table.delete.return_value.eq.return_value.eq.return_value
        delete_chain.execute.return_value = MagicMock(data=[])
        sb = MagicMock()
        sb.supabase.table.return_value = table
        with patch("ai_assistant_session._supabase", return_value=sb):
            clear_chat("user-1", "TEST")
        table.delete.assert_called()


@pytest.fixture
def auth_ok():
    with patch(
        "auth.auth_manager.verify_session",
        return_value={
            "user_id": "11111111-1111-1111-1111-111111111111",
            "email": "u@test.com",
        },
    ), patch(
        "flask_auth_utils.refresh_token_if_needed_flask",
        return_value=(True, None, None, None),
    ), patch(
        "routes.ai_routes.get_user_id_flask",
        return_value="11111111-1111-1111-1111-111111111111",
    ):
        yield


class TestSessionRoutes:
    def test_get_session(self, client, auth_ok) -> None:
        with patch(
            "ai_assistant_session.load_chat",
            return_value={
                "fund": "TEST",
                "model": "glm-5.2",
                "messages": [{"role": "user", "content": "hi"}],
                "updated_at": None,
            },
        ), patch("ai_assistant_clients.user_can_access_fund", return_value=True):
            client.set_cookie("auth_token", "test.jwt.token")
            res = client.get("/api/v2/ai/chat/session?fund=TEST")
        assert res.status_code == 200
        body = res.get_json()
        assert body["ok"] is True
        assert body["messages"][0]["content"] == "hi"

    def test_append_turns(self, client, auth_ok, app) -> None:
        app.config["WTF_CSRF_ENABLED"] = False
        with patch(
            "ai_assistant_session.append_turns",
            return_value={
                "fund": "TEST",
                "model": "glm-5.2",
                "messages": [
                    {"role": "user", "content": "q"},
                    {"role": "assistant", "content": "a"},
                ],
                "updated_at": "2026-07-25T00:00:00+00:00",
            },
        ) as mock_append, patch(
            "ai_assistant_clients.user_can_access_fund", return_value=True
        ):
            client.set_cookie("auth_token", "test.jwt.token")
            res = client.post(
                "/api/v2/ai/chat/append",
                json={
                    "fund": "TEST",
                    "model": "glm-5.2",
                    "turns": [
                        {"role": "user", "content": "q"},
                        {"role": "assistant", "content": "a"},
                    ],
                },
            )
        assert res.status_code == 200, res.get_json()
        assert res.get_json()["ok"] is True
        mock_append.assert_called_once()

    def test_clear_resets_webai(self, client, auth_ok, app) -> None:
        app.config["WTF_CSRF_ENABLED"] = False
        with patch("ai_assistant_session.clear_chat") as mock_clear, patch(
            "ai_assistant_session.reset_webai_session"
        ) as mock_reset, patch(
            "ai_assistant_clients.user_can_access_fund", return_value=True
        ):
            client.set_cookie("auth_token", "test.jwt.token")
            res = client.post("/api/v2/ai/chat/clear", json={"fund": "TEST"})
        assert res.status_code == 200, res.get_json()
        assert res.get_json()["ok"] is True
        mock_clear.assert_called_once()
        mock_reset.assert_called_once()

    def test_session_requires_fund(self, client, auth_ok) -> None:
        client.set_cookie("auth_token", "test.jwt.token")
        res = client.get("/api/v2/ai/chat/session")
        assert res.status_code == 400
