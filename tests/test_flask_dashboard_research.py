"""Flask: market brief + enriched action queue API."""

from datetime import date, datetime, UTC
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
def test_market_brief_404_when_empty(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    mock_pg = MagicMock()
    mock_row_fn = MagicMock(return_value=None)
    with patch("postgres_client.PostgresClient", return_value=mock_pg), patch(
        "market_brief_service.fetch_latest_brief", mock_row_fn
    ):
        resp = client.get("/api/dashboard/market-brief")
    assert resp.status_code == 404


@skip_without_plotly
def test_market_brief_returns_json(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    row = {
        "brief_date": date(2026, 4, 1),
        "headline": "Stocks firm",
        "narrative": "Indices up on the day.",
        "regime_json": {"risk_tone": "NEUTRAL"},
        "inputs_digest": {"tickers": {}},
        "model_used": "test-model",
        "updated_at": datetime(2026, 4, 1, 20, 0, tzinfo=UTC),
    }
    with patch("postgres_client.PostgresClient"), patch(
        "market_brief_service.fetch_latest_brief", return_value=row
    ):
        resp = client.get("/api/dashboard/market-brief")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["headline"] == "Stocks firm"
    assert "2026-04-01" in (data.get("brief_date") or "")


@skip_without_plotly
def test_action_queue_enrich_merges_research_and_ai(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    mock_supabase = MagicMock()
    item = {
        "ticker": "ABC",
        "action": "BUY",
        "overall_signal": "BUY",
        "confidence": 0.8,
        "fear_level": "LOW",
        "trend": "UP",
        "priority_score": 90,
        "priority_tier": "A",
        "is_held": False,
        "analysis_date": "2026-04-01",
        "note": "test",
    }

    def _attach_rc(_pg, items):
        items[0]["research_context"] = {"analysis_stance": "BULLISH", "analysis_age_hours": 12.0}

    def _attach_ai(_pg, _fk, items):
        items[0]["ai_review"] = {
            "verdict": "ALIGNED",
            "one_liner": "ok",
            "updated_at": datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        }

    with patch(
        "routes.dashboard_routes.get_supabase_client_flask",
        return_value=mock_supabase,
    ), patch(
        "routes.dashboard_routes.build_action_queue_items",
        return_value=[item],
    ), patch(
        "routes.dashboard_routes.attach_research_context",
        side_effect=_attach_rc,
    ), patch(
        "routes.dashboard_routes.attach_ai_reviews",
        side_effect=_attach_ai,
    ):
        resp = client.get("/api/dashboard/action-queue?fund=TEST&limit=5")

    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["data"]) == 1
    row = data["data"][0]
    assert row["research_context"]["analysis_stance"] == "BULLISH"
    assert row["ai_review"]["verdict"] == "ALIGNED"
    assert "T" in (row["ai_review"]["updated_at"] or "")
