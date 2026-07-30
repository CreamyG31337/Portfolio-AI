"""
Shared Utilities for Scheduled Jobs
====================================

Common functions and utilities used across multiple job modules.
"""

import hashlib
import re
import threading
import time
from typing import List, Optional, Sequence


def calculate_relevance_score(
    tickers: List[str],
    sector: Optional[str],
    owned_tickers: Optional[List[str]] = None,
    corroboration_count: int = 1,
) -> float:
    """Calculate relevance score based on tickers, ownership, and story corroboration.

    Args:
        tickers: List of ticker symbols extracted from article
        sector: Sector name if available
        owned_tickers: Optional list of tickers we own (for performance)
        corroboration_count: Distinct publishers covering this story (Phase I1)

    Returns:
        Relevance score: 0.8 (owned tickers), 0.7 (opportunities), 0.5 (general),
        plus a small capped boost when multiple sources corroborate the story.
    """
    from story_identity import apply_corroboration_boost

    if not tickers:
        base = 0.5  # General market news
    elif owned_tickers and any(ticker in owned_tickers for ticker in tickers):
        base = 0.8  # Ticker-specific, owned
    else:
        base = 0.7  # Has tickers but none owned = opportunity discovery

    return apply_corroboration_boost(base, corroboration_count)


_MARKET_SIGNAL_PATTERN = re.compile(
    r"\b("
    r"stock|stocks|share|shares|ticker|earnings?|revenue|guidance|dividend|buyback|"
    r"ipo|etf|sec(?:\s+filing)?|10-k|10-q|market\s+cap|analyst|price\s+target|"
    r"nasdaq|nyse|tsx|s&p\s*500|russell\s*2000|bond\s+yield|treasury|"
    r"fomc|interest\s+rate|inflation|cpi|ppi"
    r")\b",
    re.IGNORECASE,
)

_SUMMARY_INPUT_HASHES_LOCK = threading.Lock()
_SUMMARY_INPUT_HASHES: dict[str, float] = {}
_SUMMARY_INPUT_TTL_SECONDS = 6 * 60 * 60


def claim_recent_summary_input(text: str, ttl_seconds: int = _SUMMARY_INPUT_TTL_SECONDS) -> tuple[bool, str]:
    """Claim a summary input hash within a TTL window.

    Returns:
        (True, hash) if this input was not seen recently and should be summarized.
        (False, hash) if it was already summarized recently and can be skipped.
    """
    input_hash = hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:8]
    now = time.time()
    ttl = max(int(ttl_seconds), 1)
    cutoff = now - ttl

    with _SUMMARY_INPUT_HASHES_LOCK:
        # Lazy cleanup of stale hashes to keep memory bounded.
        stale_hashes = [key for key, ts in _SUMMARY_INPUT_HASHES.items() if ts < cutoff]
        for key in stale_hashes:
            _SUMMARY_INPUT_HASHES.pop(key, None)

        last_seen = _SUMMARY_INPUT_HASHES.get(input_hash)
        if last_seen is not None and (now - last_seen) < ttl:
            return False, input_hash

        _SUMMARY_INPUT_HASHES[input_hash] = now
        return True, input_hash


def has_strong_market_signal(
    title: str,
    content: str,
    tickers: Optional[Sequence[str]] = None,
    required_terms: Optional[Sequence[str]] = None,
) -> bool:
    """Return True when article text has explicit market signals.

    This is a lightweight second-pass filter to catch obvious false positives where
    AI marks generic/lifestyle content as market-related.
    """
    if tickers:
        return True

    text = f"{title or ''}\n{content or ''}"[:8000]
    if not text.strip():
        return False

    if _MARKET_SIGNAL_PATTERN.search(text):
        return True

    if re.search(r"\$[A-Z]{1,5}\b", text):
        return True

    if re.search(r"\b[A-Z]{1,5}\.(?:TO|TSX|V|CN|AX|L)\b", text):
        return True

    if required_terms:
        lowered = text.lower()
        for term in required_terms:
            token = str(term or "").strip().lower()
            if len(token) < 2:
                continue
            if re.search(rf"\b{re.escape(token)}\b", lowered):
                return True

    return False


# --------------------------------------------------------------------------- #
# Alpha Hunter helpers (pure, testable)
# --------------------------------------------------------------------------- #

