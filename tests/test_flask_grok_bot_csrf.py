"""Tests verifying CSRF exemption for Grok Bot endpoints and enforcement on non-exempt routes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

TOKEN = "test-grok-bot-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


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


@skip_without_plotly
def test_grok_briefs_post_exempt_from_csrf(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """With CSRF enabled, POST /api/grok/briefs without a CSRF token succeeds."""
    monkeypatch.setitem(client.application.config, "WTF_CSRF_ENABLED", True)
    monkeypatch.setenv("GROK_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("GROK_WATCHLIST_FUNDS", "TEST")

    stored = [
        {
            "id": str(uuid4()),
            "fund": "TEST",
            "ticker": "AAA",
            "sweep_date": "2026-09-09",
            "status": "ingested",
            "notable": False,
        }
    ]

    with patch("routes.grok_bot_routes.PostgresClient", return_value=MagicMock()), patch(
        "routes.grok_bot_routes.get_admin_supabase_client", return_value=MagicMock()
    ), patch(
        "routes.grok_bot_routes.watchlist_ticker_funds", return_value={"AAA": ["TEST"]}
    ), patch(
        "routes.grok_bot_routes.upsert_briefs", return_value=stored
    ):
        resp = client.post(
            "/api/grok/briefs",
            json={"ticker": "AAA", "body": "valid brief body", "notable": False},
            headers=AUTH,
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"][0]["ticker"] == "AAA"


@skip_without_plotly
def test_comparable_non_exempt_post_rejected_by_csrf(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """With CSRF enabled, a non-exempt POST endpoint without a CSRF token is rejected with 419."""
    monkeypatch.setitem(client.application.config, "WTF_CSRF_ENABLED", True)

    resp = client.post(
        "/api/settings/theme",
        json={"theme": "dark"},
    )

    assert resp.status_code == 419
    data = resp.get_json()
    assert data["error"] == "csrf_expired"


@skip_without_plotly
def test_grok_briefs_rejected_if_csrf_exemption_removed(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """If /api/grok/ is removed from CSRF_EXEMPT_PATHS, POST /api/grok/briefs is rejected with 419."""
    monkeypatch.setitem(client.application.config, "WTF_CSRF_ENABLED", True)
    monkeypatch.setenv("GROK_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("GROK_WATCHLIST_FUNDS", "TEST")

    import web_dashboard.app as app_module

    monkeypatch.setattr(app_module, "CSRF_EXEMPT_PATHS", ["/api/webhooks/"])

    resp = client.post(
        "/api/grok/briefs",
        json={"ticker": "AAA", "body": "valid brief body", "notable": False},
        headers=AUTH,
    )

    assert resp.status_code == 419
    data = resp.get_json()
    assert data["error"] == "csrf_expired"
