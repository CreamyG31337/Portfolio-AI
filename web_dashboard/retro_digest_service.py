"""Weekly stance retro HTML digest + Mailgun send (ROADMAP G5)."""

from __future__ import annotations

import html
import logging
import os
from datetime import UTC, datetime
from typing import Any

from postgres_client import PostgresClient
from track_record_service import build_track_record_summary

logger = logging.getLogger(__name__)


def _configured_recipient_accounts() -> list[str]:
    raw = (os.getenv("RETRO_DIGEST_RECIPIENT_ACCOUNTS") or "").strip()
    return [name.strip() for name in raw.split(",") if name.strip()]


def _emails_for_accounts(
    account_names: list[str],
    *,
    supabase_client: Any | None = None,
) -> list[str]:
    """Resolve exact, case-insensitive full names to profile emails.

    Ambiguous names are skipped rather than emailing multiple accounts.
    """
    if not account_names:
        return []
    try:
        if supabase_client is None:
            from supabase_client import SupabaseClient

            supabase_client = SupabaseClient(use_service_role=True)
    except Exception as exc:
        logger.warning("retro digest account lookup unavailable: %s", exc)
        return []

    emails: list[str] = []
    for account_name in account_names:
        try:
            result = (
                supabase_client.supabase.table("user_profiles")
                .select("email,full_name")
                .ilike("full_name", account_name)
                .limit(2)
                .execute()
            )
            rows = [
                row
                for row in (result.data or [])
                if str(row.get("full_name") or "").strip().casefold()
                == account_name.casefold()
            ]
            if len(rows) != 1:
                logger.warning(
                    "retro digest account '%s' resolved to %d profiles; skipping",
                    account_name,
                    len(rows),
                )
                continue
            email = str(rows[0].get("email") or "").strip()
            if "@" in email:
                emails.append(email)
        except Exception as exc:
            logger.warning(
                "retro digest account lookup failed for '%s': %s",
                account_name,
                exc,
            )
    return emails


def get_retro_digest_recipients(
    *,
    supabase_client: Any | None = None,
) -> list[str]:
    """Resolve recipients from direct emails and/or dashboard account names.

    ``RETRO_DIGEST_RECIPIENTS`` remains supported for direct comma-separated
    emails. ``RETRO_DIGEST_RECIPIENT_ACCOUNTS`` resolves comma-separated
    ``user_profiles.full_name`` values to their current profile email.
    """
    raw = (os.getenv("RETRO_DIGEST_RECIPIENTS") or "").strip()
    direct = [e.strip() for e in raw.split(",") if e.strip() and "@" in e]
    accounts = _configured_recipient_accounts()
    resolved = _emails_for_accounts(accounts, supabase_client=supabase_client)
    # Preserve configuration order while avoiding duplicate sends.
    return list(dict.fromkeys([*direct, *resolved]))


