"""Send transactional email via Mailgun HTTP API.

Inbound newsletters use ``POST /api/webhooks/newsletter`` and only need
``MAILGUN_WEBHOOK_SIGNING_KEY`` to verify Mailgun's HMAC. The HTTP API sending
domain is irrelevant for receiving.

Outbound sends (digest, etc.) need ``MAILGUN_API_KEY`` (secret; keep in env) plus
a verified Mailgun domain. Domain and From can be non-secrets, stored in
``system_settings`` so CI does not need extra Woodpecker secrets:

- ``mailgun_send_domain`` (or legacy ``mailgun_domain``) — e.g. ``mg.example.com``
- ``mailgun_from`` — e.g. ``Portfolio <noreply@mg.example.com>``
- ``mailgun_api_base`` — optional, default ``https://api.mailgun.net/v3``

Environment variables still override DB when set: ``MAILGUN_SEND_DOMAIN``,
``MAILGUN_DOMAIN``, ``MAILGUN_FROM``, ``MAILGUN_API_BASE``. If two sources disagree
(e.g. both ``MAILGUN_SEND_DOMAIN`` and ``MAILGUN_DOMAIN``, or env vs
``system_settings``), a **one-time** WARNING is logged per conflict type so
scheduler spam is avoided.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any, TypedDict, cast

import requests

logger = logging.getLogger(__name__)

# Avoid spamming logs when get_mailgun_outbound_params runs frequently (e.g. scheduler).
_logged_mailgun_conflicts: set[str] = set()


def _warn_mailgun_conflict_once(key: str, msg: str, *args: Any) -> None:
    if key in _logged_mailgun_conflicts:
        return
    _logged_mailgun_conflicts.add(key)
    logger.warning(msg, *args)


class MailgunOutboundParams(TypedDict):
    api_key: str
    domain: str
    from_header: str
    api_base: str


def _coerce_optional_str(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, dict | list | bool):
        return None
    s = str(val).strip()
    return s or None


def get_mailgun_outbound_params() -> MailgunOutboundParams | None:
    """Return Mailgun HTTP API parameters if outbound send is configured.

    Requires ``MAILGUN_API_KEY`` in the environment and a send domain from env or
    ``system_settings`` (see module docstring).
    """
    get_setting: Callable[..., Any] | None
    try:
        from settings import get_system_setting

        get_setting = get_system_setting
    except Exception as e:
        logger.warning("Could not load settings for Mailgun: %s", e)
        get_setting = None

    api_key = _coerce_optional_str(os.getenv("MAILGUN_API_KEY"))

    env_domain_send = _coerce_optional_str(os.getenv("MAILGUN_SEND_DOMAIN"))
    env_domain_legacy = _coerce_optional_str(os.getenv("MAILGUN_DOMAIN"))
    if env_domain_send and env_domain_legacy and env_domain_send != env_domain_legacy:
        _warn_mailgun_conflict_once(
            "env_mailgun_domain_both",
            "Mailgun send domain: MAILGUN_SEND_DOMAIN (%r) and MAILGUN_DOMAIN (%r) are both set "
            "and differ; using MAILGUN_SEND_DOMAIN.",
            env_domain_send,
            env_domain_legacy,
        )
    domain_env = env_domain_send or env_domain_legacy

    db_domain_send: str | None = None
    db_domain_legacy: str | None = None
    if get_setting:
        db_domain_send = _coerce_optional_str(
            get_setting("mailgun_send_domain", default=None)
        )
        db_domain_legacy = _coerce_optional_str(
            get_setting("mailgun_domain", default=None)
        )
    if db_domain_send and db_domain_legacy and db_domain_send != db_domain_legacy:
        _warn_mailgun_conflict_once(
            "db_mailgun_domain_both",
            "Mailgun send domain: system_settings mailgun_send_domain (%r) and mailgun_domain (%r) are "
            "both set and differ; using mailgun_send_domain.",
            db_domain_send,
            db_domain_legacy,
        )
    domain_db = db_domain_send or db_domain_legacy

    if domain_env and domain_db and domain_env != domain_db:
        _warn_mailgun_conflict_once(
            "mailgun_domain_env_vs_db",
            "Mailgun send domain: environment (%r) overrides system_settings (%r); align or remove one "
            "to avoid confusion.",
            domain_env,
            domain_db,
        )
    domain = domain_env or domain_db

    env_from = _coerce_optional_str(os.getenv("MAILGUN_FROM"))
    db_from = (
        _coerce_optional_str(get_setting("mailgun_from", default=None))
        if get_setting
        else None
    )
    if env_from and db_from and env_from != db_from:
        _warn_mailgun_conflict_once(
            "mailgun_from_env_vs_db",
            "Mailgun From: MAILGUN_FROM (%r) overrides system_settings mailgun_from (%r); align or "
            "remove one to avoid confusion.",
            env_from,
            db_from,
        )
    from_header = env_from or db_from
    if not from_header:
        from_header = "Portfolio <noreply@example.com>"

    env_api_base = _coerce_optional_str(os.getenv("MAILGUN_API_BASE"))
    db_api_base = (
        _coerce_optional_str(get_setting("mailgun_api_base", default=None))
        if get_setting
        else None
    )
    default_api_base = "https://api.mailgun.net/v3"
    if env_api_base and db_api_base and env_api_base.rstrip("/") != db_api_base.rstrip("/"):
        _warn_mailgun_conflict_once(
            "mailgun_api_base_env_vs_db",
            "Mailgun API base: MAILGUN_API_BASE (%r) overrides system_settings mailgun_api_base (%r); "
            "align or remove one to avoid confusion.",
            env_api_base,
            db_api_base,
        )
    api_base = env_api_base or db_api_base
    if not api_base:
        api_base = default_api_base

    if not api_key or not domain:
        return None
    return {
        "api_key": api_key,
        "domain": domain,
        "from_header": from_header,
        "api_base": api_base,
    }


def send_mailgun_message(
    to_email: str,
    subject: str,
    html_body: str,
    *,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """POST to Mailgun messages API. Returns parsed JSON or raises on hard failure."""
    params = get_mailgun_outbound_params()
    if not params:
        raise ValueError(
            "Mailgun outbound not configured: need MAILGUN_API_KEY and a send domain "
            "(MAILGUN_SEND_DOMAIN or system_settings mailgun_send_domain)"
        )

    api_key = params["api_key"]
    domain = params["domain"]
    from_header = params["from_header"]
    api_base = params["api_base"]

    url = f"{api_base.rstrip('/')}/{domain}/messages"
    multipart: list[tuple[str, Any]] = [
        ("from", from_header),
        ("to", to_email),
        ("subject", subject),
        ("html", html_body),
    ]
    if tags:
        for tag in tags[:3]:
            multipart.append(("o:tag", tag))

    resp = requests.post(url, auth=("api", api_key), data=multipart, timeout=30)
    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": resp.text}
    if resp.status_code >= 400:
        logger.error("Mailgun error %s: %s", resp.status_code, payload)
        raise RuntimeError(f"Mailgun HTTP {resp.status_code}: {payload}")
    return cast(dict[str, Any], payload)
