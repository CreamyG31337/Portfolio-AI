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
``MAILGUN_DOMAIN``, ``MAILGUN_FROM``, ``MAILGUN_API_BASE``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any, TypedDict, cast

import requests

logger = logging.getLogger(__name__)


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
    domain = _coerce_optional_str(
        os.getenv("MAILGUN_SEND_DOMAIN") or os.getenv("MAILGUN_DOMAIN")
    )
    if not domain and get_setting:
        domain = _coerce_optional_str(
            get_setting("mailgun_send_domain", default=None)
        ) or _coerce_optional_str(get_setting("mailgun_domain", default=None))

    from_header = _coerce_optional_str(os.getenv("MAILGUN_FROM"))
    if not from_header and get_setting:
        from_header = _coerce_optional_str(get_setting("mailgun_from", default=None))
    if not from_header:
        from_header = "Portfolio <noreply@example.com>"

    api_base = _coerce_optional_str(os.getenv("MAILGUN_API_BASE"))
    if not api_base and get_setting:
        api_base = _coerce_optional_str(
            get_setting("mailgun_api_base", default=None)
        )
    if not api_base:
        api_base = "https://api.mailgun.net/v3"

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
