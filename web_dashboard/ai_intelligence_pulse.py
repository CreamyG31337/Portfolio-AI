#!/usr/bin/env python3
"""Lean Today intelligence pulse for AI Assistant context.

Keeps token cost low: market headline/regime + top ranked advise/action rows
with stance/entry hints — no OHLCV dumps or long narratives.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CANDIDATE_LIMIT = 10
_REASON_MAX = 120


def _short(text: Any, max_len: int = _REASON_MAX) -> str | None:
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _lean_candidate(row: dict[str, Any]) -> dict[str, Any]:
    """Strip a advise/action-queue style row down to chat-safe fields."""
    rc = row.get("research_context") if isinstance(row.get("research_context"), dict) else {}
    ai = row.get("ai_review") if isinstance(row.get("ai_review"), dict) else {}
    reasons = row.get("reasons") or []
    if isinstance(reasons, list):
        reason_s = ", ".join(str(r) for r in reasons[:3] if r)
    else:
        reason_s = str(reasons) if reasons else ""
    one_liner = ai.get("one_liner") or row.get("note") or row.get("explanation")
    advise = (
        row.get("advise")
        or row.get("action")
        or row.get("queue_action")
        or ""
    )
    out: dict[str, Any] = {
        "ticker": str(row.get("ticker") or "").upper().strip(),
        "advise": str(advise).upper().strip() or None,
        "confidence": row.get("confidence")
        if row.get("confidence") is not None
        else row.get("confidence_score"),
        "meta_conviction": rc.get("meta_conviction") or row.get("meta_conviction"),
        "stance": rc.get("analysis_stance") or row.get("stance"),
        "entry_zone": row.get("entry_zone"),
        "is_held": bool(row.get("is_held")) if "is_held" in row else None,
        "reason": _short(reason_s or one_liner),
    }
    # Drop empty values for compactness
    return {k: v for k, v in out.items() if v is not None and v != ""}


def _fetch_market_pulse() -> tuple[dict[str, Any] | None, str | None]:
    """Load latest market brief from Research DB.

    Returns ``(market_dict, unavailable_reason)``. Unavailable is *not* the same
    as the US cash equity session being closed — briefs are cached rows in
    ``market_daily_brief`` and should still load after hours.
    """
    try:
        from market_brief_service import fetch_latest_brief
        from market_regime_normalization import normalize_market_regime
        from postgres_client import PostgresClient

        pg = PostgresClient()
        row = fetch_latest_brief(pg)
        if not row:
            return None, "no_brief_row"
        regime_raw = row.get("regime_json")
        if isinstance(regime_raw, str):
            import json

            try:
                regime_raw = json.loads(regime_raw)
            except json.JSONDecodeError:
                regime_raw = None
        canon = normalize_market_regime(
            regime_raw if isinstance(regime_raw, dict) else None,
            brief_date=row.get("brief_date"),
        )
        return (
            {
                "brief_date": str(row.get("brief_date") or ""),
                "headline": _short(row.get("headline"), 160),
                "risk_regime": canon.get("risk_regime"),
                "breadth_proxy": canon.get("breadth_proxy"),
                "volatility_state": canon.get("volatility_state"),
                "regime_confidence": canon.get("regime_confidence"),
                "macro_themes": (canon.get("macro_themes") or [])[:4],
            },
            None,
        )
    except Exception as exc:
        logger.warning("intelligence pulse: market brief failed: %s", exc)
        return None, f"research_db:{type(exc).__name__}"


def _enrich_entry_zones(
    postgres: Any,
    candidates: list[dict[str, Any]],
) -> None:
    """Attach lean entry_zone from latest ticker_analysis when missing."""
    tickers = [c["ticker"] for c in candidates if c.get("ticker") and not c.get("entry_zone")]
    if not tickers or postgres is None:
        return
    try:
        rows = postgres.execute_query(
            """
            SELECT DISTINCT ON (ticker) ticker, entry_zone, stance, target_price, stop_loss
            FROM ticker_analysis
            WHERE ticker = ANY(%s) AND analysis_type = 'standard'
            ORDER BY ticker, updated_at DESC NULLS LAST
            """,
            (tickers,),
        ) or []
    except Exception as exc:
        logger.debug("intelligence pulse: entry_zone enrich skipped: %s", exc)
        return
    by_t = {str(r.get("ticker") or "").upper(): r for r in rows}
    for c in candidates:
        t = c.get("ticker")
        row = by_t.get(t or "")
        if not row:
            continue
        if row.get("entry_zone") and not c.get("entry_zone"):
            c["entry_zone"] = _short(row.get("entry_zone"), 40)
        if row.get("stance") and not c.get("stance"):
            c["stance"] = row.get("stance")


def _fetch_candidates(fund: str | None, limit: int) -> list[dict[str, Any]]:
    try:
        from action_queue_service import (
            attach_ai_reviews,
            attach_research_context,
            build_action_queue_items,
        )
        from advise_service import build_advise_recommendations
        from ai_assistant_clients import get_assistant_research_supabase
        from flask_data_utils import get_current_positions_flask
        from postgres_client import PostgresClient
        import pandas as pd

        # Service role after fund ACL — user JWT/anon often returns empty
        # watched_tickers_v2 / signal_analysis under RLS.
        supabase = get_assistant_research_supabase(fund)
        if not supabase:
            return []

        # Fetch a wider queue then rank via advise
        queue_limit = max(limit * 2, 20)
        try:
            positions_df = get_current_positions_flask(fund) if fund else None
        except Exception:
            positions_df = pd.DataFrame(columns=["ticker"])
        if positions_df is None:
            positions_df = pd.DataFrame(columns=["ticker"])
        actions = build_action_queue_items(
            supabase, fund, queue_limit, positions_df=positions_df
        )
        pg = None
        try:
            pg = PostgresClient()
            attach_research_context(pg, actions)
            attach_ai_reviews(pg, fund or "", actions)
        except Exception as exc:
            logger.warning("intelligence pulse: enrich skipped: %s", exc)

        advise = build_advise_recommendations(action_queue=actions, limit=limit)
        # Prefer advise_pack rows; fall back to raw queue if advise empty
        source_rows: list[dict[str, Any]] = advise if advise else actions[:limit]
        # Merge entry_zone hints from action research when advise lacks them
        action_by_t = {str(a.get("ticker") or "").upper(): a for a in actions}
        lean: list[dict[str, Any]] = []
        for row in source_rows[:limit]:
            t = str(row.get("ticker") or "").upper()
            merged = dict(row)
            aq = action_by_t.get(t) or {}
            if "is_held" not in merged and "is_held" in aq:
                merged["is_held"] = aq.get("is_held")
            if not merged.get("research_context") and aq.get("research_context"):
                merged["research_context"] = aq["research_context"]
            if not merged.get("ai_review") and aq.get("ai_review"):
                merged["ai_review"] = aq["ai_review"]
            lean.append(_lean_candidate(merged))

        from ai_assistant_candidates import annotate_and_demote_tension

        if pg is not None:
            _enrich_entry_zones(pg, lean)
        lean = [c for c in lean if c.get("ticker")]
        lean = annotate_and_demote_tension(lean)
        if lean:
            return lean

        # Fallback when action queue produced nothing
        held: set[str] = set()
        if not positions_df.empty:
            col = "ticker" if "ticker" in positions_df.columns else "symbol"
            if col in positions_df.columns:
                held = {
                    str(t).upper().strip()
                    for t in positions_df[col].dropna().tolist()
                    if str(t).strip()
                }
        from ai_assistant_candidates import build_signal_fallback_candidates

        fallback = build_signal_fallback_candidates(
            supabase,
            fund=fund,
            held_tickers=held,
            limit=limit,
        )
        if pg is not None:
            _enrich_entry_zones(pg, fallback)
        fallback = [c for c in fallback if c.get("ticker")]
        return annotate_and_demote_tension(fallback)
    except Exception as exc:
        logger.warning("intelligence pulse: candidates failed: %s", exc)
        return []


def build_intelligence_pulse(
    fund: str | None,
    *,
    candidate_limit: int = _DEFAULT_CANDIDATE_LIMIT,
) -> dict[str, Any]:
    """Return structured pulse dict (for tools/tests) — not a prompt string."""
    market, market_reason = _fetch_market_pulse()
    candidates = _fetch_candidates(fund, candidate_limit)
    source = "action_queue"
    if candidates and any(c.get("source") == "signal_fallback" for c in candidates):
        source = "signal_fallback"
    elif not candidates:
        source = "none"
    return {
        "ok": True,
        "fund": fund,
        "market": market,
        "market_unavailable_reason": market_reason,
        "candidates": candidates,
        "candidate_count": len(candidates),
        "candidate_source": source,
        "degraded": bool(market_reason) or not candidates,
    }


def format_intelligence_pulse(pulse: dict[str, Any] | None) -> str:
    """Format pulse as compact markdown for LLM context."""
    if not pulse or not pulse.get("ok"):
        return "[ Today Intelligence Pulse ]\nNo pulse data available."

    lines = ["[ Today Intelligence Pulse ]", ""]
    market = pulse.get("market")
    if isinstance(market, dict) and market:
        lines.append("Market:")
        if market.get("headline"):
            lines.append(f"  Headline: {market['headline']}")
        bits = []
        for key in ("risk_regime", "breadth_proxy", "volatility_state"):
            if market.get(key):
                bits.append(f"{key}={market[key]}")
        if market.get("regime_confidence") is not None:
            bits.append(f"confidence={market['regime_confidence']}")
        if bits:
            lines.append(f"  Regime: {', '.join(bits)}")
        themes = market.get("macro_themes") or []
        if themes:
            lines.append(f"  Themes: {', '.join(str(t) for t in themes)}")
        if market.get("brief_date"):
            lines.append(f"  As of: {market['brief_date']}")
        lines.append("")
    else:
        reason = pulse.get("market_unavailable_reason") or "research_db"
        # Not market-hours: brief is a Research DB cache row.
        lines.append(f"Market: (unavailable — {reason})")
        lines.append("")

    candidates = pulse.get("candidates") or []
    source = pulse.get("candidate_source") or ""
    src_note = f" via {source}" if source and source not in ("action_queue", "none", "") else ""
    lines.append(f"Top candidates ({len(candidates)}{src_note}):")
    if not candidates:
        lines.append("  (none)")
    else:
        lines.append(
            "  Ticker | Advise | Conf | Stance/Meta | Entry | Held | Flag | Reason"
        )
        for c in candidates:
            conf = c.get("confidence")
            try:
                conf_s = f"{float(conf):.2f}" if conf is not None else "—"
            except (TypeError, ValueError):
                conf_s = "—"
            stance_meta = c.get("stance") or c.get("meta_conviction") or "—"
            held = "Y" if c.get("is_held") else ("N" if c.get("is_held") is False else "—")
            flag = "TENSION" if c.get("tension") else "—"
            reason = c.get("reason") or "—"
            if c.get("tension_reason"):
                reason = (
                    f"{reason} ({c['tension_reason']})"
                    if reason != "—"
                    else str(c["tension_reason"])
                )
            lines.append(
                f"  {c.get('ticker', '?'):<6} | {str(c.get('advise') or '—'):<5} | "
                f"{conf_s:<4} | {stance_meta} | {c.get('entry_zone') or '—'} | "
                f"{held} | {flag} | {reason}"
            )

    lines.append("")
    lines.append(
        "Note: Pulse is a ranked hint from watchlist/action-queue research"
        + (" (signal fallback when queue empty)" if source == "signal_fallback" else "")
        + ". TENSION marks a live-signal vs stored-research conflict (demoted, not a "
        "clean entry). SELL is only shown for held positions. "
        "Use tools for sector filters, named tickers, news, or deeper market narrative. "
        "Do not invent prices or entry zones."
    )
    return "\n".join(lines)


def build_and_format_intelligence_pulse(
    fund: str | None,
    *,
    candidate_limit: int = _DEFAULT_CANDIDATE_LIMIT,
) -> str:
    return format_intelligence_pulse(
        build_intelligence_pulse(fund, candidate_limit=candidate_limit)
    )
