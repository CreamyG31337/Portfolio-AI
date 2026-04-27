"""Unit tests for UI AI summary digest stability (no Flask, no DB)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

web_dashboard = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(web_dashboard) not in sys.path:
    sys.path.insert(0, str(web_dashboard))

from dashboard_portfolio_digest import digest_fingerprint  # noqa: E402
from ui_ai_summary_scopes import make_portfolio_scope_key, scope_dashboard_portfolio  # noqa: E402
from ui_ai_summary_service import sha256_hex  # noqa: E402


def test_digest_fingerprint_stable_key_order() -> None:
    a = {"z": 1, "a": 2, "m": {"nested": True}}
    b = {"a": 2, "m": {"nested": True}, "z": 1}
    assert digest_fingerprint(a) == digest_fingerprint(b)


def test_sha256_hex_deterministic() -> None:
    assert sha256_hex("hello") == sha256_hex("hello")
    assert sha256_hex("a") != sha256_hex("b")


def test_make_portfolio_scope_key() -> None:
    assert make_portfolio_scope_key("TEST", "cad", "all") == "TEST|CAD|ALL"


def test_scope_dashboard_portfolio() -> None:
    assert scope_dashboard_portfolio() == "dashboard.portfolio_overview"


def test_json_roundtrip_summary_shape() -> None:
    payload = {"headline": "H", "narrative": "N", "bullets": ["a", "b"]}
    s = json.dumps(payload, sort_keys=True)
    assert json.loads(s)["headline"] == "H"
