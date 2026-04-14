"""Send transactional email via Mailgun HTTP API."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


def send_mailgun_message(
    to_email: str,
    subject: str,
    html_body: str,
    *,
    tags: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """POST to Mailgun messages API. Returns parsed JSON or raises on hard failure."""
    api_key = os.getenv("MAILGUN_API_KEY")
    domain = os.getenv("MAILGUN_SEND_DOMAIN") or os.getenv("MAILGUN_DOMAIN")
    from_header = os.getenv("MAILGUN_FROM", "Portfolio <noreply@example.com>")
    api_base = os.getenv("MAILGUN_API_BASE", "https://api.mailgun.net/v3")

    if not api_key or not domain:
        raise ValueError("MAILGUN_API_KEY and MAILGUN_SEND_DOMAIN (or MAILGUN_DOMAIN) are required")

    url = f"{api_base.rstrip('/')}/{domain}/messages"
    data: Dict[str, Any] = {
        "from": from_header,
        "to": to_email,
        "subject": subject,
        "html": html_body,
    }
    if tags:
        for i, tag in enumerate(tags[:3]):
            data[f"o:tag"] = tag if i == 0 else data.get("o:tag")  # Mailgun accepts repeated o:tag
        # Mailgun expects multiple o:tag fields — requests handles list of tuples
    files = None
    # Use multipart with list of tuples for repeated keys
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
    return payload
