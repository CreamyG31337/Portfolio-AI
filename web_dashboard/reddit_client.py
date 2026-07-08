#!/usr/bin/env python3
"""Reddit client for social sentiment and subreddit discovery jobs.

Auth priority:
1. Legacy OAuth app credentials (if all four REDDIT_* vars + client id/secret)
2. Browser session cookies (file/env) or username/password login
3. Public RSS feeds (increasingly blocked; fallback only)
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlparse

import requests

from env_loader import load_project_dotenv
from reddit_cookies import load_reddit_cookies, reddit_cookie_configured, reset_reddit_cookie_cache
from reddit_login import reddit_password_configured
from reddit_rss import (
    BROWSER_USER_AGENT,
    RedditFeedCache,
    RedditRssWarmStats,
    fetch_reddit_rss,
    path_to_rss_url,
    reset_rss_rate_limiter,
    rss_items_to_listing_payload,
)

load_project_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "LLM-Micro-Cap-trading-bot/1.0 (social sentiment research)"
OAUTH_BASE = "https://oauth.reddit.com"
LEGACY_BASE = "https://www.reddit.com"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
CONNECTIVITY_PROBE_PATH = "/r/wallstreetbets/hot"
MAX_RETRY_AFTER_SECONDS = 30


class RedditApiError(Exception):
    """Raised when Reddit returns a non-recoverable API error."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class RedditRequestResult:
    """Result of a Reddit HTTP request."""

    status_code: int
    payload: dict[str, Any] | None
    used_oauth: bool
    rate_limited: bool
    used_rss: bool = False
    used_cookies: bool = False


@dataclass
class RedditConnectivityStatus:
    """Result of a Reddit API connectivity probe."""

    ok: bool
    oauth_configured: bool
    cookie_configured: bool
    status_code: int | None
    rate_limited: bool
    auth_failed: bool
    message: str


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def reddit_oauth_configured() -> bool:
    """Return True when script-app OAuth credentials are present."""
    client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
    client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    username = os.getenv("REDDIT_USERNAME", "").strip()
    password = os.getenv("REDDIT_PASSWORD", "").strip()
    return bool(client_id and client_secret and username and password)


def _parse_retry_after(response: requests.Response) -> float | None:
    raw = response.headers.get("Retry-After", "").strip()
    if not raw:
        return None
    try:
        return min(float(raw), MAX_RETRY_AFTER_SECONDS)
    except ValueError:
        return None


def _format_rate_limit_headers(response: requests.Response) -> str:
    parts: list[str] = []
    for header in ("Retry-After", "X-Ratelimit-Remaining", "X-Ratelimit-Reset"):
        value = response.headers.get(header)
        if value is not None:
            parts.append(f"{header}={value}")
    return ", ".join(parts) if parts else "no rate-limit headers"


def _log_reddit_http_error(
    *,
    path: str,
    status_code: int,
    used_oauth: bool,
    response: requests.Response,
) -> None:
    header_info = _format_rate_limit_headers(response)
    if status_code == 429:
        logger.warning(
            "Reddit rate limited path=%s oauth=%s status=429 (%s)",
            path,
            used_oauth,
            header_info,
        )
        return
    if status_code in (401, 403) and used_oauth:
        logger.error(
            "Reddit auth failed path=%s oauth=%s status=%s (%s)",
            path,
            used_oauth,
            status_code,
            header_info,
        )
        return
    logger.warning(
        "Reddit request failed path=%s oauth=%s status=%s (%s)",
        path,
        used_oauth,
        status_code,
        header_info,
    )


def _rss_min_interval_seconds() -> float:
    raw = os.getenv("REDDIT_RSS_MIN_INTERVAL", "8").strip()
    try:
        return max(float(raw), 2.0)
    except ValueError:
        return 8.0


