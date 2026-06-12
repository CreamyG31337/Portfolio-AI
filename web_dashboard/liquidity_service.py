"""Liquidity / exit-risk math for holdings (ROADMAP §4.3).

Days-to-exit = shares held / (participation rate x average daily share volume).
Share-based on purpose: position value / dollar-ADV gives the identical ratio
but drags currency conversion into the math for nothing.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from flask_cache_utils import cache_data

logger = logging.getLogger(__name__)

# Selling more than ~10% of a day's volume starts moving the price on
# micro-caps; the standard practitioner assumption for exit-horizon math.
PARTICIPATION_RATE = 0.10

# Days-to-exit risk buckets at the participation rate above.
_BUCKET_LOW_MAX = 1.0
_BUCKET_ELEVATED_MAX = 5.0


# Cached: one yfinance network call per ticker (sequential, capped), same
# trade-off as earnings_calendar_service. Volume profiles drift slowly; 6h
# staleness is fine. Callers must NOT put this in a latency-sensitive path.
@cache_data(ttl=6 * 3600)
def fetch_avg_daily_volumes(tickers: tuple[str, ...]) -> dict[str, dict[str, float]]:
    """Best-effort 1-month average daily share volume per ticker via yfinance."""
    if not tickers:
        return {}

    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not available for liquidity panel")
        return {}

    out: dict[str, dict[str, float]] = {}
    for raw in tickers[:60]:
        ticker = (raw or "").upper().strip()
        if not ticker:
            continue
        try:
            hist = yf.Ticker(ticker).history(period="1mo", auto_adjust=False)
            if hist is None or getattr(hist, "empty", True) or "Volume" not in hist.columns:
                continue
            vol = hist["Volume"].dropna()
            vol = vol[vol > 0]
            if vol.empty:
                continue
            entry: dict[str, float] = {"avg_daily_volume": float(vol.mean())}
            if "Close" in hist.columns:
                closes = hist["Close"].dropna()
                if not closes.empty:
                    entry["last_close"] = float(closes.iloc[-1])
                    dollar = (hist["Close"] * hist["Volume"]).dropna()
                    if not dollar.empty:
                        entry["avg_dollar_volume"] = float(dollar.mean())
            out[ticker] = entry
        except Exception as exc:
            logger.debug("Volume lookup failed for %s: %s", ticker, exc)
    return out


def _risk_bucket(days_to_exit: float | None) -> str:
    if days_to_exit is None:
        return "unknown"
    if days_to_exit <= _BUCKET_LOW_MAX:
        return "low"
    if days_to_exit <= _BUCKET_ELEVATED_MAX:
        return "elevated"
    return "high"


def build_liquidity_panel(
    positions_df: Any,
    volumes: dict[str, dict[str, float]] | None = None,
) -> list[dict[str, Any]]:
    """Per-ticker exit-risk rows from a positions DataFrame.

    Positions for the same ticker across funds are summed — exit risk is a
    property of the book's total footprint in the name, not of one fund's slice.
    """
    if positions_df is None or getattr(positions_df, "empty", True):
        return []
    if "ticker" not in positions_df.columns or "shares" not in positions_df.columns:
        logger.warning("liquidity panel: positions frame missing ticker/shares")
        return []

    grouped: dict[str, dict[str, float]] = {}
    for _, row in positions_df.iterrows():
        ticker = str(row.get("ticker") or "").upper().strip()
        if not ticker:
            continue
        try:
            shares = float(row.get("shares") or 0.0)
        except (TypeError, ValueError):
            shares = 0.0
        if not shares > 0:  # rejects 0, negatives, and pandas NaN
            continue
        agg = grouped.setdefault(ticker, {"shares": 0.0, "market_value": 0.0})
        agg["shares"] += shares
        try:
            market_value = float(row.get("market_value") or 0.0)
            if math.isfinite(market_value):
                agg["market_value"] += market_value
        except (TypeError, ValueError):
            pass

    if not grouped:
        return []

    if volumes is None:
        volumes = fetch_avg_daily_volumes(tuple(sorted(grouped)))

    rows: list[dict[str, Any]] = []
    for ticker, agg in grouped.items():
        vol_info = volumes.get(ticker) or {}
        adv = vol_info.get("avg_daily_volume")
        days_to_exit: float | None = None
        pct_of_adv: float | None = None
        if adv and adv > 0:
            pct_of_adv = round(agg["shares"] / adv * 100, 2)
            days_to_exit = round(agg["shares"] / (PARTICIPATION_RATE * adv), 2)
        rows.append({
            "ticker": ticker,
            "shares": round(agg["shares"], 4),
            "market_value": round(agg["market_value"], 2),
            "avg_daily_volume": round(adv, 0) if adv else None,
            "pct_of_adv": pct_of_adv,
            "days_to_exit": days_to_exit,
            "risk_bucket": _risk_bucket(days_to_exit),
        })

    # Worst exit risk first; tickers with no volume data sink to the bottom
    # (unknown != risky — usually a stale/delisted symbol worth eyeballing once).
    rows.sort(
        key=lambda r: (r["days_to_exit"] is not None, r["days_to_exit"] or 0.0),
        reverse=True,
    )
    known = [r for r in rows if r["days_to_exit"] is not None]
    unknown = [r for r in rows if r["days_to_exit"] is None]
    return known + unknown
