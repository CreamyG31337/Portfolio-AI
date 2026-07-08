#!/usr/bin/env python3
"""
Executive branch (OGE 278-T) asset description -> equity ticker resolution.

Open Cabinet JSON rarely includes tickers; this module resolves company names
before inserting into congress_trades.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Literal, Optional, Set

from research_utils import normalize_ticker, validate_ticker_format
from ticker_inference import _canonicalize_company_name, infer_tickers_from_companies

logger = logging.getLogger(__name__)

ResolutionSource = Literal[
    "open_cabinet",
    "suffix",
    "securities",
    "yfinance",
    "cache",
    "skipped_bond",
    "unresolved",
]

_OGE_EXTRA_SUFFIX_TOKENS = {
    "INDS",
    "IND",
    "HLDGS",
    "HLDG",
    "INTL",
    "WORLDWIDE",
    "COM",
    "SYS",
    "TECH",
    "GRP",
    "SVCS",
    "SERVICES",
    "ENTERPRISES",
    "ENT",
    "MFG",
    "MANUFACTURING",
    "NEW",
    "OLD",
    "CL",
}

_BOND_MARKERS = (
    "DUE ",
    "YIELD TO MATURITY",
    "DIST TE",
    "DISTRICT",
    "MUNI",
    "MUNICIPAL",
    "TREAS",
    "TREASURY",
    " REVENUE",
    " BOND",
    " NOTE DUE",
    " SR NT",
    " SR UNSECURED",
    " DEBENTURE",
    " BE/R/",
    " FC ",
    " DTD ",
)

_TICKER_SUFFIX_RE = re.compile(r" - ([A-Z]{1,5})$")
_CLASS_SHARE_RE = re.compile(r"\bCLASS\s+[A-Z]\b", re.IGNORECASE)

_yfinance_last_call: float = 0.0
_YFINANCE_MIN_INTERVAL_SECONDS = 0.25


@dataclass(frozen=True)
class ExecutiveTickerResolution:
    """Result of resolving an OGE asset description to a tradable ticker."""

    ticker: Optional[str]
    source: ResolutionSource
    asset_type: str
    canonical_description: str
    company_name: str
    confidence: float
    skip_reason: Optional[str] = None


def canonicalize_oge_description(description: str) -> str:
    """Normalize an OGE asset description for display/audit (class shares stripped)."""
    text = (description or "").strip().upper()
    if not text:
        return ""
    text = _TICKER_SUFFIX_RE.sub("", text).strip()
    text = text.replace("&", " AND ")
    text = _CLASS_SHARE_RE.sub("", text)
    text = re.sub(r"[^A-Z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def canonicalize_oge_company_name(description: str) -> str:
    """Normalize company name for securities / yfinance lookup and cache keys."""
    base = canonicalize_oge_description(description)
    if not base:
        return ""
    base = _canonicalize_company_name(base)
    tokens = [tok for tok in base.split() if tok and tok not in _OGE_EXTRA_SUFFIX_TOKENS]
    return " ".join(tokens)


def is_bond_or_muni(description: str) -> bool:
    """Heuristic: skip fixed-income descriptions that have no equity ticker."""
    text = (description or "").upper()
    if not text:
        return False
    return any(marker in text for marker in _BOND_MARKERS)


def parse_ticker_suffix(description: str) -> Optional[str]:
    """Parse trailing ' - BAC' style ticker suffix from OGE descriptions."""
    match = _TICKER_SUFFIX_RE.search((description or "").strip().upper())
    if not match:
        return None
    ticker = normalize_ticker(match.group(1))
    return ticker if ticker and validate_ticker_format(ticker) else None


def _validate_resolved_ticker(ticker: Optional[str]) -> Optional[str]:
    if not ticker:
        return None
    normalized = normalize_ticker(ticker)
    if not normalized or not validate_ticker_format(normalized):
        return None
    return normalized


def resolve_from_securities(company_name: str) -> Optional[str]:
    """Exact canonical match against securities table (single ticker only)."""
    candidates = infer_tickers_from_companies([company_name])
    if len(candidates) != 1:
        return None
    return _validate_resolved_ticker(candidates[0])


def _names_overlap(oge_canonical: str, candidate_name: str) -> bool:
    oge_tokens = {t for t in oge_canonical.split() if len(t) > 1}
    candidate_tokens = {
        t for t in _canonicalize_company_name(candidate_name).split() if len(t) > 1
    }
    if not oge_tokens or not candidate_tokens:
        return False
    overlap = oge_tokens & candidate_tokens
    min_len = min(len(oge_tokens), len(candidate_tokens))
    return len(overlap) >= max(1, (min_len + 1) // 2)


def _throttle_yfinance() -> None:
    global _yfinance_last_call
    elapsed = time.time() - _yfinance_last_call
    if elapsed < _YFINANCE_MIN_INTERVAL_SECONDS:
        time.sleep(_YFINANCE_MIN_INTERVAL_SECONDS - elapsed)
    _yfinance_last_call = time.time()


def resolve_from_yfinance(company_name: str) -> Optional[tuple[str, str, float]]:
    """Search yfinance for a single unambiguous equity/ETF match.

    Returns (ticker, quote_type, confidence) or None.
    """
    if not company_name or len(company_name) < 3:
        return None

    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed; skipping yfinance ticker resolution")
        return None

    _throttle_yfinance()
    oge_canonical = canonicalize_oge_company_name(company_name)

    try:
        search = yf.Search(
            company_name,
            max_results=8,
            news_count=0,
            enable_fuzzy_query=True,
        )
        quotes = search.quotes if hasattr(search, "quotes") else []
    except Exception as exc:
        logger.debug("yfinance search failed for %r: %s", company_name, exc)
        return None

    equity_quotes: List[dict] = []
    for quote in quotes or []:
        quote_type = str(
            quote.get("quoteType") or quote.get("typeDisp") or ""
        ).upper()
        if quote_type not in ("EQUITY", "ETF"):
            continue
        symbol = _validate_resolved_ticker(quote.get("symbol"))
        if not symbol:
            continue
        long_name = str(quote.get("longname") or quote.get("shortname") or "")
        if not _names_overlap(oge_canonical, long_name):
            continue
        equity_quotes.append({"symbol": symbol, "quote_type": quote_type, "name": long_name})

    if len(equity_quotes) != 1:
        return None

    match = equity_quotes[0]
    asset_type = "ETF" if match["quote_type"] == "ETF" else "Stock"
    return match["symbol"], asset_type, 0.75


def load_og_asset_ticker_cache(
    cache_rows: Optional[Iterable[dict]] = None,
) -> Dict[str, dict]:
    """Build canonical_description -> cache row map."""
    mapping: Dict[str, dict] = {}
    for row in cache_rows or []:
        key = str(row.get("canonical_description") or "").strip()
        ticker = _validate_resolved_ticker(row.get("ticker"))
        if key and ticker:
            mapping[key] = row
    return mapping


def resolve_executive_asset(
    description: str,
    *,
    open_cabinet_ticker: Optional[str] = None,
    cache: Optional[Dict[str, dict]] = None,
    use_yfinance: bool = False,
) -> ExecutiveTickerResolution:
    """Resolve an OGE asset description to a validated equity ticker."""
    raw_description = (description or "").strip()
    company_name = canonicalize_oge_company_name(raw_description)
    canonical = company_name

    if not canonical:
        return ExecutiveTickerResolution(
            ticker=None,
            source="unresolved",
            asset_type="Stock",
            canonical_description="",
            company_name="",
            confidence=0.0,
            skip_reason="empty_description",
        )

    if is_bond_or_muni(raw_description):
        return ExecutiveTickerResolution(
            ticker=None,
            source="skipped_bond",
            asset_type="Bond",
            canonical_description=canonical,
            company_name=company_name,
            confidence=0.0,
            skip_reason="bond_or_muni",
        )

    cache_map = cache or {}
    cached = cache_map.get(canonical)
    if cached:
        ticker = _validate_resolved_ticker(cached.get("ticker"))
        if ticker:
            asset_type = "ETF" if str(cached.get("asset_type") or "").upper() == "ETF" else "Stock"
            return ExecutiveTickerResolution(
                ticker=ticker,
                source="cache",
                asset_type=asset_type,
                canonical_description=canonical,
                company_name=company_name,
                confidence=float(cached.get("confidence") or 1.0),
            )

    for source_name, candidate in (
        ("open_cabinet", open_cabinet_ticker),
        ("suffix", parse_ticker_suffix(raw_description)),
    ):
        ticker = _validate_resolved_ticker(candidate)
        if ticker:
            return ExecutiveTickerResolution(
                ticker=ticker,
                source=source_name,  # type: ignore[arg-type]
                asset_type="Stock",
                canonical_description=canonical,
                company_name=company_name,
                confidence=0.95,
            )

    securities_ticker = resolve_from_securities(company_name)
    if securities_ticker:
        return ExecutiveTickerResolution(
            ticker=securities_ticker,
            source="securities",
            asset_type="Stock",
            canonical_description=canonical,
            company_name=company_name,
            confidence=0.9,
        )

    if use_yfinance:
        yf_result = resolve_from_yfinance(company_name)
        if yf_result:
            ticker, asset_type, confidence = yf_result
            return ExecutiveTickerResolution(
                ticker=ticker,
                source="yfinance",
                asset_type=asset_type,
                canonical_description=canonical,
                company_name=company_name,
                confidence=confidence,
            )

    return ExecutiveTickerResolution(
        ticker=None,
        source="unresolved",
        asset_type="Stock",
        canonical_description=canonical,
        company_name=company_name,
        confidence=0.0,
        skip_reason="no_ticker_match",
    )


def summarize_resolution_results(
    results: Iterable[ExecutiveTickerResolution],
) -> Dict[str, int]:
    """Count resolutions by source for dry-run reporting."""
    counts: Dict[str, int] = {}
    for result in results:
        key = result.source if result.ticker is None else f"resolved_{result.source}"
        counts[key] = counts.get(key, 0) + 1
    return counts