# Low-value SearXNG result patterns, as (reason_label, title_regex, url_regex|None).
#
# The reason_label is logged in the `low_value` job step (see the alpha worker) so we
# can audit WHICH rule dropped a result and tune it later if it is too aggressive
# (eating real articles) or not aggressive enough (junk slips through).
#
# Patterns are matched against the result TITLE, and -- for rules carrying a
# url_regex -- against the URL as well. BOTH must match for those. This is the only
# information available at this stage: sentiment, conclusion and claims do not exist
# until after extraction and summarization.
#
# Rules live in web_dashboard/ideas_quality.py, shared with the inbox cleanup script
# and the ranking SQL so all three tune in one place.
#
# IMPORTANT - tuning guidance:
#   * Keep patterns NARROW and anchored. A false positive silently drops a real
#     article before it is ever extracted, and we only see it as a `low_value`
#     skip in the logs.
#   * Add a url_regex whenever the title text could plausibly appear in genuine
#     analysis ("X's dividend history suggests...", "...Event Calendar shows...").
#   * Some rules are deliberately NOT applied here at all (price_targets_page,
#     insider_activity_page). Their titles match real Benzinga upgrade notes and
#     cluster-buy stories; they are only safe once sentiment exists, so they are
#     demote-only. See the Sinda case in ideas_quality.
#   * The "listing_index" rule is anchored to a leading "Latest" because genuine
#     analysis pieces almost never start with that word, whereas auto-generated
#     index/aggregator pages do (e.g. Benzinga
#     "Latest Azitra Stock News | AMEX:AZTR | Benzinga", Seeking Alpha
#     "Latest Communication Services Stock Analysis Articles").
#   * The "quote_overview"/"price_history"/"ticker_price" rules catch
#     auto-generated quote pages (e.g. stockanalysis.com
#     "INVA Stock Price & Overview", "AAPL stock quote").
def _build_low_value_patterns() -> tuple[tuple[str, "re.Pattern[str]", "re.Pattern[str] | None"], ...]:
    """Compile the pre-extraction subset of the shared rule table.

    Only rules flagged ``prefilter`` are used here. The rest are demote-only: they
    need the sentiment field to be safe, and sentiment does not exist until after the
    article has been extracted and summarized. See ``ideas_quality`` for the Sinda
    case that motivated the split.
    """
    from ideas_quality import (
        LISTING_INDEX_RULE,
        PREFILTER_RULES,
        python_pattern,
    )

    built: list[tuple[str, "re.Pattern[str]", "re.Pattern[str] | None"]] = []
    for rule in PREFILTER_RULES:
        built.append(
            (
                rule.reason,
                re.compile(python_pattern(rule), re.IGNORECASE),
                re.compile(rule.url, re.IGNORECASE) if rule.url else None,
            )
        )
    # Anchored to the start of the title, so it cannot share the generic builder.
    built.append(
        ("listing_index", re.compile(rf"^\s*{LISTING_INDEX_RULE.core}", re.IGNORECASE), None)
    )
    built.append(
        ("ticker_price", re.compile(r"\([A-Z]{1,5}\)\s+stock\s+price\b", re.IGNORECASE), None)
    )
    return tuple(built)


_LOW_VALUE_ALPHA_PATTERNS = _build_low_value_patterns()


def select_alpha_queries(
    queries: Sequence[str],
    n: int,
    day_ordinal: int,
) -> list[str]:
    """Pick ``n`` queries for today's Alpha Hunter run, rotating through the full list.

    Uses ``day_ordinal`` (typically ``date.toordinal()``) so every query is
    covered over ``ceil(len(queries) / n)`` consecutive days without repeating
    the same batch on adjacent days when ``n < len(queries)``.

    Args:
        queries: Full configured query list.
        n: How many queries to run this invocation (clamped to ``len(queries)``).
        day_ordinal: Day index for rotation (e.g. ``datetime.date.toordinal()``).

    Returns:
        Up to ``n`` query strings (may be fewer if ``queries`` is empty).
    """
    if not queries:
        return []

    total = len(queries)
    count = max(1, min(int(n), total))
    start = (int(day_ordinal) * count) % total

    selected: list[str] = []
    for i in range(count):
        selected.append(queries[(start + i) % total])
    return selected


def relevance_for_logic_check(logic_check: Optional[str]) -> float:
    """Map AI ``logic_check`` bucket to a stored ``relevance_score``.

    HYPE_DETECTED is down-ranked to 0.1 so the existing junk filter can prune
    advertorial/clickbait while still preserving the article in the DB briefly.
    """
    if not logic_check:
        return 0.7
    normalized = str(logic_check).strip().upper()
    if normalized == "DATA_BACKED":
        return 0.9
    if normalized == "HYPE_DETECTED":
        return 0.1
    return 0.7  # NEUTRAL and unknown buckets


def low_value_alpha_reason(title: str, url: str = "") -> Optional[str]:
    """Return WHY a SearXNG hit is low-value boilerplate, or ``None`` if it looks legit.

    Cheap pre-extraction guard that skips pages which waste FlareSolverr/Ollama
    budget: auto-generated quote/overview/price pages and index/listing/
    aggregator pages ("Latest ... News/Articles/Analysis") that are not real
    analysis. Rules come from :mod:`ideas_quality` (shared with the inbox cleanup and
    ranking so there is one place to tune them).

    Matching is against ``title``, and additionally against ``url`` for rules whose
    title text is ambiguous on its own -- "Dividend History" appears in real analysis
    ("X's dividend history suggests..."), so it only counts as boilerplate when the
    URL also looks like a generated ``/dividend`` page. Both must match.

    Only rules marked ``prefilter`` are applied here. Rules that need the sentiment
    field to be safe (``price_targets_page``, ``insider_activity_page``) are
    deliberately excluded: sentiment does not exist before extraction, and dropping
    on those titles alone would silently discard real articles -- see the Sinda case
    documented in :mod:`ideas_quality`.

    The returned label (e.g. ``"listing_index"``, ``"quote_overview"``) is logged by
    the caller so drops can be audited and the patterns tuned.
    """
    text = (title or "").strip()
    if not text:
        return None
    url_text = (url or "").strip()
    for reason, pat, url_pat in _LOW_VALUE_ALPHA_PATTERNS:
        if not pat.search(text):
            continue
        if url_pat is not None and not url_pat.search(url_text):
            # Title looked like boilerplate but the URL does not corroborate it.
            # Keep the article: a false negative here is a silent data loss.
            continue
        return reason
    return None


def is_low_value_alpha_result(title: str, url: str = "") -> bool:
    """Boolean convenience wrapper around :func:`low_value_alpha_reason`."""
    return low_value_alpha_reason(title, url) is not None

