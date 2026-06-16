"""postgrest-py 2.x must use postgrest.auth(), not session.headers only."""

from __future__ import annotations

import sys
from pathlib import Path

_WEB_DASHBOARD = Path(__file__).resolve().parents[1] / "web_dashboard"
sys.path.insert(0, str(_WEB_DASHBOARD))

FAKE_USER_JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjo5OTk5OTk5OTk5fQ."
    "fake-signature"
)
ANON_KEY = "test-anon-publishable-key"


def _builder_auth_header(client) -> str:
    builder = client.supabase.postgrest.table("performance_metrics").select("date").limit(1)
    return str(builder.request.headers.get("Authorization", ""))


def test_supabase_client_puts_user_jwt_on_request_builder():
    from supabase_client import SupabaseClient

    client = SupabaseClient(user_token=FAKE_USER_JWT)
    auth_header = _builder_auth_header(client)
    assert FAKE_USER_JWT in auth_header
    assert ANON_KEY not in auth_header


def test_session_only_injection_would_be_broken():
    """Document the regression: session.headers alone does not reach RequestBuilder."""
    from supabase import create_client

    raw = create_client("https://example.supabase.co", ANON_KEY)
    raw.postgrest.session.headers["Authorization"] = f"Bearer {FAKE_USER_JWT}"
    builder = raw.postgrest.table("performance_metrics").select("date").limit(1)
    auth_header = str(builder.request.headers.get("Authorization", ""))
    assert FAKE_USER_JWT not in auth_header
