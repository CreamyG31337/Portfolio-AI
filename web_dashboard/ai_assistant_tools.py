#!/usr/bin/env python3
"""AI Assistant v1 tool schemas and executors (GLM function calling).

Tools return lean JSON. Empty data uses ``{ok: false, reason: "no_data"}``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

from ai_assistant_question_matrix import REQUIRED_TOOL_NAMES

logger = logging.getLogger(__name__)

_MAX_TOOL_JSON_CHARS = 12_000
_DEFAULT_CANDIDATE_LIMIT = 12


@dataclass
class AssistantToolContext:
    """Per-request execution context (fund-scoped, ACL via caller)."""

    user_id: str
    fund: str | None = None


def _ok(data: dict[str, Any]) -> dict[str, Any]:
    out = {"ok": True}
    out.update(data)
    return out


def _no_data(reason: str = "no_data", **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False, "reason": reason}
    out.update(extra)
    return out


def _truncate_json(payload: dict[str, Any], max_chars: int = _MAX_TOOL_JSON_CHARS) -> str:
    raw = json.dumps(payload, default=str, ensure_ascii=False)
    if len(raw) <= max_chars:
        return raw
    # Progressive shrink for list-heavy payloads
    shrunk = dict(payload)
    for key in (
        "candidates",
        "results",
        "articles",
        "sectors",
        "holdings",
        "top_signals",
        "theses",
        "events",
        "ideas",
        "earnings",
        "by_source",
        "by_domain",
        "best_calls",
        "worst_calls",
        "trades",
        "curve",
        "biggest_moves",
    ):
        val = shrunk.get(key)
        if isinstance(val, list) and len(val) > 3:
            shrunk[key] = val[: max(3, len(val) // 2)]
            shrunk["truncated"] = True
            raw = json.dumps(shrunk, default=str, ensure_ascii=False)
            if len(raw) <= max_chars:
                return raw
    return json.dumps(
        {
            "ok": False,
            "reason": "truncated",
            "message": "Tool result exceeded size cap; ask a narrower question.",
        },
        ensure_ascii=False,
    )


def _supabase(fund: str | None = None):
    """Service-role research client after fund ACL (see ai_assistant_clients)."""
    from ai_assistant_clients import get_assistant_research_supabase

    return get_assistant_research_supabase(fund)


def _postgres():
    from postgres_client import PostgresClient

    return PostgresClient()


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
        logger.warning("tool sectors lookup failed: %s", exc)
    return out


def _tool_list_entry_candidates(
    ctx: AssistantToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    from action_queue_service import (
        attach_ai_reviews,
        attach_research_context,
        build_action_queue_items,
    )
    from advise_service import build_advise_recommendations
    from ai_intelligence_pulse import _enrich_entry_zones, _lean_candidate

    limit = int(args.get("limit") or _DEFAULT_CANDIDATE_LIMIT)
    limit = max(1, min(limit, 25))
    sector_filter = (args.get("sector") or "").strip()
    action_filter = (args.get("action") or "").strip().upper()
    held_only = bool(args.get("held_only") or False)

    supabase = _supabase(ctx.fund)
    if not supabase:
        return _no_data("supabase_unavailable")

    fetch_n = max(limit * 3, 30) if (sector_filter or action_filter or held_only) else max(limit * 2, 20)
    try:
        from flask_data_utils import get_current_positions_flask
        import pandas as pd

        positions_df = get_current_positions_flask(ctx.fund) if ctx.fund else None
    except Exception:
        import pandas as pd

        positions_df = pd.DataFrame(columns=["ticker"])
    if positions_df is None:
        import pandas as pd

        positions_df = pd.DataFrame(columns=["ticker"])

    actions = build_action_queue_items(
        supabase, ctx.fund, fetch_n, positions_df=positions_df
    )
    pg = None
    try:
        pg = _postgres()
        attach_research_context(pg, actions)
        attach_ai_reviews(pg, ctx.fund or "", actions)
    except Exception as exc:
        logger.warning("list_entry_candidates enrich: %s", exc)

    advise = build_advise_recommendations(action_queue=actions, limit=fetch_n)
    source = advise if advise else actions
    action_by_t = {str(a.get("ticker") or "").upper(): a for a in actions}

    sector_map = _sectors_for_tickers(
        supabase,
        [str(r.get("ticker") or "").upper() for r in source if r.get("ticker")],
    )

    lean: list[dict[str, Any]] = []
    for row in source:
        t = str(row.get("ticker") or "").upper()
        if not t:
            continue
        aq = action_by_t.get(t) or {}
        merged = dict(row)
        if "is_held" not in merged and "is_held" in aq:
            merged["is_held"] = aq.get("is_held")
        if not merged.get("research_context") and aq.get("research_context"):
            merged["research_context"] = aq["research_context"]
        advise_action = str(
            merged.get("advise") or merged.get("action") or ""
        ).upper()
        is_held = bool(merged.get("is_held"))
        if held_only and not is_held:
            continue
        if action_filter and advise_action != action_filter:
            continue
        sec = sector_map.get(t, "")
        if sector_filter and sector_filter.lower() not in sec.lower():
            continue
        item = _lean_candidate(merged)
        if sec:
            item["sector"] = sec
        lean.append(item)

    if pg is not None:
        _enrich_entry_zones(pg, lean)

    source_label = "action_queue"
    if not lean:
        # Fallback: watchlist signal_analysis ranking (queue often empty when
        # there are no BUYs and SELL/RISK need held positions).
        held: set[str] = set()
        if positions_df is not None and not getattr(positions_df, "empty", True):
            col = "ticker" if "ticker" in positions_df.columns else "symbol"
            if col in positions_df.columns:
                held = {
                    str(t).upper().strip()
                    for t in positions_df[col].dropna().tolist()
                    if str(t).strip()
                }
        try:
            from ai_assistant_candidates import build_signal_fallback_candidates

            lean = build_signal_fallback_candidates(
                supabase,
                fund=ctx.fund,
                held_tickers=held,
                limit=limit,
                sector_filter=sector_filter or None,
                action_filter=action_filter or None,
                held_only=held_only,
            )
            if lean:
                source_label = "signal_fallback"
                if pg is not None:
                    _enrich_entry_zones(pg, lean)
        except Exception as exc:
            logger.warning("list_entry_candidates signal fallback failed: %s", exc)

    from ai_assistant_candidates import annotate_and_demote_tension

    lean = annotate_and_demote_tension(lean)
    lean = lean[:limit]
    if not lean:
        return _no_data(
            "no_data",
            sector=sector_filter or None,
            action=action_filter or None,
            held_only=held_only,
        )
    return _ok(
        {
            "candidates": lean,
            "count": len(lean),
            "source": source_label,
            "filters": {
                "sector": sector_filter or None,
                "action": action_filter or None,
                "held_only": held_only,
            },
        }
    )


def _tool_get_ticker_setup(
    ctx: AssistantToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    ticker = str(args.get("ticker") or "").upper().strip()
    if not ticker:
        return _no_data("missing_ticker")
    try:
        pg = _postgres()
        ta = pg.execute_query(
            """
            SELECT ticker, stance, sentiment, confidence_score, timeframe,
                   entry_zone, target_price, stop_loss, key_levels,
                   catalysts, risks, invalidation, summary, updated_at
            FROM ticker_analysis
            WHERE ticker = %s AND analysis_type = 'standard'
            ORDER BY updated_at DESC NULLS LAST
            LIMIT 1
            """,
            (ticker,),
        ) or []
        meta = pg.execute_query(
            """
            SELECT ticker, unified_conviction, confidence_adjusted,
                   contradictions, action_items, narrative, updated_at
            FROM ticker_meta_analysis
            WHERE ticker = %s
            ORDER BY updated_at DESC NULLS LAST
            LIMIT 1
            """,
            (ticker,),
        ) or []
    except Exception as exc:
        logger.warning("get_ticker_setup failed for %s: %s", ticker, exc)
        return _no_data("query_failed", ticker=ticker)

    if not ta and not meta:
        return _no_data("no_data", ticker=ticker)

    ta_row = ta[0] if ta else {}
    meta_row = meta[0] if meta else {}
    narrative = meta_row.get("narrative")
    if isinstance(narrative, str) and len(narrative) > 600:
        narrative = narrative[:599] + "…"
    summary = ta_row.get("summary")
    if isinstance(summary, str) and len(summary) > 300:
        summary = summary[:299] + "…"

    return _ok(
        {
            "ticker": ticker,
            "stance": ta_row.get("stance"),
            "sentiment": ta_row.get("sentiment"),
            "confidence_score": ta_row.get("confidence_score"),
            "timeframe": ta_row.get("timeframe"),
            "entry_zone": ta_row.get("entry_zone"),
            "target_price": ta_row.get("target_price"),
            "stop_loss": ta_row.get("stop_loss"),
            "key_levels": ta_row.get("key_levels"),
            "catalysts": (ta_row.get("catalysts") or [])[:5]
            if isinstance(ta_row.get("catalysts"), list)
            else ta_row.get("catalysts"),
            "risks": (ta_row.get("risks") or [])[:5]
            if isinstance(ta_row.get("risks"), list)
            else ta_row.get("risks"),
            "invalidation": ta_row.get("invalidation"),
            "summary": summary,
            "meta_conviction": meta_row.get("unified_conviction"),
            "meta_confidence": meta_row.get("confidence_adjusted"),
            "contradictions": (meta_row.get("contradictions") or [])[:4]
            if isinstance(meta_row.get("contradictions"), list)
            else meta_row.get("contradictions"),
            "action_items": (meta_row.get("action_items") or [])[:4]
            if isinstance(meta_row.get("action_items"), list)
            else meta_row.get("action_items"),
            "meta_narrative": narrative,
            "analysis_updated_at": str(ta_row.get("updated_at") or "") or None,
            "meta_updated_at": str(meta_row.get("updated_at") or "") or None,
        }
    )


def _tool_get_market_brief(
    ctx: AssistantToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    try:
        from market_brief_service import fetch_latest_brief
        from market_regime_normalization import normalize_market_regime

        row = fetch_latest_brief(_postgres())
        if not row:
            return _no_data()
        regime_raw = row.get("regime_json")
        if isinstance(regime_raw, str):
            try:
                regime_raw = json.loads(regime_raw)
            except json.JSONDecodeError:
                regime_raw = None
        canon = normalize_market_regime(
            regime_raw if isinstance(regime_raw, dict) else None,
            brief_date=row.get("brief_date"),
        )
        narrative = row.get("narrative")
        if isinstance(narrative, str) and len(narrative) > 900:
            narrative = narrative[:899] + "…"
        return _ok(
            {
                "brief_date": str(row.get("brief_date") or ""),
                "headline": row.get("headline"),
                "narrative": narrative,
                "regime": {
                    "risk_regime": canon.get("risk_regime"),
                    "breadth_proxy": canon.get("breadth_proxy"),
                    "volatility_state": canon.get("volatility_state"),
                    "regime_confidence": canon.get("regime_confidence"),
                    "macro_themes": (canon.get("macro_themes") or [])[:6],
                    "leadership_note": canon.get("leadership_note"),
                },
            }
        )
    except Exception as exc:
        logger.warning("get_market_brief failed: %s", exc)
        return _no_data("query_failed")


def _tool_get_sector_rotation(
    ctx: AssistantToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    sector = (args.get("sector") or "").strip()
    try:
        from research_repository import ResearchRepository

        repo = ResearchRepository()
        rows = repo.list_recent_sector_meta_analysis(limit=48)
    except Exception as exc:
        logger.warning("get_sector_rotation failed: %s", exc)
        return _no_data("query_failed")

    def _lean_sector(r: dict[str, Any]) -> dict[str, Any]:
        return {
            "sector": r.get("sector"),
            "sector_stance": r.get("sector_stance"),
            "momentum_state": r.get("momentum_state"),
            "news_pressure": r.get("news_pressure"),
            "rotation_rank": r.get("rotation_rank"),
            "confidence": r.get("confidence"),
            "key_drivers": (r.get("key_drivers") or [])[:4]
            if isinstance(r.get("key_drivers"), list)
            else r.get("key_drivers"),
            "risk_flags": (r.get("risk_flags") or [])[:4]
            if isinstance(r.get("risk_flags"), list)
            else r.get("risk_flags"),
            "as_of": str(r.get("as_of") or r.get("updated_at") or "") or None,
        }

    if sector:
        matched = [
            _lean_sector(r)
            for r in rows
            if sector.lower() in str(r.get("sector") or "").lower()
        ]
        # Dedupe by sector keeping first (most recent)
        seen: set[str] = set()
        uniq: list[dict[str, Any]] = []
        for m in matched:
            key = str(m.get("sector") or "").lower()
            if key in seen:
                continue
            seen.add(key)
            uniq.append(m)
        if not uniq:
            return _no_data("no_data", sector=sector)
        return _ok({"sectors": uniq, "count": len(uniq)})

    # Top rotation snapshot: unique sectors, prefer higher rotation_rank
    by_sec: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = str(r.get("sector") or "").strip()
        if not key or key in by_sec:
            continue
        by_sec[key] = _lean_sector(r)
    ranked = sorted(
        by_sec.values(),
        key=lambda x: float(x.get("rotation_rank") or 0),
        reverse=True,
    )[:12]
    if not ranked:
        return _no_data()
    return _ok({"sectors": ranked, "count": len(ranked)})


def _tool_get_signals_overview(
    ctx: AssistantToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    try:
        from ui_ai_phase2_digests import build_signals_overview_digest

        supabase = _supabase(ctx.fund)
        if not supabase:
            return _no_data("supabase_unavailable")
        digest = build_signals_overview_digest(supabase, top_n=12)
        if not digest:
            return _no_data()
        return _ok({"digest": digest})
    except Exception as exc:
        logger.warning("get_signals_overview failed: %s", exc)
        return _no_data("query_failed")


def _tool_get_holdings_snapshot(
    ctx: AssistantToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    from flask_data_utils import get_current_positions_flask

    if not ctx.fund:
        return _no_data("missing_fund")
    try:
        df = get_current_positions_flask(ctx.fund)
    except Exception as exc:
        logger.warning("get_holdings_snapshot failed: %s", exc)
        return _no_data("query_failed")

    if df is None or getattr(df, "empty", True):
        return _no_data("no_positions", fund=ctx.fund)

    want = args.get("tickers")
    want_set: set[str] | None = None
    if isinstance(want, list) and want:
        want_set = {str(t).upper().strip() for t in want if t}
    elif isinstance(want, str) and want.strip():
        want_set = {want.upper().strip()}

    holdings: list[dict[str, Any]] = []
    records = df.to_dict("records")
    for row in records:
        ticker = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
        if not ticker:
            continue
        if want_set is not None and ticker not in want_set:
            continue
        holdings.append(
            {
                "ticker": ticker,
                "shares": row.get("quantity", row.get("shares")),
                "avg_price": row.get("cost_basis", row.get("avg_price", row.get("average_cost"))),
                "current_price": row.get("current_price", row.get("price")),
                "market_value": row.get("market_value", row.get("total_value")),
                "pnl_pct": row.get("total_pnl_pct", row.get("pnl_pct", row.get("unrealized_pnl_pct"))),
                "daily_pnl_pct": row.get("daily_pnl_pct", row.get("day_change_pct")),
                "weight_pct": row.get("portfolio_weight", row.get("weight_pct", row.get("pct_port"))),
            }
        )
        if len(holdings) >= 40:
            break

    if not holdings:
        return _no_data("no_matching_tickers", fund=ctx.fund)
    return _ok({"fund": ctx.fund, "holdings": holdings, "count": len(holdings)})


_WEB_TIME_RANGES = {"day", "week", "month", "year"}


def _tool_search_web(
    ctx: AssistantToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return _no_data("missing_query")
    tickers = args.get("tickers") or []
    if isinstance(tickers, str):
        tickers = [tickers]
    # Widen the lookback beyond a week so the model can investigate older moves.
    # SearXNG only supports these coarse buckets (no arbitrary since/until).
    time_range = str(args.get("time_range") or "week").strip().lower()
    if time_range not in _WEB_TIME_RANGES:
        time_range = "week"
    try:
        from searxng_client import get_searxng_client

        client = get_searxng_client()
        if not client:
            return _no_data("searxng_unavailable")
        # Prefer news category for company news questions
        result = client.search(query, categories=["news", "general"], time_range=time_range, max_results=6)
        results = []
        for r in (result.get("results") or [])[:6]:
            results.append(
                {
                    "title": r.get("title"),
                    "url": r.get("url") or r.get("link"),
                    "snippet": (r.get("content") or r.get("snippet") or "")[:280],
                    "engine": r.get("engine"),
                }
            )
        if not results:
            return _no_data("no_data", query=query, time_range=time_range)
        return _ok(
            {
                "query": query,
                "tickers": tickers,
                "time_range": time_range,
                "results": results,
                "count": len(results),
            }
        )
    except Exception as exc:
        logger.warning("search_web failed: %s", exc)
        return _no_data("query_failed", query=query)


def _tool_search_research(
    ctx: AssistantToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return _no_data("missing_query")
    max_results = int(args.get("max_results") or 3)
    max_results = max(1, min(max_results, 5))
    min_similarity = float(args.get("min_similarity") or 0.6)
    try:
        from ollama_client import get_ollama_client
        from research_repository import ResearchRepository

        ollama = get_ollama_client()
        if not ollama:
            return _no_data("ollama_unavailable")
        embedding = ollama.generate_embedding(query)
        if not embedding:
            return _no_data("embedding_failed")
        repo = ResearchRepository()
        articles = repo.search_similar_articles(
            embedding,
            limit=max_results,
            min_similarity=min_similarity,
        )
        lean = []
        for a in articles or []:
            lean.append(
                {
                    "title": a.get("title"),
                    "source": a.get("source"),
                    "similarity": a.get("similarity"),
                    "summary": (a.get("summary") or "")[:320],
                    "tickers": a.get("tickers") or a.get("ticker"),
                    "published_at": str(a.get("published_at") or "") or None,
                }
            )
        if not lean:
            return _no_data("no_data", query=query)
        return _ok({"query": query, "articles": lean, "count": len(lean)})
    except Exception as exc:
        logger.warning("search_research failed: %s", exc)
        return _no_data("query_failed", query=query)


def _resolve_window_days(
    window: str | None,
    since: str | None,
    default_days: int | None,
) -> int | None:
    """Turn a window token / since-date into a day count.

    Returns None to mean "all history" (no cutoff). ``since`` (YYYY-MM-DD) wins
    over ``window``. Accepts Nd/Nw/Nm/Ny and 'all'/'max'/'inception'.
    """
    from datetime import date as _date

    s = str(since or "").strip()
    if s:
        try:
            parsed = _date.fromisoformat(s[:10])
            delta = (_date.today() - parsed).days
            return max(1, delta)
        except ValueError:
            pass
    w = str(window or "").strip().lower()
    if not w:
        return default_days
    if w in ("all", "max", "inception", "since_inception", "sinceinception"):
        return None
    import re

    m = re.fullmatch(r"(\d+)\s*([dwmy])", w)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        mult = {"d": 1, "w": 7, "m": 30, "y": 365}[unit]
        return max(1, n * mult)
    # Bare integer = days.
    if w.isdigit():
        return max(1, int(w))
    return default_days


def _downsample(rows: list[Any], max_points: int = 12) -> list[Any]:
    """Evenly sample a series down to max_points, always keeping first and last."""
    n = len(rows)
    if n <= max_points or max_points < 2:
        return list(rows)
    step = (n - 1) / (max_points - 1)
    idxs = sorted({round(i * step) for i in range(max_points)})
    return [rows[i] for i in idxs]


def _tool_get_portfolio_performance(
    ctx: AssistantToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    if not ctx.fund:
        return _no_data("missing_fund")
    import pandas as pd

    from flask_data_utils import calculate_portfolio_value_over_time_flask

    days = _resolve_window_days(args.get("window"), args.get("since"), None)
    window_label = "all" if days is None else f"{days}d"
    try:
        curve = calculate_portfolio_value_over_time_flask(ctx.fund, days=days)
    except Exception as exc:
        logger.warning("get_portfolio_performance failed for %s: %s", ctx.fund, exc)
        return _no_data("query_failed", fund=ctx.fund)

    if curve is None or getattr(curve, "empty", True):
        return _no_data("no_data", fund=ctx.fund, window=window_label)
    if "performance_pct" not in curve.columns or "date" not in curve.columns:
        return _no_data("no_data", fund=ctx.fund, window=window_label)

    curve = curve.sort_values("date").reset_index(drop=True)
    perf = curve["performance_pct"].astype(float)
    dates = pd.to_datetime(curve["date"])
    values = curve.get("value")

    # performance_pct is normalized to ~0 at the window start, so the last row is
    # the window return.
    total_return_pct = round(float(perf.iloc[-1]), 2)
    peak_idx = int(perf.idxmax())
    cummax = perf.cummax()
    drawdown = perf - cummax
    dd_idx = int(drawdown.idxmin())

    start_date = dates.iloc[0].strftime("%Y-%m-%d")
    end_date = dates.iloc[-1].strftime("%Y-%m-%d")
    elapsed_days = max(1, (dates.iloc[-1] - dates.iloc[0]).days)

    cagr_pct = None
    if elapsed_days >= 300:  # only annualize when the window spans ~a year+
        years = elapsed_days / 365.0
        growth = 1.0 + (total_return_pct / 100.0)
        if growth > 0:
            cagr_pct = round((growth ** (1.0 / years) - 1.0) * 100.0, 2)

    points = []
    for i in range(len(curve)):
        pt = {
            "date": dates.iloc[i].strftime("%Y-%m-%d"),
            "perf_pct": round(float(perf.iloc[i]), 2),
        }
        if values is not None:
            try:
                pt["value"] = round(float(values.iloc[i]), 2)
            except (TypeError, ValueError):
                pass
        points.append(pt)
    curve_out = _downsample(points, max_points=12)

    def _val(i: int) -> float | None:
        if values is None:
            return None
        try:
            return round(float(values.iloc[i]), 2)
        except (TypeError, ValueError):
            return None

    return _ok(
        {
            "fund": ctx.fund,
            "window": window_label,
            "start_date": start_date,
            "end_date": end_date,
            "trading_days": int(len(curve)),
            "start_value": _val(0),
            "end_value": _val(len(curve) - 1),
            "total_return_pct": total_return_pct,
            "peak": {
                "date": dates.iloc[peak_idx].strftime("%Y-%m-%d"),
                "pct": round(float(perf.iloc[peak_idx]), 2),
            },
            "max_drawdown": {
                "date": dates.iloc[dd_idx].strftime("%Y-%m-%d"),
                "pct": round(float(drawdown.iloc[dd_idx]), 2),
            },
            "cagr_pct": cagr_pct,
            "curve": curve_out,
        }
    )


def _tool_get_trade_history(
    ctx: AssistantToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    if not ctx.fund:
        return _no_data("missing_fund")
    import pandas as pd

    from flask_data_utils import get_trade_log_flask
    from utils.trade_reason import infer_trade_action, is_sell_reason

    ticker = str(args.get("ticker") or "").upper().strip()
    action_filter = str(args.get("action") or "").upper().strip()
    since = str(args.get("since") or "").strip()
    limit = int(args.get("limit") or 20)
    limit = max(1, min(limit, 50))

    try:
        df = get_trade_log_flask(limit=1000, fund=ctx.fund)
    except Exception as exc:
        logger.warning("get_trade_history failed for %s: %s", ctx.fund, exc)
        return _no_data("query_failed", fund=ctx.fund)

    if df is None or getattr(df, "empty", True):
        return _no_data("no_trades", fund=ctx.fund)

    ticker_col = "ticker" if "ticker" in df.columns else "symbol"
    ts_col = "timestamp" if "timestamp" in df.columns else "date"
    work = df.copy()
    # Column name must not start with "_" — itertuples renames those positionally.
    if ts_col in work.columns:
        work["parsed_ts"] = pd.to_datetime(work[ts_col], errors="coerce", utc=True)
    else:
        work["parsed_ts"] = pd.NaT

    if ticker and ticker_col in work.columns:
        work = work[work[ticker_col].astype(str).str.upper() == ticker]
    if since:
        try:
            cutoff = pd.Timestamp(since[:10], tz="UTC")
            work = work[work["parsed_ts"] >= cutoff]
        except (ValueError, TypeError):
            pass

    reason_series = work["reason"] if "reason" in work.columns else None
    if action_filter in ("BUY", "SELL") and reason_series is not None:
        actions = reason_series.apply(lambda r: infer_trade_action(r, default="BUY"))
        work = work[actions == action_filter]

    work = work.sort_values("parsed_ts", ascending=False, na_position="last")

    # Realized P&L is persisted per sell row by the FIFO processor (trade_log.pnl,
    # with the matched cost_basis). Surface it when present; native currency per row,
    # so realized totals are aggregated per currency (never CAD+USD summed together).
    has_pnl = "pnl" in work.columns

    rows: list[dict[str, Any]] = []
    buys = sells = 0
    bought_total = sold_total = 0.0
    for row in work.head(limit).itertuples(index=False):
        reason = getattr(row, "reason", "") or ""
        action = infer_trade_action(reason, default="BUY")
        sym = str(getattr(row, ticker_col, "") or getattr(row, "symbol", "") or "").upper()
        qty = getattr(row, "quantity", None)
        if qty is None:
            qty = getattr(row, "shares", None)
        price = getattr(row, "price", None)
        total = getattr(row, "total_value", None)
        try:
            if total in (None, "") and qty is not None and price is not None:
                total = float(qty) * float(price)
        except (TypeError, ValueError):
            total = None
        ts = getattr(row, "parsed_ts", None)
        date_str = ts.strftime("%Y-%m-%d") if ts is not None and pd.notna(ts) else None
        trade_row = {
            "date": date_str,
            "action": action,
            "ticker": sym,
            "qty": _num(qty),
            "price": _num(price),
            "total": _num(total),
        }
        # Only sells carry realized P&L; buys default to 0 in the DB.
        if has_pnl and is_sell_reason(reason):
            trade_row["realized_pnl"] = _num(getattr(row, "pnl", None))
            trade_row["currency"] = str(getattr(row, "currency", "") or "") or None
        rows.append(trade_row)

    # Summary over the full filtered set (not just the returned page).
    if reason_series is not None:
        sell_mask = work["reason"].apply(is_sell_reason)
        sells = int(sell_mask.sum())
        buys = int(len(work) - sells)
    # Realized P&L accumulated per currency (pnl is stored in the trade's native currency).
    realized: dict[str, dict[str, float]] = {}
    for row in work.itertuples(index=False):
        try:
            t = getattr(row, "total_value", None)
            if t in (None, ""):
                q = getattr(row, "quantity", None) or getattr(row, "shares", None)
                p = getattr(row, "price", None)
                t = float(q) * float(p) if q is not None and p is not None else 0.0
            t = float(t)
        except (TypeError, ValueError):
            t = 0.0
        is_sell = is_sell_reason(getattr(row, "reason", "") or "")
        if is_sell:
            sold_total += t
        else:
            bought_total += t
        if has_pnl and is_sell:
            ccy = str(getattr(row, "currency", "") or "USD").upper()
            bucket = realized.setdefault(ccy, {"pnl": 0.0, "cost_basis": 0.0, "sales": 0})
            bucket["pnl"] += _num(getattr(row, "pnl", None)) or 0.0
            bucket["cost_basis"] += _num(getattr(row, "cost_basis", None)) or 0.0
            bucket["sales"] += 1

    realized_by_currency: dict[str, dict[str, Any]] = {}
    for ccy, b in realized.items():
        cb = b["cost_basis"]
        realized_by_currency[ccy] = {
            "pnl": round(b["pnl"], 2),
            "cost_basis": round(cb, 2),
            "return_pct": round(b["pnl"] / cb * 100, 2) if cb > 0 else None,
            "sales": b["sales"],
        }

    if not rows:
        return _no_data("no_data", fund=ctx.fund, ticker=ticker or None)
    summary: dict[str, Any] = {
        "buys": buys,
        "sells": sells,
        "gross_bought": round(bought_total, 2),
        "gross_sold": round(sold_total, 2),
    }
    if realized_by_currency:
        summary["realized_pnl_by_currency"] = realized_by_currency
    return _ok(
        {
            "fund": ctx.fund,
            "ticker": ticker or None,
            "count": len(rows),
            "matched": int(len(work)),
            "trades": rows,
            "summary": summary,
            "note": (
                "Realized P&L is FIFO, matched and stored at sell time; "
                "totals are per currency (native), not converted to a base currency."
            ),
        }
    )


def _tool_get_price_history(
    ctx: AssistantToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    ticker = str(args.get("ticker") or "").upper().strip()
    if not ticker:
        return _no_data("missing_ticker")
    import pandas as pd

    days = _resolve_window_days(args.get("window"), args.get("since"), 90)
    if days is None:
        days = 1825  # cap "all" at ~5y for a single ticker to bound the fetch
    window_label = f"{days}d"

    try:
        from datetime import datetime, timedelta, timezone

        from config.settings import get_settings
        from market_data.data_fetcher import MarketDataFetcher
        from market_data.price_cache import PriceCache

        settings = get_settings()
        fetcher = MarketDataFetcher(cache_instance=PriceCache(settings=settings))
        end_d = datetime.now(timezone.utc)
        start_d = end_d - timedelta(days=days)
        result = fetcher.fetch_price_data(ticker, start_d, end_d)
    except Exception as exc:
        logger.warning("get_price_history failed for %s: %s", ticker, exc)
        return _no_data("query_failed", ticker=ticker)

    df = getattr(result, "df", None)
    if df is None or getattr(df, "empty", True):
        return _no_data("no_data", ticker=ticker, window=window_label)

    close_col = next(
        (c for c in df.columns if str(c).lower() == "close"),
        None,
    )
    if close_col is None:
        return _no_data("no_data", ticker=ticker, window=window_label)

    closes = df[close_col].astype(float).dropna()
    if closes.empty:
        return _no_data("no_data", ticker=ticker, window=window_label)

    idx = closes.index
    def _d(i: Any) -> str:
        try:
            return pd.Timestamp(i).strftime("%Y-%m-%d")
        except Exception:
            return str(i)[:10]

    first_close = float(closes.iloc[0])
    last_close = float(closes.iloc[-1])
    change_pct = round((last_close - first_close) / first_close * 100, 2) if first_close else None
    hi_idx = closes.idxmax()
    lo_idx = closes.idxmin()

    # Biggest single-day moves (the hook for "what happened on that date").
    pct = closes.pct_change().dropna() * 100
    biggest = []
    if not pct.empty:
        ordered = pct.reindex(pct.abs().sort_values(ascending=False).index)
        for i, v in ordered.head(5).items():
            biggest.append({"date": _d(i), "pct": round(float(v), 2)})

    points = [
        {"date": _d(idx[i]), "close": round(float(closes.iloc[i]), 4)}
        for i in range(len(closes))
    ]
    curve_out = _downsample(points, max_points=12)

    return _ok(
        {
            "ticker": ticker,
            "window": window_label,
            "start_date": _d(idx[0]),
            "end_date": _d(idx[-1]),
            "bars": int(len(closes)),
            "first_close": round(first_close, 4),
            "last_close": round(last_close, 4),
            "change_pct": change_pct,
            "high": {"date": _d(hi_idx), "close": round(float(closes.loc[hi_idx]), 4)},
            "low": {"date": _d(lo_idx), "close": round(float(closes.loc[lo_idx]), 4)},
            "biggest_moves": biggest,
            "curve": curve_out,
        }
    )


def _num(v: Any) -> float | None:
    """Best-effort float for lean trade rows; None when not numeric."""
    if v is None or v == "":
        return None
    try:
        import pandas as pd

        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None


def _clamp_int(v: Any, *, default: int, lo: int, hi: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _round_or_none(v: Any, ndigits: int = 2) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return round(f, ndigits)


def _pct(frac: Any) -> float | None:
    f = _round_or_none(frac, 6)
    return None if f is None else round(f * 100.0, 1)


def _tool_get_track_record(
    ctx: AssistantToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Learn-layer track record: were our stances right? Hit rate + excess return
    sliced by stance source, verdict, and evidence domain (source-ROI).
    """
    from track_record_service import build_track_record_summary

    horizon_days = _clamp_int(args.get("horizon_days"), default=30, lo=1, hi=365)
    if horizon_days not in (7, 30, 90):
        horizon_days = 30
    try:
        summary = build_track_record_summary(_postgres(), horizon_days=horizon_days)
    except Exception as exc:
        logger.warning("get_track_record failed: %s", exc)
        return _no_data("query_failed")

    total = int(summary.get("total_scored") or 0)
    if total == 0:
        return _no_data("no_data", horizon_days=horizon_days)

    counts = summary.get("counts_by_source") or {}
    rate_by_source = summary.get("hit_rate_by_source") or {}
    avg_excess = summary.get("avg_excess_by_source") or {}
    sources: list[dict[str, Any]] = []
    for src, bucket in counts.items():
        scored = int((bucket or {}).get("scored") or 0)
        if scored <= 0:
            continue
        sources.append(
            {
                "source": src,
                "scored": scored,
                "hits": int((bucket or {}).get("hits") or 0),
                "hit_rate_pct": _pct(rate_by_source.get(src)),
                "avg_excess_return": _round_or_none(avg_excess.get(src), 4),
            }
        )
    # Rank by sample size first so thin, noisy sources don't top the list.
    sources.sort(key=lambda r: (-r["scored"], -(r["hit_rate_pct"] or 0)))

    verdicts: dict[str, dict[str, Any]] = {}
    vcounts = summary.get("counts_by_verdict") or {}
    vrate = summary.get("hit_rate_by_verdict") or {}
    for v, bucket in vcounts.items():
        scored = int((bucket or {}).get("scored") or 0)
        if scored <= 0:
            continue
        verdicts[v] = {"scored": scored, "hit_rate_pct": _pct(vrate.get(v))}

    def _call(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "ticker": row.get("ticker"),
            "source": row.get("source"),
            "excess_return": _round_or_none(row.get("excess_return"), 4),
        }

    best = [_call(r) for r in (summary.get("best_calls") or [])[:3]]
    worst = [_call(r) for r in (summary.get("worst_calls") or [])[:3]]

    domains: list[dict[str, Any]] = []
    for d in (summary.get("by_domain") or [])[:5]:
        domains.append(
            {
                "domain": d.get("domain"),
                "scored": d.get("scored"),
                "hit_rate_pct": _pct(d.get("hit_rate")),
                "mean_excess": _round_or_none(d.get("mean_excess"), 4),
            }
        )

    return _ok(
        {
            "horizon_days": horizon_days,
            "total_scored": total,
            "by_source": sources[:8],
            "by_verdict": verdicts,
            "by_domain": domains,
            "best_calls": best,
            "worst_calls": worst,
            "note": (
                "hit_rate_pct = share of stances that beat their benchmark over the "
                "horizon; excess_return is vs benchmark. Low 'scored' = small sample, "
                "treat as noisy. Use to weight which sources/verdicts to trust — not a "
                "buy/sell signal by itself."
            ),
        }
    )


