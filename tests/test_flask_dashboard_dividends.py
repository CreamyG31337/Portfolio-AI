"""Tests for Flask /api/dashboard/dividends endpoint."""

from unittest.mock import patch
import pytest


@pytest.fixture
def auth_ok():
    with patch(
        "auth.auth_manager.verify_session",
        return_value={"user_id": "u1", "email": "user@example.com"},
    ), patch(
        "flask_auth_utils.refresh_token_if_needed_flask",
        return_value=(True, None, None, None),
    ):
        yield


def test_get_dividend_data_reinvested_amount(client, auth_ok):
    """Test that /api/dashboard/dividends returns reinvested_amount summing only DRIP rows."""
    client.set_cookie("auth_token", "test.jwt.token")

    mock_dividends = [
        {
            "pay_date": "2026-11-10",
            "ticker": "TD",
            "net_amount": 25.50,
            "gross_amount": 25.50,
            "reinvested_shares": 0.15,
            "drip_price": 170.0,
            "currency": "CAD",
            "securities": {"company_name": "Toronto-Dominion Bank"},
        },
        {
            "pay_date": "2026-11-05",
            "ticker": "RY",
            "net_amount": 14.50,
            "gross_amount": 14.50,
            "reinvested_shares": 0.05,
            "drip_price": 290.0,
            "currency": "CAD",
            "securities": {"company_name": "Royal Bank of Canada"},
        },
        {
            "pay_date": "2026-10-20",
            "ticker": "CSH",
            "net_amount": 10.00,
            "gross_amount": 10.00,
            "reinvested_shares": 0.0,
            "drip_price": 0.0,
            "currency": "CAD",
            "securities": {"company_name": "Cash Fund"},
        },
    ]

    with patch(
        "routes.dashboard_routes.fetch_dividend_log_flask",
        return_value=mock_dividends,
    ), patch(
        "routes.dashboard_routes.get_ticker_logo_urls",
        return_value={},
    ), patch(
        "routes.dashboard_routes.fetch_latest_rates_bulk",
        return_value={"CAD": 1.0},
    ), patch(
        "routes.dashboard_routes.get_user_currency",
        return_value="CAD",
    ):
        res = client.get("/api/dashboard/dividends?fund=TFSA&range=ALL")
        assert res.status_code == 200
        data = res.get_json()

        assert "metrics" in data
        metrics = data["metrics"]

        # Total dividends is sum of all net amounts (25.50 + 14.50 + 10.00 = 50.0)
        assert metrics["total_dividends"] == 50.0

        # Reinvested amount sums only rows where shares > 0 (25.50 + 14.50 = 40.0)
        assert metrics["reinvested_amount"] == 40.0

        # Reinvested shares sums all shares (0.15 + 0.05 = 0.20)
        assert round(metrics["reinvested_shares"], 4) == 0.20

        # Payout events count
        assert metrics["payout_events"] == 3


def test_get_dividend_data_fx_conversion(client, auth_ok):
    """Test that /api/dashboard/dividends converts foreign currency (USD) to target currency (CAD)."""
    client.set_cookie("auth_token", "test.jwt.token")

    mock_dividends = [
        {
            "pay_date": "2026-11-10",
            "ticker": "AAPL",
            "net_amount": 10.00,  # 10.00 USD
            "gross_amount": 12.00,  # 12.00 USD
            "reinvested_shares": 0.05,
            "drip_price": 200.0,
            "currency": "USD",
            "securities": {"company_name": "Apple Inc."},
        },
        {
            "pay_date": "2026-11-05",
            "ticker": "TD",
            "net_amount": 5.00,  # 5.00 CAD
            "gross_amount": 5.00,  # 5.00 CAD
            "reinvested_shares": 0.05,
            "drip_price": 100.0,
            "currency": "CAD",
            "securities": {"company_name": "Toronto-Dominion Bank"},
        },
    ]

    # USD to CAD rate is 1.40
    with patch(
        "routes.dashboard_routes.fetch_dividend_log_flask",
        return_value=mock_dividends,
    ), patch(
        "routes.dashboard_routes.get_ticker_logo_urls",
        return_value={},
    ), patch(
        "routes.dashboard_routes.fetch_latest_rates_bulk",
        return_value={"USD": 1.40, "CAD": 1.0},
    ), patch(
        "routes.dashboard_routes.get_user_currency",
        return_value="CAD",
    ):
        res = client.get("/api/dashboard/dividends?fund=TFSA&range=ALL")
        assert res.status_code == 200
        data = res.get_json()

        metrics = data["metrics"]
        # AAPL: net 10 USD * 1.40 = 14.0 CAD, gross 12 USD * 1.40 = 16.8 CAD, tax = 2.8 CAD
        # TD: net 5 CAD * 1.0 = 5.0 CAD, gross 5 CAD * 1.0 = 5.0 CAD, tax = 0 CAD
        # Total dividends = 14.0 + 5.0 = 19.0 CAD
        assert round(metrics["total_dividends"], 2) == 19.00
        assert round(metrics["total_us_tax"], 2) == 2.80
        assert round(metrics["reinvested_amount"], 2) == 19.00
        # Shares are NOT multiplied by FX rate
        assert round(metrics["reinvested_shares"], 4) == 0.10

        # Check log entries
        aapl_row = next(r for r in data["log"] if r["ticker"] == "AAPL")
        assert aapl_row["currency"] == "USD"
        assert aapl_row["rate"] == 1.40
        assert aapl_row["original_amount"] == 10.00
        assert round(aapl_row["amount"], 2) == 14.00
        assert round(aapl_row["drip_price"], 2) == 280.00  # 200 * 1.40
