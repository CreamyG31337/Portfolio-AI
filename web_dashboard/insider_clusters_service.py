"""Insider cluster-buy detection (ROADMAP §4.2).

A cluster = N+ distinct insiders buying the same ticker within the lookback
window. Pure aggregation over rows the Form-4 collector already stores in
Supabase ``insider_trades`` — no new collection, no LLM.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Scraped Form-4 rows occasionally carry placeholder tickers.
_JUNK_TICKERS = {"", "-", "N/A", "NONE", "NULL"}

# Supabase REST returns at most 1000 rows per request regardless of .limit().
_PAGE_SIZE = 1000


def fetch_recent_insider_buys(
    supabase_client: Any, *, days: int = 30
) -> list[dict[str, Any]]:
    """All Purchase rows in the window, paginated past the 1000-row cap."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = (
            supabase_client.supabase.table("insider_trades")
            .select("ticker,insider_name,insider_title,transaction_date,shares,value")
            .eq("type", "Purchase")
            .gte("transaction_date", cutoff)
            .order("transaction_date", desc=True)
            .range(offset, offset + _PAGE_SIZE - 1)
            .execute()
        )
        data = page.data or []
        rows.extend(data)
        if len(data) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return rows


def detect_cluster_buys(
    rows: list[dict[str, Any]],
    *,
    min_insiders: int = 3,
    held_tickers: set[str] | None = None,
    watched_tickers: set[str] | None = None,
    limit: int = 15,
) -> list[dict[str, Any]]:
    """Group buy rows by ticker; keep tickers with >= min_insiders distinct buyers.

    Distinctness is by insider_name — one insider averaging in over several
    Form 4s is conviction from one person, not a cluster.
    """
    held = {t.upper() for t in (held_tickers or set())}
    watched = {t.upper() for t in (watched_tickers or set())}

    by_ticker: dict[str, dict[str, Any]] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "").upper().strip()
        name = str(row.get("insider_name") or "").strip()
        if ticker in _JUNK_TICKERS or not name:
            continue
        bucket = by_ticker.setdefault(
            ticker, {"insiders": {}, "buy_count": 0, "total_value": 0.0, "latest_buy": None}
        )
        bucket["buy_count"] += 1
        try:
            value = float(row.get("value") or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        bucket["total_value"] += value
        info = bucket["insiders"].setdefault(
            name, {"name": name, "title": row.get("insider_title"), "value": 0.0}
        )
        info["value"] += value
        tx_date = row.get("transaction_date")
        if tx_date and (bucket["latest_buy"] is None or str(tx_date) > str(bucket["latest_buy"])):
            bucket["latest_buy"] = str(tx_date)

    clusters: list[dict[str, Any]] = []
    for ticker, bucket in by_ticker.items():
        insiders = bucket["insiders"]
        if len(insiders) < min_insiders:
            continue
        top_insiders = sorted(insiders.values(), key=lambda i: i["value"], reverse=True)
        clusters.append({
            "ticker": ticker,
            "insider_count": len(insiders),
            "buy_count": bucket["buy_count"],
            "total_value": round(bucket["total_value"], 2),
            "latest_buy": bucket["latest_buy"],
            "insiders": top_insiders[:5],
            "held": ticker in held,
            "watched": ticker in watched,
        })

    # Portfolio-relevant clusters outrank discovery; then breadth, then size.
    clusters.sort(
        key=lambda c: (c["held"] or c["watched"], c["insider_count"], c["total_value"]),
        reverse=True,
    )
    return clusters[:limit]


def build_insider_cluster_buys(
    supabase_client: Any,
    *,
    fund: str | None = None,
    days: int = 30,
    min_insiders: int = 3,
    limit: int = 15,
) -> list[dict[str, Any]]:
    """Fetch + flag + detect; the one entry point routes and the briefing use."""
    held: set[str] = set()
    watched: set[str] = set()
    try:
        pos_query = supabase_client.supabase.table("latest_positions").select("ticker")
        if fund:
            pos_query = pos_query.eq("fund", fund)
        pos = pos_query.execute()
        held = {str(r["ticker"]).upper() for r in (pos.data or []) if r.get("ticker")}
        wl = (
            supabase_client.supabase.table("watched_tickers_v2")
            .select("ticker")
            .eq("is_active", True)
            .execute()
        )
        watched = {str(r["ticker"]).upper() for r in (wl.data or []) if r.get("ticker")}
    except Exception as exc:
        logger.warning("insider clusters: held/watchlist lookup failed: %s", exc)

    rows = fetch_recent_insider_buys(supabase_client, days=days)
    return detect_cluster_buys(
        rows,
        min_insiders=min_insiders,
        held_tickers=held,
        watched_tickers=watched,
        limit=limit,
    )
