#!/usr/bin/env python3
"""
Ticker inference helpers.

Provides conservative company-name -> ticker inference backed by the
`securities` table, with in-memory caching to avoid repeated lookups.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Dict, Iterable, List, Optional, Set

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 3600
_company_to_tickers_cache: Optional[Dict[str, Set[str]]] = None
_cache_loaded_at: float = 0.0

_SUFFIX_TOKENS = {
    "INC",
    "INCORPORATED",
    "CORP",
    "CORPORATION",
    "CO",
    "COMPANY",
    "LTD",
    "LIMITED",
    "PLC",
    "LLC",
    "HOLDINGS",
    "HOLDING",
    "GROUP",
    "SA",
    "NV",
    "AG",
    "THE",
}


def _canonicalize_company_name(name: str) -> str:
    text = (name or "").upper().strip()
    if not text:
        return ""
    text = text.replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9\s]", " ", text)
    tokens = [tok for tok in text.split() if tok and tok not in _SUFFIX_TOKENS]
    return " ".join(tokens)


def _load_company_ticker_index() -> Dict[str, Set[str]]:
    global _company_to_tickers_cache, _cache_loaded_at

    now = time.time()
    if (
        _company_to_tickers_cache is not None
        and (now - _cache_loaded_at) < _CACHE_TTL_SECONDS
    ):
        return _company_to_tickers_cache

    index: Dict[str, Set[str]] = {}
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
                ticker = str(row.get("ticker") or "").upper().strip()
                company_name = str(row.get("company_name") or "").strip()
                if not ticker or not company_name:
                    continue
                canonical = _canonicalize_company_name(company_name)
                if not canonical:
                    continue
                if canonical not in index:
                    index[canonical] = set()
                index[canonical].add(ticker)

            if len(rows) < batch_size:
                break
            offset += batch_size
            if offset > 100000:
                logger.warning("Ticker inference securities scan safety limit reached")
                break

        logger.info("Ticker inference company index loaded: %s canonical names", len(index))
    except Exception as e:
        logger.warning("Failed loading company->ticker index: %s", e)

    _company_to_tickers_cache = index
    _cache_loaded_at = now
    return index


def infer_tickers_from_companies(companies: Iterable[str]) -> List[str]:
    """Infer ticker candidates from company names.

    Strategy:
    - Exact canonical-name match in `securities` index.
    - No fuzzy matching: prefer precision over recall to avoid junk tickers.
    """
    company_names = [c for c in (companies or []) if isinstance(c, str) and c.strip()]
    if not company_names:
        return []

    index = _load_company_ticker_index()
    if not index:
        return []

    inferred: Set[str] = set()

    for company in company_names:
        canonical = _canonicalize_company_name(company)
        if not canonical:
            continue

        if canonical in index:
            inferred.update(index[canonical])

    return sorted(inferred)


def infer_tickers_from_text(text: str) -> List[str]:
    """Infer ticker candidates by matching company names inside free text.

    Conservative rules:
    - Match canonical company names as whole phrases.
    - Only accept names mapped to a single ticker to avoid ambiguity.
    - Skip very short names that are likely noisy.
    """
    if not text or not isinstance(text, str):
        return []

    index = _load_company_ticker_index()
    if not index:
        return []

    canonical_text = f" {_canonicalize_company_name(text)} "
    if not canonical_text.strip():
        return []

    inferred: Set[str] = set()
    for company_name, tickers in index.items():
        if len(tickers) != 1:
            continue
        if len(company_name) < 8:
            continue
        if " " not in company_name and len(company_name) < 10:
            continue
        phrase = f" {company_name} "
        if phrase in canonical_text:
            inferred.update(tickers)

    return sorted(inferred)
