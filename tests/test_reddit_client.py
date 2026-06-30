"""Tests for Reddit OAuth client."""

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

WEB_DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "web_dashboard"
if str(WEB_DASHBOARD_PATH) not in sys.path:
    sys.path.insert(0, str(WEB_DASHBOARD_PATH))


@pytest.fixture(autouse=True)
def _reset_reddit_singleton():
    from reddit_client import reset_reddit_client

    reset_reddit_client()
    yield
    reset_reddit_client()


def test_reddit_oauth_configured_requires_all_fields(monkeypatch):
    from reddit_client import reddit_oauth_configured

    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("REDDIT_USERNAME", raising=False)
    monkeypatch.delenv("REDDIT_PASSWORD", raising=False)
    assert reddit_oauth_configured() is False

    monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    monkeypatch.setenv("REDDIT_USERNAME", "bot")
    monkeypatch.setenv("REDDIT_PASSWORD", "pass")
    assert reddit_oauth_configured() is True


def test_check_reddit_connectivity_not_configured(monkeypatch):
    from reddit_client import RedditClient, check_reddit_connectivity

    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("REDDIT_USERNAME", raising=False)
    monkeypatch.delenv("REDDIT_PASSWORD", raising=False)

    client = RedditClient(min_interval=0)
    sample_payload = {
        "data": {"children": [{"data": {"title": "test", "subreddit": "wallstreetbets"}}]}
    }

    class FakeResult:
        status_code = 200
        payload = sample_payload
        used_oauth = False
        used_rss = True
        rate_limited = False

    client._get_json_via_rss = lambda path, params: FakeResult()  # type: ignore[method-assign]
    status = check_reddit_connectivity(client)

    assert status.ok is True
    assert status.oauth_configured is False
    assert "RSS" in status.message


def test_check_reddit_connectivity_ok(monkeypatch):
    from reddit_client import RedditClient, check_reddit_connectivity

    monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    monkeypatch.setenv("REDDIT_USERNAME", "bot")
    monkeypatch.setenv("REDDIT_PASSWORD", "pass")

    client = RedditClient(min_interval=0)
    token_response = MagicMock()
    token_response.status_code = 200
    token_response.json.return_value = {"access_token": "tok123", "expires_in": 3600}

    listing_response = MagicMock()
    listing_response.status_code = 200
    listing_response.headers = {}
    listing_response.json.return_value = {"data": {"children": [{"data": {"title": "test"}}]}}

    with patch("reddit_client.requests.post", return_value=token_response), patch(
        "reddit_client.requests.get", return_value=listing_response
    ):
        status = check_reddit_connectivity(client)

    assert status.ok is True
    assert status.oauth_configured is True
    assert status.rate_limited is False


def test_check_reddit_connectivity_detects_429(monkeypatch):
    from reddit_client import RedditClient, check_reddit_connectivity

    monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    monkeypatch.setenv("REDDIT_USERNAME", "bot")
    monkeypatch.setenv("REDDIT_PASSWORD", "pass")

    client = RedditClient(min_interval=0)
    token_response = MagicMock()
    token_response.status_code = 200
    token_response.json.return_value = {"access_token": "tok123", "expires_in": 3600}

    rate_limited = MagicMock()
    rate_limited.status_code = 429
    rate_limited.headers = {"Retry-After": "5"}

    with patch("reddit_client.requests.post", return_value=token_response), patch(
        "reddit_client.requests.get", return_value=rate_limited
    ):
        status = check_reddit_connectivity(client)

    assert status.ok is False
    assert status.rate_limited is True
    assert status.status_code == 429


