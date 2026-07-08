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
from typing import Any, Dict, Iterable, List, Literal, Optional, Set

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


def _is_us_primary_symbol(symbol: str) -> bool:
    """US primary listings have no exchange suffix (no dot) and are short letters.

    Foreign secondary listings look like AB4.F, WA3.MU, CM.TO, ENV.AX, US2927651040.SG.
    """
    return bool(re.fullmatch(r"[A-Z]{1,5}", symbol or ""))


def _lead_token(oge_canonical: str) -> Optional[str]:
    """Distinctive lead brand token from an OGE name (first token >= 3 chars)."""
    tokens = oge_canonical.split()
    for tok in tokens:
        if len(tok) >= 3:
            return tok
    for tok in tokens:
        if len(tok) >= 2:
            return tok
    return None


def _matches_company(oge_canonical: str, candidate_name: str) -> bool:
    """Strong match: token overlap AND the OGE lead brand token is present.

    The lead-token gate rejects loose single-common-token matches such as
    'JBG SMITH PPTYS' -> 'A. O. Smith' (only 'SMITH' overlaps).
    """
    if not _names_overlap(oge_canonical, candidate_name):
        return False
    lead = _lead_token(oge_canonical)
    if not lead:
        return False
    candidate_tokens = set(_canonicalize_company_name(candidate_name).split())
    return lead in candidate_tokens


def _select_best_equity(
    oge_canonical: str, equity_quotes: List[dict]
) -> Optional[dict]:
    """Pick a single unambiguous US-primary equity/ETF.

    Requires a strong name match (overlap + lead-token), then keeps only US
    primary listings (no foreign exchange suffix). Accepts when exactly one
    distinct symbol remains, or when all remaining candidates map to the same
    company name (shortest symbol wins — e.g. common shares over unit tickers).
    """
    matching = [q for q in equity_quotes if _matches_company(oge_canonical, q["name"])]
    if not matching:
        return None

    primary = [q for q in matching if _is_us_primary_symbol(q["symbol"])]
    if not primary:
        return None

    distinct_symbols = {q["symbol"] for q in primary}
    if len(distinct_symbols) == 1:
        return min(primary, key=lambda q: len(q["symbol"]))

    distinct_names = {_canonicalize_company_name(q["name"]) for q in primary}
    if len(distinct_names) == 1:
        return min(primary, key=lambda q: len(q["symbol"]))

    return None


def resolve_from_yfinance(
    company_name: str, *, max_retries: int = 3
) -> Optional[tuple[str, str, float]]:
    """Search yfinance for a single unambiguous equity/ETF match.

    Prefers the US primary listing when a company has foreign secondary listings.
    Retries with exponential backoff on rate limiting.

    Returns (ticker, quote_type, confidence) or None.
    """
    if not company_name or len(company_name) < 3:
        return None

    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed; skipping yfinance ticker resolution")
        return None

    try:
        from yfinance.exceptions import YFRateLimitError
    except ImportError:  # older yfinance without the dedicated exception
        YFRateLimitError = None  # type: ignore[assignment]

    oge_canonical = canonicalize_oge_company_name(company_name)

    quotes: List[dict] = []
    for attempt in range(max_retries):
        _throttle_yfinance()
        try:
            search = yf.Search(
                company_name,
                max_results=10,
                news_count=0,
                enable_fuzzy_query=True,
            )
            quotes = search.quotes if hasattr(search, "quotes") else []
            break
        except Exception as exc:  # noqa: BLE001
            is_rate_limit = YFRateLimitError is not None and isinstance(
                exc, YFRateLimitError
            )
            if is_rate_limit and attempt < max_retries - 1:
                backoff = 2.0 * (2**attempt)
                logger.debug(
                    "yfinance rate-limited on %r; backing off %.1fs", company_name, backoff
                )
                time.sleep(backoff)
                continue
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
        equity_quotes.append(
            {"symbol": symbol, "quote_type": quote_type, "name": long_name}
        )

    match = _select_best_equity(oge_canonical, equity_quotes)
    if not match:
        return None

    asset_type = "ETF" if match["quote_type"] == "ETF" else "Stock"
    return match["symbol"], asset_type, 0.75


class LLMResolutionError(RuntimeError):
    """Transient LLM/infra failure; the caller should retry (not mark done)."""


