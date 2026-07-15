"""Insights / thesis thread routes."""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, render_template, request

from auth import is_admin, require_auth
from flask_auth_utils import get_effective_user_email_flask
from postgres_client import PostgresClient
from user_insights_service import (
    ThesisNotFoundError,
    ThesisPermissionError,
    add_entry,
    add_evidence,
    archive_thesis,
    create_thesis,
    delete_evidence,
    get_thesis_detail,
    hard_delete_thesis,
    list_theses,
    list_theses_due,
    restore_thesis,
    update_thesis_title,
)

logger = logging.getLogger(__name__)

insights_bp = Blueprint("insights", __name__)


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


def _actor() -> str:
    return get_effective_user_email_flask() or "unknown"


@insights_bp.route("/insights", methods=["GET"])
@require_auth
def insights_page():
    return _nav_render("insights.html", "insights")


@insights_bp.route("/api/insights", methods=["GET"])
@require_auth
def list_insights_api():
    try:
        pg = PostgresClient()
        include_archived = request.args.get("include_archived", "0").lower() in ("1", "true", "yes")
        rows = list_theses(
            pg,
            ticker=request.args.get("ticker"),
            disposition=request.args.get("disposition"),
            intent=request.args.get("intent"),
            author=request.args.get("author"),
            include_archived=include_archived,
            limit=request.args.get("limit", default=100, type=int),
        )
        return jsonify({"data": rows})
    except Exception as exc:
        logger.error("insights list failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@insights_bp.route("/api/insights/due", methods=["GET"])
@require_auth
def list_insights_due_api():
    try:
        pg = PostgresClient()
        soft = request.args.get("soft_days", default=14, type=int)
        hard = request.args.get("hard_days", default=30, type=int)
        rows = list_theses_due(
            pg,
            soft_days=soft or 14,
            hard_days=hard or 30,
            limit=request.args.get("limit", default=100, type=int),
        )
        return jsonify({"data": rows, "soft_days": soft or 14, "hard_days": hard or 30})
    except Exception as exc:
        logger.error("insights due list failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@insights_bp.route("/api/insights/attention", methods=["GET"])
@require_auth
def list_insights_attention_api():
    """Due/stale/weak + LLM TENSION/STALE_THESIS (Today/Ideas shared source)."""
    try:
        from user_insights_service import list_theses_attention

        pg = PostgresClient()
        rows = list_theses_attention(
            pg,
            soft_days=request.args.get("soft_days", default=14, type=int) or 14,
            hard_days=request.args.get("hard_days", default=30, type=int) or 30,
            limit=request.args.get("limit", default=40, type=int) or 40,
        )
        return jsonify({"data": rows})
    except Exception as exc:
        logger.error("insights attention list failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@insights_bp.route("/api/insights", methods=["POST"])
@require_auth
def create_insight_api():
    try:
        body = request.get_json(silent=True) or {}
        ticker = (body.get("ticker") or "").strip()
        if not ticker:
            return jsonify({"error": "ticker is required"}), 400
        thesis_body = (body.get("body") or "").strip()
        if not thesis_body:
            return jsonify({"error": "body is required"}), 400

        pg = PostgresClient()
        detail = create_thesis(
            pg,
            ticker=ticker,
            title=(body.get("title") or "").strip(),
            disposition=(body.get("disposition") or "neutral"),
            intent=(body.get("intent") or "monitor"),
            body=thesis_body,
            created_by=_actor(),
            source_url=body.get("source_url"),
            source_type=body.get("source_type"),
            tags=body.get("tags"),
        )
        return jsonify({"data": detail}), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.error("insights create failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@insights_bp.route("/api/insights/<thesis_id>", methods=["GET"])
@require_auth
def get_insight_api(thesis_id: str):
    try:
        pg = PostgresClient()
        return jsonify({"data": get_thesis_detail(pg, thesis_id)})
    except ThesisNotFoundError:
        return jsonify({"error": "not found"}), 404
    except Exception as exc:
        logger.error("insights get failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@insights_bp.route("/api/insights/<thesis_id>", methods=["PATCH"])
@require_auth
def patch_insight_api(thesis_id: str):
    try:
        body = request.get_json(silent=True) or {}
        title = (body.get("title") or "").strip()
        if not title:
            return jsonify({"error": "title is required"}), 400
        pg = PostgresClient()
        detail = update_thesis_title(
            pg,
            thesis_id=thesis_id,
            title=title,
            actor=_actor(),
            is_admin=is_admin(),
        )
        return jsonify({"data": detail})
    except ThesisNotFoundError:
        return jsonify({"error": "not found"}), 404
    except ThesisPermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except Exception as exc:
        logger.error("insights patch failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@insights_bp.route("/api/insights/<thesis_id>", methods=["DELETE"])
@require_auth
def delete_insight_api(thesis_id: str):
    try:
        pg = PostgresClient()
        hard_delete_thesis(pg, thesis_id=thesis_id, actor=_actor(), is_admin=is_admin())
        return jsonify({"ok": True})
    except ThesisNotFoundError:
        return jsonify({"error": "not found"}), 404
    except ThesisPermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except Exception as exc:
        logger.error("insights delete failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@insights_bp.route("/api/insights/<thesis_id>/entries", methods=["POST"])
@require_auth
def add_entry_api(thesis_id: str):
    try:
        body = request.get_json(silent=True) or {}
        entry_body = (body.get("body") or "").strip()
        entry_kind = (body.get("entry_kind") or "comment").strip().lower()
        if not entry_body:
            return jsonify({"error": "body is required"}), 400
        pg = PostgresClient()
        result = add_entry(
            pg,
            thesis_id=thesis_id,
            entry_kind=entry_kind,
            body=entry_body,
            author_id=_actor(),
            disposition=body.get("disposition"),
            intent=body.get("intent"),
        )
        return jsonify({"data": result})
    except ThesisNotFoundError:
        return jsonify({"error": "not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.error("insights entry failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@insights_bp.route("/api/insights/<thesis_id>/archive", methods=["POST"])
@require_auth
def archive_insight_api(thesis_id: str):
    try:
        pg = PostgresClient()
        detail = archive_thesis(
            pg, thesis_id=thesis_id, actor=_actor(), is_admin=is_admin()
        )
        return jsonify({"data": detail})
    except ThesisNotFoundError:
        return jsonify({"error": "not found"}), 404
    except ThesisPermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except Exception as exc:
        logger.error("insights archive failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@insights_bp.route("/api/insights/<thesis_id>/restore", methods=["POST"])
@require_auth
def restore_insight_api(thesis_id: str):
    try:
        pg = PostgresClient()
        detail = restore_thesis(
            pg, thesis_id=thesis_id, actor=_actor(), is_admin=is_admin()
        )
        return jsonify({"data": detail})
    except ThesisNotFoundError:
        return jsonify({"error": "not found"}), 404
    except ThesisPermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except Exception as exc:
        logger.error("insights restore failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@insights_bp.route("/api/insights/<thesis_id>/evidence", methods=["POST"])
@require_auth
def add_evidence_api(thesis_id: str):
    try:
        body = request.get_json(silent=True) or {}
        kind = (body.get("evidence_kind") or "user_url").strip().lower()
        pg = PostgresClient()
        result = add_evidence(
            pg,
            thesis_id=thesis_id,
            evidence_kind=kind,
            created_by=_actor(),
            entry_id=body.get("entry_id"),
            ref_id=body.get("ref_id") or body.get("article_id"),
            url=body.get("url"),
            title=body.get("title"),
            snippet=body.get("snippet"),
            relation=body.get("relation") or "context",
        )
        return jsonify({"data": result})
    except ThesisNotFoundError:
        return jsonify({"error": "not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.error("insights evidence add failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@insights_bp.route("/api/insights/<thesis_id>/evidence/<evidence_id>", methods=["DELETE"])
@require_auth
def delete_evidence_api(thesis_id: str, evidence_id: str):
    try:
        pg = PostgresClient()
        detail = delete_evidence(
            pg,
            thesis_id=thesis_id,
            evidence_id=evidence_id,
            actor=_actor(),
            is_admin=is_admin(),
        )
        return jsonify({"data": detail})
    except LookupError:
        return jsonify({"error": "not found"}), 404
    except ThesisPermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except Exception as exc:
        logger.error("insights evidence delete failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@insights_bp.route("/api/ticker/<ticker>/insights", methods=["GET"])
@require_auth
def ticker_insights_api(ticker: str):
    try:
        pg = PostgresClient()
        rows = list_theses(pg, ticker=ticker.upper().strip(), include_archived=False)
        return jsonify({"data": rows, "ticker": ticker.upper().strip()})
    except Exception as exc:
        logger.error("ticker insights failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500
