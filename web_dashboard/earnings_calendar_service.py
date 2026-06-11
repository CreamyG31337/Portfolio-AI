"""Earnings calendar for holdings/watchlist (ROADMAP §4.4)."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from flask_cache_utils import cache_data

logger = logging.getLogger(__name__)


# Cached: this fans out to one yfinance network call per ticker (up to 40,
# sequential), which is far too slow to run inline per request. Earnings dates
# change rarely; 6h staleness is fine. Proper fix per ROADMAP §4.4 is a nightly
# job writing a cached artifact — replace this when that ships.
@cache_data(ttl=6 * 3600)
def fetch_earnings_dates(tickers: tuple[str, ...]) -> list[dict[str, Any]]:
    """Best-effort earnings dates via yfinance (no new persistence)."""
    if not tickers:
        return []

    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not available for earnings calendar")
        return []

    today = date.today()
    out: list[dict[str, Any]] = []
    for raw in tickers[:40]:
        ticker = (raw or "").upper().strip()
        if not ticker:
            continue
        try:
            tk = yf.Ticker(ticker)
            cal = tk.calendar
            earnings_date: date | None = None
            if cal is not None and not getattr(cal, "empty", True):
                if "Earnings Date" in cal.index:
                    val = cal.loc["Earnings Date"]
                    if hasattr(val, "__iter__") and not isinstance(val, str):
                        val = list(val)[0] if len(val) else None
                    if val is not None:
                        if isinstance(val, datetime):
                            earnings_date = val.date()
                        elif hasattr(val, "date"):
                            earnings_date = val.date()
                        else:
                            earnings_date = date.fromisoformat(str(val)[:10])
            if earnings_date:
                days_until = (earnings_date - today).days
                out.append({
                    "ticker": ticker,
                    "earnings_date": earnings_date.isoformat(),
                    "days_until": days_until,
                })
        except Exception as exc:
            logger.debug("Earnings lookup failed for %s: %s", ticker, exc)
    out.sort(key=lambda x: x.get("days_until", 9999))
    return out


def earnings_for_fund(supabase_client: Any, fund: str | None) -> list[dict[str, Any]]:
    tickers: list[str] = []
    try:
        if fund:
            pos = (
                supabase_client.supabase.table("latest_positions")
                .select("ticker")
                .eq("fund", fund)
                .execute()
            )
            tickers.extend(str(r["ticker"]).upper() for r in (pos.data or []) if r.get("ticker"))
        wl = (
            supabase_client.supabase.table("watched_tickers_v2")
            .select("ticker")
            .eq("is_active", True)
            .execute()
        )
        tickers.extend(str(r["ticker"]).upper() for r in (wl.data or []) if r.get("ticker"))
    except Exception as exc:
        logger.warning("earnings_for_fund ticker load failed: %s", exc)
    unique = tuple(sorted(set(tickers)))
    return fetch_earnings_dates(unique)
