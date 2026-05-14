"""Infer ``research_articles.sector`` for ETF Analysis from holding tickers + ``securities``.

Research Postgres is tried first; Supabase ``securities`` is optional fallback when research
has no row or null sector. Used by the one-time backfill script and by ``etf_group_analysis``.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)

_MAX_TICKERS = 20
_MAX_SECTOR_LEN = 100


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
