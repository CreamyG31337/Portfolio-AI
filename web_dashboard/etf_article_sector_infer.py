"""Infer ``research_articles.sector`` for ETF Analysis from holding tickers + ``securities``.

Research Postgres is tried first; Supabase ``securities`` is optional fallback when research
has no row or null sector. Used by the one-time backfill script and by ``etf_group_analysis``.

**Why this module exists (meta foundation):** scheduled ``sector_meta_analysis`` buckets rows
by ``research_articles.sector``. ETF symbols often have **no** ``securities.sector``; we therefore
use a **tiered** resolver (holdings → ETF from ``etf-analysis://`` URL → curated map). See
``docs/meta_analysis_roadmap.md`` → *Data foundation (ETF Analysis → sector meta)*.

TODO(meta-foundation): when adding ETFs to the watchtower, extend ``KNOWN_ETF_IMPUTED_SECTOR`` or
improve ``refresh_securities_metadata`` / securities ingest so ``imputed_map`` is not the only signal.

TODO(meta-foundation): optional future column ``sector_resolution`` (holdings|etf_security|imputed_map)
if we need analytics without parsing logs.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)

_MAX_TICKERS = 20
_MAX_SECTOR_LEN = 100

# Parsed from ``save_article`` URLs in ``etf_group_analysis`` (``etf-analysis://{ETF}/{date}``).
_ETF_ANALYSIS_URL = re.compile(r"etf-analysis://([A-Za-z0-9.-]+)/", re.IGNORECASE)

# When ``securities.sector`` is null for the ETF symbol (common for ETFs), use a stable GICS-style
# label for sector_meta bucketing. Broad index ETFs are intentionally ``Multi-sector``.
#
# TODO(meta-foundation): keep in sync with ``ETF_NAMES`` / watchtower universe in ``etf_group_analysis.py``.
KNOWN_ETF_IMPUTED_SECTOR: dict[str, str] = {
    "ARKK": "Information Technology",
    "ARKQ": "Industrials",
    "ARKW": "Information Technology",
    "ARKG": "Health Care",
    "ARKF": "Financials",
    "ARKX": "Industrials",
    "IZRL": "Information Technology",
    "PRNT": "Industrials",
    "IVV": "Multi-sector",
    "IWM": "Multi-sector",
    "IWC": "Multi-sector",
    "IWO": "Multi-sector",
}


def article_row_tickers(row: dict[str, Any]) -> list[str]:
    """Normalize tickers from a ``research_articles`` row (array or legacy single column)."""
    raw = row.get("tickers")
    if isinstance(raw, list) and raw:
        out: list[str] = []
        for x in raw:
            s = str(x).upper().strip()
            if s:
                out.append(s)
        return out[:_MAX_TICKERS]
    single = row.get("ticker")
    if single:
        s = str(single).upper().strip()
        if s:
            return [s]
    return []


def _lookup_research(postgres: Any, ticker: str) -> str | None:
    try:
        rows = postgres.execute_query(
            "SELECT sector FROM securities WHERE UPPER(TRIM(ticker)) = %s LIMIT 1",
            (ticker.upper().strip(),),
        )
        if rows and rows[0].get("sector"):
            v = str(rows[0]["sector"]).strip()
            return v if v else None
    except Exception as exc:
        logger.debug("research securities lookup failed for %s: %s", ticker, exc)
    return None


def _lookup_supabase(supabase: Any, ticker: str) -> str | None:
    if supabase is None:
        return None
    try:
        res = (
            supabase.supabase.table("securities")
            .select("sector")
            .eq("ticker", ticker.upper().strip())
            .limit(1)
            .execute()
        )
        data = res.data or []
        if data and data[0].get("sector"):
            v = str(data[0]["sector"]).strip()
            return v if v else None
    except Exception as exc:
        logger.debug("supabase securities lookup failed for %s: %s", ticker, exc)
    return None


def dominant_sector_for_holdings(
    postgres: Any,
    supabase: Any | None,
    tickers: list[str],
    *,
    max_tickers: int = _MAX_TICKERS,
) -> str | None:
    """Return the most common non-empty sector among ``tickers``, or None if none found."""
    tickers_u = [str(t).upper().strip() for t in tickers if str(t).strip()][:max_tickers]
    sectors: list[str] = []
    for tk in tickers_u:
        s = _lookup_research(postgres, tk)
        if not s:
            s = _lookup_supabase(supabase, tk)
        if s:
            sectors.append(s)
    if not sectors:
        return None
    top = Counter(sectors).most_common(1)[0][0]
    return top[:_MAX_SECTOR_LEN]


def parse_etf_ticker_from_analysis_url(url: str | None) -> str | None:
    """Return the ETF ticker from ``etf-analysis://TICKER/YYYY-MM-DD`` URLs, or None."""
    if not url or not isinstance(url, str):
        return None
    m = _ETF_ANALYSIS_URL.search(url.strip())
    if not m:
        return None
    return m.group(1).upper().strip()


def resolve_sector_for_etf_analysis_article(
    postgres: Any,
    supabase: Any | None,
    row: dict[str, Any],
) -> tuple[str | None, str]:
    """Resolve ``sector`` for one ETF Analysis row.

    Order: (1) mode sector from holding tickers in ``securities``; (2) same for ETF from URL;
    (3) ``KNOWN_ETF_IMPUTED_SECTOR`` for that ETF. Returns ``(sector, source)`` where source is
    ``holdings``, ``etf_security``, ``imputed_map``, or ``none``.
    """
    tickers = article_row_tickers(row)
    if tickers:
        s = dominant_sector_for_holdings(postgres, supabase, tickers)
        if s:
            return s, "holdings"

    etf = parse_etf_ticker_from_analysis_url(row.get("url"))
    if etf:
        s2 = dominant_sector_for_holdings(postgres, supabase, [etf])
        if s2:
            return s2, "etf_security"
        s3 = KNOWN_ETF_IMPUTED_SECTOR.get(etf)
        if s3:
            return s3[:_MAX_SECTOR_LEN], "imputed_map"

    return None, "none"
