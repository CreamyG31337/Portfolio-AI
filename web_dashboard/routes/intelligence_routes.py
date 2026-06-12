"""Today briefing, Ideas inbox, and Track-record routes (Pillars 2–3)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, UTC
from typing import Any

from flask import Blueprint, jsonify, render_template, request

from auth import require_auth
from flask_auth_utils import get_effective_user_email_flask
from flask_data_utils import get_available_funds_flask, get_supabase_client_flask
from postgres_client import PostgresClient
from today_briefing_service import build_today_briefing, fetch_alpha_ideas
from track_record_service import build_track_record_summary
from earnings_calendar_service import earnings_for_fund
from insider_clusters_service import build_insider_cluster_buys
from liquidity_service import build_liquidity_panel

logger = logging.getLogger(__name__)

intelligence_bp = Blueprint("intelligence", __name__)


def _nav_render(template: str, current_page: str, **extra: Any):
    from app import get_navigation_context

    nav_context = get_navigation_context(current_page=current_page)
    nav_clean = {k: v for k, v in nav_context.items() if k != "available_funds"}
    return render_template(
        template,
        nav_context=nav_context,
        user_email=get_effective_user_email_flask(),
        **nav_clean,
        **extra,
    )


def _serialize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key, val in list(item.items()):
            if hasattr(val, "isoformat") and callable(val.isoformat):
                item[key] = val.isoformat()
            elif isinstance(val, (list, dict)):
                continue
            elif hasattr(val, "__float__") and not isinstance(val, bool):
                try:
                    item[key] = float(val)
                except (TypeError, ValueError):
                    pass
        out.append(item)
    return out


@intelligence_bp.route("/today", methods=["GET"])
@require_auth
def today_page():
    return _nav_render("today.html", "today")


@intelligence_bp.route("/api/today/briefing", methods=["GET"])
@require_auth
def today_briefing_api():
    try:
        fund = request.args.get("fund")
        limit = request.args.get("limit", default=8, type=int)
        supabase = get_supabase_client_flask()
        if not supabase:
            return jsonify({"error": "Database client unavailable"}), 500
        payload = build_today_briefing(supabase, fund=fund, fund_limit=max(1, min(limit, 25)))
        return jsonify(payload)
    except Exception as exc:
        logger.error("today/briefing failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@intelligence_bp.route("/ideas", methods=["GET"])
@require_auth
def ideas_page():
    return _nav_render("ideas.html", "ideas")


@intelligence_bp.route("/api/ideas/inbox", methods=["GET"])
@require_auth
def ideas_inbox_api():
    try:
        pg = PostgresClient()
        limit = request.args.get("limit", default=50, type=int)
        rows = fetch_alpha_ideas(pg, limit=max(1, min(limit, 100)))
        return jsonify({"data": _serialize_rows(rows)})
    except Exception as exc:
        logger.error("ideas/inbox failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@intelligence_bp.route("/api/ideas/triage", methods=["POST"])
@require_auth
def ideas_triage_api():
    try:
        body = request.get_json(silent=True) or {}
        article_id = body.get("article_id")
        status = (body.get("status") or "").strip().lower()
        notes = body.get("notes")
        fund = body.get("fund")
        tickers = body.get("tickers") or []

        if not article_id or status not in {"accepted", "dismissed", "snoozed"}:
            return jsonify({"error": "article_id and status required"}), 400

        if status == "accepted" and fund and tickers:
            allowed_funds = get_available_funds_flask()
            if fund not in allowed_funds:
                return jsonify({"error": f"No access to fund {fund}"}), 403

        email = get_effective_user_email_flask() or "unknown"
        snooze_until = None
        if status == "snoozed":
            days = int(body.get("snooze_days") or 7)
            snooze_until = datetime.now(UTC) + timedelta(days=days)

        pg = PostgresClient()
        pg.execute_update(
            """
            INSERT INTO idea_triage (article_id, status, decided_by, notes, snooze_until)
            VALUES (%s::uuid, %s, %s, %s, %s)
            ON CONFLICT (article_id) DO UPDATE SET
                status = EXCLUDED.status,
                decided_by = EXCLUDED.decided_by,
                notes = EXCLUDED.notes,
                snooze_until = EXCLUDED.snooze_until,
                decided_at = NOW()
            """,
            (article_id, status, email, notes, snooze_until),
        )

        watchlist_results: dict[str, str] = {}
        if status == "accepted" and fund and tickers:
            supabase = get_supabase_client_flask()
            if supabase:
                for t in tickers:
                    ticker = str(t).upper().strip()
                    if not ticker:
                        continue
                    try:
                        # watched_tickers_v2.ticker has an FK to securities(ticker);
                        # newly discovered tickers must be registered there first or
                        # the watchlist upsert fails.
                        try:
                            from utils.ticker_utils import get_ticker_currency

                            currency = get_ticker_currency(ticker)
                        except Exception:
                            currency = "USD"
                        supabase.ensure_ticker_in_securities(ticker, currency)
                        supabase.supabase.table("watched_tickers_v2").upsert(
                            {
                                "fund": fund,
                                "ticker": ticker,
                                "priority_tier": "B",
                                "is_active": True,
                                "source": "ideas_inbox",
                            },
                            on_conflict="fund,ticker",
                        ).execute()
                        watchlist_results[ticker] = "added"
                    except Exception as wl_exc:
                        logger.warning("watchlist upsert failed %s: %s", ticker, wl_exc)
                        watchlist_results[ticker] = "failed"

        failed = sorted(t for t, r in watchlist_results.items() if r != "added")
        return jsonify({
            "ok": not failed,
            "status": status,
            "watchlist_results": watchlist_results,
            "failed_tickers": failed,
        })
    except Exception as exc:
        logger.error("ideas/triage failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@intelligence_bp.route("/track-record", methods=["GET"])
@require_auth
def track_record_page():
    return _nav_render("track_record.html", "track_record")


@intelligence_bp.route("/api/track-record/summary", methods=["GET"])
@require_auth
def track_record_summary_api():
    try:
        horizon = request.args.get("horizon", default=30, type=int)
        summary = build_track_record_summary(horizon_days=max(7, min(horizon, 90)))
        return jsonify(summary)
    except Exception as exc:
        logger.error("track-record/summary failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@intelligence_bp.route("/api/ticker/<ticker>/evidence-timeline", methods=["GET"])
@require_auth
def ticker_evidence_timeline(ticker: str):
    """Chronological stance + article events for dossier timeline (§2.3)."""
    try:
        ticker_u = ticker.upper().strip()
        pg = PostgresClient()
        stances = pg.execute_query(
            """
            SELECT 'stance' AS event_type, as_of AS event_at, stance AS label,
                   source, confidence, metadata
            FROM stance_history
            WHERE ticker = %s
            ORDER BY as_of DESC
            LIMIT 50
            """,
            (ticker_u,),
        )
        articles = pg.execute_query(
            """
            SELECT 'article' AS event_type, fetched_at AS event_at,
                   title AS label, article_type AS source, relevance_score AS confidence,
                   NULL::jsonb AS metadata
            FROM research_articles
            WHERE ticker = %s OR %s = ANY(tickers)
            ORDER BY fetched_at DESC
            LIMIT 30
            """,
            (ticker_u, ticker_u),
        )
        events = _serialize_rows(list(stances) + list(articles))
        events.sort(key=lambda e: e.get("event_at") or "", reverse=True)
        return jsonify({"ticker": ticker_u, "events": events[:60]})
    except Exception as exc:
        logger.error("evidence-timeline failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@intelligence_bp.route("/api/insiders/cluster-buys", methods=["GET"])
@require_auth
def insider_cluster_buys_api():
    """3+ distinct insiders buying within the window (ROADMAP §4.2)."""
    try:
        fund = request.args.get("fund")
        days = request.args.get("days", default=30, type=int)
        min_insiders = request.args.get("min_insiders", default=3, type=int)
        supabase = get_supabase_client_flask()
        if not supabase:
            return jsonify({"error": "Database client unavailable"}), 500
        clusters = build_insider_cluster_buys(
            supabase,
            fund=fund,
            days=max(7, min(days, 90)),
            min_insiders=max(2, min(min_insiders, 10)),
        )
        return jsonify({"data": clusters, "window_days": max(7, min(days, 90))})
    except Exception as exc:
        logger.error("insiders/cluster-buys failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@intelligence_bp.route("/api/liquidity/panel", methods=["GET"])
@require_auth
def liquidity_panel_api():
    """Days-to-exit per holding (ROADMAP §4.3). Cold cache is slow by design:
    one yfinance call per ticker, 6h TTL — keep it out of the briefing payload."""
    try:
        fund = request.args.get("fund")
        from flask_data_utils import get_current_positions_flask
        from liquidity_service import PARTICIPATION_RATE

        positions_df = get_current_positions_flask(fund=fund)
        rows = build_liquidity_panel(positions_df)
        return jsonify({"data": rows, "participation_rate": PARTICIPATION_RATE})
    except Exception as exc:
        logger.error("liquidity/panel failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@intelligence_bp.route("/api/earnings/calendar", methods=["GET"])
@require_auth
def earnings_calendar_api():
    try:
        fund = request.args.get("fund")
        supabase = get_supabase_client_flask()
        if not supabase:
            return jsonify({"error": "Database client unavailable"}), 500
        rows = earnings_for_fund(supabase, fund)
        return jsonify({"data": rows})
    except Exception as exc:
        logger.error("earnings/calendar failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500
