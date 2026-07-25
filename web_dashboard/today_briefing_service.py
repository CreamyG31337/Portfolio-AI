"""Aggregate data for the Today briefing screen (ROADMAP §2.1)."""

from __future__ import annotations

import logging
from datetime import datetime, UTC
from typing import Any

from action_queue_service import attach_ai_reviews, attach_research_context, build_action_queue_items
from market_brief_service import fetch_latest_brief
from market_regime_normalization import normalize_market_regime
from postgres_client import PostgresClient

logger = logging.getLogger(__name__)


def fetch_stance_flips(postgres: PostgresClient, *, days: int = 2, limit: int = 20) -> list[dict[str, Any]]:
    """Latest stance change per (ticker, source, fund_key) within the window.

    Single owner of the flip-detection SQL — the dashboard stance-flips API and
    the weekly retro job call this too; don't fork the query.
    """
    rows = postgres.execute_query(
        """
        WITH ranked AS (
            SELECT ticker, source, fund_key, stance, confidence, as_of, model_used, metadata,
                   ROW_NUMBER() OVER (
                       PARTITION BY ticker, source, fund_key ORDER BY as_of DESC
                   ) AS rn
            FROM stance_history
            WHERE as_of >= NOW() - (%s || ' days')::interval
        )
        SELECT cur.ticker, cur.source, cur.fund_key,
               prev.stance AS from_stance, cur.stance AS to_stance,
               cur.as_of AS flipped_at, cur.confidence, cur.model_used, cur.metadata
        FROM ranked cur
        JOIN ranked prev
          ON prev.ticker = cur.ticker AND prev.source = cur.source
         AND prev.fund_key = cur.fund_key AND prev.rn = 2
        WHERE cur.rn = 1 AND cur.stance IS DISTINCT FROM prev.stance
        ORDER BY cur.as_of DESC
        LIMIT %s
        """,
        (days, limit),
    )
    return [dict(r) for r in rows]


def _normalize_ideas_ticker_filter(ticker: str | None) -> str | None:
    """Uppercase alnum/.- only prefix for Ideas inbox filter; None = no filter."""
    if not ticker:
        return None
    cleaned = "".join(ch for ch in str(ticker).upper().strip() if ch.isalnum() or ch in ".-")
    return cleaned[:20] or None


def fetch_alpha_ideas(
    postgres: PostgresClient,
    *,
    limit: int = 15,
    ticker: str | None = None,
) -> list[dict[str, Any]]:
    ticker_prefix = _normalize_ideas_ticker_filter(ticker)
    try:
        return _fetch_alpha_ideas_query(postgres, limit=limit, ticker_prefix=ticker_prefix)
    except Exception as exc:
        logger.warning("fetch_alpha_ideas failed (idea_triage may be missing): %s", exc)
        return _fetch_alpha_ideas_fallback(postgres, limit=limit, ticker_prefix=ticker_prefix)


def _ticker_prefix_clause(column_expr: str = "ra.tickers") -> str:
    # Prefix match so typing "CO" finds COST without loading the full 14d pool client-side.
    return f"""
          AND EXISTS (
              SELECT 1
              FROM unnest(COALESCE({column_expr}, ARRAY[]::text[])) AS t(sym)
              WHERE upper(t.sym) LIKE %s
          )
    """


def _fetch_alpha_ideas_fallback(
    postgres: PostgresClient,
    *,
    limit: int,
    ticker_prefix: str | None,
) -> list[dict[str, Any]]:
    sql = """
            SELECT id, title, article_type, source, fetched_at,
                   relevance_score, tickers, summary
            FROM research_articles
            WHERE article_type IN ('Alpha Research', 'Opportunity Discovery')
              AND fetched_at >= NOW() - INTERVAL '14 days'
    """
    params: list[Any] = []
    if ticker_prefix:
        sql += _ticker_prefix_clause("tickers")
        params.append(f"{ticker_prefix}%")
    sql += """
            ORDER BY relevance_score DESC NULLS LAST, fetched_at DESC
            LIMIT %s
            """
    params.append(limit)
    return postgres.execute_query(sql, tuple(params))


