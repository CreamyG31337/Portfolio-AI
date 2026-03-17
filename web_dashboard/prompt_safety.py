#!/usr/bin/env python3
"""
Prompt safety helpers for untrusted content.

This module provides lightweight sanitization and delimiting helpers for text that
originates from external sources (social posts, scraped content, third-party APIs).
"""

from __future__ import annotations

import re
from typing import Optional

# Keep newline/tab for readability; strip other ASCII control chars.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")

# Remove invisible/bidi chars that can obfuscate content or instructions.
_INVISIBLE_BIDI_RE = re.compile(
    r"[\u200B\u200C\u200D\u2060\uFEFF\u202A-\u202E\u2066-\u2069]"
)

# Lightweight heuristic for instruction-like payloads in untrusted text.
_INSTRUCTION_LIKE_RE = re.compile(
    r"(ignore\s+previous|system\s+prompt|developer\s+message|"
    r"follow\s+these\s+instructions|tool\s+call|execute\s+this)",
    re.IGNORECASE,
)


def sanitize_for_llm(text: Optional[str], *, max_chars: int | None = None) -> str:
    """Normalize untrusted text for safer LLM ingestion.

    - Removes control, zero-width, and bidi override characters.
    - Trims leading/trailing whitespace.
    - Optionally truncates to a maximum character length.
    """
    if text is None:
        return ""

    safe = str(text)
    safe = _INVISIBLE_BIDI_RE.sub("", safe)
    safe = _CONTROL_CHARS_RE.sub(" ", safe)
    safe = safe.strip()

    if max_chars is not None and max_chars > 0 and len(safe) > max_chars:
        safe = safe[:max_chars]

    return safe


def wrap_untrusted_content(text: str, *, source: str = "external") -> str:
    """Wrap untrusted text in explicit prompt delimiters."""
    return f'<user_content source="{source}">\n{text}\n</user_content>'


def contains_instruction_like_text(text: Optional[str]) -> bool:
    """Return True when untrusted text appears to contain instruction-like patterns."""
    if not text:
        return False
    return bool(_INSTRUCTION_LIKE_RE.search(str(text)))


def prepare_untrusted_for_prompt(
    text: Optional[str],
    *,
    source: str,
    max_chars: int | None = None,
) -> str:
    """Sanitize and wrap untrusted text for safe prompt interpolation."""
    sanitized = sanitize_for_llm(text, max_chars=max_chars)
    return wrap_untrusted_content(sanitized, source=source)

