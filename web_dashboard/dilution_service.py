"""Dilution detection via shares-outstanding growth (ROADMAP G3).

Free, country-agnostic alternative to filing-based dilution watch: a rising
share count *is* dilution, and yfinance exposes it for US and Canadian (`.TO`)
tickers alike — the exact names the US-only EDGAR filing watch (G2) cannot see.
Lagging (detects realized issuance, not forward intent like a shelf filing) but
certain and free. See docs/PHASE_G_PLAN.md G3.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, UTC
from typing import Any

from flask_cache_utils import cache_data

logger = logging.getLogger(__name__)

# Percent share-count growth that flags a window as dilution. Windows and bars
# tuned against a live scan of the real book (2026-06-14): dilution is usually
# *gradual*, and yfinance's share-count tail runs ~50 days stale, so short
# windows under-detect. Year-over-year is the reliable signal —
#   365d: GLO.TO +59%, GANX +37%, OKLO +25%, PANW +21% flagged; large-cap
#         buyback names (NVDA, COST, ...) sit negative and don't.
#   90d:  catches an acute raise the YoY window would dilute away (LTRX +12%).
DEFAULT_THRESHOLDS: dict[int, float] = {90: 10.0, 365: 20.0}
WINDOWS: tuple[int, ...] = (90, 365)

# yfinance share-count history is irregular (point counts varied 29–100 across
# tickers in the scan). Require at least this many points inside a window
# before trusting a delta, so a single stale reading can't fabricate a spike.
MIN_POINTS_IN_WINDOW = 2

# Must exceed the widest window (365d) so the year-over-year baseline has data.
_LOOKBACK_DAYS = 400


@cache_data(ttl=6 * 3600)
def fetch_shares_history(
    tickers: tuple[str, ...], lookback_days: int = _LOOKBACK_DAYS
) -> dict[str, list[tuple[str, float]]]:
    """Best-effort shares-outstanding series per ticker via yfinance.

    Returns ``{ticker: [(iso_date, shares), ...]}`` sorted ascending, one entry
    per distinct date. Cached 6h — share counts move slowly and this fans out
    one network call per ticker, so it must stay off any request path.
    """
    if not tickers:
        return {}
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not available for dilution watch")
        return {}

    start = (date.today() - timedelta(days=lookback_days)).isoformat()
    out: dict[str, list[tuple[str, float]]] = {}
    for raw in tickers:
        ticker = (raw or "").upper().strip()
        if not ticker:
            continue
        try:
            series = yf.Ticker(ticker).get_shares_full(start=start)
            if series is None or len(series) == 0:
                continue
            # yfinance returns a DatetimeIndex Series, often with duplicate dates
            # and occasional NaN — collapse to one positive value per date.
            by_date: dict[str, float] = {}
            for idx, val in series.items():
                if val is None:
                    continue
                day = idx.date() if hasattr(idx, "date") else None
                if day is None:
                    continue
                try:
                    fval = float(val)
                except (TypeError, ValueError):
                    continue
                if fval > 0:
                    by_date[day.isoformat()] = fval
            if by_date:
                out[ticker] = sorted(by_date.items())
        except Exception as exc:
            logger.debug("shares-outstanding lookup failed for %s: %s", ticker, exc)
    return out


def compute_dilution_observations(
    shares_history: dict[str, list[tuple[str, float]]],
    *,
    as_of: date | None = None,
    windows: tuple[int, ...] = WINDOWS,
    thresholds: dict[int, float] | None = None,
    min_points: int = MIN_POINTS_IN_WINDOW,
) -> list[dict[str, Any]]:
    """Pure: per-(ticker, window) share-count delta, flagging big growth.

    Baseline is the earliest reading inside the window (≈ window-days ago);
    end is the most recent reading overall. ``flagged`` marks growth above the
    window's threshold. Windows with fewer than ``min_points`` readings are
    skipped (irregular yfinance history → not enough to trust).
    """
    as_of = as_of or datetime.now(UTC).date()
    thresholds = thresholds or DEFAULT_THRESHOLDS
    out: list[dict[str, Any]] = []

    for ticker, series in shares_history.items():
        if not series:
            continue
        parsed = [(date.fromisoformat(d), v) for d, v in series]
        _, latest_shares = parsed[-1]
        if latest_shares <= 0:
            continue

        for window in windows:
            cutoff = as_of - timedelta(days=window)
            in_window = [(d, v) for d, v in parsed if d >= cutoff]
            if len(in_window) < min_points:
                continue
            _, baseline_shares = in_window[0]
            if baseline_shares <= 0:
                continue
            pct = (latest_shares - baseline_shares) / baseline_shares * 100.0
            threshold = thresholds.get(window, 10.0)
            out.append({
                "ticker": ticker,
                "as_of": as_of.isoformat(),
                "window_days": window,
                "shares_start": round(baseline_shares, 2),
                "shares_end": round(latest_shares, 2),
                "pct_change": round(pct, 2),
                "flagged": pct >= threshold,
            })
    return out


def fetch_recent_dilution_flags(
    postgres: Any, *, tickers: list[str] | None = None, days: int = 45, limit: int = 50
) -> list[dict[str, Any]]:
    """Recent flagged dilution rows, worst growth first (for Today + dossier).

    One row per (ticker, window) — the most recent flagged observation, so a
    serial diluter shows once per window rather than once per scan.
    """
    params: list[Any] = [days]
    ticker_filter = ""
    if tickers:
        ticker_filter = "AND ticker = ANY(%s)"
        params.append([t.upper() for t in tickers])
    params.append(limit)
    try:
        # Cast to JSON-safe types in SQL: the Today briefing payload is jsonified
        # without a Decimal/date encoder, so return float/text, not Decimal/date.
        return postgres.execute_query(
            f"""
            SELECT ticker, window_days,
                   shares_start::float8 AS shares_start,
                   shares_end::float8 AS shares_end,
                   pct_change::float8 AS pct_change,
                   as_of::text AS as_of
            FROM (
                SELECT DISTINCT ON (ticker, window_days)
                       ticker, window_days, shares_start, shares_end, pct_change, as_of
                FROM dilution_observations
                WHERE flagged = TRUE
                  AND as_of >= (CURRENT_DATE - (%s || ' days')::interval)
                  {ticker_filter}
                ORDER BY ticker, window_days, as_of DESC
            ) latest
            ORDER BY pct_change DESC
            LIMIT %s
            """,
            tuple(params),
        )
    except Exception as exc:
        logger.warning("fetch_recent_dilution_flags failed (table missing?): %s", exc)
        return []
