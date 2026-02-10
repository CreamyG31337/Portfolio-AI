"""Shared access helpers for fund-scoped watchlists with legacy fallback.

Strict mode
-----------
Set the environment variable ``WATCHLIST_STRICT=1`` to disable legacy
fallback entirely.  When strict mode is active, only ``watched_tickers_v2``
is queried and any fallback attempt is skipped.

Switch criteria (all must be true before enabling strict mode):
- v2 is populated for all required funds.
- All key endpoints tested with v2-only data.
- No fallback hits observed for a defined monitoring period.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

WATCHLIST_V2_TABLE = "watched_tickers_v2"
WATCHLIST_LEGACY_TABLE = "watched_tickers"

_STRICT_MODE: bool | None = None


def _is_strict_mode() -> bool:
    """Return True when legacy fallback is disabled."""
    global _STRICT_MODE
    if _STRICT_MODE is None:
        _STRICT_MODE = os.environ.get("WATCHLIST_STRICT", "").strip() in ("1", "true", "yes")
    return _STRICT_MODE


def _normalize_watchlist_rows(rows: list[dict[str, Any]], default_fund: str | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in rows:
        ticker = str(item.get("ticker") or "").upper().strip()
        if not ticker:
            continue

        fund = item.get("fund")
        if fund is None and default_fund is not None:
            fund = default_fund

        row = {
            "fund": fund,
            "ticker": ticker,
            "priority_tier": item.get("priority_tier") or "C",
            "is_active": bool(item.get("is_active", True)),
            "source": item.get("source"),
            "created_at": item.get("created_at"),
        }
        dedupe_key = (str(row.get("fund") or ""), ticker)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(row)
    return normalized


def get_active_watchlist_rows(
    supabase_client: Any,
    fund: str | None = None,
    fallback_if_empty: bool = True,
) -> list[dict[str, Any]]:
    """Return active watchlist rows using v2 table first, then legacy fallback.

    When ``WATCHLIST_STRICT=1`` is set (or *fallback_if_empty* is ``False``),
    the legacy table is never consulted.
    """
    strict = _is_strict_mode()
    effective_fallback = fallback_if_empty and not strict

    v2_rows: list[dict[str, Any]] = []
    try:
        query = supabase_client.supabase.table(WATCHLIST_V2_TABLE).select(
            "fund, ticker, priority_tier, is_active, source, created_at"
        ).eq("is_active", True)
        if fund:
            query = query.eq("fund", fund)
        v2_result = query.execute()
        v2_rows = _normalize_watchlist_rows(v2_result.data or [], default_fund=fund)
        if v2_rows or not effective_fallback:
            return v2_rows
    except Exception as e:
        logger.debug("watchlist v2 query failed (%s): %s", WATCHLIST_V2_TABLE, e)
        if strict:
            logger.warning("strict mode active — skipping legacy fallback after v2 failure")
            return []

    logger.info("watchlist fallback: v2 returned 0 rows for fund=%s, consulting legacy table", fund)

    try:
        legacy_result = supabase_client.supabase.table(WATCHLIST_LEGACY_TABLE).select(
            "ticker, priority_tier, is_active, source, created_at"
        ).eq("is_active", True).execute()
        return _normalize_watchlist_rows(legacy_result.data or [], default_fund=fund)
    except Exception as e:
        logger.warning("watchlist query failed (legacy=%s): %s", WATCHLIST_LEGACY_TABLE, e)
        return []


def get_active_watchlist_tickers(
    supabase_client: Any,
    fund: str | None = None,
    fallback_if_empty: bool = True,
) -> list[str]:
    """Return unique active tickers from watchlist rows."""
    rows = get_active_watchlist_rows(
        supabase_client=supabase_client,
        fund=fund,
        fallback_if_empty=fallback_if_empty,
    )
    return sorted({row["ticker"] for row in rows if row.get("ticker")})
