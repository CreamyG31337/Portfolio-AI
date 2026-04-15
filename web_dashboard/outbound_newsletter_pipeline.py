"""Create issues, send portfolio digest emails, update Supabase send rows."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from flask import has_app_context, render_template

from digest_token import sign_digest_view_token
from mailgun_outbound import get_mailgun_outbound_params, send_mailgun_message
from outbound_digest_builder import (
    PORTFOLIO_DIGEST_SLUG,
    build_digest_payload,
    resolve_newsletter_type_id,
)
from supabase_client import SupabaseClient

logger = logging.getLogger(__name__)


def _public_base_url() -> str:
    return (os.getenv("PUBLIC_BASE_URL") or os.getenv("FLASK_PUBLIC_URL") or "").rstrip("/")


def _render_digest_thin_email(**template_vars: Any) -> str:
    """Jinja ``render_template`` requires a Flask application context (scheduler has none)."""
    if has_app_context():
        return render_template("email/digest_thin.html", **template_vars)
    # Lazy import avoids circular import while ``app`` module is still loading.
    from app import app as flask_app

    with flask_app.app_context():
        return render_template("email/digest_thin.html", **template_vars)


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def create_issue(
    triggered_by: str,
    *,
    newsletter_type_id: Optional[str] = None,
    ttl_days: int = 7,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    client = SupabaseClient(use_service_role=True)
    ntid = newsletter_type_id or resolve_newsletter_type_id(client)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=ttl_days)
    row = {
        "newsletter_type_id": ntid,
        "triggered_by": triggered_by,
        "status": "sending",
        "sent_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "metadata": metadata or {},
    }
    ins = client.supabase.table("outbound_newsletter_issues").insert(row).execute()
    if not ins.data:
        raise RuntimeError("Failed to insert outbound_newsletter_issues")
    return ins.data[0]


def update_issue_status(issue_id: str, status: str) -> None:
    client = SupabaseClient(use_service_role=True)
    client.supabase.table("outbound_newsletter_issues").update({"status": status}).eq("id", issue_id).execute()


def get_user_email_service(user_id: str) -> Optional[str]:
    client = SupabaseClient(use_service_role=True)
    r = client.supabase.table("user_profiles").select("email").eq("user_id", user_id).limit(1).execute()
    if r.data and r.data[0].get("email"):
        return str(r.data[0]["email"])
    return None


def send_digest_for_user(
    issue_id: str,
    user_id: str,
    *,
    to_email: Optional[str] = None,
) -> Dict[str, Any]:
    """Build thin email + Mailgun send; insert outbound_newsletter_sends."""
    email = to_email or get_user_email_service(user_id)
    if not email:
        raise ValueError(f"No email for user {user_id}")

    base = _public_base_url()
    token = sign_digest_view_token(user_id, issue_id)
    digest_url = f"{base}/digest/view?token={token}" if base else f"/digest/view?token={token}"
    dashboard_url = f"{base}/dashboard" if base else "/dashboard"

    payload = build_digest_payload(user_id, issue_id=issue_id)
    kpi_value_url = f"{base}/digest/kpi.png?token={token}&kind=value" if base else None
    kpi_week_url = f"{base}/digest/kpi.png?token={token}&kind=week" if base else None
    manage_url = f"{base}/settings" if base else None
    thin_html = _render_digest_thin_email(
        as_of=payload["as_of"],
        week_label=payload["week_label"],
        digest_url=digest_url if base else None,
        dashboard_url=dashboard_url,
        manage_url=manage_url,
        market_brief=payload.get("market_brief"),
        kpi_value_url=kpi_value_url,
        kpi_week_url=kpi_week_url,
    )

    subject = os.getenv("OUTBOUND_DIGEST_SUBJECT", "Your portfolio digest")
    mg = send_mailgun_message(
        email,
        subject,
        thin_html,
        tags=["portfolio_digest"],
    )
    msg_id = mg.get("id") if isinstance(mg, dict) else None

    client = SupabaseClient(use_service_role=True)
    send_row = {
        "issue_id": issue_id,
        "user_id": user_id,
        "email": email,
        "mailgun_message_id": msg_id,
        "status": "sent",
    }
    client.supabase.table("outbound_newsletter_sends").insert(send_row).execute()

    # last_sent_at on subscription (optional)
    try:
        ntid = resolve_newsletter_type_id(client)
        client.supabase.table("user_newsletter_subscriptions").update(
            {"last_sent_at": datetime.now(timezone.utc).isoformat()}
        ).eq("user_id", user_id).eq("newsletter_type_id", ntid).execute()
    except Exception as e:
        logger.debug("subscription last_sent_at update skipped: %s", e)

    return {"email": email, "mailgun": mg}


def validate_issue_not_expired(issue_id: str) -> Optional[Dict[str, Any]]:
    client = SupabaseClient(use_service_role=True)
    r = client.supabase.table("outbound_newsletter_issues").select("*").eq("id", issue_id).limit(1).execute()
    if not r.data:
        return None
    row = r.data[0]
    exp = _parse_ts(row.get("expires_at"))
    if exp and datetime.now(timezone.utc) > exp:
        return None
    return row


def list_due_subscriptions(cadence: str, newsletter_type_id: str) -> List[str]:
    """Return user_ids due for send (simple interval from last_sent_at)."""
    client = SupabaseClient(use_service_role=True)
    r = (
        client.supabase.table("user_newsletter_subscriptions")
        .select("user_id,last_sent_at,cadence")
        .eq("newsletter_type_id", newsletter_type_id)
        .eq("is_active", True)
        .eq("cadence", cadence)
        .execute()
    )
    if not r.data:
        return []

    delta = {
        "daily": timedelta(days=1),
        "weekly": timedelta(days=7),
        "biweekly": timedelta(days=14),
        "monthly": timedelta(days=30),
    }.get(cadence, timedelta(days=7))

    now = datetime.now(timezone.utc)
    due: List[str] = []
    for row in r.data:
        last = _parse_ts(row.get("last_sent_at"))
        if last is None or (now - last) >= delta:
            due.append(str(row["user_id"]))
    return due


def run_scheduled_digest_wave(cadence: str = "weekly") -> Dict[str, Any]:
    """Phase 3 entry: one issue per cadence wave for portfolio_digest."""
    if not get_mailgun_outbound_params():
        logger.info("Skipping outbound digest wave: Mailgun send not configured")
        return {"issue": None, "sent": 0, "message": "mailgun not configured"}

    client = SupabaseClient(use_service_role=True)
    ntid = resolve_newsletter_type_id(client)
    user_ids = list_due_subscriptions(cadence, ntid)
    if not user_ids:
        return {"issue": None, "sent": 0, "message": "no due subscribers"}

    issue = create_issue("scheduler", newsletter_type_id=ntid, ttl_days=7, metadata={"cadence": cadence})
    issue_id = str(issue["id"])
    sent = 0
    errors: List[str] = []
    for uid in user_ids:
        try:
            send_digest_for_user(issue_id, uid)
            sent += 1
        except Exception as e:
            logger.error("digest send failed %s: %s", uid, e, exc_info=True)
            errors.append(f"{uid}: {e}")
    update_issue_status(issue_id, "completed" if not errors else "failed")
    return {"issue_id": issue_id, "sent": sent, "errors": errors}
