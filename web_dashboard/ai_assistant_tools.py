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
    for key in ("candidates", "results", "articles", "sectors", "holdings", "top_signals"):
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
    try:
        from searxng_client import get_searxng_client

        client = get_searxng_client()
        if not client:
            return _no_data("searxng_unavailable")
        # Prefer news category for company news questions
        result = client.search(query, categories=["news", "general"], time_range="week", max_results=6)
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
            return _no_data("no_data", query=query)
        return _ok({"query": query, "tickers": tickers, "results": results, "count": len(results)})
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


TOOL_HANDLERS: dict[str, Callable[[AssistantToolContext, dict[str, Any]], dict[str, Any]]] = {
    "list_entry_candidates": _tool_list_entry_candidates,
    "get_ticker_setup": _tool_get_ticker_setup,
    "get_market_brief": _tool_get_market_brief,
    "get_sector_rotation": _tool_get_sector_rotation,
    "get_signals_overview": _tool_get_signals_overview,
    "get_holdings_snapshot": _tool_get_holdings_snapshot,
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
            "name": "search_web",
            "description": (
                "Live web/news search via SearXNG. Use for recent news; "
                "not a substitute for get_ticker_setup entry levels."
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
