"""Tests for loose JSON parsing helpers used by social_service (Phase 2)."""

from __future__ import annotations

import sys
from pathlib import Path

web_dashboard = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(web_dashboard) not in sys.path:
    sys.path.insert(0, str(web_dashboard))

from social_service import _extract_json_array, _extract_json_object  # noqa: E402


def test_extract_json_object_plain() -> None:
    assert _extract_json_object('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}


def test_extract_json_object_markdown_fence() -> None:
    raw = 'Here:\n```json\n{"is_opportunity": true, "ticker": "ABC"}\n```'
    assert _extract_json_object(raw) == {"is_opportunity": True, "ticker": "ABC"}


def test_extract_json_object_leading_prose() -> None:
    raw = 'Sure! {"sentiment_label": "BULLISH", "sentiment_score": 1.0}'
    out = _extract_json_object(raw)
    assert out is not None
    assert out.get("sentiment_label") == "BULLISH"


def test_extract_json_object_returns_none_on_garbage() -> None:
    assert _extract_json_object("not json at all") is None


def test_extract_json_object_first_of_two_objects_not_greedy_span() -> None:
    """Greedy \\{.*\\} would merge two objects into invalid JSON; raw_decode finds the first."""
    raw = '{"valid": 1} text {"another": 2}'
    assert _extract_json_object(raw) == {"valid": 1}


def test_extract_json_object_nested_inner_braces() -> None:
    raw = 'Ok {"outer": {"inner": 1}} trailing'
    assert _extract_json_object(raw) == {"outer": {"inner": 1}}


def test_extract_json_array_first_of_two_arrays() -> None:
    raw = '[1, 2] and later [3, 4]'
    assert _extract_json_array(raw) == [1, 2]


def test_extract_json_array_plain() -> None:
    assert _extract_json_array('[{"ticker": "AAPL"}]') == [{"ticker": "AAPL"}]


def test_extract_json_array_fence() -> None:
    raw = "```\n[{\"ticker\": \"X\"}]\n```"
    assert _extract_json_array(raw) == [{"ticker": "X"}]


def test_extract_json_array_returns_none_for_object() -> None:
    assert _extract_json_array('{"ticker": "X"}') is None