def test_check_reddit_connectivity_with_retry_waits_for_rss_cooldown(monkeypatch):
    from reddit_client import (
        RedditClient,
        RedditConnectivityStatus,
        check_reddit_connectivity_with_retry,
    )
    from reddit_rss import reset_rss_rate_limiter

    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("REDDIT_USERNAME", raising=False)
    monkeypatch.delenv("REDDIT_PASSWORD", raising=False)

    reset_rss_rate_limiter()
    client = RedditClient(min_interval=0)
    calls: list[int] = []

    def fake_check(_client=None):
        calls.append(1)
        if len(calls) == 1:
            return RedditConnectivityStatus(
                ok=False,
                oauth_configured=False,
                status_code=429,
                rate_limited=True,
                auth_failed=False,
                message="Reddit rate limited (429) during connectivity probe",
            )
        return RedditConnectivityStatus(
            ok=True,
            oauth_configured=False,
            status_code=200,
            rate_limited=False,
            auth_failed=False,
            message="Reddit RSS feeds reachable (no API app required)",
        )

    with patch("reddit_client.check_reddit_connectivity", side_effect=fake_check), patch(
        "reddit_rss.get_rss_rate_limiter"
    ) as limiter_mock, patch("reddit_client.time.sleep") as sleep_mock:
        limiter_mock.return_value.seconds_until_ready.return_value = 5.0
        status = check_reddit_connectivity_with_retry(client)

    assert status.ok is True
    assert len(calls) == 2
    sleep_mock.assert_called_once_with(5.0)


def test_get_json_uses_oauth_base_when_configured(monkeypatch):
    from reddit_client import RedditClient

    monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    monkeypatch.setenv("REDDIT_USERNAME", "bot")
    monkeypatch.setenv("REDDIT_PASSWORD", "pass")

    client = RedditClient(min_interval=0)

    token_response = MagicMock()
    token_response.status_code = 200
    token_response.json.return_value = {"access_token": "tok123", "expires_in": 3600}

    listing_response = MagicMock()
    listing_response.status_code = 200
    listing_response.headers = {}
    listing_response.json.return_value = {"data": {"children": []}}

    with patch("reddit_client.requests.post", return_value=token_response) as post_mock, patch(
        "reddit_client.requests.get", return_value=listing_response
    ) as get_mock:
        result = client.get_json("/r/wallstreetbets/hot", params={"limit": 5})

    assert result.status_code == 200
    assert result.used_oauth is True
    assert result.payload == {"data": {"children": []}}
    assert post_mock.call_count == 1
    get_mock.assert_called_once()
    called_url = get_mock.call_args.args[0]
    assert called_url.startswith("https://oauth.reddit.com/")


def test_get_json_reports_rate_limit_without_payload(monkeypatch):
    from reddit_client import RedditClient
    from reddit_rss import RedditRssFetchResult

    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("REDDIT_USERNAME", raising=False)
    monkeypatch.delenv("REDDIT_PASSWORD", raising=False)

    client = RedditClient(min_interval=0)

    with patch(
        "reddit_client.fetch_reddit_rss",
        return_value=RedditRssFetchResult(status_code=429, items=[], rate_limited=True),
    ):
        result = client.get_json("/search", params={"q": "$AAPL"})

    assert result.rate_limited is True
    assert result.payload is None
    assert result.used_rss is True


def test_get_json_logs_rate_limit_warning(monkeypatch, caplog):
    from reddit_client import RedditClient
    from reddit_rss import RedditRssFetchResult

    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("REDDIT_USERNAME", raising=False)
    monkeypatch.delenv("REDDIT_PASSWORD", raising=False)

    client = RedditClient(min_interval=0)

    with caplog.at_level(logging.WARNING), patch(
        "reddit_client.fetch_reddit_rss",
        return_value=RedditRssFetchResult(status_code=429, items=[], rate_limited=True),
    ):
        client.get_json("/search", params={"q": "$AAPL"})

    assert any("rate limited" in record.message.lower() for record in caplog.records)
    assert any("RSS" in record.message or "/search" in record.message for record in caplog.records)


def test_fetch_reddit_sentiment_logs_degraded_when_all_429(monkeypatch, caplog):
    from social_service import SocialSentimentService
    from reddit_client import RedditRequestResult

    service = SocialSentimentService.__new__(SocialSentimentService)
    service.ollama = None

    class FakeReddit:
        oauth_enabled = True
        rss_enabled = False

        @staticmethod
        def check_robots_allowed(_url: str) -> bool:
            return True

        @staticmethod
        def get_json(_path: str, *, params=None):
            return RedditRequestResult(
                status_code=429,
                payload=None,
                used_oauth=True,
                rate_limited=True,
            )

    service.reddit = FakeReddit()

    with caplog.at_level(logging.ERROR):
        result = service.fetch_reddit_sentiment("NVDA", max_duration=30)

    assert result["volume"] == 0
    assert "429" in result["reddit_error_codes"]
    assert any("rate limited" in record.message.lower() for record in caplog.records)
