#!/usr/bin/env python3
"""
Unified web fetch client (FlareSolverr + direct HTTP).

Centralizes duplicated fetch logic previously spread across research_utils,
rss_utils, social_service, jobs_insiders, and seed scripts.
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any, Mapping, Optional

import requests

from domain_fetch_strategies import apply_domain_fetch_headers

logger = logging.getLogger(__name__)

DEFAULT_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

DEFAULT_HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
DEFAULT_RSS_ACCEPT = "application/rss+xml, application/xml, text/xml, */*"

DEFAULT_FLARESOLVERR_MAX_TIMEOUT_MS = 60_000


@dataclass(frozen=True)
class FlareSolverrSolution:
    """Parsed FlareSolverr ``solution`` payload."""

    response_body: str
    http_status: int
    headers: Mapping[str, str]


def _load_dotenv_fallback() -> None:
    try:
        from dotenv import load_dotenv

        project_root = Path(__file__).resolve().parent.parent
        load_dotenv(project_root / ".env")
        load_dotenv(project_root / "web_dashboard" / ".env")
    except Exception:
        return


def get_flaresolverr_url() -> str:
    """Resolve FlareSolverr base URL from env, dotenv, or environment heuristics."""
    explicit = os.getenv("FLARESOLVERR_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")

    _load_dotenv_fallback()
    explicit = os.getenv("FLARESOLVERR_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")

    try:
        socket.gethostbyname("host.docker.internal")
        return "http://host.docker.internal:8191"
    except socket.gaierror:
        return "http://localhost:8191"


def _solution_body_as_text(body: object) -> str:
    if body is None:
        return ""
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="replace")
    return str(body)


def _parse_json_from_flaresolverr_body(response_body: str) -> Optional[dict[str, Any]]:
    """Parse JSON API responses that FlareSolverr may wrap in HTML."""
    if not response_body or not response_body.strip():
        return None

    try:
        parsed = json.loads(response_body)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    json_match = re.search(r"\{.*\}", response_body, re.DOTALL)
    if not json_match:
        return None

    try:
        parsed = json.loads(json_match.group(0))
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return None
    return None


def extract_rss_bytes_from_flaresolverr_body(
    response_body: str,
    *,
    content_type: str = "",
) -> Optional[bytes]:
    """Normalize FlareSolverr RSS/XML bodies (may be HTML-wrapped) to raw bytes."""
    if not response_body:
        return None

    content_type_lower = content_type.lower()
    if "html" in content_type_lower or response_body.strip().startswith("<html"):
        pre_match = re.search(r"<pre[^>]*>(.*?)</pre>", response_body, re.DOTALL | re.IGNORECASE)
        if pre_match:
            unescaped = unescape(pre_match.group(1))
            if unescaped.strip().startswith(("<?xml", "<rss", "<feed")):
                if "</rss>" in unescaped or "</feed>" in unescaped:
                    return unescaped.encode("utf-8")

        xml_match = re.search(
            r"(<\?xml[^>]*>.*?</rss>)",
            response_body,
            re.DOTALL | re.IGNORECASE,
        )
        if xml_match:
            return xml_match.group(1).encode("utf-8")

        if "&lt;?xml" in response_body or "&lt;rss" in response_body:
            unescaped = unescape(response_body)
            xml_match = re.search(
                r"(<\?xml[^>]*>.*?</rss>)",
                unescaped,
                re.DOTALL | re.IGNORECASE,
            )
            if xml_match:
                return xml_match.group(1).encode("utf-8")
        return None

    return response_body.encode("utf-8")


class WebFetchClient:
    """Fetch web content via FlareSolverr and/or direct HTTP."""

    def __init__(self, flaresolverr_url: Optional[str] = None) -> None:
        self.flaresolverr_url = (flaresolverr_url or get_flaresolverr_url()).rstrip("/")

    def check_health(self, timeout: float = 5.0) -> bool:
        try:
            response = requests.get(f"{self.flaresolverr_url}/health", timeout=timeout)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def fetch_via_flaresolverr(
        self,
        url: str,
        *,
        max_timeout_ms: int = DEFAULT_FLARESOLVERR_MAX_TIMEOUT_MS,
        request_timeout_seconds: Optional[float] = None,
        extra_headers: Optional[Mapping[str, str]] = None,
        require_http_200: bool = False,
    ) -> Optional[FlareSolverrSolution]:
        """Fetch ``url`` through FlareSolverr. Returns ``None`` on any failure."""
        if not self.flaresolverr_url:
            return None

        payload: dict[str, Any] = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": max(1000, max_timeout_ms),
        }
        if extra_headers:
            payload["headers"] = dict(extra_headers)

        post_timeout = request_timeout_seconds
        if post_timeout is None:
            post_timeout = (max_timeout_ms / 1000.0) + 10.0

        try:
            logger.debug("Requesting via FlareSolverr: %s", url)
            response = requests.post(
                f"{self.flaresolverr_url}/v1",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=post_timeout,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            logger.debug("FlareSolverr unavailable or timed out for %s: %s", url, exc)
            return None
        except ValueError as exc:
            logger.debug("FlareSolverr returned invalid JSON for %s: %s", url, exc)
            return None

        if data.get("status") != "ok":
            logger.debug(
                "FlareSolverr error for %s: %s",
                url,
                data.get("message", "Unknown error"),
            )
            return None

        solution = data.get("solution") or {}
        if not solution:
            logger.debug("FlareSolverr response missing solution for %s", url)
            return None

        http_status = int(solution.get("status") or 0)
        response_body = _solution_body_as_text(solution.get("response"))
        response_headers = solution.get("headers") or {}
        if not isinstance(response_headers, dict):
            response_headers = {}

        if require_http_200 and http_status != 200:
            logger.debug("FlareSolverr target HTTP %s for %s", http_status, url)
            return None

        if not response_body.strip():
            logger.debug("FlareSolverr returned empty body for %s", url)
            return None

        return FlareSolverrSolution(
            response_body=response_body,
            http_status=http_status,
            headers=response_headers,
        )

    def fetch_via_flaresolverr_text(
        self,
        url: str,
        *,
        max_timeout_ms: int = DEFAULT_FLARESOLVERR_MAX_TIMEOUT_MS,
        request_timeout_seconds: Optional[float] = None,
        extra_headers: Optional[Mapping[str, str]] = None,
        require_http_200: bool = False,
    ) -> Optional[str]:
        solution = self.fetch_via_flaresolverr(
            url,
            max_timeout_ms=max_timeout_ms,
            request_timeout_seconds=request_timeout_seconds,
            extra_headers=extra_headers,
            require_http_200=require_http_200,
        )
        return solution.response_body if solution else None

    def fetch_via_flaresolverr_rss_bytes(
        self,
        url: str,
        *,
        max_timeout_ms: int = DEFAULT_FLARESOLVERR_MAX_TIMEOUT_MS,
        request_timeout_seconds: Optional[float] = None,
    ) -> Optional[bytes]:
        solution = self.fetch_via_flaresolverr(
            url,
            max_timeout_ms=max_timeout_ms,
            request_timeout_seconds=request_timeout_seconds,
            extra_headers={
                "Accept": DEFAULT_RSS_ACCEPT,
                "Accept-Language": "en-US,en;q=0.9",
            },
            require_http_200=True,
        )
        if solution is None:
            return None

        content_type = str(solution.headers.get("content-type", ""))
        return extract_rss_bytes_from_flaresolverr_body(
            solution.response_body,
            content_type=content_type,
        )

    def fetch_json_via_flaresolverr(
        self,
        url: str,
        *,
        max_timeout_ms: int = DEFAULT_FLARESOLVERR_MAX_TIMEOUT_MS,
        request_timeout_seconds: Optional[float] = None,
    ) -> Optional[dict[str, Any]]:
        solution = self.fetch_via_flaresolverr(
            url,
            max_timeout_ms=max_timeout_ms,
            request_timeout_seconds=request_timeout_seconds,
            require_http_200=True,
        )
        if solution is None:
            return None

        parsed = _parse_json_from_flaresolverr_body(solution.response_body)
        if parsed is None:
            preview = solution.response_body[:500]
            logger.warning("Failed to parse JSON from FlareSolverr response for %s", url)
            logger.debug("Response preview: %s", preview)
        return parsed

    def fetch_direct_html(
        self,
        url: str,
        *,
        timeout_seconds: float = 25.0,
        accept: str = DEFAULT_HTML_ACCEPT,
        apply_domain_strategy: bool = True,
    ) -> str:
        """Direct GET with browser headers and optional domain fetch strategy."""
        base_headers = {
            "User-Agent": DEFAULT_BROWSER_USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
        }
        headers = (
            apply_domain_fetch_headers(base_headers, url)
            if apply_domain_strategy
            else base_headers
        )
        response = requests.get(url, headers=headers, timeout=timeout_seconds)
        response.raise_for_status()
        return response.text

    def fetch_text_with_fallback(
        self,
        url: str,
        *,
        flaresolverr_max_timeout_ms: int = DEFAULT_FLARESOLVERR_MAX_TIMEOUT_MS,
        flaresolverr_request_timeout_seconds: Optional[float] = None,
        direct_timeout_seconds: float = 25.0,
        direct_accept: str = DEFAULT_HTML_ACCEPT,
        apply_domain_strategy: bool = True,
    ) -> Optional[str]:
        """Try FlareSolverr first, then direct HTTP with domain strategy."""
        body = self.fetch_via_flaresolverr_text(
            url,
            max_timeout_ms=flaresolverr_max_timeout_ms,
            request_timeout_seconds=flaresolverr_request_timeout_seconds,
        )
        if body:
            return body

        try:
            return self.fetch_direct_html(
                url,
                timeout_seconds=direct_timeout_seconds,
                accept=direct_accept,
                apply_domain_strategy=apply_domain_strategy,
            )
        except requests.RequestException as exc:
            logger.debug("Direct fetch failed for %s: %s", url, exc)
            return None


_default_client: Optional[WebFetchClient] = None


def get_web_fetch_client() -> WebFetchClient:
    """Return the process-wide ``WebFetchClient`` singleton."""
    global _default_client
    if _default_client is None:
        _default_client = WebFetchClient()
    return _default_client


def fetch_page_via_flaresolverr(
    url: str,
    *,
    max_timeout_ms: int = DEFAULT_FLARESOLVERR_MAX_TIMEOUT_MS,
    request_timeout_seconds: Optional[float] = None,
) -> Optional[str]:
    """Module-level helper for scripts that only need FlareSolverr text fetch."""
    return get_web_fetch_client().fetch_via_flaresolverr_text(
        url,
        max_timeout_ms=max_timeout_ms,
        request_timeout_seconds=request_timeout_seconds,
    )


# Backwards-compatible alias used by RSS test scripts.
FLARESOLVERR_URL = get_flaresolverr_url()
