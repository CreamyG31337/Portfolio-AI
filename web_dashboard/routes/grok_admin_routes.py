"""Cookie-session admin page for the Grok Bot X-sweep: recent briefs, health, skip list.

Separate from grok_bot_routes on purpose: that blueprint is token-auth and CSRF-exempt
(the Bot has no cookies); this one is a dashboard page behind require_auth and the
global Flask-WTF CSRF check. Never mount these routes under /api/grok/.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from typing import Any

from flask import Blueprint, jsonify, render_template, request

from auth import require_auth
from flask_auth_utils import get_user_email_flask
from postgres_client import PostgresClient
from watchlist_access import normalize_ticker

logger = logging.getLogger(__name__)

grok_admin_bp = Blueprint("grok_admin", __name__)

BRIEFS_PAGE_LIMIT = 50
MAX_SKIP_REASON_CHARS = 200


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _parse_posts(raw: Any) -> list[dict[str, Any]]:
    """posts is jsonb in Postgres; accept list (driver-decoded) or JSON string."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    return [dict(p) for p in raw if isinstance(p, dict)]


def fetch_recent_briefs(
    pg: Any,
    *,
    ticker: str | None = None,
    notable: bool | None = None,
    limit: int = BRIEFS_PAGE_LIMIT,
) -> list[dict[str, Any]]:
    """Most recent briefs first, optionally filtered by ticker and notable."""
    clauses: list[str] = []
    params: list[Any] = []
    if ticker:
        clauses.append("ticker = %s")
        params.append(ticker)
    if notable is not None:
        clauses.append("notable = %s")
        params.append(notable)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = pg.execute_query(
        f"""
        SELECT id, fund, ticker, sweep_date, body, themes, posts, notable,
               cited_urls, status, created_at, updated_at
        FROM grok_x_briefs{where}
        ORDER BY sweep_date DESC, created_at DESC
        LIMIT %s
        """,
        tuple(params + [limit]),
    )
    briefs: list[dict[str, Any]] = []
    for row in rows or []:
        posts = _parse_posts(row.get("posts"))
        briefs.append(
            {
                "id": str(row.get("id") or ""),
                "fund": row.get("fund"),
                "ticker": row.get("ticker"),
                "sweep_date": _iso(row.get("sweep_date")),
                "body": row.get("body") or "",
                "themes": list(row.get("themes") or []),
                "posts": posts,
                "post_count": len(posts),
                "notable": bool(row.get("notable")),
                "cited_urls": list(row.get("cited_urls") or []),
                "status": row.get("status") or "ingested",
                "created_at": _iso(row.get("created_at")),
                "updated_at": _iso(row.get("updated_at")),
            }
        )
    return briefs


def fetch_activity_summary(pg: Any) -> dict[str, Any]:
    """Answer 'what is the bot doing?' — last sweep, its size, and totals."""
    rows = pg.execute_query(
        """
        SELECT COUNT(*) AS total, MAX(sweep_date) AS last_sweep
        FROM grok_x_briefs
        """
    )
    total = int(rows[0].get("total") or 0) if rows else 0
    last_sweep = _iso(rows[0].get("last_sweep")) if rows else None
    summary: dict[str, Any] = {
        "total_briefs": total,
        "last_sweep": last_sweep,
        "tickers_last_sweep": 0,
        "notable_last_sweep": 0,
        "swept_today": False,
    }
    if last_sweep:
        day_rows = pg.execute_query(
            """
            SELECT COUNT(DISTINCT ticker) AS tickers,
                   COUNT(*) FILTER (WHERE notable) AS notable
            FROM grok_x_briefs
            WHERE sweep_date = %s
            """,
            (last_sweep[:10],),
        )
        if day_rows:
            summary["tickers_last_sweep"] = int(day_rows[0].get("tickers") or 0)
            summary["notable_last_sweep"] = int(day_rows[0].get("notable") or 0)
        summary["swept_today"] = last_sweep[:10] == datetime.now(UTC).date().isoformat()
    return summary