def retro_digest_enabled(
    *,
    supabase_client: Any | None = None,
    recipients: list[str] | None = None,
) -> bool:
    raw = (os.getenv("RETRO_DIGEST_ENABLED") or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    recipient_list = (
        recipients
        if recipients is not None
        else get_retro_digest_recipients(supabase_client=supabase_client)
    )
    if not recipient_list:
        return False
    try:
        from mailgun_outbound import get_mailgun_outbound_params

        return get_mailgun_outbound_params() is not None
    except Exception:
        return False


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_rate(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{100.0 * value:.1f}%"


def build_weekly_retro_digest_html(
    postgres: PostgresClient | None = None,
    *,
    flip_days: int = 7,
    horizon_days: int = 30,
) -> str:
    """Render a compact HTML digest for the weekly retro email."""
    pg = postgres or PostgresClient()
    from today_briefing_service import fetch_stance_flips

    flips = fetch_stance_flips(pg, days=flip_days, limit=50)
    summary = build_track_record_summary(pg, horizon_days=horizon_days)

    confluence_rows: list[dict[str, Any]] = []
    try:
        confluence_rows = pg.execute_query(
            """
            SELECT ticker, direction, score, families, as_of
            FROM confluence_events
            WHERE as_of >= NOW() - make_interval(days => %s)
            ORDER BY score DESC, as_of DESC
            LIMIT 10
            """,
            (flip_days,),
        )
    except Exception as exc:
        logger.debug("confluence_events unavailable for retro digest: %s", exc)

    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    parts: list[str] = [
        "<html><body style=\"font-family:sans-serif;color:#111;\">",
        f"<h2>Weekly stance retro</h2><p><em>Generated {html.escape(now)}</em></p>",
        f"<h3>Stance flips ({flip_days}d)</h3>",
    ]
    if flips:
        parts.append("<ul>")
        for f in flips[:15]:
            parts.append(
                "<li>"
                f"<strong>{html.escape(str(f.get('ticker') or ''))}</strong> "
                f"{html.escape(str(f.get('old_stance') or '?'))} → "
                f"{html.escape(str(f.get('new_stance') or '?'))} "
                f"({html.escape(str(f.get('source') or ''))})"
                "</li>"
            )
        parts.append("</ul>")
        if len(flips) > 15:
            parts.append(f"<p>…and {len(flips) - 15} more.</p>")
    else:
        parts.append("<p>No stance flips in the window.</p>")

    parts.append(f"<h3>Track record ({horizon_days}d horizon)</h3>")
    total = summary.get("total_scored") or 0
    if total == 0:
        parts.append(
            "<p>No scored outcomes yet at this horizon — expected until ledger rows age "
            f"≥ {horizon_days} days (~2026-07-10 for 30d).</p>"
        )
        # Fall back to 7d if available so the email isn't empty once scoring starts.
        summary7 = build_track_record_summary(pg, horizon_days=7)
        if (summary7.get("total_scored") or 0) > 0:
            parts.append("<p><strong>7-day preview:</strong></p><ul>")
            for src, rate in (summary7.get("hit_rate_by_source") or {}).items():
                counts = (summary7.get("counts_by_source") or {}).get(src) or {}
                parts.append(
                    "<li>"
                    f"{html.escape(src)}: hit rate {_fmt_rate(rate)} "
                    f"({counts.get('hits', 0)}/{counts.get('scored', 0)} scored)"
                    "</li>"
                )
            parts.append("</ul>")
    else:
        parts.append(f"<p>Total scored: {total}</p><ul>")
        for src, rate in (summary.get("hit_rate_by_source") or {}).items():
            counts = (summary.get("counts_by_source") or {}).get(src) or {}
            parts.append(
                "<li>"
                f"{html.escape(src)}: hit rate {_fmt_rate(rate)} "
                f"({counts.get('hits', 0)}/{counts.get('scored', 0)} scored)"
                "</li>"
            )
        parts.append("</ul>")
        verdict_rates = summary.get("hit_rate_by_verdict") or {}
        if verdict_rates:
            parts.append("<p><strong>AI review calibration:</strong></p><ul>")
            for verdict, rate in verdict_rates.items():
                parts.append(f"<li>{html.escape(verdict)}: {_fmt_rate(rate)}</li>")
            parts.append("</ul>")

    parts.append(f"<h3>Confluence events ({flip_days}d)</h3>")
    if confluence_rows:
        parts.append("<ul>")
        for row in confluence_rows:
            fam = row.get("families")
            fam_n = len(fam) if isinstance(fam, list) else 0
            parts.append(
                "<li>"
                f"<strong>{html.escape(str(row.get('ticker') or ''))}</strong> "
                f"{html.escape(str(row.get('direction') or ''))} "
                f"score={row.get('score')} ({fam_n} families)"
                "</li>"
            )
        parts.append("</ul>")
    else:
        parts.append("<p>None in the window.</p>")

    parts.append(
        "<hr><p style=\"color:#666;font-size:12px;\">"
        "System self-review digest — not investment advice. "
        "Disable: unset RETRO_DIGEST_RECIPIENTS and RETRO_DIGEST_RECIPIENT_ACCOUNTS, "
        "or set RETRO_DIGEST_ENABLED=false."
        "</p></body></html>"
    )
    return "".join(parts)


def send_weekly_retro_digest(
    postgres: PostgresClient | None = None,
    *,
    flip_days: int = 7,
    horizon_days: int = 30,
) -> dict[str, Any]:
    """Build and send the retro digest to configured recipients. No-op when disabled."""
    recipients = get_retro_digest_recipients()
    if not recipients or not retro_digest_enabled(recipients=recipients):
        return {"sent": 0, "skipped": True, "reason": "retro_digest_disabled"}

    from mailgun_outbound import send_mailgun_message

    pg = postgres or PostgresClient()
    body = build_weekly_retro_digest_html(pg, flip_days=flip_days, horizon_days=horizon_days)
    subject = f"Weekly stance retro — {datetime.now(UTC).strftime('%Y-%m-%d')}"
    sent = 0
    errors: list[str] = []
    for email in recipients:
        try:
            send_mailgun_message(email, subject, body, tags=["stance-retro"])
            sent += 1
        except Exception as exc:
            errors.append(f"{email}: {exc}")
            logger.warning("retro digest send failed for %s: %s", email, exc)
    return {"sent": sent, "skipped": False, "recipients": len(recipients), "errors": errors}
