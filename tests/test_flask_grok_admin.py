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


def _assert_page_explains_itself(html: str) -> None:
    """Viewer-facing copy that must stay on /grok/admin (glossary tips + cost)."""
    assert "data-tooltip-target=" in html
    assert "fa-circle-question" in html
    assert "Stocks here are not searched, which saves money" in html
    assert "An auto row means a search found nothing." in html
    assert "Each sweep covers at most five stocks and spends X credits" in html
    assert "docs/GROK_BOT_RESEARCH.md" in html
    assert "grok_x_briefs" in html
    assert "Health numbers are counted from grok_x_briefs" in html
    assert "weekday sweep" in html
    assert "|safe" not in html


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
    _assert_page_explains_itself(html)
    assert "What does Ingested mean?" in html
    assert "What does Notable mean?" in html
    assert "What does Sweep mean?" in html
    assert "What does X brief mean?" in html
    assert "What does Auto skip mean?" in html
    assert "Saved, but nothing has read it yet." in html


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
    _assert_page_explains_itself(html)


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


@skip_without_plotly
def test_page_post_url_safety_filters_dangerous_schemes_and_hosts(client) -> None:
    today = datetime.now(UTC).date().isoformat()
    hostile_brief = {
        "id": "row-hostile",
        "fund": "TEST",
        "ticker": "EVIL",
        "sweep_date": today,
        "body": "Hostile brief content test.",
        "themes": ["exploit attempt"],
        "posts": [
            {"url": "javascript:alert('xss')", "summary": "Dangerous scheme"},
            {"url": "https://x.com.evil.example/status/123", "summary": "Lookalike host"},
            {"url": "https://evil.example/x.com", "summary": "Path lookalike"},
            {"url": "data:text/html,<script>alert(1)</script>", "summary": "Data URI"},
            {"url": "http://x.com/insecure", "summary": "Insecure HTTP"},
            {"url": "https://x.com/legit_user/status/456", "summary": "Legitimate X link"},
            {"url": "https://twitter.com/legit_user/status/789", "summary": "Legitimate Twitter link"},
        ],
        "notable": False,
        "cited_urls": [],
        "status": "ingested",
        "created_at": "2026-09-11T14:00:00+00:00",
        "updated_at": "2026-09-11T14:00:00+00:00",
    }

    pg = MagicMock()
    pg.execute_query.side_effect = [
        [hostile_brief],  # recent briefs
        [{"total": 1, "last_sweep": today}],  # activity totals
        [{"tickers": 1, "notable": 0}],  # last-sweep day stats
        [],  # skip list
    ]
    verify, access_token = _auth_patches()
    with verify, access_token, patch("routes.grok_admin_routes.PostgresClient", return_value=pg):
        client.set_cookie("auth_token", "test.token.value")
        resp = client.get("/grok/admin")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # 1. javascript: url renders as text and NOT as an href
    assert "href=\"javascript:" not in html
    assert "href='javascript:" not in html
    assert "javascript:alert(&#39;xss&#39;)" in html or "javascript:alert('xss')" in html

    # 2. Look-alike hosts do NOT become links (rendered as plain text + unverified marker)
    assert "href=\"https://x.com.evil.example" not in html
    assert "href='https://x.com.evil.example" not in html
    assert "href=\"https://evil.example" not in html
    assert "href='https://evil.example" not in html
    assert "x.com.evil.example/status/123" in html
    assert "evil.example/x.com" in html

    # Unverified link marker is shown for unsafe URLs
    assert "unverified link" in html

    # 3. Genuine https://x.com/... and https://twitter.com/... DO become links
    assert 'href="https://x.com/legit_user/status/456"' in html
    assert 'href="https://twitter.com/legit_user/status/789"' in html
    assert 'target="_blank"' in html
    assert 'rel="noopener noreferrer"' in html


@skip_without_plotly
def test_page_status_chips_use_matching_glossary_keys(client) -> None:
    today = datetime.now(UTC).date().isoformat()
    evaluated = _brief_row("BBB", notable=False)
    evaluated["id"] = "row-2"
    evaluated["status"] = "evaluated"
    evaluated["body"] = "Quiet tape."
    ignored = _brief_row("CCC", notable=False)
    ignored["id"] = "row-3"
    ignored["status"] = "ignored"
    ignored["body"] = "Noise only."
    pg = MagicMock()
    pg.execute_query.side_effect = [
        [evaluated, ignored],
        [{"total": 2, "last_sweep": today}],
        [{"tickers": 2, "notable": 0}],
        [_skip_row("QQQ", source="manual")],
    ]
    verify, access_token = _auth_patches()
    with verify, access_token, patch("routes.grok_admin_routes.PostgresClient", return_value=pg):
        client.set_cookie("auth_token", "test.token.value")
        resp = client.get("/grok/admin")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "What does Evaluated mean?" in html
    assert "What does Ignored mean?" in html
    assert "What does Manual skip mean?" in html
    assert "An AI review has already read this brief" in html
    assert "Marked as not worth acting on." in html
    assert "Quiet tape." in html
    assert "Noise only." in html


def test_is_safe_post_url_validation() -> None:
    from routes.grok_admin_routes import is_safe_post_url

    # Allowed genuine domains with https
    assert is_safe_post_url("https://x.com/user/status/1") == "https://x.com/user/status/1"
    assert is_safe_post_url("https://www.x.com/user/status/2") == "https://www.x.com/user/status/2"
    assert is_safe_post_url("https://twitter.com/user/status/3") == "https://twitter.com/user/status/3"
    assert is_safe_post_url("https://www.twitter.com/user/status/4") == "https://www.twitter.com/user/status/4"
    assert is_safe_post_url("https://mobile.twitter.com/user/status/5") == "https://mobile.twitter.com/user/status/5"
    assert is_safe_post_url("HTTPS://X.COM/status/6") == "HTTPS://X.COM/status/6"

    # Dangerous schemes
    assert is_safe_post_url("javascript:alert(1)") is None
    assert is_safe_post_url("data:text/html,<script>alert(1)</script>") is None
    assert is_safe_post_url("http://x.com/user/status/1") is None
    assert is_safe_post_url("file:///etc/passwd") is None
    assert is_safe_post_url("//x.com/status/1") is None

    # Lookalike hosts
    assert is_safe_post_url("https://x.com.evil.example/") is None
    assert is_safe_post_url("https://evil.example/x.com") is None
    assert is_safe_post_url("https://notx.com/status") is None
    assert is_safe_post_url("https://faketwitter.com/status") is None
    assert is_safe_post_url("https://x.com@evil.example/") is None

    # Invalid / None / empty
    assert is_safe_post_url(None) is None
    assert is_safe_post_url("") is None
    assert is_safe_post_url(123) is None  # type: ignore[arg-type]

