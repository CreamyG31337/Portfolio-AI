"""Integration tests for fund cash balance Flask routes (minimal app + mocked Supabase)."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

web_dashboard_path = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(web_dashboard_path) not in sys.path:
    sys.path.insert(0, str(web_dashboard_path))

sys.modules.setdefault("yfinance", MagicMock())


@pytest.fixture
def cash_api_client():
    """Flask app with only fund_bp — avoids loading full web_dashboard.app."""
    from flask import Flask
    from routes.fund_routes import fund_bp

    app = Flask(__name__)
    app.register_blueprint(fund_bp, url_prefix="/api/v2")
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return app.test_client()


def _mock_admin_auth(is_admin: bool = True):
    return patch.multiple(
        "auth.auth_manager",
        verify_session=MagicMock(
            return_value={"user_id": "admin-user-id", "email": "admin@example.com"}
        ),
        is_admin=MagicMock(return_value=is_admin),
    )


def _set_admin_cookie(client) -> None:
    client.set_cookie("auth_token", "test.token.value")


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


def _make_supabase_for_get():
    mock_client = MagicMock()

    def table_side_effect(name: str):
        tb = MagicMock()
        if name == "funds":
            tb.select.return_value.eq.return_value.execute.return_value = MagicMock(
                data=[{"name": "MyFund"}]
            )
        elif name == "cash_balances":
            tb.select.return_value.eq.return_value.execute.return_value = MagicMock(
                data=[
                    {"currency": "CAD", "amount": 100.25},
                    {"currency": "USD", "amount": 42.0},
                ]
            )
        return tb

    mock_client.supabase.table.side_effect = table_side_effect
    return mock_client


def _make_supabase_for_put():
    mock_client = MagicMock()

    def table_side_effect(name: str):
        tb = MagicMock()
        if name == "funds":
            tb.select.return_value.eq.return_value.execute.return_value = MagicMock(
                data=[{"name": "MyFund"}]
            )
        elif name == "cash_balances":
            up = MagicMock()
            up.execute.return_value = MagicMock(data=[])
            tb.upsert.return_value = up
        return tb

    mock_client.supabase.table.side_effect = table_side_effect
    return mock_client


def test_get_cash_balances_ok(cash_api_client, mock_admin_supabase):
    mock_db = _make_supabase_for_get()
    with _mock_admin_auth(True), patch(
        "routes.fund_routes.SupabaseClient", return_value=mock_db
    ):
        _set_admin_cookie(cash_api_client)
        resp = cash_api_client.get("/api/v2/funds/MyFund/cash-balances")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["CAD"] == 100.25
    assert data["USD"] == 42.0


def test_get_cash_balances_fund_not_found(cash_api_client, mock_admin_supabase):
    mock_client = MagicMock()

    def table_side_effect(name: str):
        tb = MagicMock()
        if name == "funds":
            tb.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        return tb

    mock_client.supabase.table.side_effect = table_side_effect
    with _mock_admin_auth(True), patch(
        "routes.fund_routes.SupabaseClient", return_value=mock_client
    ):
        _set_admin_cookie(cash_api_client)
        resp = cash_api_client.get("/api/v2/funds/MissingFund/cash-balances")

    assert resp.status_code == 404


def test_put_cash_balances_forbidden_when_readonly(cash_api_client, mock_admin_supabase):
    mock_db = _make_supabase_for_put()
    with _mock_admin_auth(True), patch(
        "routes.fund_routes.SupabaseClient", return_value=mock_db
    ), patch("flask_auth_utils.can_modify_data_flask", return_value=False):
        _set_admin_cookie(cash_api_client)
        resp = cash_api_client.put(
            "/api/v2/funds/MyFund/cash-balances",
            data=json.dumps({"CAD": 1.0, "USD": 2.0}),
            content_type="application/json",
        )

    assert resp.status_code == 403
    assert "Read-only" in (resp.get_json() or {}).get("error", "")


def test_put_cash_balances_bad_body_returns_400(cash_api_client, mock_admin_supabase):
    mock_db = _make_supabase_for_put()
    with _mock_admin_auth(True), patch(
        "routes.fund_routes.SupabaseClient", return_value=mock_db
    ), patch("flask_auth_utils.can_modify_data_flask", return_value=True):
        _set_admin_cookie(cash_api_client)
        resp = cash_api_client.put(
            "/api/v2/funds/MyFund/cash-balances",
            data=json.dumps({"CAD": 1.0}),
            content_type="application/json",
        )

    assert resp.status_code == 400


def test_put_cash_balances_success(cash_api_client, mock_admin_supabase):
    mock_db = _make_supabase_for_put()
    with _mock_admin_auth(True), patch(
        "routes.fund_routes.SupabaseClient", return_value=mock_db
    ), patch("flask_auth_utils.can_modify_data_flask", return_value=True), patch(
        "cache_version.bump_cache_version"
    ) as bump:
        _set_admin_cookie(cash_api_client)
        resp = cash_api_client.put(
            "/api/v2/funds/MyFund/cash-balances",
            data=json.dumps({"CAD": 11.5, "USD": 22.25}),
            content_type="application/json",
        )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["balances"]["CAD"] == 11.5
    assert payload["balances"]["USD"] == 22.25
    bump.assert_called_once()
