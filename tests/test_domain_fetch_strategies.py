"""Tests for domain-specific publisher fetch strategies (header/cookie presets)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from web_dashboard import research_utils
from web_dashboard.domain_fetch_strategies import (
    LIVE_CANARY_MIN_CONTENT_LEN,
    apply_domain_fetch_headers,
    match_domain_fetch_strategy,
    normalize_hostname,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "domain_fetch"
BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 TestBrowser",
    "Accept": "text/html",
}


class TestStrategyMatching:
    def test_nytimes_matches_googlebot_strategy(self) -> None:
        strategy = match_domain_fetch_strategy(
            "https://www.nytimes.com/2024/03/15/business/markets.html"
        )
        assert strategy is not None
        assert strategy.id == "nytimes_googlebot"

    def test_time_com_shares_nytimes_strategy(self) -> None:
        strategy = match_domain_fetch_strategy("https://time.com/7123456/article/")
        assert strategy is not None
        assert strategy.id == "nytimes_googlebot"

    def test_ft_matches_social_referer_strategy(self) -> None:
        strategy = match_domain_fetch_strategy(
            "https://www.ft.com/content/5348ec64-010e-40f4-a27e-6d1252a0c537"
        )
        assert strategy is not None
        assert strategy.id == "ft_social_referer"

    def test_unrelated_domain_has_no_strategy(self) -> None:
        assert match_domain_fetch_strategy("https://finance.yahoo.com/news/foo") is None

    def test_normalize_hostname_strips_www_and_port(self) -> None:
        assert normalize_hostname("https://WWW.Example.COM:443/path") == "example.com"


class TestHeaderApplication:
    def test_nytimes_overrides_user_agent_and_sets_cookies(self) -> None:
        headers = apply_domain_fetch_headers(
            BASE_HEADERS,
            "https://www.nytimes.com/2024/03/15/business/markets.html",
        )
        assert "Googlebot" in headers["User-Agent"]
        assert headers["Referer"] == "https://www.google.com/"
        assert "nyt-privacy=1" in headers["Cookie"]

    def test_ft_adds_referer_but_keeps_base_user_agent(self) -> None:
        headers = apply_domain_fetch_headers(
            BASE_HEADERS,
            "https://www.ft.com/content/example",
        )
        assert headers["User-Agent"] == BASE_HEADERS["User-Agent"]
        assert headers["Referer"] == "https://t.co/x?amp=1"

    def test_unknown_domain_returns_base_headers_unchanged(self) -> None:
        headers = apply_domain_fetch_headers(
            BASE_HEADERS,
            "https://www.reuters.com/markets/us/",
        )
        assert headers == BASE_HEADERS


class TestDirectFetchUsesStrategy:
    def test_fetch_direct_html_sends_nytimes_headers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def fake_get(url: str, *, headers: dict[str, str], timeout: float) -> MagicMock:
            captured["url"] = url
            captured["headers"] = headers
            response = MagicMock()
            response.text = "<html><body>ok</body></html>"
            response.raise_for_status = MagicMock()
            return response

        monkeypatch.setattr("web_dashboard.web_fetch_client.requests.get", fake_get)

        url = "https://www.nytimes.com/2024/03/15/business/markets.html"
        from web_dashboard.web_fetch_client import get_web_fetch_client

        html = get_web_fetch_client().fetch_direct_html(url, timeout_seconds=5.0)

        assert html is not None
        assert captured["url"] == url
        assert "Googlebot" in captured["headers"]["User-Agent"]
        assert "nyt-privacy=1" in captured["headers"]["Cookie"]


class TestFixtureExtractionPipeline:
    """Prove the extraction pipeline accepts good HTML and rejects paywall fixtures."""

    @staticmethod
    def _disable_flaresolverr(monkeypatch: pytest.MonkeyPatch) -> None:
        def fail_post(*_args: Any, **_kwargs: Any) -> None:
            raise requests.ConnectionError("FlareSolverr unavailable in unit test")

        monkeypatch.setattr("web_dashboard.web_fetch_client.requests.post", fail_post)

    @staticmethod
    def _serve_fixture(monkeypatch: pytest.MonkeyPatch, fixture_name: str) -> None:
        html = (FIXTURE_DIR / fixture_name).read_text(encoding="utf-8")

        def fake_get(url: str, *, headers: dict[str, str], timeout: float) -> MagicMock:
            response = MagicMock()
            response.text = html
            response.raise_for_status = MagicMock()
            return response

        monkeypatch.setattr("web_dashboard.web_fetch_client.requests.get", fake_get)

    def test_nytimes_fixture_extracts_substantive_content(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        if research_utils.trafilatura is None:
            pytest.skip("trafilatura not installed")

        self._disable_flaresolverr(monkeypatch)
        self._serve_fixture(monkeypatch, "nytimes_article.html")

        result = research_utils.extract_article_content(
            "https://www.nytimes.com/2024/03/15/business/markets.html",
            max_seconds=30.0,
        )

        assert result["success"] is True
        assert len(result["content"]) >= LIVE_CANARY_MIN_CONTENT_LEN["nytimes_googlebot"]
        assert "earnings" in result["content"].lower()

    def test_nytimes_paywall_fixture_triggers_paid_subscription(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        if research_utils.trafilatura is None:
            pytest.skip("trafilatura not installed")

        self._disable_flaresolverr(monkeypatch)
        self._serve_fixture(monkeypatch, "nytimes_paywall.html")

        archive_called = {"submit": False}

        def fake_submit(url: str, timeout: int = 30) -> bool:
            archive_called["submit"] = True
            return True

        monkeypatch.setattr("archive_service.submit_for_archiving", fake_submit)
        monkeypatch.setattr(
            "archive_service.check_archived",
            lambda url, timeout=10: None,
        )

        result = research_utils.extract_article_content(
            "https://www.nytimes.com/2024/03/15/business/paywalled.html",
            max_seconds=30.0,
        )

        assert result["success"] is False
        assert result["error"] == "paid_subscription"
        assert archive_called["submit"] is True

    def test_ft_paywall_fixture_triggers_paid_subscription(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        if research_utils.trafilatura is None:
            pytest.skip("trafilatura not installed")

        self._disable_flaresolverr(monkeypatch)
        self._serve_fixture(monkeypatch, "ft_paywall.html")

        monkeypatch.setattr(
            "archive_service.check_archived",
            lambda url, timeout=10: None,
        )
        monkeypatch.setattr("archive_service.submit_for_archiving", lambda url, timeout=30: True)

        result = research_utils.extract_article_content(
            "https://www.ft.com/content/example-paywalled",
            max_seconds=30.0,
        )

        assert result["success"] is False
        assert result["error"] == "paid_subscription"
