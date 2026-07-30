"""Unit tests for sources bulk-preview classification (no network)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web_dashboard"
for path in (ROOT, WEB):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from sources_service import (  # noqa: E402
    classify_bulk_rows,
    normalize_handle,
    normalize_ticker,
    parse_bulk_payload,
)
from yt_brand_display import decorate_brand_text, undecorate_brand_text  # noqa: E402


def test_normalize_ticker_accepts_common_symbols() -> None:
    assert normalize_ticker("nvda") == "NVDA"
    assert normalize_ticker("BRK.B") == "BRK.B"
    assert normalize_ticker("bad ticker!") is None


def test_normalize_handle_adds_at_and_decorates() -> None:
    h = normalize_handle("ExampleChannel")
    assert h is not None
    assert undecorate_brand_text(h) == "@ExampleChannel"
    assert h != "@ExampleChannel"
    assert "\u200b" in h
    assert undecorate_brand_text(normalize_handle("@Foo") or "") == "@Foo"


def test_decorate_brand_breaks_exact_match() -> None:
    plain = "Example Brand Name"
    deco = decorate_brand_text(plain)
    assert plain not in deco
    assert undecorate_brand_text(deco) == plain
    assert decorate_brand_text(deco) == deco  # idempotent


def test_parse_bulk_json_ignores_unknown_keys() -> None:
    payload = """
    [
      {
        "label": "Example Research Channel",
        "handle": "@ExampleResearchCh",
        "kind": "channel",
        "alpha_mechanism": "TEARDOWN",
        "expected_tickers": ["NVDA", "INTC"],
        "cadence": "weekly",
        "mystery": true
      }
    ]
    """
    rows, errors = parse_bulk_payload("json", payload)
    assert errors == []
    assert len(rows) == 1
    assert rows[0]["label"] == "Example Research Channel"
    assert "mystery" not in rows[0]
    assert "cadence" not in rows[0]


def test_classify_bulk_rows_new_duplicate_invalid() -> None:
    rows = [
        {
            "label": "New Channel",
            "handle": "@NewOne",
            "kind": "channel",
            "alpha_mechanism": "ANALYSIS",
            "expected_tickers": ["AMD"],
        },
        {
            "label": "Dup",
            "handle": "@Existing",
            "kind": "channel",
        },
        {
            "label": "",
            "handle": "@Nope",
            "kind": "channel",
        },
        {
            "label": "Bad ticker",
            "handle": "@Bad",
            "kind": "channel",
            "expected_tickers": ["!!!"],
        },
    ]
    result = classify_bulk_rows(
        rows,
        existing_channel_ids=set(),
        existing_handles={"@Existing"},
        existing_queries=set(),
    )
    statuses = [r["status"] for r in result["rows"]]
    assert statuses == ["new", "duplicate", "invalid", "invalid"]
    assert result["summary"] == {"new": 1, "duplicate": 1, "invalid": 2}
    assert "\u200b" in result["rows"][0]["label"]
    assert undecorate_brand_text(result["rows"][0]["label"]) == "New Channel"


def test_classify_search_requires_query() -> None:
    result = classify_bulk_rows(
        [{"label": "Search", "kind": "search"}],
        existing_channel_ids=set(),
        existing_handles=set(),
        existing_queries=set(),
    )
    assert result["rows"][0]["status"] == "invalid"


def _mock_admin_auth(is_admin: bool = True):
    return patch.multiple(
        "auth.auth_manager",
        verify_session=MagicMock(
            return_value={"user_id": "admin-user-id", "email": "admin@example.com"}
        ),
        is_admin=MagicMock(return_value=is_admin),
    )


def test_bulk_preview_route_readonly_403(client) -> None:
    with _mock_admin_auth(True), patch(
        "routes.sources_routes.can_modify_data_flask", return_value=False
    ), patch("supabase_client.SupabaseClient") as mock_sb:
        mock_sb.return_value.supabase.rpc.return_value.execute.return_value = MagicMock(
            data=True
        )
        client.set_cookie("auth_token", "test.token.value")
        res = client.post(
            "/api/admin/sources/youtube/bulk-preview",
            json={"format": "json", "payload": "[]"},
        )
        assert res.status_code == 403


def test_bulk_preview_route_classifies(client) -> None:
    payload = (
        '[{"label":"Example","handle":"@ExampleResearchCh","kind":"channel",'
        '"alpha_mechanism":"TEARDOWN","expected_tickers":["NVDA"]}]'
    )
    with _mock_admin_auth(True), patch(
        "routes.sources_routes.can_modify_data_flask", return_value=True
    ), patch(
        "routes.sources_routes._existing_youtube_keys", return_value=(set(), set(), set())
    ), patch("supabase_client.SupabaseClient") as mock_sb:
        mock_sb.return_value.supabase.rpc.return_value.execute.return_value = MagicMock(
            data=True
        )
        client.set_cookie("auth_token", "test.token.value")
        res = client.post(
            "/api/admin/sources/youtube/bulk-preview",
            json={"format": "json", "payload": payload},
        )
        assert res.status_code == 200
        body = res.get_json()
        assert body["summary"]["new"] == 1
        assert body["rows"][0]["status"] == "new"
