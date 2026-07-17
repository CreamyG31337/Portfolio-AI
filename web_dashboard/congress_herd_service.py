"""Congress herd-buy detection (ROADMAP Pillar 5.1a).

A herd = N+ distinct politicians with ``type='Purchase'`` on the same ticker
within the lookback window. Pure aggregation over ``congress_trades_enriched`` —
no new collection, no LLM.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)

_JUNK_TICKERS = {"", "-", "N/A", "NONE", "NULL"}
_PAGE_SIZE = 1000


def fetch_recent_congress_buys(
    supabase_client: Any, *, days: int = 30
) -> list[dict[str, Any]]:
    """All Purchase rows in the window, paginated past the 1000-row cap."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = (
            supabase_client.supabase.table("congress_trades_enriched")
            .select(
                "politician_id,ticker,politician,party,chamber,transaction_date,amount,type"
            )
            .eq("type", "Purchase")
            .neq("quality_status", "garbage")
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


def detect_herd_buys(
    rows: list[dict[str, Any]],
    *,
    min_politicians: int = 2,
    held_tickers: set[str] | None = None,
    watched_tickers: set[str] | None = None,
    limit: int = 15,
) -> list[dict[str, Any]]:
    """Group purchase rows by ticker; keep tickers with >= min_politicians distinct buyers."""
    held = {t.upper() for t in (held_tickers or set())}
    watched = {t.upper() for t in (watched_tickers or set())}

    by_ticker: dict[str, dict[str, Any]] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "").upper().strip()
        politician_id = row.get("politician_id")
        if ticker in _JUNK_TICKERS or politician_id is None:
            continue
        pid = str(politician_id)
        bucket = by_ticker.setdefault(
            ticker,
            {"politicians": {}, "buy_count": 0, "latest_buy": None},
        )
        bucket["buy_count"] += 1
        info = bucket["politicians"].setdefault(
            pid,
            {
                "politician_id": pid,
                "name": row.get("politician") or "",
                "party": row.get("party"),
                "chamber": row.get("chamber"),
                "buy_count": 0,
                "latest_buy": None,
            },
        )
        info["buy_count"] += 1
        tx_date = row.get("transaction_date")
        if tx_date:
            tx_s = str(tx_date)
            if bucket["latest_buy"] is None or tx_s > str(bucket["latest_buy"]):
                bucket["latest_buy"] = tx_s
            if info["latest_buy"] is None or tx_s > str(info["latest_buy"]):
                info["latest_buy"] = tx_s

    herds: list[dict[str, Any]] = []
    for ticker, bucket in by_ticker.items():
        politicians = bucket["politicians"]
        if len(politicians) < min_politicians:
            continue
        top_politicians = sorted(
            politicians.values(),
            key=lambda p: (p.get("buy_count") or 0, p.get("latest_buy") or ""),
            reverse=True,
        )
        herds.append({
            "ticker": ticker,
            "politician_count": len(politicians),
            "buy_count": bucket["buy_count"],
            "latest_buy": bucket["latest_buy"],
            "politicians": top_politicians[:5],
            "held": ticker in held,
            "watched": ticker in watched,
        })

    herds.sort(
        key=lambda h: (h["held"] or h["watched"], h["politician_count"], h["buy_count"]),
        reverse=True,
    )
    return herds[:limit]


def build_congress_herd_buys(
    supabase_client: Any,
    *,
    fund: str | None = None,
    days: int = 30,
    min_politicians: int = 2,
    limit: int = 15,
) -> list[dict[str, Any]]:
    """Fetch + detect; entry point for routes and the Today briefing."""
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
        logger.warning("congress herd: held/watchlist lookup failed: %s", exc)

    rows = fetch_recent_congress_buys(supabase_client, days=days)
    return detect_herd_buys(
        rows,
        min_politicians=min_politicians,
        held_tickers=held,
        watched_tickers=watched,
        limit=limit,
    )
