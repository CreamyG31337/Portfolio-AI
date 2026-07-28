"""Admin Sources page — RSS feeds + YouTube allowlist CRUD.

See docs/PHASE_K_SOURCES_UI_PLAN.md. Does not grow admin_routes.py.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from flask import Blueprint, jsonify, render_template, request

from auth import require_admin
from flask_auth_utils import can_modify_data_flask, get_user_email_flask
from postgres_client import PostgresClient
from sources_service import (
    classify_bulk_rows,
    normalize_handle,
    normalize_kind,
    normalize_mechanism,
    normalize_tickers,
    parse_bulk_payload,
    serialize_row,
)

logger = logging.getLogger(__name__)

sources_bp = Blueprint("sources", __name__)

_probe_lock = threading.Lock()
_ALPHA_MECHANISMS = ("MARKET_MOVER", "LEAK", "TEARDOWN", "ANALYSIS", "EARNINGS_IR")


def _deny_readonly():
    if not can_modify_data_flask():
        return jsonify({"error": "Read-only admin cannot modify sources"}), 403
    return None


def _pg() -> PostgresClient:
    return PostgresClient()


def _iso_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


@sources_bp.route("/admin/sources")
@require_admin
def sources_page():
    try:
        from app import get_navigation_context

        nav_context = get_navigation_context(current_page="admin_sources")
        return render_template(
            "sources.html",
            user_email=get_user_email_flask(),
            can_modify_data=can_modify_data_flask(),
            alpha_mechanisms=_ALPHA_MECHANISMS,
            **nav_context,
        )
    except Exception as exc:
        logger.error("Error rendering sources page: %s", exc, exc_info=True)
        return render_template(
            "sources.html",
            user_email="Admin",
            can_modify_data=False,
            alpha_mechanisms=_ALPHA_MECHANISMS,
        )


# ---------------------------------------------------------------------------
# RSS CRUD
# ---------------------------------------------------------------------------


@sources_bp.route("/api/admin/sources/rss", methods=["GET"])
@require_admin
def api_list_rss():
    try:
        rows = _pg().execute_query(
            """
            SELECT id, name, url, category, enabled, last_fetched_at,
                   notes, consecutive_failures, last_error, last_success_at,
                   created_at, updated_at
            FROM rss_feeds
            ORDER BY enabled DESC, name ASC
            """
        )
        return jsonify({"feeds": [serialize_row(r) for r in rows]})
    except Exception as exc:
        logger.error("list rss failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@sources_bp.route("/api/admin/sources/rss", methods=["POST"])
@require_admin
def api_create_rss():
    denied = _deny_readonly()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()
    url = str(data.get("url") or "").strip()
    category = (str(data.get("category") or "").strip() or None)
    notes = (str(data.get("notes") or "").strip() or None)
    enabled = bool(data.get("enabled", True))
    if not name or not url:
        return jsonify({"error": "name and url are required"}), 400
    try:
        _pg().execute_update(
            """
            INSERT INTO rss_feeds (name, url, category, enabled, notes, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            """,
            (name, url, category, enabled, notes),
        )
        rows = _pg().execute_query(
            "SELECT id, name, url, category, enabled, notes FROM rss_feeds WHERE url = %s",
            (url,),
        )
        return jsonify({"success": True, "feed": serialize_row(rows[0]) if rows else None}), 201
    except Exception as exc:
        logger.error("create rss failed: %s", exc, exc_info=True)
        msg = str(exc)
        status = 409 if "unique" in msg.lower() or "duplicate" in msg.lower() else 500
        return jsonify({"error": msg}), status


@sources_bp.route("/api/admin/sources/rss/<int:feed_id>", methods=["PATCH"])
@require_admin
def api_update_rss(feed_id: int):
    denied = _deny_readonly()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    fields: list[str] = []
    params: list[Any] = []
    for col in ("name", "url", "category", "notes"):
        if col in data:
            fields.append(f"{col} = %s")
            val = data.get(col)
            params.append(None if val is None or val == "" else str(val).strip())
    if "enabled" in data:
        fields.append("enabled = %s")
        params.append(bool(data.get("enabled")))
    if not fields:
        return jsonify({"error": "no fields to update"}), 400
    fields.append("updated_at = NOW()")
    params.append(feed_id)
    try:
        n = _pg().execute_update(
            f"UPDATE rss_feeds SET {', '.join(fields)} WHERE id = %s",
            tuple(params),
        )
        if n == 0:
            return jsonify({"error": "feed not found"}), 404
        rows = _pg().execute_query("SELECT * FROM rss_feeds WHERE id = %s", (feed_id,))
        return jsonify({"success": True, "feed": serialize_row(rows[0]) if rows else None})
    except Exception as exc:
        logger.error("update rss failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@sources_bp.route("/api/admin/sources/rss/<int:feed_id>", methods=["DELETE"])
@require_admin
def api_delete_rss(feed_id: int):
    denied = _deny_readonly()
    if denied:
        return denied
    try:
        n = _pg().execute_update("DELETE FROM rss_feeds WHERE id = %s", (feed_id,))
        if n == 0:
            return jsonify({"error": "feed not found"}), 404
        return jsonify({"success": True})
    except Exception as exc:
        logger.error("delete rss failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# YouTube CRUD
# ---------------------------------------------------------------------------


def _existing_youtube_keys(pg: PostgresClient) -> tuple[set[str], set[str], set[str]]:
    rows = pg.execute_query(
        "SELECT channel_id, handle, query_text FROM youtube_sources"
    )
    channel_ids = {r["channel_id"] for r in rows if r.get("channel_id")}
    handles = {r["handle"] for r in rows if r.get("handle")}
    queries = {r["query_text"] for r in rows if r.get("query_text")}
    return channel_ids, handles, queries


def _resolve_channel_id(handle: Optional[str], channel_id: Optional[str]) -> Optional[str]:
    """Best-effort yt-dlp resolve of @handle → UC… id. Soft-fails to None."""
    if channel_id:
        return channel_id
    if not handle:
        return None
    try:
        import yt_dlp
    except ImportError:
        return None
    url = f"https://www.youtube.com/{handle.lstrip('@')}"
    if handle.startswith("@"):
        url = f"https://www.youtube.com/{handle}"
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "playlistend": 1}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            return None
        cid = info.get("channel_id") or info.get("id")
        if cid and str(cid).startswith("UC"):
            return str(cid)
        # channel tab sometimes nests
        if info.get("entries"):
            first = info["entries"][0] or {}
            nested = first.get("channel_id")
            if nested:
                return str(nested)
        return None
    except Exception as exc:
        logger.info("channel_id resolve failed for %s: %s", handle, exc)
        return None


@sources_bp.route("/api/admin/sources/youtube", methods=["GET"])
@require_admin
def api_list_youtube():
    try:
        rows = _pg().execute_query(
            """
            SELECT *
            FROM youtube_sources
            ORDER BY enabled DESC, label ASC
            """
        )
        return jsonify({"sources": [serialize_row(r) for r in rows]})
    except Exception as exc:
        logger.error("list youtube failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


def _parse_youtube_body(data: dict[str, Any]) -> tuple[Optional[dict[str, Any]], Optional[tuple]]:
    label = str(data.get("label") or "").strip()
    kind = normalize_kind(data.get("kind"))
    handle = normalize_handle(data.get("handle"))
    channel_id = (str(data.get("channel_id") or "").strip() or None)
    query_text = (str(data.get("query_text") or "").strip() or None)
    mechanism = normalize_mechanism(data.get("alpha_mechanism"))
    if data.get("alpha_mechanism") not in (None, "") and mechanism is None:
        return None, (jsonify({"error": f"invalid alpha_mechanism: {data.get('alpha_mechanism')}"}), 400)
    tickers, ticker_errors = normalize_tickers(data.get("expected_tickers"))
    if ticker_errors:
        return None, (jsonify({"error": "; ".join(ticker_errors)}), 400)
    try:
        weight = float(data.get("confidence_weight", 1.0))
    except (TypeError, ValueError):
        return None, (jsonify({"error": "invalid confidence_weight"}), 400)
    if weight < 0.0 or weight > 2.0:
        return None, (jsonify({"error": "confidence_weight must be 0.00–2.00"}), 400)
    if not label:
        return None, (jsonify({"error": "label is required"}), 400)
    if kind == "search":
        if not query_text:
            return None, (jsonify({"error": "query_text required for search"}), 400)
    elif not channel_id and not handle:
        return None, (jsonify({"error": "channel_id or handle required"}), 400)

    enabled = bool(data.get("enabled", True))
    notes = (str(data.get("notes") or "").strip() or None)
    source_of_recommendation = (
        str(data.get("source_of_recommendation") or "").strip() or None
    )
    max_videos = int(data.get("max_videos_per_poll", 5) or 5)
    min_duration = int(data.get("min_duration_s", 120) or 120)
    max_duration_raw = data.get("max_duration_s")
    max_duration = int(max_duration_raw) if max_duration_raw not in (None, "") else None

    return {
        "label": label,
        "kind": kind,
        "handle": handle,
        "channel_id": channel_id,
        "query_text": query_text,
        "alpha_mechanism": mechanism,
        "expected_tickers": tickers,
        "confidence_weight": weight,
        "enabled": enabled,
        "notes": notes,
        "source_of_recommendation": source_of_recommendation,
        "max_videos_per_poll": max_videos,
        "min_duration_s": min_duration,
        "max_duration_s": max_duration,
    }, None


@sources_bp.route("/api/admin/sources/youtube", methods=["POST"])
@require_admin
def api_create_youtube():
    denied = _deny_readonly()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    parsed, err = _parse_youtube_body(data)
    if err:
        return err
    assert parsed is not None
    if parsed["kind"] != "search" and not parsed["channel_id"]:
        parsed["channel_id"] = _resolve_channel_id(parsed["handle"], None)
    added_by = get_user_email_flask()
    try:
        _pg().execute_update(
            """
            INSERT INTO youtube_sources (
                kind, channel_id, handle, query_text, label,
                alpha_mechanism, confidence_weight, expected_tickers,
                enabled, max_videos_per_poll, min_duration_s, max_duration_s,
                notes, added_by, source_of_recommendation, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, NOW()
            )
            """,
            (
                parsed["kind"],
                parsed["channel_id"],
                parsed["handle"],
                parsed["query_text"],
                parsed["label"],
                parsed["alpha_mechanism"],
                parsed["confidence_weight"],
                parsed["expected_tickers"],
                parsed["enabled"],
                parsed["max_videos_per_poll"],
                parsed["min_duration_s"],
                parsed["max_duration_s"],
                parsed["notes"],
                added_by,
                parsed["source_of_recommendation"],
            ),
        )
        # Fetch by most unique key
        if parsed["channel_id"]:
            rows = _pg().execute_query(
                "SELECT * FROM youtube_sources WHERE channel_id = %s",
                (parsed["channel_id"],),
            )
        elif parsed["query_text"]:
            rows = _pg().execute_query(
                "SELECT * FROM youtube_sources WHERE query_text = %s",
                (parsed["query_text"],),
            )
        else:
            rows = _pg().execute_query(
                "SELECT * FROM youtube_sources WHERE handle = %s ORDER BY id DESC LIMIT 1",
                (parsed["handle"],),
            )
        return jsonify({"success": True, "source": serialize_row(rows[0]) if rows else None}), 201
    except Exception as exc:
        logger.error("create youtube failed: %s", exc, exc_info=True)
        msg = str(exc)
        status = 409 if "unique" in msg.lower() or "duplicate" in msg.lower() else 500
        return jsonify({"error": msg}), status


@sources_bp.route("/api/admin/sources/youtube/<int:source_id>", methods=["PATCH"])
@require_admin
def api_update_youtube(source_id: int):
    denied = _deny_readonly()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    fields: list[str] = []
    params: list[Any] = []

    simple_str = {
        "label": "label",
        "notes": "notes",
        "source_of_recommendation": "source_of_recommendation",
        "last_error_reason": "last_error_reason",
        "last_video_id": "last_video_id",
    }
    for key, col in simple_str.items():
        if key in data:
            fields.append(f"{col} = %s")
            val = data.get(key)
            params.append(None if val is None or val == "" else str(val).strip())

    if "kind" in data:
        fields.append("kind = %s")
        params.append(normalize_kind(data.get("kind")))
    if "handle" in data:
        fields.append("handle = %s")
        params.append(normalize_handle(data.get("handle")))
    if "channel_id" in data:
        fields.append("channel_id = %s")
        val = data.get("channel_id")
        params.append(None if val is None or val == "" else str(val).strip())
    if "query_text" in data:
        fields.append("query_text = %s")
        val = data.get("query_text")
        params.append(None if val is None or val == "" else str(val).strip())
    if "alpha_mechanism" in data:
        mech = normalize_mechanism(data.get("alpha_mechanism"))
        if data.get("alpha_mechanism") not in (None, "") and mech is None:
            return jsonify({"error": "invalid alpha_mechanism"}), 400
        fields.append("alpha_mechanism = %s")
        params.append(mech)
    if "expected_tickers" in data:
        tickers, errs = normalize_tickers(data.get("expected_tickers"))
        if errs:
            return jsonify({"error": "; ".join(errs)}), 400
        fields.append("expected_tickers = %s")
        params.append(tickers)
    if "confidence_weight" in data:
        try:
            weight = float(data.get("confidence_weight"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid confidence_weight"}), 400
        if weight < 0.0 or weight > 2.0:
            return jsonify({"error": "confidence_weight must be 0.00–2.00"}), 400
        fields.append("confidence_weight = %s")
        params.append(weight)
    if "enabled" in data:
        fields.append("enabled = %s")
        params.append(bool(data.get("enabled")))
    for int_col in ("max_videos_per_poll", "min_duration_s", "max_duration_s", "consecutive_failures"):
        if int_col in data:
            fields.append(f"{int_col} = %s")
            val = data.get(int_col)
            params.append(None if val in (None, "") else int(val))
    if "captions_ok" in data:
        fields.append("captions_ok = %s")
        params.append(data.get("captions_ok"))

    if not fields:
        return jsonify({"error": "no fields to update"}), 400
    fields.append("updated_at = NOW()")
    params.append(source_id)
    try:
        n = _pg().execute_update(
            f"UPDATE youtube_sources SET {', '.join(fields)} WHERE id = %s",
            tuple(params),
        )
        if n == 0:
            return jsonify({"error": "source not found"}), 404
        rows = _pg().execute_query("SELECT * FROM youtube_sources WHERE id = %s", (source_id,))
        return jsonify({"success": True, "source": serialize_row(rows[0]) if rows else None})
    except Exception as exc:
        logger.error("update youtube failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@sources_bp.route("/api/admin/sources/youtube/<int:source_id>", methods=["DELETE"])
@require_admin
def api_delete_youtube(source_id: int):
    denied = _deny_readonly()
    if denied:
        return denied
    try:
        n = _pg().execute_update("DELETE FROM youtube_sources WHERE id = %s", (source_id,))
        if n == 0:
            return jsonify({"error": "source not found"}), 404
        return jsonify({"success": True})
    except Exception as exc:
        logger.error("delete youtube failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Test captions (live network — only endpoint that does)
# ---------------------------------------------------------------------------


@sources_bp.route("/api/admin/sources/youtube/test", methods=["POST"])
@require_admin
def api_test_youtube():
    denied = _deny_readonly()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    url_or_id = (str(data.get("url_or_id") or "").strip() or None)
    source_id = data.get("id")

    if not url_or_id and source_id is None:
        return jsonify({"error": "url_or_id or id required"}), 400

    if not _probe_lock.acquire(blocking=False):
        return jsonify({"error": "Another caption probe is already in progress"}), 429

    try:
        pg = _pg()
        row = None
        if source_id is not None:
            rows = pg.execute_query(
                "SELECT * FROM youtube_sources WHERE id = %s", (int(source_id),)
            )
            if not rows:
                return jsonify({"error": "source not found"}), 404
            row = rows[0]
            if not url_or_id:
                # Probe a recent video if we have last_video_id, else channel home is not a video —
                # require url_or_id for channel rows without a known video.
                if row.get("last_video_id"):
                    url_or_id = str(row["last_video_id"])
                else:
                    return jsonify(
                        {
                            "error": "No last_video_id on this source — pass url_or_id of a known video to test captions",
                        }
                    ), 400

        from youtube_captions import CaptionFetchError, fetch_caption_text

        try:
            result = fetch_caption_text(
                url_or_id,
                include_metadata=True,
                use_ytdlp_fallback=True,
            )
        except CaptionFetchError as exc:
            if row is not None:
                pg.execute_update(
                    """
                    UPDATE youtube_sources
                    SET captions_ok = FALSE,
                        consecutive_failures = consecutive_failures + 1,
                        last_error_reason = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (exc.reason, int(source_id)),
                )
            return jsonify({"ok": False, "reason": exc.reason, "message": str(exc)})

        if row is not None:
            pg.execute_update(
                """
                UPDATE youtube_sources
                SET captions_ok = TRUE,
                    consecutive_failures = 0,
                    last_error_reason = NULL,
                    last_success_at = NOW(),
                    channel_id = COALESCE(channel_id, %s),
                    updated_at = NOW()
                WHERE id = %s
                """,
                (result.channel_id, int(source_id)),
            )

        return jsonify(
            {
                "ok": True,
                "video_id": result.video_id,
                "language": result.language,
                "caption_kind": result.caption_kind,
                "char_count": result.char_count,
                "title": result.title,
                "channel_id": result.channel_id,
                "fetch_source": result.fetch_source,
            }
        )
    except Exception as exc:
        logger.error("youtube test failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500
    finally:
        _probe_lock.release()


# ---------------------------------------------------------------------------
# Bulk import
# ---------------------------------------------------------------------------


@sources_bp.route("/api/admin/sources/youtube/bulk-preview", methods=["POST"])
@require_admin
def api_bulk_preview():
    denied = _deny_readonly()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    fmt = str(data.get("format") or "json")
    payload = str(data.get("payload") or "")
    rows, top_errors = parse_bulk_payload(fmt, payload)
    if top_errors:
        return jsonify({"error": "; ".join(top_errors), "rows": [], "summary": {}}), 400
    try:
        channel_ids, handles, queries = _existing_youtube_keys(_pg())
        result = classify_bulk_rows(
            rows,
            existing_channel_ids=channel_ids,
            existing_handles=handles,
            existing_queries=queries,
        )
        return jsonify(result)
    except Exception as exc:
        # Table may not exist yet in some envs — still classify against empty sets.
        logger.warning("bulk-preview existing-key lookup failed: %s", exc)
        result = classify_bulk_rows(
            rows,
            existing_channel_ids=set(),
            existing_handles=set(),
            existing_queries=set(),
        )
        return jsonify(result)


@sources_bp.route("/api/admin/sources/youtube/bulk-commit", methods=["POST"])
@require_admin
def api_bulk_commit():
    denied = _deny_readonly()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    fmt = str(data.get("format") or "json")
    payload = str(data.get("payload") or "")
    rows, top_errors = parse_bulk_payload(fmt, payload)
    if top_errors:
        return jsonify({"error": "; ".join(top_errors)}), 400

    pg = _pg()
    channel_ids, handles, queries = _existing_youtube_keys(pg)
    classified = classify_bulk_rows(
        rows,
        existing_channel_ids=channel_ids,
        existing_handles=handles,
        existing_queries=queries,
    )
    added_by = get_user_email_flask()
    inserted = 0
    skipped = 0
    errors: list[str] = []

    for row in classified["rows"]:
        if row["status"] != "new":
            skipped += 1
            continue
        channel_id = row.get("channel_id")
        if row["kind"] != "search" and not channel_id:
            channel_id = _resolve_channel_id(row.get("handle"), None)
        try:
            pg.execute_update(
                """
                INSERT INTO youtube_sources (
                    kind, channel_id, handle, query_text, label,
                    alpha_mechanism, confidence_weight, expected_tickers,
                    enabled, notes, added_by, source_of_recommendation, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    TRUE, %s, %s, %s, NOW()
                )
                """,
                (
                    row["kind"],
                    channel_id,
                    row.get("handle"),
                    row.get("query_text"),
                    row["label"],
                    row.get("alpha_mechanism"),
                    row.get("confidence_weight", 1.0),
                    row.get("expected_tickers") or [],
                    row.get("notes"),
                    added_by,
                    row.get("source_of_recommendation"),
                ),
            )
            inserted += 1
            if channel_id:
                channel_ids.add(channel_id)
            if row.get("handle"):
                handles.add(row["handle"])
            if row.get("query_text"):
                queries.add(row["query_text"])
        except Exception as exc:
            errors.append(f"{row.get('label')}: {exc}")

    return jsonify(
        {
            "success": True,
            "inserted": inserted,
            "skipped": skipped,
            "errors": errors,
            "summary": classified["summary"],
        }
    )
