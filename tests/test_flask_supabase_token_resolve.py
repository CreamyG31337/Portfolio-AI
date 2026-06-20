"""Supabase JWT resolution for RLS-backed Flask data queries."""

from __future__ import annotations

import base64
import json
import time
from unittest.mock import patch

import pytest


def _fake_supabase_jwt(exp_offset_seconds: int = 3600) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {
                "aud": "authenticated",
                "iss": "https://example.supabase.co/auth/v1",
                "exp": int(time.time()) + exp_offset_seconds,
            }
        ).encode()
    ).decode().rstrip("=")
    return f"{header}.{payload}.signature"


def test_resolve_prefers_fresh_refresh_token(app):
    from flask import request
    from flask_auth_utils import resolve_supabase_access_token_for_rls

    fresh = _fake_supabase_jwt()
    expired = _fake_supabase_jwt(exp_offset_seconds=-60)
    with app.test_request_context("/"):
        request._new_auth_token = fresh
        with patch.dict("os.environ", {"SUPABASE_URL": "https://example.supabase.co"}):
            assert resolve_supabase_access_token_for_rls() == fresh

            request._new_auth_token = None
            # Simulate expired auth_token cookie only
            with patch.object(request, "cookies", {"auth_token": expired}):
                assert resolve_supabase_access_token_for_rls() is None


def test_resolve_accepts_session_token_when_supabase_jwt(app):
    from flask_auth_utils import resolve_supabase_access_token_for_rls

    token = _fake_supabase_jwt()
    with app.test_request_context("/"):
        with patch.dict("os.environ", {"SUPABASE_URL": "https://example.supabase.co"}):
            with patch(
                "flask_auth_utils.request.cookies",
                {"session_token": token},
            ):
                assert resolve_supabase_access_token_for_rls() == token
