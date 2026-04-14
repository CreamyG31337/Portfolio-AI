"""Public routes for expiring portfolio digest HTML and KPI images."""

from __future__ import annotations

import logging
import os

from flask import Blueprint, Response, render_template, request

from digest_kpi_image import placeholder_expired_png, render_kpi_png
from digest_token import verify_digest_view_token, verify_preview_token
from outbound_digest_builder import build_digest_payload
from outbound_newsletter_pipeline import validate_issue_not_expired

logger = logging.getLogger(__name__)

digest_bp = Blueprint("digest", __name__)


def _public_base_url() -> str:
    return (os.getenv("PUBLIC_BASE_URL") or os.getenv("FLASK_PUBLIC_URL") or "").rstrip("/")


@digest_bp.route("/digest/view", methods=["GET"])
def digest_view():
    token = request.args.get("token") or ""
    parsed = verify_digest_view_token(token)
    if not parsed:
        return Response("Invalid or expired link.", status=403, mimetype="text/plain")

    issue = validate_issue_not_expired(parsed["issue_id"])
    if not issue:
        return render_template(
            "digest/digest_expired.html",
            dashboard_url=f"{_public_base_url()}/dashboard" if _public_base_url() else "/dashboard",
        ), 410

    payload = build_digest_payload(parsed["user_id"], issue_id=parsed["issue_id"])
    base = _public_base_url()
    settings_url = f"{base}/settings" if base else "/settings"
    return render_template(
        "digest/digest_full.html",
        **payload,
        dashboard_url=f"{base}/dashboard" if base else "/dashboard",
        settings_url=settings_url,
    )


@digest_bp.route("/digest/preview", methods=["GET"])
def digest_preview():
    """Time-limited admin preview (token from admin UI)."""
    token = request.args.get("token") or ""
    parsed = verify_preview_token(token, max_age_seconds=3600)
    if not parsed:
        return Response("Invalid preview link.", status=403, mimetype="text/plain")
    payload = build_digest_payload(parsed["user_id"], preview=True)
    base = _public_base_url()
    settings_url = f"{base}/settings" if base else "/settings"
    return render_template(
        "digest/digest_full.html",
        **payload,
        dashboard_url=f"{base}/dashboard" if base else "/dashboard",
        settings_url=settings_url,
    )


@digest_bp.route("/digest/kpi.png", methods=["GET"])
def digest_kpi_png():
    """Signed token + kind=value|week."""
    token = request.args.get("token") or ""
    kind = (request.args.get("kind") or "value").lower()
    if kind not in ("value", "week"):
        kind = "value"

    parsed = verify_digest_view_token(token)
    if not parsed:
        return Response(placeholder_expired_png(), mimetype="image/png", headers={"Cache-Control": "private, no-store"})

    issue = validate_issue_not_expired(parsed["issue_id"])
    if not issue:
        return Response(placeholder_expired_png(), mimetype="image/png", headers={"Cache-Control": "private, no-store"})

    payload = build_digest_payload(parsed["user_id"], issue_id=parsed["issue_id"])
    summary = payload.get("summary") or {}
    body = render_kpi_png(kind, summary)
    return Response(body, mimetype="image/png", headers={"Cache-Control": "private, no-store"})
