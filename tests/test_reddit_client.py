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
def _reset_reddit_singleton(monkeypatch):
    from reddit_client import reset_reddit_client
    import reddit_cookies as reddit_cookies_mod

    monkeypatch.delenv("REDDIT_COOKIES_JSON", raising=False)
    monkeypatch.delenv("REDDIT_COOKIES_FILE", raising=False)
    monkeypatch.delenv("REDDIT_USERNAME", raising=False)
    monkeypatch.delenv("REDDIT_PASSWORD", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    # Prevent local dev reddit_cookies.json from affecting unit tests.
    monkeypatch.setattr(
        reddit_cookies_mod,
        "_SHARED_COOKIE_PATH",
        Path("/nonexistent/shared/reddit_cookies.json"),
    )
    monkeypatch.setattr(
        reddit_cookies_mod,
        "_LOCAL_COOKIE_PATH",
        Path("/nonexistent/local/reddit_cookies.json"),
    )
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
                cookie_configured=False,
                status_code=429,
                rate_limited=True,
                auth_failed=False,
                message="Reddit rate limited (429) during connectivity probe",
            )
        return RedditConnectivityStatus(
            ok=True,
            oauth_configured=False,
            cookie_configured=False,
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
        cookie_enabled = False
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


def test_get_json_uses_cookie_auth_when_configured(monkeypatch):
    from reddit_client import RedditClient

    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("REDDIT_USERNAME", raising=False)
    monkeypatch.delenv("REDDIT_PASSWORD", raising=False)
    monkeypatch.setenv(
        "REDDIT_COOKIES_JSON",
        '{"reddit_session": "abc123", "token_v2": "def456"}',
    )

    client = RedditClient(min_interval=0)
    assert client.cookie_enabled is True
    assert client.rss_enabled is False

    listing_response = MagicMock()
    listing_response.status_code = 200
    listing_response.headers = {}
    listing_response.json.return_value = {"data": {"children": [{"data": {"title": "test"}}]}}

    with patch.object(client._cookie_session, "get", return_value=listing_response) as get_mock:
        result = client.get_json("/r/pennystocks/hot", params={"limit": 5})

    assert result.status_code == 200
    assert result.used_cookies is True
    assert result.used_rss is False
    get_mock.assert_called_once()
    called_url = get_mock.call_args.args[0]
    assert called_url == "https://www.reddit.com/r/pennystocks/hot.json"


def test_cookie_request_falls_back_to_flaresolverr_on_403(monkeypatch):
    from reddit_client import RedditClient

    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("REDDIT_USERNAME", raising=False)
    monkeypatch.delenv("REDDIT_PASSWORD", raising=False)
    monkeypatch.setenv("REDDIT_COOKIES_JSON", '{"reddit_session": "abc123"}')

    client = RedditClient(min_interval=0)

    blocked = MagicMock()
    blocked.status_code = 403
    blocked.headers = {}

    fs_payload = {"data": {"children": [{"data": {"title": "via-flare"}}]}}
    fake_fetch_client = MagicMock()
    fake_fetch_client.fetch_json_via_flaresolverr.return_value = fs_payload

    with patch.object(client._cookie_session, "get", return_value=blocked), patch(
        "web_fetch_client.get_flaresolverr_url", return_value="http://flare.test:8191"
    ), patch("web_fetch_client.get_web_fetch_client", return_value=fake_fetch_client):
        result = client.get_json("/r/pennystocks/hot", params={"limit": 5, "t": "day"})

    assert result.status_code == 200
    assert result.used_cookies is True
    assert result.payload == fs_payload
    called_url = fake_fetch_client.fetch_json_via_flaresolverr.call_args.args[0]
    assert called_url.startswith("https://www.reddit.com/r/pennystocks/hot.json?")
    assert fake_fetch_client.fetch_json_via_flaresolverr.call_args.kwargs["cookies"] == {
        "reddit_session": "abc123"
    }


def test_cookie_request_no_flaresolverr_returns_403(monkeypatch):
    from reddit_client import RedditClient

    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("REDDIT_USERNAME", raising=False)
    monkeypatch.delenv("REDDIT_PASSWORD", raising=False)
    monkeypatch.setenv("REDDIT_COOKIES_JSON", '{"reddit_session": "abc123"}')

    client = RedditClient(min_interval=0)

    blocked = MagicMock()
    blocked.status_code = 403
    blocked.headers = {}

    with patch.object(client._cookie_session, "get", return_value=blocked), patch(
        "web_fetch_client.get_flaresolverr_url", return_value=""
    ):
        result = client.get_json("/r/pennystocks/hot", params={"limit": 5})

    assert result.status_code == 403
    assert result.used_cookies is True


def test_check_reddit_connectivity_rss_blocked_message(monkeypatch):
    from reddit_client import RedditClient, check_reddit_connectivity

    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("REDDIT_USERNAME", raising=False)
    monkeypatch.delenv("REDDIT_PASSWORD", raising=False)

    client = RedditClient(min_interval=0)

    class FakeResult:
        status_code = 403
        payload = None
        used_oauth = False
        used_rss = True
        used_cookies = False
        rate_limited = False

    client._get_json_via_rss = lambda path, params: FakeResult()  # type: ignore[method-assign]
    status = check_reddit_connectivity(client)

    assert status.ok is False
    assert "RSS blocked" in status.message
    assert status.auth_failed is False


def test_cookie_mode_enabled_with_username_password(monkeypatch):
    from reddit_client import RedditClient
    from reddit_cookies import reddit_cookie_configured

    monkeypatch.setenv("REDDIT_USERNAME", "myuser")
    monkeypatch.setenv("REDDIT_PASSWORD", "mypass")

    assert reddit_cookie_configured() is True
    client = RedditClient(min_interval=0)
    assert client.cookie_enabled is True
    assert client.rss_enabled is False


def test_password_login_used_when_no_cookie_file(monkeypatch):
    from reddit_client import RedditClient

    monkeypatch.setenv("REDDIT_USERNAME", "myuser")
    monkeypatch.setenv("REDDIT_PASSWORD", "mypass")

    client = RedditClient(min_interval=0)
    listing_response = MagicMock()
    listing_response.status_code = 200
    listing_response.headers = {}
    listing_response.json.return_value = {"data": {"children": [{"data": {"title": "test"}}]}}

    with patch(
        "reddit_login.login_with_password",
        return_value={"reddit_session": "sess", "token_v2": "tok"},
    ) as login_mock, patch.object(client._cookie_session, "get", return_value=listing_response):
        result = client.get_json("/r/pennystocks/hot", params={"limit": 3})

    login_mock.assert_called_once()
    assert result.status_code == 200
    assert result.used_cookies is True
