#!/usr/bin/env python3
"""Phase 2 tier-1 digest builders for additional UI scopes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import yfinance as yf

from exchange_rates_utils import get_supabase_client as get_fx_supabase_client
from flask_data_utils import get_cash_balances_flask, get_current_positions_flask
from web_dashboard.watchlist_access import get_active_watchlist_rows


def build_signals_overview_digest(supabase_client: Any, top_n: int = 12) -> dict[str, Any]:
    """Build compact watchlist-signal aggregates and top rows."""
    watchlist_rows = get_active_watchlist_rows(supabase_client) or []
    tickers = []
    for row in watchlist_rows:
        ticker = str(row.get("ticker") or "").strip().upper()
        if ticker:
            tickers.append(ticker)

    latest_by_ticker: dict[str, dict[str, Any]] = {}
    if tickers:
        result = (
            supabase_client.supabase.table("signal_analysis")
            .select("*")
            .in_("ticker", tickers)
            .order("analysis_date", desc=True)
            .execute()
        )
        for row in result.data or []:
            t = str(row.get("ticker") or "").strip().upper()
            if t and t not in latest_by_ticker:
                latest_by_ticker[t] = row

    signals: list[dict[str, Any]] = []
    for ticker in tickers:
        row = latest_by_ticker.get(ticker, {})
        fear = row.get("fear_risk_signal") if isinstance(row.get("fear_risk_signal"), dict) else {}
        signals.append(
            {
                "ticker": ticker,
                "overall_signal": row.get("overall_signal", "HOLD"),
                "confidence": float(row.get("confidence_score") or 0.0),
                "fear_level": fear.get("fear_level", "LOW"),
                "risk_score": float(fear.get("risk_score") or 0.0),
                "analysis_date": row.get("analysis_date"),
            }
        )

    by_signal = {"BUY": 0, "SELL": 0, "WATCH": 0, "HOLD": 0}
    by_fear = {"LOW": 0, "MODERATE": 0, "HIGH": 0, "EXTREME": 0}
    for s in signals:
        by_signal[s["overall_signal"]] = by_signal.get(s["overall_signal"], 0) + 1
        by_fear[s["fear_level"]] = by_fear.get(s["fear_level"], 0) + 1

    top = sorted(signals, key=lambda x: x.get("confidence", 0.0), reverse=True)[:top_n]
    return {
        "watchlist_count": len(tickers),
        "coverage_count": len([s for s in signals if s.get("analysis_date")]),
        "signal_counts": by_signal,
        "fear_counts": by_fear,
        "top_signals": top,
    }


def build_research_feed_digest(postgres_client: Any, days: int = 7, limit: int = 30) -> dict[str, Any]:
    """Build compact recent research digest from article-level rows."""
    since = datetime.now(UTC) - timedelta(days=days)
    rows = postgres_client.execute_query(
        """
        SELECT id, title, source, article_type, sentiment, sentiment_score,
               conclusion, summary, tickers, published_at, fetched_at
        FROM research_articles
        WHERE COALESCE(published_at, fetched_at, created_at) >= %s
        ORDER BY COALESCE(published_at, fetched_at, created_at) DESC
        LIMIT %s
        """,
        (since, limit),
    )
    articles = [dict(r) for r in (rows or [])]

    by_sentiment: dict[str, int] = {}
    by_source: dict[str, int] = {}
    highlight_rows: list[dict[str, Any]] = []
    for row in articles:
        sentiment = str(row.get("sentiment") or "unknown").lower()
        source = str(row.get("source") or "unknown")
        by_sentiment[sentiment] = by_sentiment.get(sentiment, 0) + 1
        by_source[source] = by_source.get(source, 0) + 1
        highlight_rows.append(
            {
                "title": row.get("title"),
                "source": source,
                "sentiment": sentiment,
                "tickers": row.get("tickers") or [],
                "conclusion": (row.get("conclusion") or row.get("summary") or "")[:300],
            }
        )

    return {
        "lookback_days": days,
        "article_count": len(articles),
        "sentiment_counts": by_sentiment,
        "top_sources": sorted(by_source.items(), key=lambda kv: kv[1], reverse=True)[:8],
        "highlights": highlight_rows[:12],
    }


def build_dashboard_commodities_digest(days: int = 90) -> dict[str, Any]:
    """Build compact commodity trend digest from Yahoo series used by chart layer."""
    symbols = {"gold": "GC=F", "silver": "SI=F", "oil": "CL=F", "uranium": "URA", "lithium": "LIT"}
    period = f"{max(30, min(days, 365))}d"
    out: dict[str, Any] = {"days": days, "series": {}}
    for name, symbol in symbols.items():
        hist = yf.download(symbol, period=period, interval="1d", progress=False, auto_adjust=True)
        if hist.empty or "Close" not in hist:
            continue
        close = pd.to_numeric(hist["Close"], errors="coerce").dropna()
        if close.empty:
            continue
        start = float(close.iloc[0])
        end = float(close.iloc[-1])
        change_pct = ((end - start) / start * 100.0) if start else 0.0
        out["series"][name] = {
            "symbol": symbol,
            "start": round(start, 4),
            "end": round(end, 4),
            "change_pct": round(change_pct, 2),
            "points": int(len(close)),
        }
    return out


def build_dashboard_currency_digest(fund: str | None = None) -> dict[str, Any]:
    """Build compact currency exposure + recent USD/CAD change digest."""
    positions = get_current_positions_flask(fund)
    cash_balances = get_cash_balances_flask(fund)
    exposure: dict[str, float] = {}

    if not positions.empty and "currency" in positions.columns and "market_value" in positions.columns:
        df = positions.copy()
        df["currency"] = df["currency"].fillna("CAD").astype(str).str.upper()
        df["market_value"] = pd.to_numeric(df["market_value"], errors="coerce").fillna(0.0)
        grouped = df.groupby("currency")["market_value"].sum()
        for curr, value in grouped.items():
            exposure[str(curr)] = exposure.get(str(curr), 0.0) + float(value)

    for curr, value in (cash_balances or {}).items():
        c = str(curr or "CAD").upper()
        exposure[c] = exposure.get(c, 0.0) + float(value or 0.0)

    total = sum(abs(v) for v in exposure.values()) or 1.0
    weights = {k: round((v / total) * 100.0, 2) for k, v in exposure.items()}

    fx_client = get_fx_supabase_client(use_service_role=True)
    fx_change = None
    if fx_client:
        end = datetime.now(UTC)
        start = end - timedelta(days=30)
        rates = fx_client.get_exchange_rates(start, end, "USD", "CAD")
        vals = [float(r.get("rate")) for r in rates if r.get("rate") is not None]
        if len(vals) >= 2 and vals[0]:
            fx_change = round(((vals[-1] - vals[0]) / vals[0]) * 100.0, 3)

    return {
        "fund": fund,
        "currency_exposure": {k: round(v, 2) for k, v in exposure.items()},
        "currency_weights_pct": weights,
        "usd_cad_30d_change_pct": fx_change,
    }

