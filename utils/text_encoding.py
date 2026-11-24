"""Repair common UTF-8 / Windows-1252 mojibake in scraped text.

News titles often arrive as UTF-8 bytes that were decoded as cp1252, so curly
quotes show up as ``â€˜`` / ``â€™`` instead of ``‘`` / ``’``.
"""

from __future__ import annotations

import html
from typing import Optional

# Explicit trigrams for punctuation (right-double-quote's UTF-8 byte 0x9D is
# undefined in strict cp1252, so a full round-trip cannot recover â€ forms).
_PUNCT_MOJIBAKE: tuple[tuple[str, str], ...] = (
    ("â€˜", "\u2018"),  # ‘
    ("â€™", "\u2019"),  # ’
    ("â€œ", "\u201c"),  # “
    ("â€\u009d", "\u201d"),  # ” (C1 0x9D preserved)
    ("â€�", "\u201d"),  # ” (0x9D → U+FFFD)
    ("â€”", "\u2014"),  # —
    ("â€“", "\u2013"),  # –
    ("â€¦", "\u2026"),  # …
)

# Signatures that still warrant a full cp1252→UTF-8 pass (e.g. Ã© → é).
_MOJIBAKE_MARKERS = ("â€", "Ã", "Â")


def repair_mojibake(text: Optional[str]) -> str:
    """Return text with common mojibake repaired; empty/None-safe.

    Applies ``html.unescape``, known punctuation trigram fixes, then a
    cp1252→UTF-8 round-trip when telltale sequences remain.
    """
    if text is None:
        return ""
    if not text:
        return text

    fixed = html.unescape(text)
    for bad, good in _PUNCT_MOJIBAKE:
        if bad in fixed:
            fixed = fixed.replace(bad, good)

    if not any(marker in fixed for marker in _MOJIBAKE_MARKERS):
        return fixed

    try:
        repaired = fixed.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return fixed

    before = sum(fixed.count(m) for m in _MOJIBAKE_MARKERS)
    after = sum(repaired.count(m) for m in _MOJIBAKE_MARKERS)
    if after < before:
        return repaired
    return fixed