def _fetch_alpha_ideas_query(
    postgres: PostgresClient,
    *,
    limit: int = 15,
    ticker_prefix: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT ra.id, ra.title, ra.article_type, ra.source, ra.fetched_at,
               ra.relevance_score, ra.tickers, ra.summary
        FROM research_articles ra
        LEFT JOIN idea_triage it ON it.article_id = ra.id
        WHERE ra.article_type IN ('Alpha Research', 'Opportunity Discovery')
          AND ra.fetched_at >= NOW() - INTERVAL '14 days'
          AND (it.id IS NULL OR (it.status = 'snoozed' AND it.snooze_until < NOW()))
    """
    params: list[Any] = []
    if ticker_prefix:
        sql += _ticker_prefix_clause("ra.tickers")
        params.append(f"{ticker_prefix}%")
    sql += """
        ORDER BY ra.relevance_score DESC NULLS LAST, ra.fetched_at DESC
        LIMIT %s
        """
    params.append(limit)
    return postgres.execute_query(sql, tuple(params))


def build_today_briefing(
    supabase_client: Any,
    *,
    fund: str | None = None,
    fund_limit: int = 8,
) -> dict[str, Any]:
    """Build the Today briefing payload from existing data sources."""
    pg = PostgresClient()
    brief_row = fetch_latest_brief(pg)
    regime: dict[str, Any] = {}
    if brief_row:
        regime = normalize_market_regime(
            brief_row.get("regime_json") if isinstance(brief_row.get("regime_json"), dict) else {},
            brief_date=brief_row.get("brief_date"),
            updated_at=brief_row.get("updated_at"),
        )

    actions = build_action_queue_items(supabase_client, fund, fund_limit)
    try:
        attach_research_context(pg, actions)
        attach_ai_reviews(pg, fund or "", actions)
    except Exception as exc:
        logger.warning("Today briefing: enrich action queue failed: %s", exc)

    insider_clusters: list[dict[str, Any]] = []
    try:
        from insider_clusters_service import build_insider_cluster_buys

        insider_clusters = build_insider_cluster_buys(supabase_client, fund=fund)
    except Exception as exc:
        logger.warning("Today briefing: insider clusters failed: %s", exc)

    congress_herd_buys: list[dict[str, Any]] = []
    try:
        from congress_herd_service import build_congress_herd_buys

        congress_herd_buys = build_congress_herd_buys(supabase_client, fund=fund)
    except Exception as exc:
        logger.warning("Today briefing: congress herd buys failed: %s", exc)

    dilution_alerts: list[dict[str, Any]] = []
    try:
        from dilution_service import fetch_recent_dilution_flags

        dilution_alerts = fetch_recent_dilution_flags(pg, days=45, limit=20)
    except Exception as exc:
        logger.warning("Today briefing: dilution alerts failed: %s", exc)

    # G2 (distinct from G3's dilution_alerts): US EDGAR filing-risk events.
    filing_alerts: list[dict[str, Any]] = []
    try:
        from sec_filings_service import fetch_recent_filing_alerts

        filing_alerts = fetch_recent_filing_alerts(pg, days=14, limit=20)
    except Exception as exc:
        logger.warning("Today briefing: filing alerts failed: %s", exc)

    confluence_events: list[dict[str, Any]] = []
    try:
        from confluence_service import fetch_recent_confluence_events

        confluence_events = fetch_recent_confluence_events(pg, days=2, limit=15)
    except Exception as exc:
        logger.warning("Today briefing: confluence events failed: %s", exc)

    movers: list[dict[str, Any]] = []
    dividends: list[dict[str, Any]] = []
    try:
        from flask_data_utils import (
            fetch_dividend_log_flask,
            get_biggest_movers_flask,
            get_current_positions_flask,
        )

        positions_df = get_current_positions_flask(fund=fund)
        mover_frames = get_biggest_movers_flask(positions_df, "CAD", limit=5)
        for group in ("gainers", "losers"):
            frame = mover_frames.get(group)
            if frame is None or getattr(frame, "empty", True):
                continue
            pct_col = next(
                (c for c in ("daily_pnl_pct", "return_pct") if c in frame.columns),
                None,
            )
            for mrow in frame.to_dict('records'):
                entry: dict[str, Any] = {"ticker": mrow.get("ticker"), "group": group}
                if pct_col is not None and mrow.get(pct_col) is not None:
                    try:
                        entry["change_pct"] = round(float(mrow[pct_col]), 2)
                    except (TypeError, ValueError):
                        pass
                movers.append(entry)
        dividends = (fetch_dividend_log_flask(days_lookback=90, fund=fund) or [])[:5]
    except Exception as exc:
        logger.warning("Today briefing: movers/dividends failed: %s", exc)

    theses_attention: list[dict[str, Any]] = []
    try:
        from user_insights_service import list_theses_attention

        theses_attention = list_theses_attention(pg, limit=20)
    except Exception as exc:
        logger.warning("Today briefing: theses attention failed: %s", exc)

    advise_pack: list[dict[str, Any]] = []
    advise_source = "advise"
    try:
        from advise_service import rank_candidate_pack
        from track_record_service import build_track_record_summary

        # Prefer 7d (more samples); fall back shape is still valid if empty.
        track_summary: dict[str, Any] | None = None
        try:
            track_summary = build_track_record_summary(pg, horizon_days=7)
            if int(track_summary.get("total_scored") or 0) < 30:
                track_summary = build_track_record_summary(pg, horizon_days=30)
        except Exception as tr_exc:
            logger.warning("Today briefing: track record for advise failed: %s", tr_exc)

        # A3: shared ranking source with the chat pulse. Falls back to the same
        # held-gated watchlist signals when the queue + theses are empty, so
        # Today and chat agree instead of Today showing "no items". Inherits A2
        # tension annotation + demotion.
        def _today_signal_fallback() -> list[dict[str, Any]]:
            from ai_assistant_candidates import build_signal_fallback_candidates
            from flask_data_utils import get_current_positions_flask

            try:
                held_df = get_current_positions_flask(fund=fund)
            except Exception:
                held_df = None
            held: set[str] = set()
            if held_df is not None and not getattr(held_df, "empty", True):
                col = "ticker" if "ticker" in held_df.columns else "symbol"
                if col in held_df.columns:
                    held = {
                        str(t).upper().strip()
                        for t in held_df[col].dropna().tolist()
                        if str(t).strip()
                    }
            return build_signal_fallback_candidates(
                supabase_client, fund=fund, held_tickers=held, limit=12
            )

        advise_pack, advise_source = rank_candidate_pack(
            action_queue=actions,
            theses_attention=theses_attention,
            track_record=track_summary,
            confluence_events=confluence_events,
            signal_fallback=_today_signal_fallback,
            limit=12,
        )
    except Exception as exc:
        logger.warning("Today briefing: advise pack failed: %s", exc)

    return {
        "market_regime": regime,
        "market_brief_headline": (brief_row or {}).get("headline"),
        "advise_pack": advise_pack,
        "advise_source": advise_source,
        "stance_flips": fetch_stance_flips(pg, days=2, limit=20),
        "action_queue": actions,
        "alpha_articles": fetch_alpha_ideas(pg, limit=15),
        "insider_cluster_buys": insider_clusters,
        "congress_herd_buys": congress_herd_buys,
        "dilution_alerts": dilution_alerts,
        "filing_alerts": filing_alerts,
        "confluence_events": confluence_events,
        "theses_attention": theses_attention,
        "watchlist_movers": movers,
        "upcoming_dividends": dividends,
        "updated_at": datetime.now(UTC).isoformat(),
    }
