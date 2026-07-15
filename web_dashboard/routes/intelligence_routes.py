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
from congress_herd_service import build_congress_herd_buys
from liquidity_service import build_liquidity_panel

logger = logging.getLogger(__name__)

intelligence_bp = Blueprint("intelligence", __name__)


def _nav_render(template: str, current_page: str, **extra: Any):
    from app import get_navigation_context

    nav_context = get_navigation_context(current_page=current_page)
    # Sidebar uses top-level available_funds. Strip reserved / overridden keys
    # from the explode so render_template never gets duplicate kwargs.
    available_funds = list(nav_context.get("available_funds") or [])
    if "available_funds" in extra:
        available_funds = list(extra.pop("available_funds") or [])
    reserved = {"available_funds", "nav_context", "user_email"} | set(extra.keys())
    nav_clean = {k: v for k, v in nav_context.items() if k not in reserved}
    return render_template(
        template,
        nav_context=nav_context,
        user_email=get_effective_user_email_flask(),
        available_funds=available_funds,
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
        serialized = _serialize_rows(rows)
        try:
            from user_insights_service import thesis_attention_by_ticker

            all_tickers: list[str] = []
            for row in serialized:
                for t in row.get("tickers") or []:
                    all_tickers.append(str(t))
            flags = thesis_attention_by_ticker(pg, all_tickers, limit=60)
            for row in serialized:
                row_flags: list[dict[str, Any]] = []
                seen: set[str] = set()
                for t in row.get("tickers") or []:
                    key = str(t).upper().strip()
                    for flag in flags.get(key) or []:
                        tid = str(flag.get("thesis_id") or "")
                        if tid and tid not in seen:
                            seen.add(tid)
                            row_flags.append(flag)
                if row_flags:
                    row["thesis_attention"] = row_flags
        except Exception as att_exc:
            logger.debug("ideas thesis attention enrich skipped: %s", att_exc)
        return jsonify({"data": serialized})
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
        analysis_enqueue: dict[str, Any] | None = None
        if status == "accepted" and fund and tickers:
            from supabase_client import SupabaseClient
            from watchlist_access import (
                request_manual_ticker_analysis,
                upsert_watchlist_ticker,
            )

            write_client = SupabaseClient(use_service_role=True)
            accepted_tickers: list[str] = []
            for t in tickers:
                ticker = str(t).upper().strip()
                if not ticker:
                    continue
                outcome = upsert_watchlist_ticker(
                    write_client,
                    fund=str(fund),
                    ticker=ticker,
                    priority_tier="B",
                    source="ideas_inbox",
                    is_active=True,
                )
                watchlist_results[ticker] = "added" if outcome.get("ok") else "failed"
                if outcome.get("ok"):
                    accepted_tickers.append(ticker)

            queue_analysis = body.get("queue_analysis", False)
            if not isinstance(queue_analysis, bool):
                queue_analysis = str(queue_analysis).lower() in ("1", "true", "yes")
            if queue_analysis and accepted_tickers:
                analysis_enqueue = request_manual_ticker_analysis(
                    write_client,
                    accepted_tickers,
                    enqueued_by="ideas_accept",
                    include_meta=True,
                )

        failed = sorted(t for t, r in watchlist_results.items() if r != "added")
        payload: dict[str, Any] = {
            "ok": not failed,
            "status": status,
            "watchlist_results": watchlist_results,
            "failed_tickers": failed,
        }
        if analysis_enqueue is not None:
            payload["analysis_enqueue"] = analysis_enqueue
        return jsonify(payload)
    except Exception as exc:
        logger.error("ideas/triage failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@intelligence_bp.route("/watchlist", methods=["GET"])
@require_auth
def watchlist_page():
    # Fund-scoped page: hide "All Funds" so the Data Source picker is usable.
    return _nav_render("watchlist.html", "watchlist", allow_all_funds=False)


def _require_fund_access(fund: str | None) -> tuple[str | None, Any]:
    """Return (fund, error_response). error_response is a Flask response if ACL fails."""
    fund_s = (fund or "").strip()
    if not fund_s:
        return None, (jsonify({"error": "fund is required"}), 400)
    allowed = get_available_funds_flask()
    if fund_s not in allowed:
        return None, (jsonify({"error": f"No access to fund {fund_s}"}), 403)
    return fund_s, None


@intelligence_bp.route("/api/watchlist", methods=["GET"])
@require_auth
def watchlist_list_api():
    try:
        fund, err = _require_fund_access(request.args.get("fund"))
        if err:
            return err
        include_inactive = request.args.get("include_inactive", "0") in ("1", "true", "yes")
        from supabase_client import SupabaseClient
        from watchlist_access import enrich_watchlist_rows, list_watchlist_for_fund

        client = SupabaseClient(use_service_role=True)
        rows = list_watchlist_for_fund(
            client, fund or "", include_inactive=include_inactive
        )
        try:
            postgres = PostgresClient()
        except Exception:
            postgres = None
        enriched = enrich_watchlist_rows(
            rows, supabase_client=client, postgres_client=postgres
        )
        return jsonify({"data": _serialize_rows(enriched), "fund": fund})
    except Exception as exc:
        logger.error("watchlist list failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@intelligence_bp.route("/api/watchlist", methods=["POST"])
@require_auth
def watchlist_add_api():
    try:
        body = request.get_json(silent=True) or {}
        fund, err = _require_fund_access(body.get("fund"))
        if err:
            return err
        from watchlist_access import (
            MAX_BULK_TICKERS,
            normalize_priority_tier,
            parse_ticker_list,
            upsert_watchlist_tickers_bulk,
        )
        from supabase_client import SupabaseClient

        tickers = body.get("tickers")
        if isinstance(tickers, str):
            parsed = parse_ticker_list(tickers)
        else:
            parsed = parse_ticker_list(tickers or [])
        if not parsed:
            return jsonify({"error": "tickers required"}), 400
        if len(parsed) > MAX_BULK_TICKERS:
            return jsonify({"error": f"max {MAX_BULK_TICKERS} tickers per request"}), 400
        tier = normalize_priority_tier(body.get("priority_tier"))
        source = str(body.get("source") or "watchlist_ui").strip()[:50] or "watchlist_ui"
        client = SupabaseClient(use_service_role=True)
        result = upsert_watchlist_tickers_bulk(
            client,
            fund=fund or "",
            tickers=parsed,
            priority_tier=tier,
            source=source,
        )
        return jsonify(result)
    except Exception as exc:
        logger.error("watchlist add failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@intelligence_bp.route("/api/watchlist/analyze", methods=["POST"])
@require_auth
def watchlist_analyze_api():
    """Enqueue ASAP ticker (+ meta) analysis for watchlist symbols."""
    try:
        body = request.get_json(silent=True) or {}
        fund, err = _require_fund_access(body.get("fund"))
        if err:
            return err
        from supabase_client import SupabaseClient
        from watchlist_access import parse_ticker_list, request_manual_ticker_analysis

        tickers = body.get("tickers")
        if isinstance(tickers, str):
            parsed = parse_ticker_list(tickers)
        else:
            parsed = parse_ticker_list(tickers or [])
        if not parsed:
            return jsonify({"error": "tickers required"}), 400
        include_meta = body.get("include_meta", True)
        if not isinstance(include_meta, bool):
            include_meta = str(include_meta).lower() in ("1", "true", "yes")
        client = SupabaseClient(use_service_role=True)
        outcome = request_manual_ticker_analysis(
            client,
            parsed,
            enqueued_by="watchlist_ui",
            include_meta=include_meta,
        )
        status = 200 if outcome.get("ok") else 400
        outcome["fund"] = fund
        return jsonify(outcome), status
    except Exception as exc:
        logger.error("watchlist analyze failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@intelligence_bp.route("/api/watchlist/item", methods=["PATCH"])
@require_auth
def watchlist_item_api():
    try:
        body = request.get_json(silent=True) or {}
        fund, err = _require_fund_access(body.get("fund"))
        if err:
            return err
        ticker = str(body.get("ticker") or "").upper().strip()
        if not ticker:
            return jsonify({"error": "ticker required"}), 400
        from supabase_client import SupabaseClient
        from watchlist_access import update_watchlist_item

        is_active = body.get("is_active")
        if is_active is not None and not isinstance(is_active, bool):
            is_active = str(is_active).lower() in ("1", "true", "yes")
        priority_tier = body.get("priority_tier")
        client = SupabaseClient(use_service_role=True)
        outcome = update_watchlist_item(
            client,
            fund=fund or "",
            ticker=ticker,
            is_active=is_active,
            priority_tier=str(priority_tier) if priority_tier is not None else None,
        )
        status = 200 if outcome.get("ok") else 400
        return jsonify(outcome), status
    except Exception as exc:
        logger.error("watchlist item patch failed: %s", exc, exc_info=True)
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
        dilution: list[dict[str, Any]] = []
        try:
            dilution = pg.execute_query(
                """
                SELECT 'dilution' AS event_type, as_of::timestamptz AS event_at,
                       ('+' || pct_change || '% shares / ' || window_days || 'd') AS label,
                       'dilution_watch' AS source, NULL::numeric AS confidence,
                       jsonb_build_object('pct_change', pct_change,
                                          'window_days', window_days) AS metadata
                FROM dilution_observations
                WHERE ticker = %s AND flagged = TRUE
                ORDER BY as_of DESC
                LIMIT 20
                """,
                (ticker_u,),
            )
        except Exception as dil_exc:
            logger.warning("evidence-timeline dilution lookup failed: %s", dil_exc)
        # G2 filing events (distinct from G3's 'dilution': forward SEC filing risk).
        filings: list[dict[str, Any]] = []
        try:
            filings = pg.execute_query(
                """
                SELECT 'filing' AS event_type, filed_at::timestamptz AS event_at,
                       (form_type || ' · ' || category) AS label,
                       'sec_filings' AS source, NULL::numeric AS confidence,
                       jsonb_build_object('category', category, 'direction', direction,
                                          'form_type', form_type, 'url', url) AS metadata
                FROM filing_events
                WHERE ticker = %s
                ORDER BY filed_at DESC
                LIMIT 20
                """,
                (ticker_u,),
            )
        except Exception as fil_exc:
            logger.warning("evidence-timeline filing lookup failed: %s", fil_exc)
        confluence: list[dict[str, Any]] = []
        try:
            confluence = pg.execute_query(
                """
                SELECT 'confluence' AS event_type, as_of AS event_at,
                       (direction || ' · score ' || score) AS label,
                       'confluence' AS source, NULL::numeric AS confidence,
                       jsonb_build_object('direction', direction, 'score', score,
                                          'families', families, 'details', details) AS metadata
                FROM confluence_events
                WHERE ticker = %s
                ORDER BY as_of DESC
                LIMIT 20
                """,
                (ticker_u,),
            )
        except Exception as conf_exc:
            logger.warning("evidence-timeline confluence lookup failed: %s", conf_exc)
        user_insights: list[dict[str, Any]] = []
        try:
            from user_insights_service import fetch_thesis_timeline_events

            user_insights = fetch_thesis_timeline_events(pg, ticker_u, limit=20)
        except Exception as ui_exc:
            logger.warning("evidence-timeline user insights lookup failed: %s", ui_exc)
        events = _serialize_rows(
            list(stances)
            + list(articles)
            + list(dilution)
            + list(filings)
            + list(confluence)
            + list(user_insights)
        )
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


@intelligence_bp.route("/api/congress/herd-buys", methods=["GET"])
@require_auth
def congress_herd_buys_api():
    """N+ distinct politicians purchasing the same ticker (ROADMAP Pillar 5.1a)."""
    try:
        fund = request.args.get("fund")
        days = request.args.get("days", default=30, type=int)
        min_politicians = request.args.get("min_politicians", default=2, type=int)
        supabase = get_supabase_client_flask()
        if not supabase:
            return jsonify({"error": "Database client unavailable"}), 500
        herds = build_congress_herd_buys(
            supabase,
            fund=fund,
            days=max(7, min(days, 90)),
            min_politicians=max(2, min(min_politicians, 10)),
        )
        return jsonify({"data": herds, "window_days": max(7, min(days, 90))})
    except Exception as exc:
        logger.error("congress/herd-buys failed: %s", exc, exc_info=True)
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
