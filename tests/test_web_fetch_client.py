"""Tests for the unified web fetch client."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from web_dashboard.web_fetch_client import (
    WebFetchClient,
    extract_rss_bytes_from_flaresolverr_body,
    get_flaresolverr_url,
)


class TestFlareSolverrFetch:
    def test_fetch_via_flaresolverr_text_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = WebFetchClient(flaresolverr_url="http://flaresolverr.test:8191")

        def fake_post(url: str, *, json: dict[str, Any], headers: dict[str, str], timeout: float):
            assert json["cmd"] == "request.get"
            assert json["url"] == "https://example.com/article"
            response = MagicMock()
            response.raise_for_status = MagicMock()
            response.json.return_value = {
                "status": "ok",
                "solution": {
                    "status": 200,
                    "response": "<html><body>Hello</body></html>",
                    "headers": {},
                },
            }
            return response

        monkeypatch.setattr("web_dashboard.web_fetch_client.requests.post", fake_post)

        body = client.fetch_via_flaresolverr_text("https://example.com/article")
        assert body == "<html><body>Hello</body></html>"

    def test_fetch_via_flaresolverr_returns_none_on_connection_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = WebFetchClient(flaresolverr_url="http://flaresolverr.test:8191")

        def fail_post(*_args: Any, **_kwargs: Any) -> None:
            raise requests.ConnectionError("down")

        monkeypatch.setattr("web_dashboard.web_fetch_client.requests.post", fail_post)
        assert client.fetch_via_flaresolverr_text("https://example.com/article") is None


class TestDirectFetch:
    def test_fetch_direct_html_applies_domain_strategy(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client = WebFetchClient(flaresolverr_url="http://flaresolverr.test:8191")
        captured: dict[str, Any] = {}

        def fake_get(url: str, *, headers: dict[str, str], timeout: float) -> MagicMock:
            captured["headers"] = headers
            response = MagicMock()
            response.text = "<html>ok</html>"
            response.raise_for_status = MagicMock()
            return response

        monkeypatch.setattr("web_dashboard.web_fetch_client.requests.get", fake_get)

        html = client.fetch_direct_html(
            "https://www.nytimes.com/2024/03/15/business/markets.html",
            timeout_seconds=10,
        )
        assert html == "<html>ok</html>"
        assert "Googlebot" in captured["headers"]["User-Agent"]


class TestRssNormalization:
    def test_extract_rss_bytes_from_html_wrapped_feed(self) -> None:
        html = """
        <html><body><pre>&lt;?xml version="1.0"?&gt;
        &lt;rss&gt;&lt;channel&gt;&lt;title&gt;Feed&lt;/title&gt;&lt;/channel&gt;&lt;/rss&gt;
        </pre></body></html>
        """
        raw = extract_rss_bytes_from_flaresolverr_body(html, content_type="text/html")
        assert raw is not None
        assert b"<rss>" in raw


class TestUrlResolution:
    def test_get_flaresolverr_url_honors_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("FLARESOLVERR_URL", "http://custom-flare:9191")
        assert get_flaresolverr_url() == "http://custom-flare:9191"
