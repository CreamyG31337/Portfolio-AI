"""
Load holdings-weighted ("look-through") fundamentals for ETF signal scoring.

Resolves a securities row into either the raw company fundamentals (non-ETF)
or aggregated look-through metrics from etf_holdings_log + holdings' securities.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from web_dashboard.signals.etf_lookthrough import compute_lookthrough_fundamentals
from web_dashboard.signals.fundamental_signal import _looks_like_etf

logger = logging.getLogger(__name__)

# PostgREST URL-length / response-size safety for .in_("ticker", ...)
_SECURITIES_CHUNK_SIZE = 200


def _supabase_root(supabase_client: Any) -> Any:
    """Accept SupabaseClient wrapper or raw postgrest client."""
    return getattr(supabase_client, "supabase", supabase_client)


def _fetch_latest_holdings(
    postgres_client: Any, etf_ticker: str
) -> tuple[List[Dict[str, Any]], Optional[str]]:
    """Return (holdings for compute_lookthrough, as_of YYYY-MM-DD) or ([], None)."""
    rows = postgres_client.execute_query(
        """
        SELECT date, holding_ticker, weight_percent
        FROM etf_holdings_log
        WHERE etf_ticker = %s
          AND shares_held > 0
          AND date = (
            SELECT MAX(date)
            FROM etf_holdings_log
            WHERE etf_ticker = %s AND shares_held > 0
          )
        """,
        (etf_ticker, etf_ticker),
    )
    if not rows:
        return [], None

    as_of: Optional[str] = None
    holdings: List[Dict[str, Any]] = []
    for row in rows:
        if as_of is None and row.get("date") is not None:
            as_of = str(row["date"])[:10]
        ticker = row.get("holding_ticker")
        if not ticker:
            continue
        holdings.append(
            {
                "ticker": str(ticker).strip().upper(),
                "weight_percent": row.get("weight_percent"),
            }
        )
    return holdings, as_of


def _fetch_securities_by_tickers(
    supabase_client: Any, tickers: List[str]
) -> Dict[str, Dict[str, Any]]:
    """Batch-fetch securities rows, chunking to stay under PostgREST limits."""
    root = _supabase_root(supabase_client)
    by_ticker: Dict[str, Dict[str, Any]] = {}
    unique = sorted({t.upper() for t in tickers if t})
    for i in range(0, len(unique), _SECURITIES_CHUNK_SIZE):
        chunk = unique[i : i + _SECURITIES_CHUNK_SIZE]
        result = root.table("securities").select("*").in_("ticker", chunk).execute()
        for row in result.data or []:
            t = row.get("ticker")
            if t:
                by_ticker[str(t).upper()] = row
    return by_ticker


def resolve_signal_fundamentals(
    ticker: str,
    securities_row: Optional[Dict[str, Any]],
    supabase_client: Any,
    postgres_client: Any = None,
) -> Optional[Dict[str, Any]]:
    """Resolve fundamentals for SignalEngine / FundamentalSignal.

    Non-ETF (or missing row) → return ``securities_row`` unchanged.
    ETF with holdings → look-through metrics plus ``_lookthrough`` meta.
    ETF untracked / any DB error → return ``securities_row`` unchanged (never raise).
    """
    if securities_row is None or not _looks_like_etf(securities_row):
        return securities_row

    etf_ticker = (ticker or securities_row.get("ticker") or "").strip().upper()
    if not etf_ticker:
        return securities_row

    try:
        pg = postgres_client
        if pg is None:
            try:
                from postgres_client import PostgresClient
            except ImportError:
                from web_dashboard.postgres_client import PostgresClient

            pg = PostgresClient()

        holdings, as_of = _fetch_latest_holdings(pg, etf_ticker)
        if not holdings:
            logger.debug(
                "ETF look-through: no holdings for %s; falling back to securities row",
                etf_ticker,
            )
            return securities_row

        holding_tickers = [h["ticker"] for h in holdings]
        fundamentals_by_ticker = _fetch_securities_by_tickers(
            supabase_client, holding_tickers
        )
        result = compute_lookthrough_fundamentals(holdings, fundamentals_by_ticker)
        meta = {
            "etf_ticker": etf_ticker,
            "as_of": as_of or "",
            "holdings_total": result["holdings_total"],
            "holdings_with_fundamentals": result["holdings_with_fundamentals"],
            "weight_with_fundamentals": result["weight_with_fundamentals"],
        }
        return {**result["metrics"], "_lookthrough": meta}
    except Exception as exc:
        logger.warning(
            "ETF look-through failed for %s; falling back to securities row: %s",
            etf_ticker,
            exc,
            exc_info=True,
        )
        return securities_row