class RedditClient:
    """Minimal Reddit API client with OAuth token caching and rate limiting."""

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        min_interval: float | None = None,
    ) -> None:
        self._oauth_enabled = reddit_oauth_configured()
        self._cookie_enabled = not self._oauth_enabled and reddit_cookie_configured()
        if self._oauth_enabled:
            self.user_agent = os.getenv("REDDIT_USER_AGENT", user_agent).strip() or user_agent
            self.min_interval = min_interval if min_interval is not None else 2.0
        else:
            self.user_agent = os.getenv("REDDIT_USER_AGENT", BROWSER_USER_AGENT).strip() or BROWSER_USER_AGENT
            self.min_interval = min_interval if min_interval is not None else _rss_min_interval_seconds()
        self._last_request_time = 0.0
        self._access_token: str | None = None
        self._token_expires_at = 0.0
        self._feed_cache = RedditFeedCache(user_agent=self.user_agent)
        self._cookie_session = requests.Session()
        if self._oauth_enabled:
            logger.info("Reddit client using OAuth API")
        elif self._cookie_enabled:
            if reddit_password_configured():
                logger.info("Reddit client using username/password login (session cookies)")
            else:
                logger.info("Reddit client using browser session cookies")
        else:
            logger.info(
                "Reddit client using public RSS feeds (no API app required). "
                "Spacing=%.0fs between requests.",
                self.min_interval,
            )

    @property
    def oauth_enabled(self) -> bool:
        return self._oauth_enabled

    @property
    def cookie_enabled(self) -> bool:
        return self._cookie_enabled

    @property
    def rss_enabled(self) -> bool:
        return not self._oauth_enabled and not self._cookie_enabled

    @property
    def feed_cache(self) -> RedditFeedCache:
        return self._feed_cache

    def warm_sentiment_feed_cache(self, *, force: bool = False) -> RedditRssWarmStats:
        """Prefetch finance subreddit hot feeds for ticker filtering (RSS mode)."""
        if self._oauth_enabled or self._cookie_enabled:
            return RedditRssWarmStats(
                subs_requested=0,
                subs_fetched=0,
                subs_rate_limited=0,
                posts_cached=0,
            )
        return self._feed_cache.warm(force=force)

    def _wait_for_rate_limit(self) -> None:
        elapsed = time.time() - self._last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request_time = time.time()

    def _get_access_token(self) -> str:
        if self._access_token and time.time() < self._token_expires_at - 30:
            return self._access_token

        client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
        client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
        username = os.getenv("REDDIT_USERNAME", "").strip()
        password = os.getenv("REDDIT_PASSWORD", "").strip()
        if not all([client_id, client_secret, username, password]):
            raise RedditApiError("Reddit OAuth credentials are incomplete")

        self._wait_for_rate_limit()
        response = requests.post(
            TOKEN_URL,
            auth=(client_id, client_secret),
            data={"grant_type": "password", "username": username, "password": password},
            headers={"User-Agent": self.user_agent},
            timeout=15,
        )
        if response.status_code != 200:
            raise RedditApiError(
                f"Reddit OAuth token request failed ({response.status_code})",
                status_code=response.status_code,
            )

        data = response.json()
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise RedditApiError("Reddit OAuth token response missing access_token")

        expires_in = int(data.get("expires_in", 3600))
        self._access_token = token
        self._token_expires_at = time.time() + expires_in
        return token

    def _build_url(self, path: str, *, use_oauth: bool) -> str:
        normalized = path if path.startswith("/") else f"/{path}"
        base = OAUTH_BASE if use_oauth else LEGACY_BASE
        if normalized.endswith(".json"):
            return f"{base}{normalized}"
        return f"{base}{normalized}.json"

    def _request_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None,
        use_oauth: bool,
        headers: dict[str, str],
    ) -> requests.Response:
        url = self._build_url(path, use_oauth=use_oauth)
        self._wait_for_rate_limit()
        return requests.get(url, headers=headers, params=params, timeout=15)

    def _result_from_response(
        self,
        response: requests.Response,
        *,
        path: str,
        use_oauth: bool,
        used_cookies: bool = False,
    ) -> RedditRequestResult:
        status_code = response.status_code
        if status_code == 429:
            return RedditRequestResult(
                status_code=429,
                payload=None,
                used_oauth=use_oauth,
                rate_limited=True,
                used_rss=False,
                used_cookies=used_cookies,
            )

        if status_code != 200:
            _log_reddit_http_error(
                path=path,
                status_code=status_code,
                used_oauth=use_oauth,
                response=response,
            )
            return RedditRequestResult(
                status_code=status_code,
                payload=None,
                used_oauth=use_oauth,
                rate_limited=False,
                used_cookies=used_cookies,
            )

        try:
            payload = response.json()
        except ValueError:
            return RedditRequestResult(
                status_code=status_code,
                payload=None,
                used_oauth=use_oauth,
                rate_limited=False,
                used_cookies=used_cookies,
            )

        if not isinstance(payload, dict):
            return RedditRequestResult(
                status_code=status_code,
                payload=None,
                used_oauth=use_oauth,
                rate_limited=False,
                used_cookies=used_cookies,
            )

        return RedditRequestResult(
            status_code=status_code,
            payload=payload,
            used_oauth=use_oauth,
            rate_limited=False,
            used_rss=False,
            used_cookies=used_cookies,
        )

    def _cookie_headers(self, cookies: Mapping[str, str] | None = None) -> dict[str, str]:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        token_v2 = (cookies or {}).get("token_v2", "").strip()
        # Legacy .json endpoints authenticate via reddit_session cookie only.
        # Sending a guest token_v2 Bearer alongside reddit_session causes 403s.
        if token_v2 and not (cookies or {}).get("reddit_session"):
            headers["Authorization"] = f"Bearer {token_v2}"
        return headers

    def _cookie_json_url(self, path: str, cookies: Mapping[str, str]) -> str:
        normalized = path if path.startswith("/") else f"/{path}"
        if normalized.endswith(".json"):
            suffix = normalized
        else:
            suffix = f"{normalized}.json"
        if cookies.get("token_v2") and not cookies.get("reddit_session"):
            return f"{OAUTH_BASE}{suffix}"
        return f"{LEGACY_BASE}{suffix}"

    def _get_json_via_cookies(
        self,
        path: str,
        params: Mapping[str, Any] | None,
    ) -> RedditRequestResult:
        cookies = load_reddit_cookies()
        if not cookies:
            logger.warning("Reddit cookie auth enabled but cookies missing at request time")
            return RedditRequestResult(
                status_code=401,
                payload=None,
                used_oauth=False,
                rate_limited=False,
                used_cookies=True,
            )

        normalized = path if path.startswith("/") else f"/{path}"
        url = self._cookie_json_url(path, cookies)

        self._wait_for_rate_limit()
        try:
            response = self._cookie_session.get(
                url,
                headers=self._cookie_headers(cookies),
                cookies=cookies,
                params=params,
                timeout=15,
            )
        except requests.RequestException as exc:
            logger.warning("Reddit cookie request failed path=%s: %s", path, exc)
            return RedditRequestResult(
                status_code=0,
                payload=None,
                used_oauth=False,
                rate_limited=False,
                used_cookies=True,
            )

        if response.status_code == 429:
            return RedditRequestResult(
                status_code=429,
                payload=None,
                used_oauth=False,
                rate_limited=True,
                used_cookies=True,
            )

        result = self._result_from_response(
            response,
            path=path,
            use_oauth=False,
            used_cookies=True,
        )

        active_cookies = cookies
        if result.status_code in (401, 403) and reddit_password_configured():
            logger.info("Reddit session rejected — re-logging in with username/password")
            reset_reddit_cookie_cache()
            fresh = load_reddit_cookies()
            if fresh and fresh != cookies:
                self._wait_for_rate_limit()
                try:
                    retry = self._cookie_session.get(
                        url,
                        headers=self._cookie_headers(fresh),
                        cookies=fresh,
                        params=params,
                        timeout=15,
                    )
                    result = self._result_from_response(
                        retry,
                        path=path,
                        use_oauth=False,
                        used_cookies=True,
                    )
                    active_cookies = fresh
                except requests.RequestException as exc:
                    logger.warning("Reddit cookie retry failed path=%s: %s", path, exc)

        # Cloudflare-style block (403/503): retry via FlareSolverr carrying our session.
        if result.status_code in (403, 503):
            fallback = self._get_json_via_flaresolverr(url, params, active_cookies)
            if fallback is not None:
                return fallback

        return result

    def _get_json_via_flaresolverr(
        self,
        url: str,
        params: Mapping[str, Any] | None,
        cookies: Mapping[str, str],
    ) -> RedditRequestResult | None:
        """Fetch a Reddit JSON URL through FlareSolverr (Cloudflare bypass)."""
        try:
            from web_fetch_client import get_flaresolverr_url, get_web_fetch_client
        except ImportError:
            return None

        if not get_flaresolverr_url():
            return None

        full_url = url
        if params:
            query = urlencode(
                {k: v for k, v in dict(params).items() if v is not None},
                doseq=True,
            )
            if query:
                sep = "&" if "?" in full_url else "?"
                full_url = f"{full_url}{sep}{query}"

        try:
            payload = get_web_fetch_client().fetch_json_via_flaresolverr(
                full_url,
                cookies=dict(cookies),
            )
        except Exception as exc:
            logger.debug("Reddit FlareSolverr fallback error for %s: %s", url, exc)
            return None

        if not isinstance(payload, dict):
            logger.warning("Reddit FlareSolverr fallback returned no JSON for %s", url)
            return None

        logger.info("Reddit fetched via FlareSolverr fallback: %s", url)
        return RedditRequestResult(
            status_code=200,
            payload=payload,
            used_oauth=False,
            rate_limited=False,
            used_cookies=True,
        )

    def _get_json_via_rss(
        self,
        path: str,
        params: Mapping[str, Any] | None,
    ) -> RedditRequestResult:
        param_dict = dict(params or {})
        rss_url = path_to_rss_url(path, param_dict)
        if rss_url is None:
            logger.warning("No Reddit RSS mapping for path=%s params=%s", path, param_dict)
            return RedditRequestResult(
                status_code=400,
                payload=None,
                used_oauth=False,
                rate_limited=False,
                used_rss=True,
            )

        # Spacing is enforced inside fetch_reddit_rss (shared process limiter).
        rss_result = fetch_reddit_rss(rss_url, user_agent=self.user_agent)
        if rss_result.rate_limited:
            logger.warning(
                "Reddit RSS rate limited path=%s url=%s oauth=False status=429",
                path,
                rss_url,
            )
            return RedditRequestResult(
                status_code=429,
                payload=None,
                used_oauth=False,
                rate_limited=True,
                used_rss=True,
            )
        if rss_result.status_code != 200 or not rss_result.items:
            logger.warning(
                "Reddit RSS fetch failed path=%s url=%s status=%s items=%s",
                path,
                rss_url,
                rss_result.status_code,
                len(rss_result.items),
            )
            return RedditRequestResult(
                status_code=rss_result.status_code or 0,
                payload=None,
                used_oauth=False,
                rate_limited=False,
                used_rss=True,
            )

        limit = param_dict.get("limit")
        items = rss_result.items
        if isinstance(limit, int) and limit > 0:
            items = items[:limit]

        return RedditRequestResult(
            status_code=200,
            payload=rss_items_to_listing_payload(items),
            used_oauth=False,
            rate_limited=False,
            used_rss=True,
        )

    def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> RedditRequestResult:
        """Fetch a Reddit listing via OAuth, session cookies, or public RSS."""
        if self._cookie_enabled:
            return self._get_json_via_cookies(path, params)
        if not self._oauth_enabled:
            return self._get_json_via_rss(path, params)

        use_oauth = True
        headers: dict[str, str] = {"User-Agent": self.user_agent}
        if use_oauth:
            headers["Authorization"] = f"bearer {self._get_access_token()}"

        response = self._request_json(path, params=params, use_oauth=use_oauth, headers=headers)

        if response.status_code == 429:
            retry_after = _parse_retry_after(response)
            _log_reddit_http_error(
                path=path,
                status_code=429,
                used_oauth=use_oauth,
                response=response,
            )
            if retry_after is not None:
                logger.info(
                    "Reddit 429 on path=%s — sleeping %.1fs before one retry",
                    path,
                    retry_after,
                )
                time.sleep(retry_after)
                response = self._request_json(path, params=params, use_oauth=use_oauth, headers=headers)

        if response.status_code == 401 and use_oauth:
            self._access_token = None
            self._token_expires_at = 0.0
            headers["Authorization"] = f"bearer {self._get_access_token()}"
            response = self._request_json(path, params=params, use_oauth=use_oauth, headers=headers)

        if response.status_code == 429:
            _log_reddit_http_error(
                path=path,
                status_code=429,
                used_oauth=use_oauth,
                response=response,
            )
            return RedditRequestResult(
                status_code=429,
                payload=None,
                used_oauth=use_oauth,
                rate_limited=True,
                used_rss=False,
            )

        return self._result_from_response(response, path=path, use_oauth=use_oauth)

    @staticmethod
    def check_robots_allowed(url: str) -> bool:
        """Optional robots.txt gate for Reddit requests."""
        if not _truthy_env("ENABLE_ROBOTS_TXT_CHECKS"):
            return True
        try:
            from robots_utils import is_url_allowed

            return bool(is_url_allowed(url))
        except Exception as exc:
            logger.warning("Reddit robots.txt check failed for %s: %s", url, exc)
            return True


