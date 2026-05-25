from __future__ import annotations

from typing import Any

from newsletter_service import NewsletterService


def _raw_email(
    *,
    from_header: str = "Research Desk <research@example.com>",
    subject: str = "Fwd: Cloudflare webhook test AAPL",
    message_id: str = "<cf-webhook-test-1@example.com>",
    body: str = "AAPL and NVDA are mentioned in this test newsletter.",
    date_header: str | None = None,
) -> str:
    headers = [
        f"From: {from_header}",
        "To: inbound@example.com",
        f"Subject: {subject}",
        f"Message-ID: {message_id}",
    ]
    if date_header:
        headers.append(f"Date: {date_header}")
    headers.extend(
        [
            "MIME-Version: 1.0",
            'Content-Type: text/plain; charset="utf-8"',
            "Content-Transfer-Encoding: 7bit",
            "",
            body,
        ]
    )
    return "\n".join(headers)


def _webhook_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "from": "cloudflare-envelope@example.com",
        "to": "newsletter-inbox@example.com",
        "subject": "Fwd: Cloudflare webhook test AAPL",
        "raw_eml": _raw_email(),
    }
    payload.update(overrides)
    return payload


def _raw_multipart_email(
    *,
    from_header: str = "Research Desk <research@example.com>",
    subject: str = "Fwd: Multipart newsletter AAPL",
    message_id: str = "<cf-webhook-multipart-1@example.com>",
    plain_body: str = "AAPL plain text body.",
    html_body: str = "<html><body><p>AAPL <b>HTML</b> body.</p></body></html>",
) -> str:
    """Build a multipart/alternative email with both text/plain and text/html parts."""
    boundary = "newsletter-multipart-alt"
    return "\n".join(
        [
            f"From: {from_header}",
            "To: inbound@example.com",
            f"Subject: {subject}",
            f"Message-ID: {message_id}",
            "MIME-Version: 1.0",
            f'Content-Type: multipart/alternative; boundary="{boundary}"',
            "",
            f"--{boundary}",
            'Content-Type: text/plain; charset="utf-8"',
            "Content-Transfer-Encoding: 7bit",
            "",
            plain_body,
            f"--{boundary}",
            'Content-Type: text/html; charset="utf-8"',
            "Content-Transfer-Encoding: 7bit",
            "",
            html_body,
            f"--{boundary}--",
        ]
    )


def _raw_email_with_attachments(*attached_messages: str) -> str:
    boundary = "gmail-forwarded-newsletters"
    lines = [
        "From: Lance Colton <lance.colton@gmail.com>",
        "To: inbound@example.com",
        "Subject: Fwd: newsletters as attachments",
        "MIME-Version: 1.0",
        f'Content-Type: multipart/mixed; boundary="{boundary}"',
        "",
        f"--{boundary}",
        'Content-Type: text/plain; charset="utf-8"',
        "",
        "Forwarded newsletters attached.",
    ]
    for idx, attached in enumerate(attached_messages, start=1):
        lines.extend(
            [
                f"--{boundary}",
                "Content-Type: message/rfc822",
                f'Content-Disposition: attachment; filename="newsletter-{idx}.eml"',
                "",
                attached,
            ]
        )
    lines.append(f"--{boundary}--")
    return "\n".join(lines)


def _patch_service_side_effects(monkeypatch) -> None:
    monkeypatch.setattr(
        NewsletterService,
        "extract_article_url_with_llm_fallback",
        lambda self, **kwargs: None,
    )
    monkeypatch.setattr(
        NewsletterService,
        "get_known_tickers_for_validation",
        lambda self: {"AAPL", "NVDA"},
    )


