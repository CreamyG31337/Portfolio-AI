"""Clean-room story identity for near-duplicate news titles (Phase I1).

Reimplements the *technique* described in ``docs/research/WORLDMONITOR.md``
(dual-view hashed lexical vectors + containment rescue) without copying any
AGPL WorldMonitor source. Used to skip re-extract/re-summarize when SearXNG and
RSS surface the same catalyst under different URLs/wording, and to accumulate a
``corroboration_count`` (distinct sources) on the kept article.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DIM = 512
DEFAULT_THRESHOLD = 0.58
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?")
_NON_ASCII_RE = re.compile(r"[^\x00-\x7f]")


def _fnv1a_32(data: bytes) -> int:
    h = 2166136261
    for b in data:
        h ^= b
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def _hash_bucket(token: str) -> int:
    return _fnv1a_32(token.encode("utf-8")) % DIM


def tokenize_words(title: str) -> list[str]:
    """Lowercased alphanumeric word tokens (apostrophes kept inside words)."""
    return [m.group(0).lower() for m in _WORD_RE.finditer(title or "")]


def source_key(source: Optional[str] = None, url: Optional[str] = None) -> str:
    """Stable identity for a publisher — prefer URL host, else source label."""
    if url:
        try:
            host = (urlparse(url).hostname or "").lower()
            if host.startswith("www."):
                host = host[4:]
            if host:
                return host
        except Exception:
            pass
    label = (source or "").strip().lower()
    return label or "unknown"


@dataclass(frozen=True)
class StoryVector:
    """L2-normalized dual views over a 512-dim hashed bag."""

    uniform: tuple[float, ...]
    entity: tuple[float, ...]
    tokens: tuple[str, ...]


def _l2_normalize(vec: list[float]) -> tuple[float, ...]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 0.0:
        return tuple(0.0 for _ in vec)
    return tuple(v / norm for v in vec)


def _add_feature(vec: list[float], token: str, weight: float) -> None:
    if not token or weight == 0.0:
        return
    vec[_hash_bucket(token)] += weight


def _is_entity_token(raw_token: str) -> bool:
    """Capitalized words and ticker-like ALL-CAPS tokens count as entities."""
    if not raw_token or any(ch.isdigit() for ch in raw_token):
        return False
    if raw_token.isupper() and len(raw_token) >= 2 and raw_token.isalpha():
        return True
    return raw_token[:1].isupper() and not raw_token.isupper()


def vectorize_title(title: str) -> StoryVector:
    """Build dual-view feature-hashed vectors for a headline."""
    raw = title or ""
    words = tokenize_words(raw)
    raw_words = [m.group(0) for m in _WORD_RE.finditer(raw)]

    uniform = [0.0] * DIM
    entity = [0.0] * DIM

    for w in words:
        _add_feature(uniform, f"w:{w}", 2.0)

    for a, b in zip(words, words[1:]):
        _add_feature(uniform, f"bg:{a}_{b}", 1.5)

    # Char 4-grams — uniform view only (morphology fuzz).
    compact = re.sub(r"\s+", "", raw.lower())
    for i in range(max(0, len(compact) - 3)):
        _add_feature(uniform, f"c4:{compact[i : i + 4]}", 1.0)

    for w in words:
        if _NON_ASCII_RE.search(w):
            for i in range(max(0, len(w) - 1)):
                _add_feature(uniform, f"c2:{w[i : i + 2]}", 1.0)

    # Entity view: named entities / tickers / numbers dominate.
    for rw in raw_words:
        low = rw.lower()
        is_num = any(ch.isdigit() for ch in rw)
        if _is_entity_token(rw):
            _add_feature(entity, f"w:{low}", 6.0)
        elif is_num:
            _add_feature(entity, f"w:{low}", 4.0)
        else:
            _add_feature(entity, f"w:{low}", 0.35)

    for (rw_a, rw_b), (a, b) in zip(
        zip(raw_words, raw_words[1:]), zip(words, words[1:])
    ):
        ent_bigram = (
            _is_entity_token(rw_a)
            or _is_entity_token(rw_b)
            or any(ch.isdigit() for ch in rw_a + rw_b)
        )
        _add_feature(entity, f"bg:{a}_{b}", 3.0 if ent_bigram else 0.4)

    return StoryVector(
        uniform=_l2_normalize(uniform),
        entity=_l2_normalize(entity),
        tokens=tuple(words),
    )


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return float(sum(x * y for x, y in zip(a, b)))


def containment_match(a_tokens: Sequence[str], b_tokens: Sequence[str]) -> bool:
    """True when a truncated title is almost fully contained in a longer one.

    Equal-length single-token swaps (Turkey vs Argentina) must NOT match — only
    rescue severely truncated wire copies (smaller set clearly shorter).
    """
    if not a_tokens or not b_tokens:
        return False
    set_a, set_b = set(a_tokens), set(b_tokens)
    smaller, larger = (set_a, set_b) if len(set_a) <= len(set_b) else (set_b, set_a)
    if len(smaller) < 4:
        return False
    if len(smaller) > 0.85 * len(larger):
        return False
    return (len(smaller & larger) / len(smaller)) >= 0.90


def story_similarity(a: StoryVector, b: StoryVector) -> float:
    """Min of dual-view cosines (both views must agree)."""
    return min(_cosine(a.uniform, b.uniform), _cosine(a.entity, b.entity))


def same_story(
    title_a: str,
    title_b: str,
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> bool:
    """Whether two headlines are the same story under I1 rules."""
    va, vb = vectorize_title(title_a), vectorize_title(title_b)
    if containment_match(va.tokens, vb.tokens):
        return True
    return story_similarity(va, vb) >= threshold


@dataclass(frozen=True)
class StoryMatch:
    article_id: str
    title: str
    source: Optional[str]
    url: Optional[str]
    similarity: float
    via_containment: bool


def find_matching_story(
    title: str,
    candidates: Iterable[dict],
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> Optional[StoryMatch]:
    """Return the best matching recent article row, or None.

    Each candidate dict needs ``id`` and ``title``; ``source`` / ``url`` optional.
    """
    probe = vectorize_title(title)
    if not probe.tokens:
        return None

    best: Optional[StoryMatch] = None
    for row in candidates:
        other_title = str(row.get("title") or "")
        if not other_title:
            continue
        other = vectorize_title(other_title)
        via_containment = containment_match(probe.tokens, other.tokens)
        sim = story_similarity(probe, other)
        if not via_containment and sim < threshold:
            continue
        match = StoryMatch(
            article_id=str(row["id"]),
            title=other_title,
            source=row.get("source"),
            url=row.get("url"),
            similarity=1.0 if via_containment else sim,
            via_containment=via_containment,
        )
        if best is None or match.similarity > best.similarity:
            best = match
    return best


def apply_corroboration_boost(base_score: float, corroboration_count: int) -> float:
    """Bump relevance for additional distinct sources (capped)."""
    base = float(base_score)
    extra = max(int(corroboration_count) - 1, 0)
    if extra <= 0:
        return base
    boost = min(0.15, 0.05 * extra)
    return min(1.0, base + boost)


def try_corroborate_incoming_story(
    research_repo: Any,
    *,
    title: str,
    source: Optional[str] = None,
    url: Optional[str] = None,
    hours: int = 72,
) -> Optional[StoryMatch]:
    """Match ``title`` against recent articles; on hit, record corroboration and return match.

    Returns the :class:`StoryMatch` when the caller should skip extract/summarize.
    Returns ``None`` when this is a new story (or dedup is disabled / unavailable).
    """
    try:
        from settings import is_story_dedup_enabled
    except Exception:
        return None

    if not is_story_dedup_enabled():
        return None
    if not title or not research_repo:
        return None

    try:
        candidates = research_repo.fetch_recent_story_candidates(hours=hours)
    except Exception as exc:
        logger.warning("story dedup candidate fetch failed: %s", exc)
        return None

    filtered = [
        row for row in candidates if not url or str(row.get("url") or "") != url
    ]
    match = find_matching_story(title, filtered)
    if match is None:
        return None

    key = source_key(source, url)
    try:
        research_repo.record_story_corroboration(match.article_id, key)
    except Exception as exc:
        logger.warning("story corroboration update failed: %s", exc)
    return match
