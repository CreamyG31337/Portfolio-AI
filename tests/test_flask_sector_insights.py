"""Flask: Phase 3 preview sector_insights page (ETF Analysis read-only list)."""

from datetime import datetime, UTC
from unittest.mock import MagicMock, patch

import pytest


def test_shared_navigation_includes_sector_insights():
    """Sector insights must be listed for Flask/Streamlit shared nav (sidebar source of truth)."""
    from shared_navigation import get_navigation_links

    pages = [link["page"] for link in get_navigation_links()]
    assert "sector_insights" in pages


def test_ensure_flask_sidebar_navigation_links_restores_sector_if_stripped():
    from shared_navigation import ensure_flask_sidebar_navigation_links, get_navigation_links

    stripped = [dict(x) for x in get_navigation_links() if x["page"] != "sector_insights"]
    assert "sector_insights" not in {x["page"] for x in stripped}
    fixed = ensure_flask_sidebar_navigation_links(stripped)
    pages = [x["page"] for x in fixed]
    assert "sector_insights" in pages
    etf_i = pages.index("etf_holdings")
    assert pages.index("sector_insights") == etf_i + 1


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
    uid = "550e8400-e29b-41d4-a716-446655440000"
    with patch(
        "auth.auth_manager.verify_session",
        return_value={"user_id": uid, "email": "user@example.com"},
    ), patch(
        "flask_auth_utils.refresh_token_if_needed_flask",
        return_value=(True, None, None, None),
    ), patch("flask_auth_utils.get_user_id_flask", return_value=uid), patch(
        "flask_auth_utils.get_user_email_flask", return_value="user@example.com"
    ):
        yield


@skip_without_plotly
def test_sector_insights_lists_etf_analysis_rows(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    mock_article = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "title": "ARKK Holdings Analysis - 2026-05-01",
        "summary": "Test summary for rotation context.",
        "tickers": ["TSLA", "COIN"],
        "sentiment": "NEUTRAL",
        "source": "ETF AI Analysis",
        "published_at": datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        "fetched_at": datetime(2026, 5, 1, 18, 0, tzinfo=UTC),
    }
    with patch(
        "routes.etf_routes.ResearchRepository",
        return_value=MagicMock(
            get_recent_articles=MagicMock(return_value=[mock_article]),
        ),
    ):
        resp = client.get("/sector_insights")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Phase 3 stepping stone" in body
    assert "ARKK Holdings Analysis" in body
    assert "Test summary for rotation context." in body


@skip_without_plotly
def test_sector_insights_empty_state(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    with patch(
        "routes.etf_routes.ResearchRepository",
        return_value=MagicMock(get_recent_articles=MagicMock(return_value=[])),
    ):
        resp = client.get("/sector_insights")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "No ETF Analysis articles" in body


@skip_without_plotly
def test_sector_insights_requires_auth(client):
    resp = client.get("/sector_insights")
    assert resp.status_code == 302
    assert "/auth" in resp.headers.get("Location", "")
