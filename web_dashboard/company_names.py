"""Ticker -> company name, so screens can show "CMI · Cummins Inc" not just "CMI".

A ticker is only readable to someone who already knows it. Names live in the
Supabase `securities` table (`company_name`, properly cased — the Research
Postgres `securities.name` is uppercase and less presentable).

Coverage is partial: ETFs and some Canadian listings have no row. Every helper
here falls back to the ticker itself rather than showing a blank, so a missing
name degrades to today's behaviour instead of an empty column.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 3600
# PostgREST caps a plain select at 1000 rows, so full loads are paged and
# targeted loads filter by ticker instead of scanning.
_PAGE_SIZE = 1000
_IN_CHUNK = 200
_cache: dict[str, str] = {}
_cache_loaded_at = 0.0
_lock = threading.Lock()

# Suffixes worth trimming for display; the legal form rarely helps a reader.
_NOISE_SUFFIXES = (
    " CLASS A",
    " CLASS B",
    " COMMON STOCK",
    " ORDINARY SHARES",
)

# Words title() would ruin: initialisms and legal forms that belong in capitals.
_KEEP_UPPERCASE = frozenset(
    {
        "ETF", "ETN", "REIT", "ADR", "GDR", "SPAC",
        "GE", "AI", "US", "USA", "UK", "EU", "TSX", "NYSE",
        "PLC", "NV", "SA", "AG", "AB", "SE", "LP", "LLC", "SPA",
        "II", "III", "IV", "V", "VI",
        "3M", "AT&T", "H&R", "S&P",
    }
)


def tidy_company_name(raw: Any) -> str:
    """Trim legal boilerplate and fix shouty names for display."""
    name = str(raw or "").strip()
    if not name:
        return ""
    upper = name.upper()
    for suffix in _NOISE_SUFFIXES:
        if upper.endswith(suffix):
            name = name[: -len(suffix)].strip()
            upper = name.upper()
    # "CUMMINS INC" reads badly next to prose; "Cummins Inc" does not. Names that
    # are already mixed case are left alone (e.g. "iShares", "lululemon").
    if name == upper and len(name) > 4:
        name = name.title()
        # title() also lowercases initialisms: "GE VERNOVA" -> "Ge Vernova",
        # "MINERS ETF" -> "Miners Etf". Put the known ones back.
        name = " ".join(
            word.upper() if word.upper() in _KEEP_UPPERCASE else word
            for word in name.split(" ")
        )
    return name


def get_company_names(supabase_client: Any, tickers: list[str] | None = None) -> dict[str, str]:
    """{ticker: display name} for the tickers asked for (or everything cached).

    Cached for an hour: names change about never, and every page wants them.
    """
    global _cache_loaded_at
    wanted = {str(t).upper().strip() for t in (tickers or []) if str(t).strip()}
    now = time.time()
    with _lock:
        fresh = _cache and (now - _cache_loaded_at) < _CACHE_TTL_SECONDS
        if fresh:
            return {t: _cache[t] for t in wanted if t in _cache} if wanted else dict(_cache)

    names: dict[str, str] = {}
    try:
        table = supabase_client.supabase.table("securities")
        if wanted:
            # Ask for exactly the tickers needed. A bare select() is capped at
            # 1000 rows by PostgREST, which silently returns an arbitrary slice
            # of the table and no name for anything outside it.
            ordered = sorted(wanted)
            for start in range(0, len(ordered), _IN_CHUNK):
                chunk = ordered[start : start + _IN_CHUNK]
                result = table.select("ticker, company_name").in_("ticker", chunk).execute()
                names.update(_rows_to_names(result.data))
        else:
            page = 0
            while True:
                lo = page * _PAGE_SIZE
                result = (
                    table.select("ticker, company_name")
                    .range(lo, lo + _PAGE_SIZE - 1)
                    .execute()
                )
                rows = result.data or []
                names.update(_rows_to_names(rows))
                if len(rows) < _PAGE_SIZE:
                    break
                page += 1
    except Exception as exc:
        logger.warning("company name lookup failed: %s", exc)
        return {}

    with _lock:
        _cache.update(names)
        if not wanted:
            _cache_loaded_at = now
    return names


def _rows_to_names(rows: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in rows or []:
        ticker = str(row.get("ticker") or "").upper().strip()
        name = tidy_company_name(row.get("company_name"))
        if ticker and name and name.upper() != ticker:
            out[ticker] = name
    return out


def attach_company_names(
    supabase_client: Any,
    items: list[dict[str, Any]],
    *,
    key: str = "ticker",
    field: str = "company_name",
) -> None:
    """Add a display name to each row that has a ticker. Missing names are omitted."""
    if not items:
        return
    tickers = [str(i.get(key) or "") for i in items if i.get(key)]
    if not tickers:
        return
    names = get_company_names(supabase_client, tickers)
    for item in items:
        ticker = str(item.get(key) or "").upper().strip()
        if ticker and ticker in names:
            item[field] = names[ticker]
