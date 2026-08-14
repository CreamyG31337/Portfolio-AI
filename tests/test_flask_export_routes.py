"""Export APIs must page through PostgREST's 1000-row cap instead of .limit()."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _admin_auth(client):
    client.set_cookie("auth_token", "test.token.value")
    return patch(
        "auth.auth_manager.verify_session",
        return_value={"user_id": "admin-user-id", "email": "admin@example.com"},
    )


def test_export_portfolio_uses_fetch_all_rows(client) -> None:
    rows = [{"ticker": "AAA"}, {"ticker": "BBB"}]
    with (
        _admin_auth(client),
        patch("web_dashboard.app.is_admin", return_value=True),
        patch("web_dashboard.app.get_supabase_client", return_value=MagicMock()),
        patch("supabase_pagination.fetch_all_rows", return_value=rows) as mock_fetch,
    ):
        response = client.get("/api/export/portfolio?fund=TEST&limit=5000")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["success"] is True
    assert payload["data"] == rows
    assert payload["count"] == 2
    mock_fetch.assert_called_once_with(
        mock_fetch.call_args.args[0],
        "portfolio_positions",
        filters=[("fund", "eq", "TEST")],
        max_rows=5000,
    )


def test_export_trades_uses_fetch_all_rows(client) -> None:
    rows = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
    with (
        _admin_auth(client),
        patch("web_dashboard.app.is_admin", return_value=True),
        patch("web_dashboard.app.get_supabase_client", return_value=MagicMock()),
        patch("supabase_pagination.fetch_all_rows", return_value=rows) as mock_fetch,
    ):
        response = client.get("/api/export/trades?fund=TEST&limit=2500")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["success"] is True
    assert payload["count"] == 3
    mock_fetch.assert_called_once_with(
        mock_fetch.call_args.args[0],
        "trade_log",
        filters=[("fund", "eq", "TEST")],
        order="date",
        order_desc=True,
        max_rows=2500,
    )


def test_export_portfolio_rejects_non_admin(client) -> None:
    with (
        _admin_auth(client),
        patch("web_dashboard.app.is_admin", return_value=False),
    ):
        response = client.get("/api/export/portfolio")

    assert response.status_code == 403
