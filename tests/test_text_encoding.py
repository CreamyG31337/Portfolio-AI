"""Tests for scraped-text mojibake repair (cp1252 UTF-8 mis-decode)."""

from __future__ import annotations

from utils.text_encoding import repair_mojibake


def _as_mojibake(text: str) -> str:
    """Decode UTF-8 bytes as cp1252 (replace undefined bytes like 0x9D)."""
    return text.encode("utf-8").decode("cp1252", errors="replace")


def test_repairs_curly_single_quotes_mojibake() -> None:
    broken = _as_mojibake(
        "Elon Musk Says \u2018Mistake\u2019 Corrected, "
        "But Michael Burry Calls Company \u2018Weak, Craven\u2019"
    )
    fixed = repair_mojibake(broken)
    assert "â€˜" not in fixed
    assert "â€™" not in fixed
    assert "\u2018Mistake\u2019" in fixed
    assert "\u2018Weak, Craven\u2019" in fixed


def test_repairs_curly_double_quotes_and_dash() -> None:
    broken = _as_mojibake("Nvidia \u201cAI boom\u201d \u2014 still strong")
    fixed = repair_mojibake(broken)
    assert "â€" not in fixed
    assert "\u201cAI boom\u201d" in fixed
    assert "\u2014" in fixed


def test_repairs_accented_latin_via_roundtrip() -> None:
    broken = _as_mojibake("caf\u00e9 r\u00e9sum\u00e9")
    assert "Ã" in broken
    assert repair_mojibake(broken) == "café résumé"


def test_leaves_clean_unicode_alone() -> None:
    clean = "Jensen Huang\u2019s Nvidia Return: \u2018Mistake\u2019 Corrected"
    assert repair_mojibake(clean) == clean


def test_unescapes_html_entities() -> None:
    assert repair_mojibake("Musk Says &lsquo;Mistake&rsquo;") == "Musk Says \u2018Mistake\u2019"


def test_none_and_empty() -> None:
    assert repair_mojibake(None) == ""
    assert repair_mojibake("") == ""


def test_ascii_passthrough() -> None:
    assert repair_mojibake("Plain NVDA title") == "Plain NVDA title"
