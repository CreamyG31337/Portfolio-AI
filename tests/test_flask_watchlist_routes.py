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
    assert body["funds"] == ["Project Chimera"]
    assert body["watchlist_by_fund"]["Project Chimera"]["CELH"] == "added"
    assert "analysis_enqueue" not in body
    mock_upsert.assert_called_once()
    assert mock_upsert.call_args.kwargs["source"] == "ideas_inbox"


@skip_without_plotly
def test_ideas_triage_accept_multiple_funds(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    with patch(
        "routes.intelligence_routes.get_available_funds_flask",
        return_value=["Project Chimera", "RRSP", "TFSA"],
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
                "article_id": "00000000-0000-0000-0000-000000000099",
                "status": "accepted",
                "funds": ["Project Chimera", "RRSP"],
                "tickers": ["CELH"],
            },
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["funds"] == ["Project Chimera", "RRSP"]
    assert mock_upsert.call_count == 2
    funds_called = {c.kwargs["fund"] for c in mock_upsert.call_args_list}
    assert funds_called == {"Project Chimera", "RRSP"}


@skip_without_plotly
def test_ideas_triage_accept_requires_fund_when_tickers(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    with patch(
        "routes.intelligence_routes.PostgresClient",
    ) as mock_pg:
        mock_pg.return_value.execute_update.return_value = None
        resp = client.post(
            "/api/ideas/triage",
            json={
                "article_id": "00000000-0000-0000-0000-000000000098",
                "status": "accepted",
                "tickers": ["CELH"],
            },
        )
    assert resp.status_code == 400
    assert "fund" in resp.get_json()["error"].lower()
    mock_pg.return_value.execute_update.assert_not_called()


@skip_without_plotly
def test_ideas_triage_accept_can_queue_analysis(client, auth_ok):
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
    ), patch(
        "watchlist_access.request_manual_ticker_analysis",
        return_value={"ok": True, "enqueued": 1, "tickers": ["CELH"]},
    ) as mock_analyze:
        mock_pg.return_value.execute_update.return_value = None
        resp = client.post(
            "/api/ideas/triage",
            json={
                "article_id": "00000000-0000-0000-0000-000000000002",
                "status": "accepted",
                "fund": "Project Chimera",
                "tickers": ["CELH"],
                "queue_analysis": True,
            },
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["analysis_enqueue"]["enqueued"] == 1
    mock_analyze.assert_called_once()
    assert mock_analyze.call_args.args[1] == ["CELH"]
    assert mock_analyze.call_args.kwargs["enqueued_by"] == "ideas_accept"