def test_newsletter_webhook_saves_cloudflare_raw_email_and_starts_ai(
    client,
    monkeypatch,
) -> None:
    _patch_service_side_effects(monkeypatch)
    saved_rows: list[dict[str, Any]] = []
    threads: list[dict[str, Any]] = []

    class FakeRepo:
        def find_recent_duplicate_by_body(self, body_plain, days=30):
            return None

        def save_newsletter(self, **kwargs):
            saved_rows.append(kwargs)
            return "11111111-1111-1111-1111-111111111111"

    class FakeThread:
        def __init__(self, *, target, args, daemon, name):
            threads.append(
                {
                    "target": target,
                    "args": args,
                    "daemon": daemon,
                    "name": name,
                    "started": False,
                }
            )

        def start(self):
            threads[-1]["started"] = True

    monkeypatch.setattr("newsletter_repository.NewsletterRepository", FakeRepo)
    monkeypatch.setattr("threading.Thread", FakeThread)

    response = client.post("/api/webhooks/newsletter", json=_webhook_payload())

    assert response.status_code == 200
    assert response.get_json()["id"] == "11111111-1111-1111-1111-111111111111"
    assert saved_rows
    saved = saved_rows[0]
    assert saved["sender"] == "research@example.com"
    assert saved["sender_name"] == "Research Desk"
    assert saved["recipient"] == "newsletter-inbox@example.com"
    assert saved["subject"] == "Cloudflare webhook test AAPL"
    assert saved["message_id"] == "<cf-webhook-test-1@example.com>"
    assert "AAPL and NVDA" in saved["body_plain"]
    assert saved["tickers"] == ["AAPL", "NVDA"]
    assert threads[0]["args"] == ("11111111-1111-1111-1111-111111111111",)
    assert threads[0]["daemon"] is True
    assert threads[0]["started"] is True


def test_newsletter_webhook_extracts_both_html_and_plain_from_multipart(
    client,
    monkeypatch,
) -> None:
    """Multipart/alternative emails must populate both body_plain and body_html.

    Regression test: prior to this fix the webhook hard-coded body_html=None,
    which meant the dashboard could only show plain text even when the original
    email had a rich HTML part.
    """
    _patch_service_side_effects(monkeypatch)
    saved_rows: list[dict[str, Any]] = []

    class FakeRepo:
        def find_recent_duplicate_by_body(self, body_plain, days=30):
            return None

        def save_newsletter(self, **kwargs):
            saved_rows.append(kwargs)
            return "22222222-2222-2222-2222-222222222222"

    class FakeThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr("newsletter_repository.NewsletterRepository", FakeRepo)
    monkeypatch.setattr("threading.Thread", FakeThread)

    raw_eml = _raw_multipart_email(
        plain_body="AAPL plain-text body.",
        html_body="<html><body><p>AAPL <b>HTML</b> body.</p></body></html>",
    )
    response = client.post(
        "/api/webhooks/newsletter",
        json=_webhook_payload(raw_eml=raw_eml),
    )

    assert response.status_code == 200
    assert len(saved_rows) == 1
    saved = saved_rows[0]
    assert "AAPL plain-text body." in (saved.get("body_plain") or "")
    body_html = saved.get("body_html") or ""
    assert "<b>HTML</b>" in body_html
    assert "<p>AAPL" in body_html


