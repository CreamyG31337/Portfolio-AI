#!/usr/bin/env python3
"""Send a synthetic Cloudflare Email Worker newsletter webhook payload."""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import requests


DEFAULT_URL = "http://127.0.0.1:5000/api/webhooks/newsletter"


def _build_raw_email(
    *,
    from_name: str,
    from_address: str,
    to_address: str,
    subject: str,
    body: str,
    message_id: str,
) -> str:
    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_address))
    msg["To"] = to_address
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    msg.set_content(body)
    return msg.as_string()


def main() -> int:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(
        description="POST a synthetic newsletter webhook payload for parser/ingest testing."
    )
    parser.add_argument(
        "--url",
        default=os.getenv("NEWSLETTER_WEBHOOK_URL", DEFAULT_URL),
        help=f"Webhook URL. Defaults to NEWSLETTER_WEBHOOK_URL or {DEFAULT_URL}.",
    )
    parser.add_argument("--from-name", default="Synthetic Research Desk")
    parser.add_argument("--from-address", default="synthetic-newsletter@example.com")
    parser.add_argument("--to", default="newsletter-inbox@example.com")
    parser.add_argument("--subject", default=f"Webhook dry-run test {now} AAPL NVDA")
    parser.add_argument(
        "--body",
        default=(
            "Synthetic Cloudflare webhook test newsletter.\n\n"
            "This should extract $AAPL and $NVDA and prove raw_eml parsing works."
        ),
    )
    parser.add_argument("--message-id", default=make_msgid("newsletter-webhook-test"))
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the row and start background AI. Default is dry_run.",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("NEWSLETTER_WEBHOOK_TEST_TOKEN"),
        help="Dry-run token. Defaults to NEWSLETTER_WEBHOOK_TEST_TOKEN.",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    dry_run = not args.write
    if dry_run and not args.token:
        parser.error("dry-run requires --token or NEWSLETTER_WEBHOOK_TEST_TOKEN")

    raw_eml = _build_raw_email(
        from_name=args.from_name,
        from_address=args.from_address,
        to_address=args.to,
        subject=args.subject,
        body=args.body,
        message_id=args.message_id,
    )
    payload = {
        "from": args.from_address,
        "to": args.to,
        "subject": args.subject,
        "raw_eml": raw_eml,
        "dry_run": dry_run,
    }
    headers = {}
    if dry_run:
        headers["X-Newsletter-Webhook-Test-Token"] = args.token

    response = requests.post(args.url, json=payload, headers=headers, timeout=args.timeout)
    print(f"Status: {response.status_code}")
    try:
        print(response.json())
    except ValueError:
        print(response.text)
    return 0 if 200 <= response.status_code < 300 else 1


if __name__ == "__main__":
    raise SystemExit(main())
