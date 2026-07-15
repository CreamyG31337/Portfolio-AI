"""Flask watchlist CRUD routes."""

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
    reason="plotly required to import web_dashboard.app",
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
def test_watchlist_list_api(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    rows = [
        {
            "fund": "Project Chimera",
            "ticker": "CRM",
            "priority_tier": "B",
            "is_active": True,
            "source": "bulk_paste",
        }
    ]
    enriched = [
        {
            **rows[0],
            "analyzed": True,
            "analysis_date": "2026-07-10",
            "dossier_url": "/ticker?ticker=CRM",
            "queue_status": None,
        }
    ]
    with patch(
        "routes.intelligence_routes.get_available_funds_flask",
        return_value=["Project Chimera", "TEST"],
    ), patch(
        "supabase_client.SupabaseClient",
        return_value=MagicMock(),
    ), patch(
        "routes.intelligence_routes.PostgresClient",
        return_value=MagicMock(),
    ), patch(
        "watchlist_access.list_watchlist_for_fund",
        return_value=rows,
    ), patch(
        "watchlist_access.enrich_watchlist_rows",
        return_value=enriched,
    ):
        resp = client.get("/api/watchlist?fund=Project%20Chimera")
    assert resp.status_code == 200
    data = resp.get_json()["data"][0]
    assert data["ticker"] == "CRM"
    assert data["analyzed"] is True
    assert data["dossier_url"] == "/ticker?ticker=CRM"


@skip_without_plotly
def test_watchlist_list_forbidden_fund(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    with patch(
        "routes.intelligence_routes.get_available_funds_flask",
        return_value=["TEST"],
    ):
        resp = client.get("/api/watchlist?fund=Project%20Chimera")
    assert resp.status_code == 403


@skip_without_plotly
def test_watchlist_add_api(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    with patch(
        "routes.intelligence_routes.get_available_funds_flask",
        return_value=["Project Chimera"],
    ), patch(
        "supabase_client.SupabaseClient",
        return_value=MagicMock(),
    ), patch(
        "watchlist_access.upsert_watchlist_tickers_bulk",
        return_value={
            "ok": True,
            "results": {"CRM": "added", "NOW": "added"},
            "failed_tickers": [],
            "added_count": 2,
        },
    ) as mock_bulk:
        resp = client.post(
            "/api/watchlist",
            json={
                "fund": "Project Chimera",
                "tickers": ["CRM", "NOW"],
                "priority_tier": "B",
                "source": "bulk_paste",
            },
        )
    assert resp.status_code == 200
    assert resp.get_json()["added_count"] == 2
    assert mock_bulk.call_args.kwargs["fund"] == "Project Chimera"


@skip_without_plotly
def test_watchlist_item_deactivate(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    with patch(
        "routes.intelligence_routes.get_available_funds_flask",
        return_value=["Project Chimera"],
    ), patch(
        "supabase_client.SupabaseClient",
        return_value=MagicMock(),
    ), patch(
        "watchlist_access.update_watchlist_item",
        return_value={"ok": True, "ticker": "IREN", "is_active": False},
    ):
        resp = client.patch(
            "/api/watchlist/item",
            json={"fund": "Project Chimera", "ticker": "IREN", "is_active": False},
        )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


@skip_without_plotly
def test_watchlist_analyze_api(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    with patch(
        "routes.intelligence_routes.get_available_funds_flask",
        return_value=["Project Chimera"],
    ), patch(
        "supabase_client.SupabaseClient",
        return_value=MagicMock(),
    ), patch(
        "watchlist_access.request_manual_ticker_analysis",
        return_value={
            "ok": True,
            "tickers": ["CRM", "NOW"],
            "enqueued": 2,
            "ticker_analysis": {"attempted": 2, "enqueued": 2, "failed": 0},
            "ticker_meta": {"attempted": 2, "enqueued": 2, "failed": 0},
            "legacy_queued": ["CRM", "NOW"],
        },
    ) as mock_req:
        resp = client.post(
            "/api/watchlist/analyze",
            json={
                "fund": "Project Chimera",
                "tickers": ["CRM", "NOW"],
                "include_meta": True,
            },
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["enqueued"] == 2
    assert mock_req.call_args.kwargs["include_meta"] is True


@skip_without_plotly
def test_watchlist_page_renders_fund_options(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    with patch(
        "app.get_navigation_context",
        return_value={
            "available_funds": ["Project Chimera", "TEST"],
            "selected_fund": "Project Chimera",
            "nav_links": [],
            "current_page": "watchlist",
            "is_admin": False,
            # Present in real nav context; page also passes allow_all_funds=False
            "allow_all_funds": True,
        },
    ), patch(
        "routes.intelligence_routes.get_effective_user_email_flask",
        return_value="user@example.com",
    ):
        resp = client.get("/watchlist")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'id="global-fund-select"' in html
    assert "Project Chimera" in html
    assert "TEST" in html
    assert "(No funds available)" not in html
    assert ">All Funds</option>" not in html


@skip_without_plotly
def test_ideas_triage_accept_uses_upsert_helper(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    with patch(
        "routes.intelligence_routes.get_available_funds_flask",
        return_value=["Project Chimera"],
    ), patch(
        "routes.intelligence_routes.PostgresClient",
    ) as mock_pg, patch(
        "supabase_client.SupabaseClient",
        return_value=MagicMock(),
    ), patch(
        "watchlist_access.upsert_watchlist_ticker",
        return_value={"ok": True, "ticker": "CELH"},
    ) as mock_upsert:
        mock_pg.return_value.execute_update.return_value = None
        resp = client.post(
            "/api/ideas/triage",
            json={
                "article_id": "00000000-0000-0000-0000-000000000001",
                "status": "accepted",
                "fund": "Project Chimera",
                "tickers": ["CELH"],
            },
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["watchlist_results"]["CELH"] == "added"
    mock_upsert.assert_called_once()
    assert mock_upsert.call_args.kwargs["source"] == "ideas_inbox"
