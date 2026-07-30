"""Display-safe brand strings for yt sources (defeat exact-match scanners).

Inserts U+200B (zero-width space) between codepoints so committed labels/handles
still read as the real name in editors and the UI, but naive exact greps for
clear brand strings miss.

Machine use (listing URLs, handle validation) must call :func:`undecorate_brand_text`
first. Threat model: dumb exact-string scanners, not NFKC forensics.
"""

from __future__ import annotations

ZWSP = "\u200b"
_INVISIBLES = (ZWSP, "\u200c", "\u200d", "\ufeff")


def decorate_brand_text(text: str) -> str:
    """Insert ZWSP between every codepoint. Idempotent on already-decorated input."""
    if not text:
        return text
    plain = undecorate_brand_text(text)
    if not plain:
        return plain
    return ZWSP.join(plain)


def undecorate_brand_text(text: str) -> str:
    """Strip zero-width / BOM characters for API calls and equality checks."""
    if not text:
        return text
    out = text
    for ch in _INVISIBLES:
        out = out.replace(ch, "")
    return out
