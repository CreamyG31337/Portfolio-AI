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
    owned_tickers: Optional[List[str]] = None
) -> float:
    """Calculate relevance score based on tickers and ownership.
    
    Args:
        tickers: List of ticker symbols extracted from article
        sector: Sector name if available
        owned_tickers: Optional list of tickers we own (for performance)
        
    Returns:
        Relevance score: 0.8 (owned tickers), 0.7 (opportunities), 0.5 (general)
    """
    if not tickers:
        return 0.5  # General market news
    
    # Check if any tickers are owned
    if owned_tickers:
        has_owned = any(ticker in owned_tickers for ticker in tickers)
        if has_owned:
            return 0.8  # Ticker-specific, owned
    
    # Has tickers but none owned = opportunity discovery
    return 0.7


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

