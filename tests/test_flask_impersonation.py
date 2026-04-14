"""Tests for admin view-as-user (Flask session impersonation)."""

import pytest
from unittest.mock import patch

ADMIN_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
TARGET_UUID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def _authenticated_admin_mocks():
    """Patches for @require_auth + stable admin user id from JWT helpers."""
    with patch(
        "auth.auth_manager.verify_session",
        return_value={"user_id": ADMIN_UUID, "email": "admin@test.com"},
    ), patch("flask_auth_utils.get_user_id_flask", return_value=ADMIN_UUID):
        yield


def test_impersonate_start_forbidden_when_not_full_admin(client, _authenticated_admin_mocks):
    with patch("flask_auth_utils.can_modify_data_flask", return_value=False):
        client.set_cookie("auth_token", "test.token.value")
        response = client.post(
            "/api/admin/impersonate/start",
            json={"user_id": TARGET_UUID},
        )
    assert response.status_code == 403


def test_impersonate_start_success(client, _authenticated_admin_mocks):
    with patch("flask_auth_utils.can_modify_data_flask", return_value=True), patch(
        "routes.admin_routes._get_cached_users_flask",
        return_value=[{"user_id": TARGET_UUID, "email": "target@test.com"}],
    ):
        client.set_cookie("auth_token", "test.token.value")
        response = client.post(
            "/api/admin/impersonate/start",
            json={"user_id": TARGET_UUID},
        )
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert data.get("success") is True
    assert data.get("impersonate_user_id") == TARGET_UUID


def test_impersonate_start_rejects_self(client, _authenticated_admin_mocks):
    with patch("flask_auth_utils.can_modify_data_flask", return_value=True):
        client.set_cookie("auth_token", "test.token.value")
        response = client.post(
            "/api/admin/impersonate/start",
            json={"user_id": ADMIN_UUID},
        )
    assert response.status_code == 400


def test_impersonate_stop_clears_session(client, _authenticated_admin_mocks):
    from flask_auth_utils import SESSION_IMPERSONATE_USER_ID, SESSION_IMPERSONATE_USER_EMAIL

    client.set_cookie("auth_token", "test.token.value")
    with client.session_transaction() as sess:
        sess[SESSION_IMPERSONATE_USER_ID] = TARGET_UUID
        sess[SESSION_IMPERSONATE_USER_EMAIL] = "target@test.com"

    response = client.post("/api/admin/impersonate/stop")
    assert response.status_code == 200

    with client.session_transaction() as sess:
        assert SESSION_IMPERSONATE_USER_ID not in sess
        assert SESSION_IMPERSONATE_USER_EMAIL not in sess


def test_set_user_preference_blocked_while_impersonating(app):
    with app.test_request_context("/"):
        with patch(
            "auth.auth_manager.verify_session",
            return_value={"user_id": ADMIN_UUID, "email": "admin@test.com"},
        ), patch("flask_auth_utils.get_user_id_flask", return_value=ADMIN_UUID), patch(
            "flask_auth_utils.is_impersonating_flask", return_value=True
        ), patch("user_preferences._is_authenticated", return_value=True):
            from user_preferences import set_user_preference

            assert set_user_preference("theme", "dark") is False


def test_get_effective_user_id_when_session_set(app):
    from flask import session
    from flask_auth_utils import SESSION_IMPERSONATE_USER_ID, get_effective_user_id_flask

    with app.test_request_context("/"):
        with patch("flask_auth_utils.get_user_id_flask", return_value=ADMIN_UUID), patch(
            "flask_auth_utils.can_modify_data_flask", return_value=True
        ):
            session[SESSION_IMPERSONATE_USER_ID] = TARGET_UUID
            session.modified = True
            assert get_effective_user_id_flask() == TARGET_UUID
