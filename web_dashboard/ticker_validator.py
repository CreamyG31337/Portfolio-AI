"""
Ticker Validator
================

Validates LLM-extracted tickers by cross-referencing against real company data.

Problem: Local LLMs guess tickers from company names (e.g. "Preat Corp" → "PRE")
but PRE is actually Prenetics.  This module catches those mismatches.

Validation chain:
1. Securities table lookup (fast, cached in-memory)
2. yfinance fallback for unknown tickers (rate-limited, cached to disk)
3. Fuzzy company name comparison between what the LLM claims and the real entity

Usage:
    from ticker_validator import validate_extracted_tickers

    # LLM returned these
    raw_tickers = ["PRE", "AAPL", "FAKEX"]
    companies = ["Preat Corporation", "Apple Inc", "Fake Company"]
    article_text = "Preat Corporation introduces PreatLoc..."

    validated = validate_extracted_tickers(raw_tickers, companies, article_text)
    # Returns: ["AAPL"]  (PRE rejected: real company is Prenetics, not Preat)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache for yfinance lookups (disk-based, survives restarts)
# ---------------------------------------------------------------------------
_YF_CACHE_DIR = Path(__file__).resolve().parent / ".cache"
_YF_CACHE_FILE = _YF_CACHE_DIR / "ticker_company_names.json"
_YF_CACHE_TTL = 7 * 24 * 3600  # 7 days - company names don't change often

_yf_cache: Optional[Dict[str, Any]] = None  # ticker -> {"name": str, "ts": float}
_yf_cache_loaded = False

# In-memory securities table cache
_SECURITIES_CACHE: Optional[Dict[str, str]] = None  # ticker -> company_name
_SECURITIES_CACHE_TS: float = 0.0
_SECURITIES_CACHE_TTL = 3600  # 1 hour


def _load_yf_cache() -> Dict[str, Any]:
    """Load yfinance company name cache from disk."""
    global _yf_cache, _yf_cache_loaded
    if _yf_cache_loaded and _yf_cache is not None:
        return _yf_cache

    _yf_cache = {}
    try:
        if _YF_CACHE_FILE.exists():
            with open(_YF_CACHE_FILE, "r", encoding="utf-8") as f:
                _yf_cache = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to load yfinance cache: %s", e)
        _yf_cache = {}

    _yf_cache_loaded = True
    return _yf_cache


def _save_yf_cache() -> None:
    """Persist yfinance cache to disk."""
    if _yf_cache is None:
        return
    try:
        _YF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(_YF_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_yf_cache, f, indent=0)
    except OSError as e:
        logger.warning("Failed to save yfinance cache: %s", e)


def _load_securities_cache() -> Dict[str, str]:
    """Load ticker -> company_name from the securities table."""
    global _SECURITIES_CACHE, _SECURITIES_CACHE_TS

    now = time.time()
    if _SECURITIES_CACHE is not None and (now - _SECURITIES_CACHE_TS) < _SECURITIES_CACHE_TTL:
        return _SECURITIES_CACHE

    index: Dict[str, str] = {}
    try:
        from supabase_client import SupabaseClient
        client = SupabaseClient(use_service_role=True)
        batch_size = 1000
        offset = 0
        while True:
            result = (
                client.supabase
                .table("securities")
                .select("ticker, company_name")
                .range(offset, offset + batch_size - 1)
                .execute()
            )
            rows = result.data or []
            if not rows:
                break
            for row in rows:
                ticker = (row.get("ticker") or "").upper().strip()
                name = (row.get("company_name") or "").strip()
                if ticker and name:
                    index[ticker] = name
            if len(rows) < batch_size:
                break
            offset += batch_size
            if offset > 100000:
                break

        logger.debug("Ticker validator: loaded %d securities", len(index))
    except Exception as e:
        logger.warning("Failed to load securities for ticker validation: %s", e)

    _SECURITIES_CACHE = index
    _SECURITIES_CACHE_TS = now
    return index


def _get_real_company_name(ticker: str) -> Optional[str]:
    """Get the real company name for a ticker.

    1. Check securities table (fast)
    2. Check yfinance disk cache (fast)
    3. Call yfinance API (slow, rate-limited)

    Returns company name or None if ticker doesn't exist.
    """
    ticker = ticker.upper().strip()

    # 1. Securities table
    securities = _load_securities_cache()
    if ticker in securities:
        return securities[ticker]

    # 2. yfinance disk cache
    cache = _load_yf_cache()
    now = time.time()
    if ticker in cache:
        entry = cache[ticker]
        if isinstance(entry, dict) and (now - entry.get("ts", 0)) < _YF_CACHE_TTL:
            return entry.get("name")  # May be None if ticker doesn't exist

    # 3. yfinance API (only for tickers not in cache or expired)
    try:
        import yfinance as yf
        obj = yf.Ticker(ticker)
        info = obj.info or {}

        # yfinance returns {"trailingPegRatio": null} for invalid tickers
        # Check for a real company name
        name = info.get("shortName") or info.get("longName")
        quote_type = info.get("quoteType")

        if name and quote_type:
            # Valid ticker
            cache[ticker] = {"name": name, "ts": now}
            _save_yf_cache()
            return name
        else:
            # Invalid ticker - cache the negative result
            cache[ticker] = {"name": None, "ts": now}
            _save_yf_cache()
            return None

    except Exception as e:
        logger.debug("yfinance lookup failed for %s: %s", ticker, e)
        # Cache failure as unknown (shorter TTL)
        cache[ticker] = {"name": None, "ts": now - _YF_CACHE_TTL + 3600}
        _save_yf_cache()
        return None


# ---------------------------------------------------------------------------
# Fuzzy company name matching
# ---------------------------------------------------------------------------

_COMPANY_SUFFIXES = re.compile(
    r"\b(inc\.?|incorporated|corp\.?|corporation|co\.?|company|ltd\.?|limited|"
    r"plc|llc|holdings?|group|sa|a/?s|ab|nv|ag|se|the|class\s*[a-z])\b",
    re.IGNORECASE,
)


def _normalize_name(name: str) -> str:
    """Strip suffixes and normalize for comparison."""
    name = _COMPANY_SUFFIXES.sub("", name)
    name = re.sub(r"[^a-z0-9\s]", "", name.lower())
    return " ".join(name.split()).strip()


def _names_match(llm_context: str, real_name: str, threshold: float = 0.65) -> bool:
    """Check if the LLM's company context matches the real company name.

    Uses multiple strategies:
    1. Normalized substring containment (either direction)
    2. SequenceMatcher ratio for fuzzy matching

    Args:
        llm_context: What the LLM thinks the company is (or article text snippet)
        real_name: The actual company name from securities/yfinance
        threshold: Minimum similarity ratio (0.0 - 1.0)
    """
    norm_llm = _normalize_name(llm_context)
    norm_real = _normalize_name(real_name)

    if not norm_llm or not norm_real:
        return False

    # Strategy 1: one contains the other (or first significant word matches)
    if norm_real in norm_llm or norm_llm in norm_real:
        return True

    # Strategy 2: first word match (e.g. "apple" vs "apple inc")
    llm_first = norm_llm.split()[0] if norm_llm else ""
    real_first = norm_real.split()[0] if norm_real else ""
    if llm_first and real_first and len(llm_first) >= 4 and llm_first == real_first:
        return True

    # Strategy 3: fuzzy ratio
    ratio = SequenceMatcher(None, norm_llm, norm_real).ratio()
    return ratio >= threshold


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_extracted_tickers(
    tickers: List[str],
    companies: List[str],
    article_text: str,
    strict: bool = True,
) -> List[str]:
    """Validate LLM-extracted tickers against real company data.

    For each ticker:
    1. Look up the real company name (securities table → yfinance)
    2. If the ticker doesn't exist at all → reject
    3. If strict mode: check if the real company name matches something
       in the LLM's company list or the article text → reject mismatches
    4. If the ticker was explicitly mentioned in the article text ($TICKER,
       (TICKER), NASDAQ:TICKER) → always keep (LLM didn't guess, it read it)

    Args:
        tickers: Raw tickers from LLM extraction
        companies: Company names the LLM extracted from the same article
        article_text: The article title + content for context matching
        strict: If True, reject tickers whose real name doesn't match context

    Returns:
        List of validated tickers (subset of input)
    """
    if not tickers:
        return []

    validated: List[str] = []
    article_upper = (article_text or "").upper()
    companies_text = " ".join(companies) if companies else ""

    for ticker in tickers:
        ticker = ticker.upper().strip()
        if not ticker:
            continue

        # Check if ticker was explicitly mentioned in article
        # Patterns: $AAPL, (AAPL), NASDAQ:AAPL, NYSE:AAPL, TSX:AAPL, AAPL)
        explicit_patterns = [
            f"${ticker}",
            f"({ticker})",
            f"NASDAQ:{ticker}",
            f"NYSE:{ticker}",
            f"TSX:{ticker}",
            f"ASX:{ticker}",
            f"TSE:{ticker}",
            f"(NASDAQ: {ticker})",
            f"(NYSE: {ticker})",
        ]
        is_explicit = any(p in article_upper for p in explicit_patterns)

        if is_explicit:
            # Ticker was literally in the text -- trust it
            validated.append(ticker)
            logger.debug("Ticker %s: KEPT (explicitly mentioned in article)", ticker)
            continue

        # Look up real company name
        real_name = _get_real_company_name(ticker)

        if real_name is None:
            # Ticker doesn't exist at all
            logger.info("Ticker %s: REJECTED (not found in securities or yfinance)", ticker)
            continue

        if not strict:
            # Non-strict: ticker exists, that's enough
            validated.append(ticker)
            continue

        # Strict: check if the real company name matches the article context
        # Try matching against the companies list first, then article text
        context_to_check = companies_text if companies_text else article_text[:2000]

        if _names_match(context_to_check, real_name):
            validated.append(ticker)
            logger.debug(
                "Ticker %s: KEPT (real name '%s' matches context)",
                ticker, real_name,
            )
        else:
            # Last check: does the real company name appear anywhere in the article?
            real_norm = _normalize_name(real_name)
            article_norm = _normalize_name(article_text[:5000])
            if real_norm and len(real_norm) >= 4 and real_norm in article_norm:
                validated.append(ticker)
                logger.debug(
                    "Ticker %s: KEPT (real name '%s' found in article body)",
                    ticker, real_name,
                )
            else:
                logger.info(
                    "Ticker %s: REJECTED (real company '%s' doesn't match article context)",
                    ticker, real_name,
                )

    return validated


def extract_and_validate_tickers(
    summary_data: dict,
    title: str,
    article_text: str,
) -> List[str]:
    """Extract tickers from LLM summary data with real-company validation.

    Shared helper used by all article-processing jobs to ensure consistent
    ticker extraction across the pipeline.

    Steps:
      1. Collect tickers from summary_data["tickers"]
      2. Infer additional tickers from summary_data["companies"]
      3. Validate format (reject company names, nonsense)
      4. Validate against real company names (securities table -> yfinance)
         to prevent mismatches like "Preat Corp" -> PRE (which is Prenetics)
      5. Fall back to title-based inference if nothing found

    Returns:
        List of validated, normalized ticker strings.
    """
    from research_utils import validate_ticker_format, normalize_ticker

    raw_tickers: List[str] = []

    if isinstance(summary_data, dict) and summary_data:
        # 1. Direct tickers from LLM
        ai_tickers = list(summary_data.get("tickers", []))

        # 1b. Cross-check against ticker_sentiment — tickers the LLM couldn't
        #     write a sentiment reason for are likely sidebar/ad noise.
        ticker_sentiments = summary_data.get("ticker_sentiment", [])
        if isinstance(ticker_sentiments, list) and ticker_sentiments and ai_tickers:
            sentiment_tickers = set()
            for ts in ticker_sentiments:
                if isinstance(ts, dict) and ts.get("ticker"):
                    sentiment_tickers.add(ts["ticker"].upper().strip().lstrip("$"))
            if sentiment_tickers:
                filtered = [t for t in ai_tickers if t.upper().strip().lstrip("$") in sentiment_tickers]
                dropped = set(ai_tickers) - set(filtered)
                if dropped:
                    logger.info(
                        "Dropped %d ticker(s) with no ticker_sentiment entry (likely sidebar noise): %s",
                        len(dropped), sorted(dropped),
                    )
                ai_tickers = filtered

        # 2. Infer from company names
        companies = summary_data.get("companies", [])
        try:
            from ticker_inference import infer_tickers_from_companies
            ai_tickers = list(set(ai_tickers) | set(infer_tickers_from_companies(companies)))
        except Exception as e:
            logger.warning("Company->ticker inference failed: %s", e)
            companies = []

        # 3. Format validation + normalization
        for t in ai_tickers:
            if not validate_ticker_format(t):
                logger.debug("Rejected invalid ticker format: %s", t)
                continue
            normalized = normalize_ticker(t)
            if normalized:
                raw_tickers.append(normalized)
    else:
        companies = []

    # 4. Cross-reference against real company data
    if raw_tickers:
        try:
            validated = validate_extracted_tickers(
                tickers=raw_tickers,
                companies=companies if companies else [],
                article_text=f"{title}\n{article_text}" if article_text else title,
                strict=True,
            )
            removed = set(raw_tickers) - set(validated)
            if removed:
                logger.info(
                    "Ticker validation removed %d/%d: %s",
                    len(removed), len(raw_tickers), sorted(removed),
                )
            return validated
        except Exception as e:
            logger.warning("Ticker validation failed, using unvalidated: %s", e)
            return raw_tickers

    # 5. Fallback: infer from title
    try:
        from ticker_inference import infer_tickers_from_text
        inferred = infer_tickers_from_text(title)
        if inferred:
            logger.info("Inferred ticker(s) from title: %s", inferred)
            try:
                validated = validate_extracted_tickers(
                    tickers=inferred,
                    companies=[],
                    article_text=f"{title}\n{article_text}" if article_text else title,
                    strict=True,
                )
                return validated
            except Exception:
                return inferred
    except Exception as e:
        logger.warning("Title/company ticker inference failed: %s", e)

    return []
