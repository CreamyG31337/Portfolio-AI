"""Unit tests for GLM judge JSON parsing (loose extract, not greedy-regex)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web_dashboard"
for p in (str(WEB), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from tests.benchmarks.llm_quality_bench import _parse_judge_json  # noqa: E402


def test_parse_judge_json_plain() -> None:
    raw = '{"factuality": 4, "relevance": 3, "ticker_correctness": 5, "clarity": 4, "hallucination_flag": 0, "notes": "ok"}'
    d = _parse_judge_json(raw)
    assert d.get("factuality") == 4
    assert d.get("hallucination_flag") == 0


def test_parse_judge_json_markdown_fence() -> None:
    raw = (
        "```json\n"
        '{"factuality": 1, "relevance": 2, "ticker_correctness": 3, "clarity": 4, "hallucination_flag": 1, "notes": "n"}\n'
        "```"
    )
    d = _parse_judge_json(raw)
    assert d.get("factuality") == 1
    assert d.get("notes") == "n"


def test_parse_judge_json_leading_prose() -> None:
    raw = (
        "Here is the JSON evaluation:\n"
        '{"factuality": 5, "relevance": 5, "ticker_correctness": 4, "clarity": 5, "hallucination_flag": 0, "notes": "fine"}'
    )
    d = _parse_judge_json(raw)
    assert d.get("relevance") == 5


def test_parse_judge_json_first_object_when_two() -> None:
    """Greedy brace span would merge two objects; raw_decode must take the first."""
    raw = '{"factuality": 3, "relevance": 3, "ticker_correctness": 3, "clarity": 3, "hallucination_flag": 0, "notes": "a"} junk {"factuality": 1}'
    d = _parse_judge_json(raw)
    assert d.get("factuality") == 3


def test_parse_judge_json_empty() -> None:
    assert _parse_judge_json("") == {}
    assert _parse_judge_json("no braces") == {}