_reddit_client: RedditClient | None = None


def get_reddit_client() -> RedditClient:
    """Return a process-wide RedditClient singleton."""
    global _reddit_client
    if _reddit_client is None:
        _reddit_client = RedditClient()
    return _reddit_client


def reset_reddit_client() -> None:
    """Clear the process-wide RedditClient singleton (for tests)."""
    global _reddit_client
    _reddit_client = None
    reset_rss_rate_limiter()
    reset_reddit_cookie_cache()


def check_reddit_connectivity_with_retry(
    client: RedditClient | None = None,
    *,
    max_cooldown_wait: float | None = None,
) -> RedditConnectivityStatus:
    """Probe Reddit; wait out one RSS cooldown window before reporting rate-limited.

    Social sentiment and subreddit scanner share the process-wide RSS limiter.
    When the probe runs during an active cooldown, sleep and retry once so a
    transient 429 does not fail the whole job.
    """
    from reddit_rss import _rss_cooldown_seconds, get_rss_rate_limiter

    reddit = client or get_reddit_client()
    status = check_reddit_connectivity(reddit)
    if status.ok or not status.rate_limited or reddit.oauth_enabled:
        return status

    wait_cap = (
        max_cooldown_wait
        if max_cooldown_wait is not None
        else _rss_cooldown_seconds() + 5.0
    )
    wait = min(get_rss_rate_limiter().seconds_until_ready(), wait_cap)
    if wait <= 0:
        return status

    logger.info("Reddit RSS cooldown — waiting %.0fs before connectivity retry", wait)
    time.sleep(wait)
    return check_reddit_connectivity(reddit)


