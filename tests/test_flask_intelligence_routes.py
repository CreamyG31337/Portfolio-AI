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
        "confluence_events": [{"ticker": "AAA", "direction": "bullish", "score": 3}],
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
    body = resp.get_json()
    assert body["market_regime"]["risk_regime"] == "NEUTRAL"
    assert body["confluence_events"][0]["ticker"] == "AAA"


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
def test_insider_cluster_buys_api(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    clusters = [{
        "ticker": "AAA", "insider_count": 3, "buy_count": 4,
        "total_value": 120000.0, "latest_buy": "2026-06-09",
        "insiders": [], "held": True, "watched": False,
    }]
    with patch(
        "routes.intelligence_routes.get_supabase_client_flask",
        return_value=MagicMock(),
    ), patch(
        "routes.intelligence_routes.build_insider_cluster_buys",
        return_value=clusters,
    ) as mock_build:
        resp = client.get("/api/insiders/cluster-buys?days=200&min_insiders=1")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"][0]["ticker"] == "AAA"
    # Query params are clamped to sane ranges before reaching the service.
    assert mock_build.call_args.kwargs["days"] == 90
    assert mock_build.call_args.kwargs["min_insiders"] == 2


@skip_without_plotly
def test_liquidity_panel_api(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    rows = [{
        "ticker": "AAA", "shares": 5000.0, "market_value": 25000.0,
        "avg_daily_volume": 10000.0, "pct_of_adv": 50.0,
        "days_to_exit": 5.0, "risk_bucket": "elevated",
    }]
    with patch(
        "flask_data_utils.get_current_positions_flask",
        return_value=MagicMock(),
    ), patch(
        "routes.intelligence_routes.build_liquidity_panel",
        return_value=rows,
    ):
        resp = client.get("/api/liquidity/panel?fund=TFSA")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"][0]["risk_bucket"] == "elevated"
    assert body["participation_rate"] == 0.1


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
