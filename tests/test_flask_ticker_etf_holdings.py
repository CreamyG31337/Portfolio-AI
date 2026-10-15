"""Flask: /api/ticker/<ticker>/etf-holdings (ETF holdings panel on ticker details)."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest


def _has_plotly() -> bool:
    try:
        import plotly.graph_objs  # noqa: F401
    except ImportError:
        return False
    return True


skip_without_plotly = pytest.mark.skipif(
    not _has_plotly(),
    reason="plotly required to import web_dashboard.app (see conftest)",
)


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


def _pg_client(execute_query=None):
    pc = MagicMock()
    pc.execute_query = execute_query if execute_query is not None else MagicMock()
    return pc


@skip_without_plotly
def test_ticker_etf_holdings_tracked(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    # Rows come back from the DB already ordered by weight desc (ORDER BY in SQL)
    rows = [
        {"holding_ticker": "SENS", "holding_name": "Senseonics", "shares_held": 900000, "weight_percent": 4.02},
        {"holding_ticker": "AME", "holding_name": "Amplify Energy Corp", "shares_held": 250000, "weight_percent": 3.21},
    ]
    execute_query = MagicMock(side_effect=[
        [{"latest_date": date(2026, 10, 10)}],  # MAX(date) lookup
        rows,                                   # holdings for that date
    ])
    with patch("routes.etf_routes._get_postgres_client", return_value=_pg_client(execute_query)):
        resp = client.get("/api/ticker/buzz/etf-holdings")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["is_tracked_etf"] is True
    assert body["as_of"] == "2026-10-10"
    assert body["holding_count"] == 2
    assert [h["ticker"] for h in body["holdings"]] == ["SENS", "AME"]  # weight desc preserved
    assert body["holdings"][0]["shares"] == 900000
    assert body["holdings"][0]["weight_percent"] == 4.02

    # Ticker uppercased/stripped and passed as a SQL parameter (never interpolated)
    assert execute_query.call_args_list[0].args[1] == ("BUZZ",)
    assert execute_query.call_args_list[1].args[1] == ("2026-10-10", "BUZZ")


@skip_without_plotly
def test_ticker_etf_holdings_untracked_is_not_an_error(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    execute_query = MagicMock(return_value=[{"latest_date": None}])
    with patch("routes.etf_routes._get_postgres_client", return_value=_pg_client(execute_query)):
        resp = client.get("/api/ticker/AAPL/etf-holdings")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["is_tracked_etf"] is False
    assert body["as_of"] is None
    assert body["holdings"] == []
    assert body["holding_count"] == 0
    # Only the MAX(date) lookup ran; no holdings query for untracked tickers
    assert execute_query.call_count == 1


@skip_without_plotly
def test_ticker_etf_holdings_empty_latest_result(client, auth_ok):
    """MAX(date) returning no rows at all is also untracked, not an error."""
    client.set_cookie("auth_token", "test.jwt.token")
    execute_query = MagicMock(return_value=[])
    with patch("routes.etf_routes._get_postgres_client", return_value=_pg_client(execute_query)):
        resp = client.get("/api/ticker/NVDA/etf-holdings")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["is_tracked_etf"] is False
    assert body["holdings"] == []


@skip_without_plotly
def test_ticker_etf_holdings_db_error_returns_500(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    execute_query = MagicMock(side_effect=RuntimeError("connection refused"))
    with patch("routes.etf_routes._get_postgres_client", return_value=_pg_client(execute_query)):
        resp = client.get("/api/ticker/BUZZ/etf-holdings")

    assert resp.status_code == 500
    body = resp.get_json()
    assert body["success"] is False
