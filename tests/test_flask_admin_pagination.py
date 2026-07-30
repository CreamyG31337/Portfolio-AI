"""Admin routes should use supabase_pagination for unbounded reads."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from flask_cache_utils import clear_all_caches


def test_fetch_trade_log_batches_delegates_to_fetch_all_rows() -> None:
    from routes.admin_routes import _fetch_trade_log_batches

    client = MagicMock()
    with patch(
        "supabase_pagination.fetch_all_rows",
        return_value=[{"id": "1"}, {"id": "2"}],
    ) as mock_fetch:
        rows = _fetch_trade_log_batches(client, "TEST", batch_size=1000)

    assert rows == [{"id": "1"}, {"id": "2"}]
    mock_fetch.assert_called_once_with(
        client,
        "trade_log",
        filters=[("fund", "eq", "TEST"), ("reason", "neq", "DRIP")],
        order="date",
        order_desc=True,
        page_size=1000,
    )


def test_get_portfolio_tickers_uses_fetch_all_rows() -> None:
    clear_all_caches()
    with patch("routes.admin_routes.SupabaseClient") as mock_client_cls, patch(
        "supabase_pagination.fetch_all_rows",
        return_value=[
            {"ticker": "AAA"},
            {"ticker": "BBB"},
            {"ticker": "AAA"},
            {"ticker": None},
        ],
    ) as mock_fetch:
        mock_client_cls.return_value = MagicMock()
        from routes.admin_routes import _get_portfolio_tickers

        tickers = _get_portfolio_tickers()

    assert tickers == {"AAA", "BBB"}
    mock_fetch.assert_called_once()
    assert mock_fetch.call_args.args[1] == "portfolio_positions"
    assert mock_fetch.call_args.kwargs.get("select") == "ticker"


def test_security_metadata_stock_mode_filters_etfs_and_paginates(client) -> None:
    clear_all_caches()
    securities = [
        {"ticker": "SPY", "company_name": "SPDR S&P 500", "description": "etf"},
        {"ticker": "AAA", "company_name": "Alpha", "description": "stock a"},
        {"ticker": "BBB", "company_name": "Beta", "description": "stock b"},
        {"ticker": "CCC", "company_name": "Gamma", "description": "stock c"},
    ]

    with patch("auth.auth_manager.verify_session") as mock_verify, patch(
        "flask_auth_utils.get_supabase_access_token", return_value="fake.jwt.token"
    ), patch("supabase_client.SupabaseClient") as mock_supabase_client_class, patch(
        "flask_auth_utils.can_modify_data_flask", return_value=True
    ), patch(
        "routes.admin_routes._get_cached_etf_tickers", return_value={"SPY"}
    ), patch(
        "supabase_pagination.fetch_all_rows", return_value=securities
    ) as mock_fetch:
        mock_verify.return_value = {
            "user_id": "admin-user-id",
            "email": "admin@example.com",
        }
        mock_client_instance = MagicMock()
        mock_rpc_response = MagicMock()
        mock_rpc_response.data = True
        mock_rpc_chain = MagicMock()
        mock_rpc_chain.execute.return_value = mock_rpc_response
        mock_client_instance.supabase.rpc.return_value = mock_rpc_chain
        mock_supabase_client_class.return_value = mock_client_instance

        client.set_cookie("auth_token", "test.token.value")
        response = client.get(
            "/api/admin/security-metadata?mode=stock&limit=2&offset=0"
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["success"] is True
    assert payload["total"] == 3  # SPY excluded
    assert payload["has_more"] is True
    assert [s["ticker"] for s in payload["securities"]] == ["AAA", "BBB"]
    mock_fetch.assert_called_once()
    assert mock_fetch.call_args.args[1] == "securities"
