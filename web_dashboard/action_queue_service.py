#!/usr/bin/env python3
"""Build dashboard action queue rows and attach research / AI-review context."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

from postgres_client import PostgresClient
from settings import get_signal_alert_policy, normalize_fund_type
from supabase_client import SupabaseClient

try:
    from web_dashboard.utils.logo_utils import get_ticker_logo_urls
    from web_dashboard.watchlist_access import get_active_watchlist_rows
except ImportError:
    from utils.logo_utils import get_ticker_logo_urls
    from watchlist_access import get_active_watchlist_rows

from flask_data_utils import get_current_positions_flask as get_current_positions

logger = logging.getLogger(__name__)


def _build_global_dashboard_alert_policy(policies: list[dict[str, Any]]) -> dict[str, Any]:
    if not policies:
        return get_signal_alert_policy(None)

    min_confidence = max(float(policy.get("min_confidence", 0.72)) for policy in policies)
    fear_sets: list[set[str]] = []
    for policy in policies:
        raw = policy.get("fear_levels", [])
        if isinstance(raw, list):
            fear_sets.append({str(level).strip().upper() for level in raw if str(level).strip()})

    if fear_sets:
        common_levels = set.intersection(*fear_sets) if len(fear_sets) > 1 else fear_sets[0]
        if not common_levels:
            common_levels = set.union(*fear_sets)
    else:
        common_levels = {"HIGH", "EXTREME"}

    return {
        "profile_key": "GLOBAL_STRICT",
        "min_confidence": min_confidence,
        "fear_levels": sorted(common_levels),
    }


def _resolve_dashboard_alert_policy(supabase_client: SupabaseClient, fund: str | None) -> dict[str, Any]:
    try:
        if fund:
            fund_result = (
                supabase_client.supabase.table("funds")
                .select("fund_type")
                .eq("name", fund)
                .limit(1)
                .execute()
            )
            if fund_result.data:
                fund_type = fund_result.data[0].get("fund_type")
                return get_signal_alert_policy(normalize_fund_type(fund_type))

        rows_result = supabase_client.supabase.table("funds").select("fund_type, is_production").execute()
        rows = rows_result.data or []
        production_rows = [row for row in rows if row.get("is_production") is True]
        scoped_rows = production_rows if production_rows else rows
        profile_keys = {
            normalize_fund_type(row.get("fund_type")) for row in scoped_rows if row.get("fund_type")
        }
        if profile_keys:
            policies = [get_signal_alert_policy(profile_key) for profile_key in sorted(profile_keys)]
            return _build_global_dashboard_alert_policy(policies)
    except Exception as e:
        logger.warning("[action_queue] Failed resolving alert policy: %s", e)

    return get_signal_alert_policy(None)


def _json_safe_number(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def build_action_queue_items(
    supabase_client: SupabaseClient,
    fund: str | None,
    limit: int,
    positions_df: Any | None = None,
) -> list[dict[str, Any]]:
    """Rules-based queue (same semantics as dashboard get_action_queue).

    If ``positions_df`` is provided (e.g. outbound digest service-role path), it is used
    instead of loading via Flask-scoped ``get_current_positions``.
    """
    if positions_df is None:
        positions_df = get_current_positions(fund)
    held_tickers: set[str] = set()
    if not positions_df.empty and "ticker" in positions_df.columns:
        held_tickers = set(
            positions_df["ticker"].dropna().astype(str).str.upper().str.strip().tolist()
        )

    watchlist = get_active_watchlist_rows(supabase_client, fund=fund)
    if not watchlist:
        return []

    tickers = list({item.get("ticker") for item in watchlist if item.get("ticker")})

    latest_by_ticker: dict[str, dict[str, Any]] = {}
    try:
        batch_size = 100
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i : i + batch_size]
            rows = (
                supabase_client.supabase.table("signal_analysis")
                .select(
                    "ticker, analysis_date, structure_signal, timing_signal, "
                    "fear_risk_signal, overall_signal, confidence_score, explanation"
                )
                .in_("ticker", batch)
                .order("analysis_date", desc=True)
                .execute()
            )
            if rows.data:
                for row in rows.data:
                    row_ticker = row.get("ticker")
                    if row_ticker and row_ticker not in latest_by_ticker:
                        latest_by_ticker[row_ticker] = row
    except Exception as e:
        logger.warning("[action_queue] Error fetching signal_analysis: %s", e)

    company_names_map: dict[str, str] = {}
    try:
        for i in range(0, len(tickers), 100):
            batch = tickers[i : i + 100]
            result = (
                supabase_client.supabase.table("securities")
                .select("ticker, company_name")
                .in_("ticker", batch)
                .execute()
            )
            if result.data:
                for row in result.data:
                    t = row.get("ticker")
                    if t:
                        company_names_map[t] = row.get("company_name") or t
    except Exception as e:
        logger.warning("[action_queue] Error fetching company names: %s", e)

    logo_urls_map: dict[str, str] = {}
    try:
        logo_urls_map = get_ticker_logo_urls(tickers)
    except Exception as e:
        logger.warning("[action_queue] Error fetching logo URLs: %s", e)

    alert_policy = _resolve_dashboard_alert_policy(supabase_client, fund)
    min_confidence = float(alert_policy.get("min_confidence", 0.72))
    risk_fear_levels = {
        str(level).strip().upper() for level in alert_policy.get("fear_levels", ["HIGH", "EXTREME"])
    }
    watch_confidence_floor = max(min_confidence - 0.10, 0.50)

    def _get_fear_level(signal_row: dict[str, Any]) -> str:
        fear = signal_row.get("fear_risk_signal")
        if isinstance(fear, dict):
            return str(fear.get("fear_level") or "LOW").upper()
        return "LOW"

    def _get_trend(signal_row: dict[str, Any]) -> str:
        structure = signal_row.get("structure_signal")
        if isinstance(structure, dict):
            return structure.get("trend") or "NEUTRAL"
        return "NEUTRAL"

    def _score_action(action: str, confidence: float, fear_level: str, tier: str, is_held: bool) -> int:
        base = 0
        if action == "SELL":
            base = 100
        elif action == "BUY":
            base = 90
        elif action == "RISK":
            base = 80
        elif action == "WATCH":
            base = 60

        base += int((confidence or 0) * 20)

        if fear_level == "EXTREME":
            base += 15
        elif fear_level == "HIGH":
            base += 10
        elif fear_level == "MODERATE":
            base += 5

        if tier == "A":
            base += 5
        elif tier == "B":
            base += 3

        if is_held:
            base += 2

        return base

    actions: list[dict[str, Any]] = []
    for item in watchlist:
        ticker = item.get("ticker")
        if not ticker:
            continue

        signal = latest_by_ticker.get(ticker)
        if not signal:
            continue

        overall_signal = signal.get("overall_signal") or "HOLD"
        confidence = _json_safe_number(signal.get("confidence_score"), 0.0)
        fear_level = _get_fear_level(signal)
        trend = _get_trend(signal)
        is_held = ticker in held_tickers
        priority_tier = item.get("priority_tier") or "C"

        action = None
        if overall_signal == "SELL" and is_held and confidence >= min_confidence:
            action = "SELL"
        elif overall_signal == "BUY" and not is_held and confidence >= min_confidence:
            action = "BUY"
        elif fear_level in risk_fear_levels and is_held:
            action = "RISK"
        elif overall_signal == "WATCH" and confidence >= watch_confidence_floor and not is_held:
            action = "WATCH"

        if not action:
            continue

        score = _score_action(action, confidence, fear_level, priority_tier, is_held)
        note = f"{overall_signal} signal, trend {trend}, fear {fear_level}"

        actions.append(
            {
                "ticker": ticker,
                "company_name": company_names_map.get(ticker),
                "_logo_url": logo_urls_map.get(ticker),
                "action": action,
                "overall_signal": overall_signal,
                "confidence": confidence,
                "fear_level": fear_level,
                "trend": trend,
                "priority_score": score,
                "priority_tier": priority_tier,
                "is_held": is_held,
                "analysis_date": signal.get("analysis_date"),
                "explanation": signal.get("explanation"),
                "note": note,
            }
        )

    actions.sort(key=lambda x: x.get("priority_score", 0), reverse=True)
    return actions[:limit]


def _parse_analysis_date(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        s = str(raw).replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def attach_research_context(postgres: PostgresClient | None, items: list[dict[str, Any]]) -> None:
    if not postgres or not items:
        return
    tickers = [i["ticker"] for i in items if i.get("ticker")]
    if not tickers:
        return
    now = datetime.now(timezone.utc)
    try:
        ta_rows = postgres.execute_query(
            """
            SELECT DISTINCT ON (ticker) ticker, stance, sentiment, updated_at
            FROM ticker_analysis
            WHERE ticker = ANY(%s) AND analysis_type = 'standard'
            ORDER BY ticker, updated_at DESC NULLS LAST
            """,
            (tickers,),
        ) or []
        meta_rows = postgres.execute_query(
            """
            SELECT DISTINCT ON (ticker) ticker, unified_conviction, confidence_adjusted, updated_at
            FROM ticker_meta_analysis
            WHERE ticker = ANY(%s)
            ORDER BY ticker, updated_at DESC NULLS LAST
            """,
            (tickers,),
        ) or []
    except Exception as exc:
        logger.debug("research context fetch skipped: %s", exc)
        return

    ta_map = {r["ticker"]: r for r in ta_rows}
    meta_map = {r["ticker"]: r for r in meta_rows}

    for it in items:
        t = it.get("ticker")
        rc: dict[str, Any] = {}
        if t in ta_map:
            row = ta_map[t]
            u = row.get("updated_at")
            if isinstance(u, datetime) and u.tzinfo is None:
                u = u.replace(tzinfo=timezone.utc)
            age = (now - u).total_seconds() / 3600.0 if u else None
            rc["analysis_stance"] = row.get("stance")
            rc["analysis_sentiment"] = row.get("sentiment")
            rc["analysis_age_hours"] = round(age, 1) if age is not None else None
        if t in meta_map:
            row = meta_map[t]
            u = row.get("updated_at")
            if isinstance(u, datetime) and u.tzinfo is None:
                u = u.replace(tzinfo=timezone.utc)
            age = (now - u).total_seconds() / 3600.0 if u else None
            rc["meta_conviction"] = row.get("unified_conviction")
            rc["meta_confidence_adjusted"] = (
                float(row["confidence_adjusted"]) if row.get("confidence_adjusted") is not None else None
            )
            rc["meta_age_hours"] = round(age, 1) if age is not None else None
        if rc:
            it["research_context"] = rc


def attach_ai_reviews(
    postgres: PostgresClient | None,
    fund_key: str,
    items: list[dict[str, Any]],
) -> None:
    if not postgres or not items:
        return
    tickers = [i["ticker"] for i in items if i.get("ticker")]
    if not tickers:
        return
    fk = fund_key or ""
    try:
        rows = postgres.execute_query(
            """
            SELECT ticker, signal_analysis_date, verdict, one_liner, updated_at
            FROM action_queue_ai_review
            WHERE fund_key = %s AND ticker = ANY(%s)
            """,
            (fk, tickers),
        ) or []
    except Exception as exc:
        logger.debug("ai_review fetch skipped: %s", exc)
        return

    def _dkey(ad: Any) -> str:
        """Date key for matching cached AI reviews; aligns with nightly job sentinel for missing dates."""
        if ad is None:
            return "1970-01-01"
        if hasattr(ad, "isoformat"):
            return ad.isoformat()[:10]
        s = str(ad)
        return s[:10] if len(s) >= 10 else s

    keyed: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        k = (r["ticker"], _dkey(r.get("signal_analysis_date")))
        keyed[k] = r

    for it in items:
        t = it.get("ticker")
        k = (t, _dkey(it.get("analysis_date")))
        row = keyed.get(k)
        if row:
            it["ai_review"] = {
                "verdict": row.get("verdict"),
                "one_liner": row.get("one_liner"),
                "updated_at": row.get("updated_at"),
            }
