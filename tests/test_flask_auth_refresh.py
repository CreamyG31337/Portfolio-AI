"""Tests for idempotent Supabase token refresh and centralized cookie persistence.

Supabase refresh tokens are single-use: exchanging one revokes it and issues a new
one. Reusing the old token more than the reuse interval (~10s) after the exchange
revokes the entire session family and logs the user out everywhere. These tests
cover the two defenses:

1. flask_auth_utils caches refresh results per old token so concurrent/late
   requests carrying a stale refresh_token get the already-issued tokens instead
   of replaying the exchange against Supabase.
2. The app-level persist_refreshed_tokens after_request hook sets cookies on every
   response where a refresh happened, regardless of which code path performed it.
"""

import base64
import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest


def _make_jwt(payload: dict) -> str:
    """Build an unsigned JWT-shaped token for parsing-only code paths."""
    def b64(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip('=')
    return f"{b64({'alg': 'HS256', 'typ': 'JWT'})}.{b64(payload)}.signature"


def _supabase_ok_response(access_token: str, refresh_token: str, expires_in: int = 3600) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
    }
    return response


SUPABASE_ENV = {
    "SUPABASE_URL": "https://test-project.supabase.co",
    "SUPABASE_ANON_KEY": "test-anon-key",
}


@pytest.fixture(autouse=True)
def _clear_refresh_state():
    """Reset module-level refresh cache/locks between tests."""
    import flask_auth_utils as fau
    fau._recent_refreshes.clear()
    fau._refresh_locks.clear()
    yield
    fau._recent_refreshes.clear()
    fau._refresh_locks.clear()


class TestRefreshWithCache:
    def test_second_call_with_same_token_uses_cache(self):
        """Two requests carrying the same (already exchanged) refresh token must
        result in exactly ONE network call; the second gets the cached tokens."""
        import flask_auth_utils as fau

        new_jwt = _make_jwt({"sub": "u1", "aud": "authenticated", "exp": int(time.time()) + 3600})
        with patch.dict(os.environ, SUPABASE_ENV), \
             patch("requests.post", return_value=_supabase_ok_response(new_jwt, "RT2")) as mock_post:
            first = fau._refresh_with_cache("RT1")
            second = fau._refresh_with_cache("RT1")

        assert mock_post.call_count == 1
        assert first == (True, new_jwt, "RT2", 3600)
        assert second == first

    def test_cache_expires_after_ttl(self):
        """A refresh token reused after the grace period triggers a real exchange."""
        import flask_auth_utils as fau

        new_jwt = _make_jwt({"sub": "u1", "aud": "authenticated", "exp": int(time.time()) + 3600})
        # Simulate a cache entry older than the TTL
        fau._recent_refreshes["RT1"] = (
            time.time() - fau._REFRESH_CACHE_TTL - 1, "stale-token", "RT-stale", 3600
        )
        with patch.dict(os.environ, SUPABASE_ENV), \
             patch("requests.post", return_value=_supabase_ok_response(new_jwt, "RT2")) as mock_post:
            result = fau._refresh_with_cache("RT1")

        assert mock_post.call_count == 1
        assert result == (True, new_jwt, "RT2", 3600)

    def test_failed_refresh_is_not_cached(self):
        """Failures must not be served from cache; each attempt hits Supabase."""
        import flask_auth_utils as fau

        error_response = MagicMock()
        error_response.status_code = 400
        error_response.json.return_value = {"error_code": "refresh_token_already_used"}
        error_response.text = "already used"
        with patch.dict(os.environ, SUPABASE_ENV), \
             patch("requests.post", return_value=error_response) as mock_post:
            first = fau._refresh_with_cache("RT1")
            second = fau._refresh_with_cache("RT1")

        assert mock_post.call_count == 2
        assert first == (False, None, None, None)
        assert second == (False, None, None, None)

    def test_lock_survives_successful_refresh(self):
        """The per-token lock must not be deleted on success: deleting it allowed a
        late request to create a fresh lock and replay the exchange concurrently."""
        import flask_auth_utils as fau

        new_jwt = _make_jwt({"sub": "u1", "aud": "authenticated", "exp": int(time.time()) + 3600})
        with patch.dict(os.environ, SUPABASE_ENV), \
             patch("requests.post", return_value=_supabase_ok_response(new_jwt, "RT2")):
            fau._refresh_with_cache("RT1")

        assert "RT1" in fau._refresh_locks
        assert "RT1" in fau._recent_refreshes

    def test_nonblocking_skips_when_lock_held(self):
        """Proactive refresh must skip (not fail) when another request holds the lock."""
        import flask_auth_utils as fau

        lock = fau._get_refresh_lock("RT1")
        lock.acquire()
        try:
            with patch("requests.post") as mock_post:
                result = fau._refresh_with_cache("RT1", blocking=False)
        finally:
            lock.release()

        assert result == (True, None, None, None)
        mock_post.assert_not_called()


class TestPersistRefreshedTokensHook:
    def test_hook_sets_cookies_when_tokens_stashed(self, app):
        from web_dashboard.app import persist_refreshed_tokens
        from flask import Response, request

        with app.test_request_context('/'):
            request._new_auth_token = "new.access.token"
            request._new_refresh_token = "new-refresh-token"
            request._token_expires_in = 1800
            response = persist_refreshed_tokens(Response("ok"))

        cookies = response.headers.getlist('Set-Cookie')
        auth_cookie = next((c for c in cookies if c.startswith('auth_token=')), None)
        refresh_cookie = next((c for c in cookies if c.startswith('refresh_token=')), None)
        assert auth_cookie is not None and "new.access.token" in auth_cookie
        assert "Max-Age=1800" in auth_cookie
        assert "HttpOnly" in auth_cookie
        assert refresh_cookie is not None and "new-refresh-token" in refresh_cookie

    def test_hook_noop_without_refresh(self, app):
        from web_dashboard.app import persist_refreshed_tokens
        from flask import Response

        with app.test_request_context('/'):
            response = persist_refreshed_tokens(Response("ok"))

        assert not response.headers.getlist('Set-Cookie')

    def test_index_route_persists_cookies_after_refresh(self, client):
        """End-to-end: expired auth_token + valid refresh_token on '/' must produce
        Set-Cookie headers with the refreshed tokens (via the after_request hook)."""
        expired_jwt = _make_jwt({
            "sub": "u1", "email": "t@example.com",
            "aud": "authenticated", "exp": int(time.time()) - 100,
        })
        new_jwt = _make_jwt({
            "sub": "u1", "email": "t@example.com",
            "aud": "authenticated", "exp": int(time.time()) + 3600,
        })
        client.set_cookie('auth_token', expired_jwt)
        client.set_cookie('refresh_token', 'RT1')

        with patch.dict(os.environ, SUPABASE_ENV), \
             patch("requests.post", return_value=_supabase_ok_response(new_jwt, "RT2")):
            response = client.get('/')

        cookies = response.headers.getlist('Set-Cookie')
        auth_cookie = next((c for c in cookies if c.startswith('auth_token=')), None)
        refresh_cookie = next((c for c in cookies if c.startswith('refresh_token=')), None)
        assert auth_cookie is not None and new_jwt in auth_cookie
        assert refresh_cookie is not None and "RT2" in refresh_cookie
