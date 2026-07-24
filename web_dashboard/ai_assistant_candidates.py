#!/usr/bin/env python3
"""Shared candidate builders for AI Assistant pulse + tools.

Action-queue rows are preferred. When the queue is empty (common when there are
no BUY signals and positions are unavailable for SELL/RISK gating), fall back to
a lean ranking from latest watchlist ``signal_analysis`` rows.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from web_dashboard.watchlist_access import get_active_watchlist_rows
except ImportError:  # pragma: no cover - script/path variants
    from watchlist_access import get_active_watchlist_rows

# Prefer actionable over passive HOLD noise for discovery.
_SIGNAL_PRIORITY = {
    "SELL": 0,
    "BUY": 1,
    "WATCH": 2,
    "HOLD": 3,
}
_FEAR_PRIORITY = {
    "EXTREME": 0,
    "HIGH": 1,
    "MODERATE": 2,
    "LOW": 3,
}


def _fear_level(row: dict[str, Any]) -> str:
    fear = row.get("fear_risk_signal")
    if isinstance(fear, dict):
        return str(fear.get("fear_level") or "LOW").upper()
    return "LOW"


def _risk_score(row: dict[str, Any]) -> float:
    fear = row.get("fear_risk_signal")
    if isinstance(fear, dict):
        try:
            return float(fear.get("risk_score") or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _sectors_for_tickers(supabase: Any, tickers: list[str]) -> dict[str, str]:
    if not supabase or not tickers:
        return {}
    out: dict[str, str] = {}
    try:
        for i in range(0, len(tickers), 100):
            batch = tickers[i : i + 100]
            result = (
                supabase.supabase.table("securities")
                .select("ticker, sector")
                .in_("ticker", batch)
                .execute()
            )
            for row in result.data or []:
                t = str(row.get("ticker") or "").upper()
                sec = row.get("sector")
                if t and sec:
                    out[t] = str(sec)
    except Exception as exc:
        logger.warning("candidate sectors lookup failed: %s", exc)
    return out


def build_signal_fallback_candidates(
    supabase: Any,
    *,
    fund: str | None = None,
    held_tickers: set[str] | None = None,
    limit: int = 12,
    sector_filter: str | None = None,
    action_filter: str | None = None,
    held_only: bool = False,
    include_hold: bool = False,
) -> list[dict[str, Any]]:
    """Lean candidates from latest watchlist signals (assistant fallback).

    Returns rows shaped like pulse lean candidates:
    ``ticker, advise, confidence, reason, is_held, sector?, fear_level?``.
    """
    if not supabase:
        return []

    held = {t.upper() for t in (held_tickers or set()) if t}
    try:
        watchlist = get_active_watchlist_rows(supabase, fund=fund) or []
    except Exception as exc:
        logger.warning("signal fallback watchlist failed: %s", exc)
        return []

    tickers = [
        str(item.get("ticker") or "").upper().strip()
        for item in watchlist
        if item.get("ticker")
    ]
    tickers = [t for t in tickers if t]
    if not tickers:
        return []

    latest_by_ticker: dict[str, dict[str, Any]] = {}
    try:
        for i in range(0, len(tickers), 100):
            batch = tickers[i : i + 100]
            rows = (
                supabase.supabase.table("signal_analysis")
                .select(
                    "ticker, analysis_date, overall_signal, confidence_score, "
                    "fear_risk_signal, structure_signal"
                )
                .in_("ticker", batch)
                .order("analysis_date", desc=True)
                .execute()
            )
            for row in rows.data or []:
                t = str(row.get("ticker") or "").upper()
                if t and t not in latest_by_ticker:
                    latest_by_ticker[t] = row
    except Exception as exc:
        logger.warning("signal fallback fetch failed: %s", exc)
        return []

    action_filter_u = (action_filter or "").strip().upper()
    # MONITOR is advise-only; map to HOLD for signal fallback.
    if action_filter_u == "MONITOR":
        action_filter_u = "HOLD"
    if action_filter_u == "RISK":
        # RISK is queue-derived from held + high fear; approximate via held + HIGH/EXTREME.
        pass

    sector_map = _sectors_for_tickers(supabase, tickers)
    sector_f = (sector_filter or "").strip()

    scored: list[tuple[tuple[int, int, float], dict[str, Any]]] = []
    for ticker in tickers:
        row = latest_by_ticker.get(ticker)
        if not row:
            continue
        overall = str(row.get("overall_signal") or "HOLD").upper()
        conf = float(row.get("confidence_score") or 0.0)
        fear = _fear_level(row)
        is_held = ticker in held

        if held_only and not is_held:
            continue

        advise = overall
        if action_filter_u == "RISK":
            if not (is_held and fear in {"HIGH", "EXTREME"}):
                continue
            advise = "RISK"
        elif action_filter_u and overall != action_filter_u:
            continue
        elif not include_hold and overall == "HOLD" and not action_filter_u:
            # Skip passive HOLD noise unless explicitly requested.
            continue

        sec = sector_map.get(ticker, "")
        if sector_f and sector_f.lower() not in sec.lower():
            continue

        reason = f"signal:{overall}"
        if fear and fear != "LOW":
            reason += f" fear={fear}"
        item: dict[str, Any] = {
            "ticker": ticker,
            "advise": advise,
            "confidence": conf,
            "is_held": is_held,
            "reason": reason,
            "fear_level": fear,
            "source": "signal_fallback",
        }
        if sec:
            item["sector"] = sec
        score = (
            _SIGNAL_PRIORITY.get(advise if advise != "RISK" else "SELL", 9),
            _FEAR_PRIORITY.get(fear, 9),
            -conf,
        )
        scored.append((score, item))

    scored.sort(key=lambda x: x[0])
    return [item for _, item in scored[: max(1, limit)]]
