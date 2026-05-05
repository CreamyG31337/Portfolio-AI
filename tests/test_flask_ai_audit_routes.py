import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _set_admin_cookie(client) -> None:
    client.set_cookie("auth_token", "test.token.value")


@pytest.fixture
def ai_audit_logs(tmp_path, monkeypatch):
    from routes import admin_routes

    log_dir = tmp_path / "ai_audit"
    log_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(admin_routes, "_AI_AUDIT_LOG_DIR", log_dir)
    return log_dir


def _mock_admin_auth(is_admin: bool = True):
    return patch.multiple(
        "auth.auth_manager",
        verify_session=MagicMock(return_value={"user_id": "admin-user-id", "email": "admin@example.com"}),
        is_admin=MagicMock(return_value=is_admin),
    )


@pytest.fixture
def mock_admin_supabase():
    with patch("supabase_client.SupabaseClient") as mock_client_class:
        mock_client_instance = MagicMock()
        mock_rpc_response = MagicMock()
        mock_rpc_response.data = True
        mock_rpc_chain = MagicMock()
        mock_rpc_chain.execute.return_value = mock_rpc_response
        mock_client_instance.supabase.rpc.return_value = mock_rpc_chain

        mock_table_result = MagicMock()
        mock_table_result.data = [{"role": "admin", "email": "admin@example.com"}]
        mock_table_chain = MagicMock()
        mock_table_chain.execute.return_value = mock_table_result
        mock_table_chain.eq.return_value = mock_table_chain
        mock_table_chain.select.return_value = mock_table_chain
        mock_client_instance.supabase.table.return_value = mock_table_chain
        mock_client_class.return_value = mock_client_instance
        yield


def _write_jsonl(path: Path, rows: list[dict | str]) -> None:
    lines: list[str] = []
    for row in rows:
        if isinstance(row, str):
            lines.append(row)
        else:
            lines.append(json.dumps(row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def seeded_ai_audit_logs(ai_audit_logs):
    _write_jsonl(
        ai_audit_logs / "2026-02-08.jsonl",
        [
            {
                "timestamp": "2026-02-08T10:00:00Z",
                "function": "generate_summary",
                "model": "granite3.3:8b",
                "provider": "ollama",
                "duration_ms": 1200,
                "success": True,
                "tickers_extracted": ["AAPL", "MSFT"],
                "sentiment": "positive",
                "article_title": "AAPL outlook",
                "article_url": "https://example.com/aapl",
            },
            {
                "timestamp": "2026-02-08T11:30:00Z",
                "function": "analyze_crowd_sentiment",
                "model": "glm-5.1",
                "provider": "glm",
                "duration_ms": 800,
                "success": False,
                "tickers_extracted": ["TSLA"],
                "sentiment": "negative",
            },
            "not valid json",
            {
                "timestamp": "2026-02-08T12:00:00Z",
                "function": "generate_summary",
                "model": "granite3.3:8b",
                "provider": "ollama",
                "duration_ms": 450,
                "success": True,
            },
        ],
    )
    _write_jsonl(
        ai_audit_logs / "2026-02-07.jsonl",
        [
            {
                "timestamp": "2026-02-07T09:00:00Z",
                "function": "generate_embedding",
                "model": "nomic-embed-text",
                "provider": "ollama",
                "duration_ms": 200,
                "success": True,
            }
        ],
    )
    return ai_audit_logs


def test_ai_audit_dates_endpoint_returns_newest_first(client, mock_admin_supabase, seeded_ai_audit_logs):
    with _mock_admin_auth(is_admin=True):
        _set_admin_cookie(client)
        response = client.get("/api/admin/ai-audit/dates")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload == {"dates": ["2026-02-08", "2026-02-07"]}


def test_ai_audit_entries_endpoint_returns_parsed_entries(client, mock_admin_supabase, seeded_ai_audit_logs):
    with _mock_admin_auth(is_admin=True):
        _set_admin_cookie(client)
        response = client.get("/api/admin/ai-audit/entries?date=2026-02-08")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["date"] == "2026-02-08"
    assert payload["total"] == 3
    assert payload["malformed_lines_skipped"] == 1
    assert payload["entries"][0]["timestamp"] == "2026-02-08T12:00:00Z"


def test_ai_audit_entries_endpoint_filters(client, mock_admin_supabase, seeded_ai_audit_logs):
    with _mock_admin_auth(is_admin=True):
        _set_admin_cookie(client)
        response = client.get(
            "/api/admin/ai-audit/entries?date=2026-02-08&function=generate_summary&model=granite3.3:8b&provider=ollama&success=true"
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total"] == 2
    assert payload["filters_applied"] == {
        "function": "generate_summary",
        "model": "granite3.3:8b",
        "provider": "ollama",
        "success": "true",
    }
    assert all(entry["function"] == "generate_summary" for entry in payload["entries"])
    assert all(entry["provider"] == "ollama" for entry in payload["entries"])
    assert all(entry["model"] == "granite3.3:8b" for entry in payload["entries"])
    assert all(entry["success"] is True for entry in payload["entries"])


def test_ai_audit_entries_invalid_date_format_returns_400(client, mock_admin_supabase, seeded_ai_audit_logs):
    with _mock_admin_auth(is_admin=True):
        _set_admin_cookie(client)
        response = client.get("/api/admin/ai-audit/entries?date=2026/02/08")

    assert response.status_code == 400
    payload = response.get_json()
    assert "Invalid date format" in payload["error"]


def test_ai_audit_entries_path_traversal_attempt_returns_400(client, mock_admin_supabase, seeded_ai_audit_logs):
    with _mock_admin_auth(is_admin=True):
        _set_admin_cookie(client)
        response = client.get("/api/admin/ai-audit/entries?date=../../etc/passwd")

    assert response.status_code == 400


def test_ai_audit_entries_missing_date_file_returns_404(client, mock_admin_supabase, seeded_ai_audit_logs):
    with _mock_admin_auth(is_admin=True):
        _set_admin_cookie(client)
        response = client.get("/api/admin/ai-audit/entries?date=2026-02-09")

    assert response.status_code == 404


def test_ai_audit_entries_non_admin_gets_403(client, mock_admin_supabase, seeded_ai_audit_logs):
    with _mock_admin_auth(is_admin=False):
        _set_admin_cookie(client)
        response = client.get("/api/admin/ai-audit/entries?date=2026-02-08")

    assert response.status_code == 403
    payload = response.get_json()
    assert payload["error"] == "Admin privileges required"
