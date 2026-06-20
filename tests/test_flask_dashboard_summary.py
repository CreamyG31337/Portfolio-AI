"""Flask /api/dashboard/summary — user_investment field (mocked; no production data)."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


def _has_plotly() -> bool:
    try:
        import plotly.graph_objs  # noqa: F401
    except ImportError:
        return False
    return True


skip_without_plotly = pytest.mark.skipif(
    not _has_plotly(),
    reason="plotly required to import web_dashboard.app",
)


@pytest.fixture
def auth_ok():
    with patch(
        "auth.auth_manager.verify_session",
        return_value={"user_id": "u1", "email": "alice@example.com"},
    ), patch(
        "flask_auth_utils.refresh_token_if_needed_flask",
        return_value=(True, None, None, None),
    ):
        yield


@skip_without_plotly
def test_summary_includes_user_investment_when_multi_investor(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    empty_positions = pd.DataFrame(
        columns=["currency", "market_value", "unrealized_pnl", "daily_pnl"]
    )
    mock_ui = {
        "net_contribution": 1000.0,
        "current_value": 1200.0,
        "gain_loss": 200.0,
        "gain_loss_pct": 20.0,
        "ownership_pct": 40.0,
        "contributor_name": "Alice",
        "units": 100.0,
        "unit_price": 12.0,
    }
    with patch(
        "routes.dashboard_routes.get_current_positions",
        return_value=empty_positions,
    ), patch(
        "routes.dashboard_routes.get_cash_balances",
        return_value={"CAD": 10000.0},
    ), patch(
        "routes.dashboard_routes.fetch_latest_rates_bulk",
        return_value={"CAD": 1.0},
    ), patch(
        "routes.dashboard_routes.get_fund_thesis_data",
        return_value=None,
    ), patch(
        "routes.dashboard_routes.get_investor_count",
        return_value=2,
    ), patch(
        "routes.dashboard_routes.get_portfolio_start_date",
        return_value=None,
    ), patch(
        "routes.dashboard_routes.calculate_portfolio_value_over_time",
        return_value=pd.DataFrame(),
    ), patch(
        "flask_auth_utils.get_user_email_flask",
        return_value="alice@example.com",
    ), patch(
        "portfolio_metrics.get_user_investment_metrics",
        return_value=mock_ui,
    ):
        resp = client.get("/api/dashboard/summary?fund=SyntheticTestFund&range=ALL")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data is not None
    assert data.get("investor_count") == 2
    ui = data.get("user_investment")
    assert ui is not None
    assert ui["contributor_name"] == "Alice"
    assert ui["current_value"] == 1200.0
    assert ui["ownership_pct"] == 40.0
    assert "user_day_change" in ui


@skip_without_plotly
def test_summary_user_investment_null_when_helper_returns_none(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    empty_positions = pd.DataFrame(
        columns=["currency", "market_value", "unrealized_pnl", "daily_pnl"]
    )
    with patch(
        "routes.dashboard_routes.get_current_positions",
        return_value=empty_positions,
    ), patch(
        "routes.dashboard_routes.get_cash_balances",
        return_value={"CAD": 5000.0},
    ), patch(
        "routes.dashboard_routes.fetch_latest_rates_bulk",
        return_value={"CAD": 1.0},
    ), patch(
        "routes.dashboard_routes.get_fund_thesis_data",
        return_value=None,
    ), patch(
        "routes.dashboard_routes.get_investor_count",
        return_value=2,
    ), patch(
        "routes.dashboard_routes.get_portfolio_start_date",
        return_value=None,
    ), patch(
        "routes.dashboard_routes.calculate_portfolio_value_over_time",
        return_value=pd.DataFrame(),
    ), patch(
        "flask_auth_utils.get_user_email_flask",
        return_value="no-match@example.com",
    ), patch(
        "portfolio_metrics.get_user_investment_metrics",
        return_value=None,
    ):
        resp = client.get("/api/dashboard/summary?fund=SyntheticTestFund&range=ALL")
    assert resp.status_code == 200
    assert resp.get_json().get("user_investment") is None


@skip_without_plotly
def test_summary_skips_user_investment_single_investor(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    empty_positions = pd.DataFrame(
        columns=["currency", "market_value", "unrealized_pnl", "daily_pnl"]
    )
    mock_fn = MagicMock()
    with patch(
        "routes.dashboard_routes.get_current_positions",
        return_value=empty_positions,
    ), patch(
        "routes.dashboard_routes.get_cash_balances",
        return_value={"CAD": 1000.0},
    ), patch(
        "routes.dashboard_routes.fetch_latest_rates_bulk",
        return_value={"CAD": 1.0},
    ), patch(
        "routes.dashboard_routes.get_fund_thesis_data",
        return_value=None,
    ), patch(
        "routes.dashboard_routes.get_investor_count",
        return_value=1,
    ), patch(
        "routes.dashboard_routes.get_portfolio_start_date",
        return_value=None,
    ), patch(
        "routes.dashboard_routes.calculate_portfolio_value_over_time",
        return_value=pd.DataFrame(),
    ), patch(
        "portfolio_metrics.get_user_investment_metrics",
        mock_fn,
    ):
        resp = client.get("/api/dashboard/summary?fund=SyntheticTestFund&range=ALL")
    assert resp.status_code == 200
    mock_fn.assert_not_called()
    assert resp.get_json().get("user_investment") is None


@skip_without_plotly
def test_performance_chart_requires_auth(client):
    resp = client.get("/api/dashboard/charts/performance?fund=SyntheticTestFund&range=ALL")
    assert resp.status_code == 401


@skip_without_plotly
def test_performance_chart_returns_traces_when_authenticated(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    sample_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-10", "2026-06-11"]),
            "value": [100.0, 101.0],
            "cost_basis": [90.0, 90.0],
            "pnl": [10.0, 11.0],
            "performance_pct": [0.0, 1.0],
            "performance_index": [100.0, 101.0],
        }
    )
    with patch(
        "flask_data_utils.calculate_portfolio_value_over_time_flask",
        return_value=sample_df,
    ), patch(
        "routes.dashboard_routes.get_user_currency",
        return_value="CAD",
    ), patch(
        "routes.dashboard_routes.get_user_theme",
        return_value="dark",
    ):
        resp = client.get("/api/dashboard/charts/performance?fund=SyntheticTestFund&range=ALL")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data is not None
    assert data.get("data")
    assert len(data["data"]) > 0