def _tool_get_theses_attention(
    ctx: AssistantToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Human thesis threads needing review: due/stale/weak or LLM TENSION/STALE_THESIS."""
    from user_insights_service import list_theses_attention

    ticker = str(args.get("ticker") or "").upper().strip() or None
    limit = _clamp_int(args.get("limit"), default=15, lo=1, hi=40)
    try:
        # Pass ticker into the service (SQL filter) so a global top-N cannot hide it.
        rows = list_theses_attention(_postgres(), limit=limit, ticker=ticker)
    except Exception as exc:
        logger.warning("get_theses_attention failed: %s", exc)
        return _no_data("query_failed")

    out: list[dict[str, Any]] = []
    for r in rows or []:
        tk = str(r.get("ticker") or "").upper()
        out.append(
            {
                "ticker": tk or None,
                "title": (str(r.get("title") or "")[:120] or None),
                "disposition": r.get("disposition"),
                "reasons": r.get("attention_reasons") or [],
                "llm_verdict": r.get("llm_verdict") or None,
                "age_days": r.get("age_days"),
                "review_status": r.get("review_status"),
            }
        )
    if not out:
        return _no_data("no_data", ticker=ticker)
    return _ok(
        {
            "count": len(out),
            "theses": out,
            "note": (
                "Human thesis threads flagged for review (due/stale/weak, or the LLM "
                "review found TENSION / STALE_THESIS). Advisory only — surface them so "
                "the user can revisit; do not auto-trade off them."
            ),
        }
    )


def _tool_get_confluence(
    ctx: AssistantToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Recent confluence events: multiple independent signal families aligning on a ticker."""
    from confluence_service import fetch_recent_confluence_events

    ticker = str(args.get("ticker") or "").upper().strip()
    days = _clamp_int(args.get("days"), default=7, lo=1, hi=30)
    limit = _clamp_int(args.get("limit"), default=15, lo=1, hi=25)
    tickers = [ticker] if ticker else None
    try:
        rows = fetch_recent_confluence_events(
            _postgres(), tickers=tickers, days=days, limit=limit
        )
    except Exception as exc:
        logger.warning("get_confluence failed: %s", exc)
        return _no_data("query_failed")
    if not rows:
        return _no_data("no_data", ticker=ticker or None, days=days)

    out: list[dict[str, Any]] = []
    for r in rows:
        fams = r.get("families")
        if not isinstance(fams, list):
            fams = [fams] if fams else []
        out.append(
            {
                "ticker": str(r.get("ticker") or "").upper() or None,
                "direction": r.get("direction"),
                "score": r.get("score"),
                "families": [str(f) for f in fams],
                "as_of": str(r.get("as_of") or "")[:10] or None,
            }
        )
    return _ok(
        {
            "count": len(out),
            "days": days,
            "events": out,
            "note": (
                "Confluence = several independent signal families (insider / dilution / "
                "filing / confluence) landing on the same ticker; higher score = more "
                "families aligned. direction='risk' can downgrade a BUY."
            ),
        }
    )


def _tool_get_ideas_triage(
    ctx: AssistantToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Untriaged discovery ideas (Alpha Research / Opportunity Discovery), highest relevance first."""
    from today_briefing_service import fetch_alpha_ideas

    ticker = str(args.get("ticker") or "").upper().strip() or None
    limit = _clamp_int(args.get("limit"), default=12, lo=1, hi=25)
    try:
        rows = fetch_alpha_ideas(_postgres(), limit=limit, ticker=ticker)
    except Exception as exc:
        logger.warning("get_ideas_triage failed: %s", exc)
        return _no_data("query_failed")
    if not rows:
        return _no_data("no_data", ticker=ticker)

    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "title": (str(r.get("title") or "")[:140] or None),
                "tickers": [str(t).upper() for t in (r.get("tickers") or [])][:8],
                "relevance": _round_or_none(r.get("relevance_score")),
                "type": r.get("article_type"),
                "source": r.get("source"),
                "fetched_at": str(r.get("fetched_at") or "")[:10] or None,
            }
        )
    return _ok(
        {
            "count": len(out),
            "ideas": out,
            "note": (
                "Untriaged discovery ideas from the last 14 days (highest relevance "
                "first). Raw ideas, not vetted candidates — confirm with get_ticker_setup "
                "before acting."
            ),
        }
    )


def _next_earnings_date(yf: Any, ticker: str):
    """Best-effort next *upcoming* earnings date via yfinance; None on failure or only past."""
    from datetime import date as _date
    from datetime import datetime as _dt

    def _to_date(v: Any):
        if v is None:
            return None
        if isinstance(v, _date) and not isinstance(v, _dt):
            return v
        if isinstance(v, _dt):
            return v.date()
        try:
            return _dt.fromisoformat(str(v)[:10]).date()
        except (TypeError, ValueError):
            return None

    try:
        tk = yf.Ticker(ticker)
    except Exception:
        return None

    dates: list[Any] = []
    # Newer yfinance: .calendar is a dict with 'Earnings Date': [date, ...].
    try:
        cal = tk.calendar
    except Exception:
        cal = None
    if isinstance(cal, dict):
        ed = cal.get("Earnings Date")
        if isinstance(ed, (list, tuple)):
            dates = [_to_date(x) for x in ed]
        elif ed is not None:
            dates = [_to_date(ed)]
    elif cal is not None:
        # Older yfinance: DataFrame with an 'Earnings Date' row.
        try:
            if hasattr(cal, "index") and "Earnings Date" in list(cal.index):
                val = cal.loc["Earnings Date"]
                seq = val.tolist() if hasattr(val, "tolist") else [val]
                dates = [_to_date(x) for x in seq]
        except Exception:
            pass
    if not any(d for d in dates):
        try:
            df = tk.get_earnings_dates(limit=8)
            if df is not None and not getattr(df, "empty", True):
                dates = [_to_date(i) for i in df.index]
        except Exception:
            pass

    dates = [d for d in dates if d is not None]
    if not dates:
        return None
    today = _date.today()
    future = sorted(d for d in dates if d >= today)
    # Only upcoming dates — past "last known" dates confused the model as "next".
    return future[0] if future else None


def _tool_get_earnings_calendar(
    ctx: AssistantToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Next scheduled earnings date per ticker (on-demand yfinance read; no DB writes)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from datetime import date as _date

    tickers: list[str] = []
    raw = args.get("tickers")
    if isinstance(raw, list):
        tickers = [str(t).upper().strip() for t in raw if str(t).strip()]
    one = str(args.get("ticker") or "").upper().strip()
    if one:
        tickers.append(one)
    seen: set[str] = set()
    tickers = [t for t in tickers if not (t in seen or seen.add(t))]
    if not tickers:
        return _no_data(
            "missing_ticker",
            message="Pass ticker or tickers[] (e.g. holdings from get_holdings_snapshot).",
        )
    tickers = tickers[:10]

    try:
        import yfinance as yf
    except Exception as exc:
        logger.warning("get_earnings_calendar: yfinance unavailable: %s", exc)
        return _no_data("query_failed", message="earnings data source unavailable")

    today = _date.today()

    def _one(t: str) -> dict[str, Any]:
        d = _next_earnings_date(yf, t)
        if d is None:
            return {"ticker": t, "next_earnings_date": None, "days_until": None}
        return {
            "ticker": t,
            "next_earnings_date": d.isoformat(),
            "days_until": (d - today).days,
        }

    events: list[dict[str, Any]] = []
    # Parallelize yfinance I/O — sequential calls were too slow in the chat tool loop.
    workers = min(8, len(tickers))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_one, t): t for t in tickers}
        by_ticker: dict[str, dict[str, Any]] = {}
        for fut in as_completed(futures):
            t = futures[fut]
            try:
                by_ticker[t] = fut.result()
            except Exception as exc:
                logger.warning("get_earnings_calendar %s failed: %s", t, exc)
                by_ticker[t] = {
                    "ticker": t,
                    "next_earnings_date": None,
                    "days_until": None,
                }
        events = [by_ticker[t] for t in tickers]

    events.sort(
        key=lambda e: (
            e["days_until"] is None,
            e["days_until"] if e["days_until"] is not None else 0,
        )
    )
    if not any(e["next_earnings_date"] for e in events):
        return _no_data("no_data", tickers=tickers)
    return _ok(
        {
            "as_of": today.isoformat(),
            "count": len(events),
            "earnings": events,
            "note": (
                "Next *upcoming* earnings per ticker (yfinance, on-demand). "
                "Dates may be estimates/TBC; next_earnings_date=null means no upcoming "
                "date was available (past-only dates are omitted)."
            ),
        }
    )


TOOL_HANDLERS: dict[str, Callable[[AssistantToolContext, dict[str, Any]], dict[str, Any]]] = {
    "list_entry_candidates": _tool_list_entry_candidates,
    "get_ticker_setup": _tool_get_ticker_setup,
    "get_market_brief": _tool_get_market_brief,
    "get_sector_rotation": _tool_get_sector_rotation,
    "get_signals_overview": _tool_get_signals_overview,
    "get_holdings_snapshot": _tool_get_holdings_snapshot,
    "get_portfolio_performance": _tool_get_portfolio_performance,
    "get_trade_history": _tool_get_trade_history,
    "get_price_history": _tool_get_price_history,
    "get_track_record": _tool_get_track_record,
    "get_theses_attention": _tool_get_theses_attention,
    "get_confluence": _tool_get_confluence,
    "get_ideas_triage": _tool_get_ideas_triage,
    "get_earnings_calendar": _tool_get_earnings_calendar,
    "search_web": _tool_search_web,
    "search_research": _tool_search_research,
}


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_entry_candidates",
            "description": (
                "List ranked BUY/SELL/RISK/WATCH candidates from the fund watchlist "
                "and action queue. Optional sector/action/held_only filters."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max rows (1-25)"},
                    "sector": {
                        "type": "string",
                        "description": "Filter by securities.sector substring (e.g. Energy)",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["BUY", "SELL", "RISK", "WATCH", "MONITOR"],
                        "description": "Filter by advise/action type",
                    },
                    "held_only": {
                        "type": "boolean",
                        "description": "If true, only currently held positions",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ticker_setup",
            "description": (
                "Get stored research setup for a ticker: stance, entry_zone, target, "
                "stop, key levels, meta conviction. Does not invent prices."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Ticker symbol"},
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_market_brief",
            "description": "Latest cached daily market brief (headline, narrative, regime).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sector_rotation",
            "description": (
                "Sector meta rotation snapshot. Pass sector for one bucket, "
                "or omit for top rotation ranks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sector": {
                        "type": "string",
                        "description": "Sector name substring (optional)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_signals_overview",
            "description": "Compact watchlist signals digest (counts and top tickers).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_holdings_snapshot",
            "description": (
                "Lean current fund holdings (shares, price, P&L). "
                "Optional tickers filter."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tickers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional ticker list to include",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_portfolio_performance",
            "description": (
                "Fund performance over a window: total return, peak, max drawdown, "
                "and a downsampled equity curve. Use window='all' for since-inception "
                "or e.g. '30d'/'90d'/'1y'/'2y'. Fund-scoped, read-only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "window": {
                        "type": "string",
                        "description": "Nd/Nw/Nm/Ny or 'all' (e.g. '90d', '1y', 'all')",
                    },
                    "since": {
                        "type": "string",
                        "description": "Optional start date YYYY-MM-DD (overrides window)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trade_history",
            "description": (
                "Past executed trades for this fund (date/action/ticker/qty/price/total) "
                "plus buy/sell counts. Sell rows carry realized_pnl; the summary reports "
                "realized_pnl_by_currency (FIFO, native currency — never sum across currencies). "
                "Filter by ticker, action, or since-date."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Optional ticker filter"},
                    "action": {
                        "type": "string",
                        "enum": ["BUY", "SELL"],
                        "description": "Optional action filter",
                    },
                    "since": {
                        "type": "string",
                        "description": "Optional start date YYYY-MM-DD",
                    },
                    "limit": {"type": "integer", "description": "Max rows (1-50)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_price_history",
            "description": (
                "Historical daily closes for a ticker over a window: first/last close, "
                "high/low, % change, the 5 biggest single-day moves (with dates), and a "
                "downsampled close curve. Pair the biggest-move dates with search_web to "
                "explain what drove a move."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Ticker symbol"},
                    "window": {
                        "type": "string",
                        "description": "Nd/Nw/Nm/Ny (e.g. '90d', '1y'); default 90d",
                    },
                    "since": {
                        "type": "string",
                        "description": "Optional start date YYYY-MM-DD (overrides window)",
                    },
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "Live web/news search via SearXNG. Use for recent news; "
                "not a substitute for get_ticker_setup entry levels. "
                "Widen time_range to investigate older events."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "tickers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional related tickers",
                    },
                    "time_range": {
                        "type": "string",
                        "enum": ["day", "week", "month", "year"],
                        "description": "Lookback bucket (default week)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_research",
            "description": "Semantic search over the internal research article repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "min_similarity": {"type": "number"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_track_record",
            "description": (
                "Learn-layer scorecard: were our past stances right? Hit rate and average "
                "excess-return vs benchmark, sliced by stance source, LLM verdict "
                "(ALIGNED/TENSION), and evidence domain (source-ROI), plus best/worst calls. "
                "Use to judge which signals/sources to trust. Not a live buy/sell signal."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "horizon_days": {
                        "type": "integer",
                        "enum": [7, 30, 90],
                        "description": "Scoring horizon in days (default 30)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_theses_attention",
            "description": (
                "Human thesis threads that need review: due/stale/weak, or the LLM review "
                "flagged TENSION / STALE_THESIS (stored stance conflicts with the thread). "
                "Advisory — surface for the user to revisit, never auto-trade. Optional ticker filter."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Optional ticker filter"},
                    "limit": {"type": "integer", "description": "Max rows (1-40)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_confluence",
            "description": (
                "Recent confluence events: multiple independent signal families "
                "(insider/dilution/filing/…) aligning on the same ticker. Higher score = "
                "more families; direction can be bullish or risk. Optional ticker filter; "
                "days window (default 7)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Optional ticker filter"},
                    "days": {"type": "integer", "description": "Lookback days (1-30, default 7)"},
                    "limit": {"type": "integer", "description": "Max rows (1-25)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ideas_triage",
            "description": (
                "Untriaged discovery ideas (Alpha Research / Opportunity Discovery) from the "
                "last 14 days, highest relevance first. Raw ideas, not vetted candidates — "
                "confirm with get_ticker_setup before acting. Optional ticker filter."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Optional ticker prefix filter"},
                    "limit": {"type": "integer", "description": "Max rows (1-25)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_earnings_calendar",
            "description": (
                "Next upcoming earnings date per ticker (on-demand). Pass ticker or tickers[] "
                "(e.g. holdings from get_holdings_snapshot to check 'any holdings reporting "
                "soon?'). Returns next date + days_until; null when no upcoming date. "
                "Dates may be estimates/TBC. Up to 10 tickers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Single ticker"},
                    "tickers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Up to 10 tickers",
                    },
                },
            },
        },
    },
]


def catalog_tool_names() -> set[str]:
    return {t["function"]["name"] for t in TOOL_SCHEMAS}


def assert_catalog_covers_matrix() -> None:
    missing = REQUIRED_TOOL_NAMES - catalog_tool_names()
    if missing:
        raise RuntimeError(f"Tool catalog missing required tools: {sorted(missing)}")


def execute_tool(
    name: str,
    arguments: dict[str, Any] | str | None,
    ctx: AssistantToolContext,
) -> str:
    """Execute a tool and return JSON string for the model."""
    if name not in TOOL_HANDLERS:
        return _truncate_json(_no_data("unknown_tool", tool=name))
    args: dict[str, Any]
    if arguments is None:
        args = {}
    elif isinstance(arguments, str):
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            return _truncate_json(_no_data("invalid_arguments", tool=name))
    elif isinstance(arguments, dict):
        args = arguments
    else:
        args = {}
    try:
        result = TOOL_HANDLERS[name](ctx, args)
    except Exception as exc:
        logger.error("tool %s raised: %s", name, exc, exc_info=True)
        result = _no_data("exception", tool=name, message=str(exc)[:200])
    return _truncate_json(result if isinstance(result, dict) else _no_data("bad_result"))


# Validate catalog at import
assert_catalog_covers_matrix()
