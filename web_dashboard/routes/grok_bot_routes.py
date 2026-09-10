"""Token-auth Grok Bot ingest: watchlist queue + X-brief upsert."""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from admin_utils import get_admin_supabase_client
from grok_bot_service import (
    GrokBotAuthError,
    GrokBotRequestError,
    QUEUE_LIMIT,
    build_queue,
    get_watchlist_funds,
    parse_brief_payloads,
    upsert_briefs,
    verify_grok_bot_token,
    watchlist_ticker_funds,
)
from postgres_client import PostgresClient
from rate_limiter import rate_limit

logger = logging.getLogger(__name__)

grok_bp = Blueprint("grok_bot", __name__)


def _auth_or_error() -> tuple[Any, int] | None:
    try:
        verify_grok_bot_token(request.headers.get("Authorization"))
    except GrokBotAuthError as exc:
        return jsonify({"error": str(exc)}), exc.status_code
    return None


@grok_bp.route("/api/grok/queue", methods=["GET"])
@rate_limit(limit=30, period=3600)
def grok_queue():
    failed = _auth_or_error()
    if failed:
        return failed
    funds = get_watchlist_funds()
    try:
        pg = PostgresClient()
        supabase = get_admin_supabase_client()
        items = build_queue(pg, supabase, funds=funds, limit=QUEUE_LIMIT)
    except Exception:
        logger.exception("Grok Bot queue failed funds=%s", funds)
        return jsonify({"error": "failed to build queue"}), 500
    return jsonify({"funds": funds, "limit": QUEUE_LIMIT, "data": items})


@grok_bp.route("/api/grok/briefs", methods=["POST"])
@rate_limit(limit=30, period=3600)
def grok_briefs():
    failed = _auth_or_error()
    if failed:
        return failed
    funds = get_watchlist_funds()
    try:
        briefs = parse_brief_payloads(request.get_json(silent=True))
        pg = PostgresClient()
        supabase = get_admin_supabase_client()
        ticker_funds = watchlist_ticker_funds(supabase, funds=funds)
        stored = upsert_briefs(pg, funds=funds, briefs=briefs, ticker_funds=ticker_funds)
    except GrokBotRequestError as exc:
        return jsonify({"error": str(exc)}), exc.status_code
    except Exception:
        logger.exception("Grok Bot brief upsert failed funds=%s", funds)
        return jsonify({"error": "failed to store briefs"}), 500
    return jsonify({"funds": funds, "data": stored})
