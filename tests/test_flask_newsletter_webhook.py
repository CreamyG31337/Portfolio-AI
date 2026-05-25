from __future__ import annotations

from typing import Any

from newsletter_service import NewsletterService


def _raw_email(
    *,
    from_header: str = "Research Desk <research@example.com>",
    subject: str = "Fwd: Cloudflare webhook test AAPL",
    message_id: str = "<cf-webhook-test-1@example.com>",
    body: str = "AAPL and NVDA are mentioned in this test newsletter.",
) -> str:
    return "\n".join(
        [
            f"From: {from_header}",
            "To: inbound@example.com",
            f"Subject: {subject}",
            f"Message-ID: {message_id}",
            "MIME-Version: 1.0",
            'Content-Type: text/plain; charset="utf-8"',
            "Content-Transfer-Encoding: 7bit",
            "",
            body,
        ]
    )


def _webhook_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "from": "cloudflare-envelope@example.com",
        "to": "newsletter-inbox@example.com",
        "subject": "Fwd: Cloudflare webhook test AAPL",
        "raw_eml": _raw_email(),
    }
    payload.update(overrides)
    return payload


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


def test_newsletter_webhook_rejects_missing_cloudflare_fields(client) -> None:
    response = client.post(
        "/api/webhooks/newsletter",
        json={
            "from": "sender@example.com",
            "to": "newsletter-inbox@example.com",
            "subject": "Missing raw email",
        },
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "Missing required fields"}


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