_LLM_TICKER_PROMPT = """You map a U.S. government financial-disclosure asset description to its stock ticker.

Asset description (from an OGE Form 278-T filing):
"{description}"

Rules:
- Return the ticker of the U.S.-listed common stock or ETF for this issuer.
- Use the PRIMARY U.S. listing symbol only (no exchange suffix like .F, .TO, .SG).
- If it is a bond, municipal security, private fund, or you are not confident it
  is a U.S.-listed equity/ETF, return null for the ticker.
- Do NOT guess. Precision matters far more than coverage.

Return ONLY compact JSON, no prose:
{{"ticker": "SYM or null", "company_name": "official company name or null", "confidence": 0.0}}
"""


def _build_llm_ticker_prompt(description: str) -> str:
    return _LLM_TICKER_PROMPT.format(description=(description or "").strip()[:300])


def _parse_llm_ticker_json(text: str) -> Optional[dict]:
    """Parse the model's JSON reply, tolerating code fences and extra prose."""
    import json

    if not text or not text.strip():
        return None
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def confirm_ticker_symbol(
    symbol: str, description: str, llm_company_name: Optional[str] = None
) -> Optional[tuple[str, str]]:
    """Verify a proposed ticker actually exists and belongs to this issuer.

    Guards against LLM hallucination: looks the symbol up on yfinance, confirms
    it resolves to a U.S. primary equity/ETF, and requires the real company name
    to token-overlap the OGE description (or the model's proposed name).

    Returns (normalized_symbol, asset_type) when confirmed, else None.
    """
    normalized = _validate_resolved_ticker(symbol)
    if not normalized or not _is_us_primary_symbol(normalized):
        return None

    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed; cannot validate LLM ticker")
        return None

    _throttle_yfinance()
    try:
        search = yf.Search(
            normalized, max_results=10, news_count=0, enable_fuzzy_query=False
        )
        quotes = search.quotes if hasattr(search, "quotes") else []
    except Exception as exc:  # noqa: BLE001
        logger.debug("yfinance validation search failed for %r: %s", normalized, exc)
        return None

    exact = None
    for quote in quotes or []:
        if str(quote.get("symbol") or "").upper().strip() == normalized:
            exact = quote
            break
    if not exact:
        return None

    quote_type = str(exact.get("quoteType") or exact.get("typeDisp") or "").upper()
    if quote_type not in ("EQUITY", "ETF"):
        return None

    real_name = str(exact.get("longname") or exact.get("shortname") or "")
    oge_canonical = canonicalize_oge_company_name(description)
    name_ok = _matches_company(oge_canonical, real_name)
    if not name_ok and llm_company_name:
        name_ok = _matches_company(
            canonicalize_oge_company_name(llm_company_name), real_name
        )
    if not name_ok:
        return None

    asset_type = "ETF" if quote_type == "ETF" else "Stock"
    return normalized, asset_type


def resolve_from_llm(
    description: str,
    *,
    ollama_client: Any,
    model: Optional[str] = None,
    validate: bool = True,
) -> Optional[tuple[str, str, float]]:
    """Resolve a ticker via LLM, then validate before trusting it.

    Returns (ticker, asset_type, confidence) on a validated hit, or None when
    the model declines / the proposal fails validation. Raises
    :class:`LLMResolutionError` on transient infra failure so the queue retries.
    """
    prompt = _build_llm_ticker_prompt(description)
    try:
        raw = ollama_client.generate_completion(
            prompt, model=model, json_mode=True, temperature=0.0
        )
    except Exception as exc:  # noqa: BLE001
        raise LLMResolutionError(f"LLM call failed: {exc}") from exc

    if raw is None or not str(raw).strip():
        # generate_completion swallows infra errors and returns None; treat as
        # transient so the task is retried rather than marked done.
        raise LLMResolutionError("LLM returned no response")

    parsed = _parse_llm_ticker_json(str(raw))
    if not parsed:
        return None

    proposed = parsed.get("ticker")
    if proposed is None or str(proposed).strip().lower() in ("", "null", "none"):
        return None

    llm_name = parsed.get("company_name")
    try:
        confidence = float(parsed.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    if not validate:
        normalized = _validate_resolved_ticker(proposed)
        if not normalized or not _is_us_primary_symbol(normalized):
            return None
        return normalized, "Stock", min(confidence, 0.6)

    confirmed = confirm_ticker_symbol(str(proposed), description, llm_name)
    if not confirmed:
        return None
    symbol, asset_type = confirmed
    return symbol, asset_type, max(0.6, min(confidence, 0.85))


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