def fetch_skips(pg: Any) -> list[dict[str, Any]]:
    rows = pg.execute_query(
        """
        SELECT ticker, reason, source, created_at, updated_at
        FROM grok_x_skips
        ORDER BY ticker
        """
    )
    return [
        {
            "ticker": row.get("ticker"),
            "reason": row.get("reason") or "",
            "source": row.get("source") or "manual",
            "created_at": _iso(row.get("created_at")),
            "updated_at": _iso(row.get("updated_at")),
        }
        for row in rows or []
    ]


def add_skip(pg: Any, *, ticker: str, reason: str) -> str:
    """Insert or update a manual skip. Returns the normalized ticker."""
    normalized = normalize_ticker(ticker)
    if not normalized:
        raise ValueError("ticker is required")
    pg.execute_update(
        """
        INSERT INTO grok_x_skips (ticker, reason, source)
        VALUES (%s, %s, 'manual')
        ON CONFLICT (ticker) DO UPDATE SET
            reason = EXCLUDED.reason,
            source = 'manual',
            updated_at = now()
        """,
        (normalized, reason.strip()[:MAX_SKIP_REASON_CHARS]),
    )
    return normalized


def remove_skip(pg: Any, *, ticker: str) -> str:
    """Delete a skip row (auto or manual) — this resumes sweeping the ticker."""
    normalized = normalize_ticker(ticker)
    if not normalized:
        raise ValueError("ticker is required")
    pg.execute_update("DELETE FROM grok_x_skips WHERE ticker = %s", (normalized,))
    return normalized


@grok_admin_bp.route("/grok/admin", methods=["GET"])
@require_auth
def grok_admin_page():
    from app import get_navigation_context  # Import here to avoid circular import

    ticker_filter = normalize_ticker(request.args.get("ticker") or "") or None
    notable_arg = (request.args.get("notable") or "").strip().lower()
    notable_filter: bool | None = None
    if notable_arg == "true":
        notable_filter = True
    elif notable_arg == "false":
        notable_filter = False

    try:
        pg = PostgresClient()
        briefs = fetch_recent_briefs(pg, ticker=ticker_filter, notable=notable_filter)
        summary = fetch_activity_summary(pg)
        skips = fetch_skips(pg)
    except Exception as exc:
        logger.error("Grok admin page failed: %s", exc, exc_info=True)
        nav_context = get_navigation_context(current_page="grok_admin")
        return render_template(
            "grok_admin.html",
            user_email=get_user_email_flask(),
            error="Error loading Grok Bot admin page",
            error_message=str(exc),
            briefs=[],
            summary=None,
            skips=[],
            ticker_filter=ticker_filter or "",
            notable_filter=notable_arg,
            **nav_context,
        ), 500

    nav_context = get_navigation_context(current_page="grok_admin")
    return render_template(
        "grok_admin.html",
        user_email=get_user_email_flask(),
        briefs=briefs,
        summary=summary,
        skips=skips,
        ticker_filter=ticker_filter or "",
        notable_filter=notable_arg,
        **nav_context,
    )


@grok_admin_bp.route("/grok/admin/skips", methods=["POST"])
@require_auth
def grok_admin_add_skip():
    payload = request.get_json(silent=True) or {}
    try:
        pg = PostgresClient()
        ticker = add_skip(pg, ticker=str(payload.get("ticker") or ""), reason=str(payload.get("reason") or ""))
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception:
        logger.exception("Failed to add Grok skip")
        return jsonify({"success": False, "error": "failed to add skip"}), 500
    return jsonify({"success": True, "ticker": ticker})


@grok_admin_bp.route("/grok/admin/skips/remove", methods=["POST"])
@require_auth
def grok_admin_remove_skip():
    payload = request.get_json(silent=True) or {}
    try:
        pg = PostgresClient()
        ticker = remove_skip(pg, ticker=str(payload.get("ticker") or ""))
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception:
        logger.exception("Failed to remove Grok skip")
        return jsonify({"success": False, "error": "failed to remove skip"}), 500
    return jsonify({"success": True, "ticker": ticker})
