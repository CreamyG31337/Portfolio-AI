"""Flask: stance-flips API."""

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
def test_stance_flips_returns_json(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    mock_pg = MagicMock()
    mock_pg.execute_query.return_value = [
        {
            "ticker": "ABC",
            "source": "ticker_meta_analysis",
            "fund_key": "",
            "from_stance": "NEUTRAL",
            "to_stance": "BULLISH",
            "flipped_at": datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            "confidence": 0.75,
            "model_used": "test-model",
            "metadata": {"contradictions_count": 0},
        }
    ]
    with patch("postgres_client.PostgresClient", return_value=mock_pg):
        resp = client.get("/api/dashboard/stance-flips?days=7&limit=10")

    assert resp.status_code == 200
    body = resp.get_json()
    assert "data" in body
    assert len(body["data"]) == 1
    row = body["data"][0]
    assert row["ticker"] == "ABC"
    assert row["from_stance"] == "NEUTRAL"
    assert row["to_stance"] == "BULLISH"
    assert row["confidence"] == 0.75
    assert "updated_at" in body