def check_reddit_connectivity(client: RedditClient | None = None) -> RedditConnectivityStatus:
    """Probe Reddit reachability with OAuth or public RSS feeds."""
    reddit = client or get_reddit_client()
    oauth_configured = reddit.oauth_enabled
    cookie_configured = reddit.cookie_enabled

    try:
        result = reddit.get_json(CONNECTIVITY_PROBE_PATH, params={"limit": 1})
    except RedditApiError as exc:
        status_code = exc.status_code
        auth_failed = status_code in (401, 403) if status_code is not None else True
        return RedditConnectivityStatus(
            ok=False,
            oauth_configured=oauth_configured,
            cookie_configured=cookie_configured,
            status_code=status_code,
            rate_limited=False,
            auth_failed=auth_failed,
            message=str(exc),
        )
    except Exception as exc:
        return RedditConnectivityStatus(
            ok=False,
            oauth_configured=oauth_configured,
            cookie_configured=cookie_configured,
            status_code=None,
            rate_limited=False,
            auth_failed=False,
            message=f"Reddit connectivity probe failed: {exc}",
        )

    if result.rate_limited or result.status_code == 429:
        return RedditConnectivityStatus(
            ok=False,
            oauth_configured=oauth_configured,
            cookie_configured=cookie_configured,
            status_code=429,
            rate_limited=True,
            auth_failed=False,
            message="Reddit rate limited (429) during connectivity probe",
        )

    if result.status_code in (401, 403):
        if result.used_oauth:
            block_message = f"Reddit OAuth rejected (HTTP {result.status_code})"
        elif result.used_cookies:
            block_message = (
                f"Reddit session cookies rejected (HTTP {result.status_code}) "
                "— re-export reddit_session from your browser"
            )
        else:
            block_message = f"Reddit RSS blocked (HTTP {result.status_code})"
        return RedditConnectivityStatus(
            ok=False,
            oauth_configured=oauth_configured,
            cookie_configured=cookie_configured,
            status_code=result.status_code,
            rate_limited=False,
            auth_failed=result.used_oauth or result.used_cookies,
            message=block_message,
        )

    if result.payload is None or result.status_code != 200:
        return RedditConnectivityStatus(
            ok=False,
            oauth_configured=oauth_configured,
            cookie_configured=cookie_configured,
            status_code=result.status_code,
            rate_limited=False,
            auth_failed=False,
            message=f"Reddit connectivity probe failed (HTTP {result.status_code})",
        )

    children = (result.payload.get("data") or {}).get("children") or []
    if not isinstance(children, list) or not children:
        return RedditConnectivityStatus(
            ok=False,
            oauth_configured=oauth_configured,
            cookie_configured=cookie_configured,
            status_code=result.status_code,
            rate_limited=False,
            auth_failed=False,
            message="Reddit connectivity probe returned empty listing",
        )

    if result.used_rss:
        message = "Reddit RSS feeds reachable (no API app required)"
    elif result.used_cookies:
        message = "Reddit API reachable via browser session cookies"
    elif oauth_configured:
        message = "Reddit API reachable via OAuth"
    else:
        message = "Reddit reachable"

    return RedditConnectivityStatus(
        ok=True,
        oauth_configured=oauth_configured,
        cookie_configured=cookie_configured,
        status_code=200,
        rate_limited=False,
        auth_failed=False,
        message=message,
    )


def reddit_api_host(url: str) -> str:
    """Extract host from a Reddit URL (for logging/tests)."""
    return urlparse(url).netloc
