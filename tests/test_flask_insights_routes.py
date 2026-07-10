"""Flask: Insights / thesis thread routes."""

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


@skip_without_plotly
def test_insights_page(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    resp = client.get("/insights")
    assert resp.status_code == 200
    assert b"Insights" in resp.data


@skip_without_plotly
def test_list_insights_api(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    rows = [{
        "id": "t1",
        "ticker": "MSFT",
        "title": "Cloud moat",
        "disposition": "bullish",
        "intent": "monitor",
        "status": "active",
        "created_by": "user@example.com",
    }]
    with patch("routes.insights_routes.PostgresClient", return_value=MagicMock()), patch(
        "routes.insights_routes.list_theses",
        return_value=rows,
    ) as mock_list:
        resp = client.get("/api/insights?ticker=MSFT&include_archived=1")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"][0]["ticker"] == "MSFT"
    mock_list.assert_called_once()
    assert mock_list.call_args.kwargs["include_archived"] is True


@skip_without_plotly
def test_create_insight_api(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    detail = {"id": "t1", "ticker": "AAPL", "title": "Services growth"}
    with patch("routes.insights_routes.PostgresClient", return_value=MagicMock()), patch(
        "routes.insights_routes.create_thesis",
        return_value=detail,
    ):
        resp = client.post(
            "/api/insights",
            json={
                "ticker": "AAPL",
                "title": "Services growth",
                "disposition": "bullish",
                "intent": "seek_entry",
                "body": "Recurring revenue expanding.",
            },
        )
    assert resp.status_code == 201
    assert resp.get_json()["data"]["ticker"] == "AAPL"


@skip_without_plotly
def test_create_insight_requires_body(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    resp = client.post("/api/insights", json={"ticker": "AAPL"})
    assert resp.status_code == 400


@skip_without_plotly
def test_ticker_insights_api(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    with patch("routes.insights_routes.PostgresClient", return_value=MagicMock()), patch(
        "routes.insights_routes.list_theses",
        return_value=[],
    ) as mock_list:
        resp = client.get("/api/ticker/nvda/insights")
    assert resp.status_code == 200
    assert resp.get_json()["ticker"] == "NVDA"
    mock_list.assert_called_once()
    assert mock_list.call_args.kwargs["ticker"] == "NVDA"


@skip_without_plotly
def test_delete_insight_admin_only(client, auth_ok):
    from user_insights_service import ThesisPermissionError

    client.set_cookie("auth_token", "test.jwt.token")
    with patch("routes.insights_routes.PostgresClient", return_value=MagicMock()), patch(
        "routes.insights_routes.is_admin",
        return_value=False,
    ), patch(
        "routes.insights_routes.hard_delete_thesis",
        side_effect=ThesisPermissionError("admin only"),
    ):
        resp = client.delete("/api/insights/00000000-0000-0000-0000-000000000001")
    assert resp.status_code == 403
