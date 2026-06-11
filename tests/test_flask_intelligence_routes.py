"""Flask: Today, Ideas, Track-record intelligence routes."""

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
def test_today_briefing_api(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    payload = {
        "market_regime": {"risk_regime": "NEUTRAL"},
        "stance_flips": [],
        "action_queue": [],
        "alpha_articles": [],
        "updated_at": "2026-06-10T00:00:00+00:00",
    }
    with patch(
        "routes.intelligence_routes.get_supabase_client_flask",
        return_value=MagicMock(),
    ), patch(
        "routes.intelligence_routes.build_today_briefing",
        return_value=payload,
    ):
        resp = client.get("/api/today/briefing")
    assert resp.status_code == 200
    assert resp.get_json()["market_regime"]["risk_regime"] == "NEUTRAL"


@skip_without_plotly
def test_track_record_summary_api(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    summary = {
        "horizon_days": 30,
        "total_scored": 0,
        "hit_rate_by_source": {},
        "hit_rate_by_verdict": {},
        "best_calls": [],
        "worst_calls": [],
    }
    with patch(
        "routes.intelligence_routes.build_track_record_summary",
        return_value=summary,
    ):
        resp = client.get("/api/track-record/summary")
    assert resp.status_code == 200
    assert resp.get_json()["horizon_days"] == 30


@skip_without_plotly
def test_ideas_triage_api(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    mock_pg = MagicMock()
    with patch("routes.intelligence_routes.PostgresClient", return_value=mock_pg), patch(
        "routes.intelligence_routes.get_supabase_client_flask",
        return_value=None,
    ):
        resp = client.post(
            "/api/ideas/triage",
            json={"article_id": "00000000-0000-0000-0000-000000000001", "status": "dismissed"},
        )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    mock_pg.execute_update.assert_called_once()
