"""Admin Chimera holder glance."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


def _mock_admin_guard(mock_supabase_client_class: MagicMock) -> None:
    mock_client_instance = MagicMock()
    mock_rpc_response = MagicMock()
    mock_rpc_response.data = True
    mock_rpc_chain = MagicMock()
    mock_rpc_chain.execute.return_value = mock_rpc_response
    mock_client_instance.supabase.rpc.return_value = mock_rpc_chain
    mock_supabase_client_class.return_value = mock_client_instance


def _admin_patches():
    return (
        patch("auth.auth_manager.verify_session"),
        patch("flask_auth_utils.get_supabase_access_token", return_value="fake.jwt.token"),
        patch("supabase_client.SupabaseClient"),
    )


def test_chimera_holders_page_renders_for_admin(client) -> None:
    verify, token, supabase = _admin_patches()
    with verify as mock_verify, token, supabase as mock_supabase:
        mock_verify.return_value = {"user_id": "admin-user-id", "email": "admin@example.com"}
        _mock_admin_guard(mock_supabase)
        client.set_cookie("auth_token", "test.token.value")
        response = client.get("/admin/chimera-holders")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Chimera holders" in body
    assert "Copy for a text" in body


def test_chimera_holders_api_uses_project_chimera_and_slices_the_day(client) -> None:
    verify, token, supabase = _admin_patches()
    positions = pd.DataFrame([{"currency": "CAD", "market_value": 100.0}])
    with verify as mock_verify, token, supabase as mock_supabase, patch(
        "routes.holder_glance_routes.get_current_positions", return_value=positions
    ), patch(
        "routes.holder_glance_routes.get_cash_balances", return_value={"CAD": 10.0}
    ), patch(
        "routes.holder_glance_routes.fetch_latest_rates_bulk", return_value={"CAD": 1.0}
    ), patch(
        "routes.holder_glance_routes.compute_core_summary_metrics",
        return_value={
            "total_value": 3000.0,
            "cash_balance": 0.0,
            "day_change": 30.0,
            "day_change_pct": 1.0,
        },
    ), patch(
        "routes.holder_glance_routes.get_user_currency", return_value="CAD"
    ), patch(
        "routes.holder_glance_routes.get_user_investment_metrics",
        return_value={
            "display_currency": "CAD",
            "fund_value": 3000.0,
            "unit_price": 2.0,
            "holders": [
                {
                    "name": "Alex",
                    "net_contribution": 1000.0,
                    "current_value": 2000.0,
                    "gain_loss": 1000.0,
                    "gain_loss_pct": 100.0,
                    "ownership_pct": 66.666666,
                }
            ],
        },
    ) as mock_metrics:
        mock_verify.return_value = {"user_id": "admin-user-id", "email": "admin@example.com"}
        _mock_admin_guard(mock_supabase)
        client.set_cookie("auth_token", "test.token.value")
        response = client.get("/api/admin/chimera-holders")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["fund"] == "Project Chimera"
    assert payload["holders"][0]["name"] == "Alex"
    assert payload["holders"][0]["day_change"] == pytest.approx(20.0)
    assert mock_metrics.call_args.args[0] == "Project Chimera"
    assert mock_metrics.call_args.kwargs["for_all_holders"] is True
