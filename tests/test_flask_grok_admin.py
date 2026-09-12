"""Flask tests for the Grok Bot admin page (briefs, health, skip list)."""

from __future__ import annotations

from datetime import UTC, datetime
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


def _brief_row(ticker: str = "AAA", *, notable: bool = True) -> dict:
    return {
        "id": "row-1",
        "fund": "TEST",
        "ticker": ticker,
        "sweep_date": "2026-09-11",
        "body": "Promoter thread claiming a financing.",
        "themes": ["financing rumor"],
        "posts": [{"url": "https://x.com/user/status/123", "post_id": "123", "summary": "Claims overnight raise"}],
        "notable": notable,
        "cited_urls": ["https://x.com/user/status/123"],
        "status": "ingested",
        "created_at": "2026-09-11T14:00:00+00:00",
        "updated_at": "2026-09-11T14:00:00+00:00",
    }


def _skip_row(ticker: str = "ZZZ", *, source: str = "manual") -> dict:
    return {
        "ticker": ticker,
        "reason": "ETF, nothing to learn on X",
        "source": source,
        "created_at": "2026-09-10T09:00:00+00:00",
        "updated_at": "2026-09-10T09:00:00+00:00",
    }


def _auth_patches():
    """require_auth passes: verified session + fake access token."""
    return (
        patch(
            "auth.auth_manager.verify_session",
            MagicMock(return_value={"user_id": "admin-user-id", "email": "admin@example.com"}),
        ),
        patch("flask_auth_utils.get_supabase_access_token", MagicMock(return_value="fake.jwt.token")),
    )


@skip_without_plotly
def test_page_requires_auth(client) -> None:
    resp = client.get("/grok/admin")
    assert resp.status_code == 302
    assert "/auth" in resp.headers["Location"]


@skip_without_plotly
def test_page_renders_briefs_summary_and_skips(client) -> None:
    today = datetime.now(UTC).date().isoformat()
    pg = MagicMock()
    pg.execute_query.side_effect = [
        [_brief_row("AAA", notable=True)],  # recent briefs
        [{"total": 7, "last_sweep": today}],  # activity totals
        [{"tickers": 5, "notable": 1}],  # last-sweep day stats
        [_skip_row("ZZZ", source="auto")],  # skip list
    ]
    verify, access_token = _auth_patches()
    with verify, access_token, patch("routes.grok_admin_routes.PostgresClient", return_value=pg):
        client.set_cookie("auth_token", "test.token.value")
        resp = client.get("/grok/admin")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "AAA" in html
    assert "financing rumor" in html
    assert "Promoter thread claiming a financing." in html
    assert "Swept today" in html
    assert "ZZZ" in html
    # post links are new-tab with noopener, never raw HTML
    assert 'rel="noopener noreferrer"' in html
    assert "<script>alert" not in html


@skip_without_plotly
def test_page_no_sweep_today_state(client) -> None:
    pg = MagicMock()
    pg.execute_query.side_effect = [
        [],  # no briefs
        [{"total": 0, "last_sweep": None}],  # never swept
        [],  # skip list (day-stats query skipped when last_sweep is None)
    ]
    verify, access_token = _auth_patches()
    with verify, access_token, patch("routes.grok_admin_routes.PostgresClient", return_value=pg):
        client.set_cookie("auth_token", "test.token.value")
        resp = client.get("/grok/admin")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "No sweeps yet" in html
    assert "No briefs ingested yet" in html


@skip_without_plotly
def test_add_skip_normalizes_ticker_and_writes_manual_row(client) -> None:
    pg = MagicMock()
    verify, access_token = _auth_patches()
    with verify, access_token, patch("routes.grok_admin_routes.PostgresClient", return_value=pg):
        client.set_cookie("auth_token", "test.token.value")
        resp = client.post("/grok/admin/skips", json={"ticker": "aaa", "reason": "too noisy"})
    assert resp.status_code == 200
    assert resp.get_json() == {"success": True, "ticker": "AAA"}
    sql, params = pg.execute_update.call_args.args
    assert "INSERT INTO grok_x_skips" in sql
    assert "'manual'" in sql
    assert params == ("AAA", "too noisy")


@skip_without_plotly
def test_add_skip_rejects_blank_ticker(client) -> None:
    pg = MagicMock()
    verify, access_token = _auth_patches()
    with verify, access_token, patch("routes.grok_admin_routes.PostgresClient", return_value=pg):
        client.set_cookie("auth_token", "test.token.value")
        resp = client.post("/grok/admin/skips", json={"ticker": "  ", "reason": "x"})
    assert resp.status_code == 400
    assert "ticker" in resp.get_json()["error"]
    pg.execute_update.assert_not_called()


@skip_without_plotly
def test_remove_skip_deletes_row(client) -> None:
    pg = MagicMock()
    verify, access_token = _auth_patches()
    with verify, access_token, patch("routes.grok_admin_routes.PostgresClient", return_value=pg):
        client.set_cookie("auth_token", "test.token.value")
        resp = client.post("/grok/admin/skips/remove", json={"ticker": "ZZZ"})
    assert resp.status_code == 200
    assert resp.get_json() == {"success": True, "ticker": "ZZZ"}
    sql, params = pg.execute_update.call_args.args
    assert "DELETE FROM grok_x_skips" in sql
    assert "WHERE ticker = %s" in sql
    assert params == ("ZZZ",)
