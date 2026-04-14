"""Tests for portfolio digest math, tokens, admin preview, and Mailgun client."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

ADMIN_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
TARGET_UUID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def _admin_session_mocks():
    with patch(
        "auth.auth_manager.verify_session",
        return_value={"user_id": ADMIN_UUID, "email": "admin@test.com"},
    ), patch("flask_auth_utils.get_user_id_flask", return_value=ADMIN_UUID), patch(
        "auth.auth_manager.is_admin", return_value=True
    ):
        yield


def test_compute_core_summary_metrics_basic():
    from portfolio_summary_math import compute_core_summary_metrics

    df = pd.DataFrame(
        {
            "currency": ["CAD", "USD"],
            "market_value": [1000.0, 500.0],
            "unrealized_pnl": [50.0, -10.0],
            "daily_pnl": [5.0, 1.0],
            "five_day_pnl": [20.0, 2.0],
        }
    )
    cash = {"CAD": 100.0}
    rates = {"USD": 1.35}
    s = compute_core_summary_metrics(df, cash, rates, "CAD")
    assert s["display_currency"] == "CAD"
    assert s["holdings_count"] == 2
    assert s["total_value"] > 0
    assert "five_day_change_pct" in s


def test_digest_view_token_roundtrip():
    os.environ["FLASK_SECRET_KEY"] = "test-secret-key-for-tokens"
    from digest_token import sign_digest_view_token, verify_digest_view_token

    t = sign_digest_view_token(TARGET_UUID, "issue-uuid-1")
    parsed = verify_digest_view_token(t)
    assert parsed is not None
    assert parsed["user_id"] == TARGET_UUID
    assert parsed["issue_id"] == "issue-uuid-1"


def test_preview_token_requires_admin_claim():
    os.environ["FLASK_SECRET_KEY"] = "test-secret-key-for-tokens"
    from digest_token import sign_preview_token, verify_preview_token

    t = sign_preview_token(TARGET_UUID, ADMIN_UUID)
    p = verify_preview_token(t, max_age_seconds=3600)
    assert p is not None
    assert p["user_id"] == TARGET_UUID
    assert p["admin_user_id"] == ADMIN_UUID


def test_admin_preview_forbidden_readonly(client, _admin_session_mocks):
    with patch("flask_auth_utils.can_modify_data_flask", return_value=False):
        client.set_cookie("auth_token", "test.token.value")
        response = client.post(
            "/api/admin/outbound-newsletter/preview",
            json={"user_id": TARGET_UUID},
        )
    assert response.status_code == 403


def test_admin_preview_success_mocked_builder(client, _admin_session_mocks):
    fake_payload = {
        "as_of": "2026-04-13",
        "week_label": "5 trading days",
        "summary": {"total_value": 1.0, "display_currency": "CAD"},
        "market_brief": None,
        "movers": {"gainers": [], "losers": []},
        "action_queue": [],
    }
    with patch("flask_auth_utils.can_modify_data_flask", return_value=True), patch(
        "routes.admin_routes._get_cached_users_flask",
        return_value=[{"user_id": TARGET_UUID, "email": "u@test.com"}],
    ), patch(
        "outbound_digest_builder.build_digest_payload",
        return_value=fake_payload,
    ):
        client.set_cookie("auth_token", "test.token.value")
        response = client.post(
            "/api/admin/outbound-newsletter/preview",
            json={"user_id": TARGET_UUID},
        )
    assert response.status_code == 200
    data = response.get_json()
    assert data.get("success") is True
    assert "email_html" in data
    assert "preview_digest_url" in data


def test_mailgun_send_requires_config():
    from mailgun_outbound import send_mailgun_message

    with patch.dict(
        os.environ,
        {"MAILGUN_API_KEY": "", "MAILGUN_SEND_DOMAIN": "", "MAILGUN_DOMAIN": ""},
        clear=False,
    ):
        with pytest.raises(ValueError):
            send_mailgun_message("a@b.com", "s", "<p>x</p>")


def test_mailgun_send_posts_multipart():
    from mailgun_outbound import send_mailgun_message

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "<test@mailgun>"}
    mock_resp.text = ""

    with patch.dict(
        os.environ,
        {
            "MAILGUN_API_KEY": "key",
            "MAILGUN_SEND_DOMAIN": "mg.example.com",
            "MAILGUN_FROM": "T <t@mg.example.com>",
        },
        clear=False,
    ), patch("mailgun_outbound.requests.post", return_value=mock_resp) as post:
        out = send_mailgun_message("u@example.com", "Subj", "<p>hi</p>", tags=["portfolio_digest"])
        assert out.get("id")
    post.assert_called_once()
    args, kwargs = post.call_args
    assert "mg.example.com" in args[0]
    assert kwargs.get("auth") == ("api", "key")


def test_render_digest_thin_email_without_flask_context(app):
    """Background jobs must render Jinja without an active app context (see scheduler)."""
    from flask import has_app_context

    from outbound_newsletter_pipeline import _render_digest_thin_email

    assert not has_app_context()
    html = _render_digest_thin_email(
        as_of="2026-01-01",
        week_label="5 trading days",
        digest_url="https://example.com/digest",
        dashboard_url="https://example.com/dashboard",
        manage_url="https://example.com/settings",
        market_brief=None,
        kpi_value_url=None,
        kpi_week_url=None,
    )
    assert "Portfolio digest" in html
    assert "2026-01-01" in html