def test_newsletter_webhook_saves_gmail_forwarded_rfc822_attachments(
    client,
    monkeypatch,
) -> None:
    _patch_service_side_effects(monkeypatch)
    saved_rows: list[dict[str, Any]] = []
    threads: list[dict[str, Any]] = []

    class FakeRepo:
        def find_recent_duplicate_by_body(self, body_plain, days=30):
            return None

        def save_newsletter(self, **kwargs):
            saved_rows.append(kwargs)
            return f"newsletter-{len(saved_rows)}"

    class FakeThread:
        def __init__(self, *, target, args, daemon, name):
            threads.append(
                {
                    "target": target,
                    "args": args,
                    "daemon": daemon,
                    "name": name,
                    "started": False,
                }
            )

        def start(self):
            threads[-1]["started"] = True

    monkeypatch.setattr("newsletter_repository.NewsletterRepository", FakeRepo)
    monkeypatch.setattr("threading.Thread", FakeThread)

    raw_eml = _raw_email_with_attachments(
        _raw_email(
            from_header="Morning Brief <brief@example.com>",
            subject="Fwd: Morning Brief AAPL",
            message_id="<batch-1@example.com>",
            body="AAPL and NVDA batch item one.",
        ),
        _raw_email(
            from_header="Opening Bell <bell@example.com>",
            subject="Opening Bell NVDA",
            message_id="<batch-2@example.com>",
            body="NVDA batch item two.",
        ),
        _raw_email(
            from_header="Market Desk <market@example.com>",
            subject="Market Desk AAPL",
            message_id="<batch-3@example.com>",
            body="AAPL batch item three.",
        ),
    )

    response = client.post(
        "/api/webhooks/newsletter",
        json=_webhook_payload(subject="Fwd: newsletters as attachments", raw_eml=raw_eml),
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "batch"
    assert payload["count"] == 3
    assert payload["saved"] == 3
    assert payload["duplicates"] == 0
    assert payload["errors"] == 0
    assert [item["id"] for item in payload["items"]] == [
        "newsletter-1",
        "newsletter-2",
        "newsletter-3",
    ]
    assert [row["sender"] for row in saved_rows] == [
        "brief@example.com",
        "bell@example.com",
        "market@example.com",
    ]
    assert [row["subject"] for row in saved_rows] == [
        "Morning Brief AAPL",
        "Opening Bell NVDA",
        "Market Desk AAPL",
    ]
    assert [row["message_id"] for row in saved_rows] == [
        "<batch-1@example.com>",
        "<batch-2@example.com>",
        "<batch-3@example.com>",
    ]
    assert len(threads) == 3
    assert all(thread["started"] for thread in threads)


def test_newsletter_webhook_batch_deduplicates_each_attached_email(
    client,
    monkeypatch,
) -> None:
    _patch_service_side_effects(monkeypatch)
    saved_rows: list[dict[str, Any]] = []
    threads: list[dict[str, Any]] = []

    class FakeRepo:
        def find_recent_duplicate_by_body(self, body_plain, days=30):
            if body_plain and "already saved" in body_plain:
                return "existing-newsletter-id"
            return None

        def save_newsletter(self, **kwargs):
            saved_rows.append(kwargs)
            return "new-newsletter-id"

    class FakeThread:
        def __init__(self, *, target, args, daemon, name):
            threads.append({"args": args, "daemon": daemon, "name": name, "started": False})

        def start(self):
            threads[-1]["started"] = True

    monkeypatch.setattr("newsletter_repository.NewsletterRepository", FakeRepo)
    monkeypatch.setattr("threading.Thread", FakeThread)

    raw_eml = _raw_email_with_attachments(
        _raw_email(
            subject="Already Saved AAPL",
            message_id="<duplicate@example.com>",
            body="AAPL already saved.",
        ),
        _raw_email(
            subject="Fresh NVDA",
            message_id="<fresh@example.com>",
            body="Fresh NVDA newsletter.",
        ),
    )

    response = client.post(
        "/api/webhooks/newsletter",
        json=_webhook_payload(subject="Fwd: newsletters as attachments", raw_eml=raw_eml),
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "batch"
    assert payload["count"] == 2
    assert payload["saved"] == 1
    assert payload["duplicates"] == 1
    assert payload["errors"] == 0
    assert payload["items"][0]["status"] == "duplicate"
    assert payload["items"][0]["duplicate_of"] == "existing-newsletter-id"
    assert payload["items"][1]["status"] == "success"
    assert payload["items"][1]["id"] == "new-newsletter-id"
    assert len(saved_rows) == 1
    assert saved_rows[0]["subject"] == "Fresh NVDA"
    assert len(threads) == 1
    assert threads[0]["args"] == ("new-newsletter-id",)
    assert threads[0]["started"] is True


def test_newsletter_webhook_decodes_rfc2047_forwarded_subject(
    client,
    monkeypatch,
) -> None:
    _patch_service_side_effects(monkeypatch)
    saved_rows: list[dict[str, Any]] = []

    class FakeRepo:
        def find_recent_duplicate_by_body(self, body_plain, days=30):
            return None

        def save_newsletter(self, **kwargs):
            saved_rows.append(kwargs)
            return "11111111-1111-1111-1111-111111111111"

    class FakeThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr("newsletter_repository.NewsletterRepository", FakeRepo)
    monkeypatch.setattr("threading.Thread", FakeThread)

    encoded_subject = "=?UTF-8?Q?Fwd=3A_=F0=9F=94=94Opening_Bell_Daily=3A_Trump=27s_Quantum_Stocks?="
    response = client.post(
        "/api/webhooks/newsletter",
        json=_webhook_payload(
            subject=encoded_subject,
            raw_eml=_raw_email(
                from_header="Lance Colton <lance.colton@gmail.com>",
                subject=encoded_subject,
            ),
        ),
    )

    assert response.status_code == 200
    assert saved_rows[0]["sender"] == "lance.colton@gmail.com"
    assert saved_rows[0]["sender_name"] == "Lance Colton"
    assert saved_rows[0]["subject"] == "🔔Opening Bell Daily: Trump's Quantum Stocks"


def test_newsletter_webhook_drops_duplicate_body_without_saving_or_starting_ai(
    client,
    monkeypatch,
) -> None:
    _patch_service_side_effects(monkeypatch)

    class FakeRepo:
        def find_recent_duplicate_by_body(self, body_plain, days=30):
            assert body_plain and "AAPL and NVDA" in body_plain
            return "existing-newsletter-id"

        def save_newsletter(self, **kwargs):
            raise AssertionError("duplicate path must not save")

    class ForbiddenThread:
        def __init__(self, *args, **kwargs):
            raise AssertionError("duplicate path must not start background AI")

    monkeypatch.setattr("newsletter_repository.NewsletterRepository", FakeRepo)
    monkeypatch.setattr("threading.Thread", ForbiddenThread)

    response = client.post("/api/webhooks/newsletter", json=_webhook_payload())

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "duplicate"
    assert body["duplicate_of"] == "existing-newsletter-id"


def test_newsletter_webhook_rejects_missing_raw_eml(client) -> None:
    response = client.post(
        "/api/webhooks/newsletter",
        json={
            "from": "sender@example.com",
            "to": "newsletter-inbox@example.com",
            "subject": "Missing raw email",
        },
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "Missing required field: raw_eml"}


def test_newsletter_webhook_uses_original_email_date_for_received_at(
    client,
    monkeypatch,
) -> None:
    """The original newsletter's Date header should land in received_at, not
    the time we processed the forwarded webhook payload."""
    _patch_service_side_effects(monkeypatch)
    saved_rows: list[dict[str, Any]] = []

    class FakeRepo:
        def find_recent_duplicate_by_body(self, body_plain, days=30):
            return None

        def save_newsletter(self, **kwargs):
            saved_rows.append(kwargs)
            return "11111111-1111-1111-1111-111111111111"

    class FakeThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr("newsletter_repository.NewsletterRepository", FakeRepo)
    monkeypatch.setattr("threading.Thread", FakeThread)

    raw_eml = _raw_email(date_header="Fri, 23 May 2026 14:05:11 -0700")
    response = client.post(
        "/api/webhooks/newsletter",
        json=_webhook_payload(raw_eml=raw_eml),
    )

    assert response.status_code == 200
    from datetime import datetime, timezone

    received_at = saved_rows[0]["received_at"]
    assert isinstance(received_at, datetime)
    expected = datetime(2026, 5, 23, 21, 5, 11, tzinfo=timezone.utc)
    assert received_at.astimezone(timezone.utc) == expected


def test_newsletter_webhook_batch_uses_each_attached_email_date(
    client,
    monkeypatch,
) -> None:
    """Each attached email in a Gmail batch keeps its own original Date."""
    _patch_service_side_effects(monkeypatch)
    saved_rows: list[dict[str, Any]] = []

    class FakeRepo:
        def find_recent_duplicate_by_body(self, body_plain, days=30):
            return None

        def save_newsletter(self, **kwargs):
            saved_rows.append(kwargs)
            return f"newsletter-{len(saved_rows)}"

    class FakeThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr("newsletter_repository.NewsletterRepository", FakeRepo)
    monkeypatch.setattr("threading.Thread", FakeThread)

    raw_eml = _raw_email_with_attachments(
        _raw_email(
            message_id="<batch-a@example.com>",
            body="AAPL batch a",
            date_header="Mon, 18 May 2026 09:30:00 -0400",
        ),
        _raw_email(
            message_id="<batch-b@example.com>",
            body="NVDA batch b",
            date_header="Tue, 19 May 2026 16:45:00 +0000",
        ),
    )

    response = client.post(
        "/api/webhooks/newsletter",
        json=_webhook_payload(raw_eml=raw_eml),
    )

    assert response.status_code == 200
    from datetime import datetime, timezone

    assert len(saved_rows) == 2
    assert saved_rows[0]["received_at"].astimezone(timezone.utc) == datetime(
        2026, 5, 18, 13, 30, 0, tzinfo=timezone.utc
    )
    assert saved_rows[1]["received_at"].astimezone(timezone.utc) == datetime(
        2026, 5, 19, 16, 45, 0, tzinfo=timezone.utc
    )


def test_newsletter_webhook_accepts_payload_with_empty_subject(
    client,
    monkeypatch,
) -> None:
    """Gmail's 'Forward as attachments' often omits the outer Subject header.

    The webhook must still process such payloads using the inner MIME headers
    (or defaults) instead of returning 400.
    """
    _patch_service_side_effects(monkeypatch)
    saved_rows: list[dict[str, Any]] = []
    threads: list[dict[str, Any]] = []

    class FakeRepo:
        def find_recent_duplicate_by_body(self, body_plain, days=30):
            return None

        def save_newsletter(self, **kwargs):
            saved_rows.append(kwargs)
            return "11111111-1111-1111-1111-111111111111"

    class FakeThread:
        def __init__(self, *, target, args, daemon, name):
            threads.append({"args": args, "daemon": daemon, "name": name, "started": False})

        def start(self):
            threads[-1]["started"] = True

    monkeypatch.setattr("newsletter_repository.NewsletterRepository", FakeRepo)
    monkeypatch.setattr("threading.Thread", FakeThread)

    payload = _webhook_payload(subject="")
    response = client.post("/api/webhooks/newsletter", json=payload)

    assert response.status_code == 200
    assert saved_rows
    assert saved_rows[0]["subject"] == "Cloudflare webhook test AAPL"
    assert threads[0]["started"] is True


def test_newsletter_webhook_dry_run_requires_test_token(client, monkeypatch) -> None:
    monkeypatch.setenv("NEWSLETTER_WEBHOOK_TEST_TOKEN", "expected-token")

    response = client.post(
        "/api/webhooks/newsletter",
        json=_webhook_payload(dry_run=True),
        headers={"X-Newsletter-Webhook-Test-Token": "wrong-token"},
    )

    assert response.status_code == 403
    assert response.get_json() == {"error": "Invalid test token"}


def test_newsletter_webhook_dry_run_parses_without_writing_or_starting_ai(
    client,
    monkeypatch,
) -> None:
    monkeypatch.setenv("NEWSLETTER_WEBHOOK_TEST_TOKEN", "expected-token")
    _patch_service_side_effects(monkeypatch)

    class ForbiddenRepo:
        def save_newsletter(self, **kwargs):
            raise AssertionError("dry_run must not save newsletter rows")

    class ForbiddenThread:
        def __init__(self, *args, **kwargs):
            raise AssertionError("dry_run must not start background AI threads")

    monkeypatch.setattr("newsletter_repository.NewsletterRepository", ForbiddenRepo)
    monkeypatch.setattr("threading.Thread", ForbiddenThread)

    response = client.post(
        "/api/webhooks/newsletter",
        json=_webhook_payload(dry_run="true"),
        headers={"X-Newsletter-Webhook-Test-Token": "expected-token"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "dry_run"
    assert payload["parsed"] == {
        "sender": "research@example.com",
        "sender_name": "Research Desk",
        "recipient": "newsletter-inbox@example.com",
        "subject": "Cloudflare webhook test AAPL",
        "message_id": "<cf-webhook-test-1@example.com>",
        "body_plain_chars": 52,
        "has_body_plain": True,
    }
    assert payload["tickers"] == ["AAPL", "NVDA"]
