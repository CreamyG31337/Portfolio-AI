"""Flask routes for per-ticker meta analysis (second-order synthesis)."""

from datetime import datetime, UTC
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
def test_meta_analysis_get_null(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    mock_pg = MagicMock()
    mock_pg.execute_query.return_value = []

    with patch("postgres_client.PostgresClient", return_value=mock_pg), patch(
        "supabase_client.SupabaseClient"
    ):
        resp = client.get("/api/v2/ticker/TEST/meta-analysis")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("meta") is None


@skip_without_plotly
def test_meta_analysis_get_serializes_row(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    row = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "ticker": "TEST",
        "unified_conviction": "NEUTRAL",
        "confidence_adjusted": 0.55,
        "contradictions": ["a vs b"],
        "what_changed_vs_last_run": "N/A",
        "action_items": ["verify filings"],
        "narrative": "Synthesis text.",
        "full_result": {"unified_conviction": "NEUTRAL"},
        "model_used": "granite3.3:8b",
        "requested_by": None,
        "created_at": datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 4, 1, 13, 0, tzinfo=UTC),
        "source_analysis_id": "660e8400-e29b-41d4-a716-446655440001",
        "source_analysis_snapshot_at": datetime(2026, 4, 1, 11, 0, tzinfo=UTC),
    }
    mock_pg = MagicMock()
    mock_pg.execute_query.return_value = [row]

    with patch("postgres_client.PostgresClient", return_value=mock_pg), patch(
        "supabase_client.SupabaseClient"
    ):
        resp = client.get("/api/v2/ticker/TEST/meta-analysis")

    assert resp.status_code == 200
    data = resp.get_json()
    meta = data["meta"]
    assert meta["unified_conviction"] == "NEUTRAL"
    assert "T13:00:00" in meta["updated_at"] or "13:00:00" in meta["updated_at"]


@skip_without_plotly
@patch("flask_wtf.csrf.validate_csrf", return_value=True)
def test_meta_analysis_rebuild_ok(mock_csrf, client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    saved = {
        "unified_conviction": "BULLISH",
        "confidence_adjusted": 0.7,
        "contradictions": [],
        "what_changed_vs_last_run": "N/A",
        "action_items": [],
        "narrative": "ok",
        "updated_at": datetime(2026, 4, 1, 14, 0, tzinfo=UTC),
        "model_used": "granite3.3:8b",
    }

    mock_ollama = MagicMock()

    with patch("postgres_client.PostgresClient"), patch(
        "supabase_client.SupabaseClient"
    ), patch("ollama_client.get_ollama_client", return_value=mock_ollama), patch(
        "meta_analysis_service.TickerMetaAnalysisService.run_meta_analysis",
        return_value=saved,
    ):
        resp = client.post(
            "/api/v2/ticker/ZZZ/meta-analysis/rebuild",
            json={},
            content_type="application/json",
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get("status") == "completed"
    assert body["meta"]["unified_conviction"] == "BULLISH"
