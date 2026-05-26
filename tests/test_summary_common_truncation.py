"""Tests for summary input-truncation helpers.

Regression coverage for the long-newsletter truncation issue: the original
hardcoded 6000-char cap silently dropped the closing thesis of newsletters
(typically 7-15k chars). These helpers raise the budget for newsletters
specifically and preserve head + tail when truncating.
"""

from __future__ import annotations

import pytest

from web_dashboard.summary_common import (
    SUMMARY_MAX_CHARS_DEFAULT,
    SUMMARY_MAX_CHARS_NEWSLETTER,
    SUMMARY_TRUNCATION_MARKER,
    compute_summary_max_chars,
    truncate_for_summary,
)


def test_compute_summary_max_chars_defaults_to_general_article_budget() -> None:
    assert compute_summary_max_chars("") == SUMMARY_MAX_CHARS_DEFAULT
    assert compute_summary_max_chars("Article") == SUMMARY_MAX_CHARS_DEFAULT
    assert compute_summary_max_chars("blog") == SUMMARY_MAX_CHARS_DEFAULT


def test_compute_summary_max_chars_uses_larger_budget_for_newsletters() -> None:
    """Newsletter article_type unlocks the larger char budget.

    The closing thesis / actionable picks live at the tail of newsletters,
    so cutting them off (as the old 6000-char cap did for ~7.5k+ char
    newsletters) loses the most important signal.
    """
    assert compute_summary_max_chars("Newsletter") == SUMMARY_MAX_CHARS_NEWSLETTER
    # Match is case-insensitive so callers passing "newsletter"/"NEWSLETTER" all hit the bigger budget.
    assert compute_summary_max_chars("newsletter") == SUMMARY_MAX_CHARS_NEWSLETTER
    assert compute_summary_max_chars("NEWSLETTER") == SUMMARY_MAX_CHARS_NEWSLETTER


def test_compute_summary_max_chars_respects_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_SUMMARY_MAX_CHARS", "8000")
    monkeypatch.setenv("AI_SUMMARY_MAX_CHARS_NEWSLETTER", "20000")
    assert compute_summary_max_chars("") == 8000
    assert compute_summary_max_chars("Newsletter") == 20000


def test_compute_summary_max_chars_ignores_garbage_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_SUMMARY_MAX_CHARS", "not-a-number")
    monkeypatch.setenv("AI_SUMMARY_MAX_CHARS_NEWSLETTER", "0")
    assert compute_summary_max_chars("") == SUMMARY_MAX_CHARS_DEFAULT
    assert compute_summary_max_chars("Newsletter") == SUMMARY_MAX_CHARS_NEWSLETTER


def test_truncate_for_summary_returns_input_unchanged_when_within_budget() -> None:
    text = "Short article body."
    assert truncate_for_summary(text, 100) == text


def test_truncate_for_summary_preserves_head_and_tail() -> None:
    """For long inputs we keep the intro AND the conclusion (head + tail).

    Naive ``text[:max_chars]`` would drop everything after position N, which
    is exactly the conclusion section in newsletters. Head+tail truncation
    keeps the signal at both ends.
    """
    head_marker = "INTRO_BUY_SIGNAL_HEADLINE"
    tail_marker = "FINAL_CONCLUSION_BUY_AAPL"
    middle = "filler " * 4000  # ~28k chars of noise between markers
    text = f"{head_marker}\n\n{middle}\n\n{tail_marker}"
    assert len(text) > 8000  # sanity check

    truncated = truncate_for_summary(text, 4000)

    assert len(truncated) <= 4000
    assert head_marker in truncated, "Head should survive truncation"
    assert tail_marker in truncated, "Tail (closing thesis) should survive truncation"
    assert SUMMARY_TRUNCATION_MARKER in truncated, (
        "Marker must signal omitted middle so the model knows content was cut"
    )


def test_truncate_for_summary_handles_pathological_inputs() -> None:
    # Empty string round-trips unchanged.
    assert truncate_for_summary("", 100) == ""
    # None is treated as empty rather than raising; matches existing call-site fallthrough.
    assert truncate_for_summary(None, 100) == ""  # type: ignore[arg-type]
    # Non-positive budget yields empty rather than negative slicing.
    assert truncate_for_summary("abc", 0) == ""
    assert truncate_for_summary("abc", -5) == ""
    # When the budget can't accommodate the marker (extreme edge case), fall back to
    # a plain head cut rather than emitting a marker-only payload. The input must
    # actually exceed the budget for truncation to engage in the first place.
    short_budget = max(1, len(SUMMARY_TRUNCATION_MARKER) - 5)
    long_text = "x" * (short_budget * 4)
    result = truncate_for_summary(long_text, short_budget)
    assert len(result) == short_budget
    assert result == "x" * short_budget
