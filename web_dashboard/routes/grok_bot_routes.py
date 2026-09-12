"""Token-auth Grok Bot ingest: watchlist queue + X-brief upsert."""

from __future__ import annotations

import logging
import time
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

# A legitimate sweep posts 5 briefs of at most 64KB. Anything near this is abuse,
# and Flask reads the whole body into memory before a view ever sees it.
MAX_REQUEST_BYTES = 512 * 1024
# @rate_limit buckets on X-Forwarded-For, which the caller controls (ProxyFix is
# configured x_proto/x_host, not x_for), so rotating that header gives unlimited
# per-IP buckets. This bucket is not per-IP and cannot be rotated away. One Bot
# sweeping five tickers needs ~6 requests/hour; 60 is generous.
GLOBAL_HOURLY_LIMIT = 60


def _too_large() -> tuple[Any, int] | None:
    length = request.content_length
    if length is not None and length > MAX_REQUEST_BYTES:
        logger.warning("Grok Bot request rejected: %s bytes", length)
        return jsonify({"error": "payload too large"}), 413
    return None


def _global_budget_exceeded() -> bool:
    """Endpoint-wide hourly ceiling, independent of any client-supplied header."""
    try:
        from rate_limiter import _get_cache

        cache = _get_cache()
        window = int(time.time() // 3600)
        key = f"grok_bot_global:{window}"
        count = cache.get(key) or 0
        if count >= GLOBAL_HOURLY_LIMIT:
            logger.warning("Grok Bot global hourly budget exhausted (%s)", count)
            return True
        cache.set(key, count + 1, timeout=3700)
    except Exception as exc:  # fail open: a cache outage must not stop the sweep
        logger.debug("Grok Bot global budget check skipped: %s", exc)
    return False


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
    if _global_budget_exceeded():
        return jsonify({"error": "Too many requests. Please try again later."}), 429
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
    oversized = _too_large()
    if oversized:
        return oversized
    if _global_budget_exceeded():
        return jsonify({"error": "Too many requests. Please try again later."}), 429
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
