#!/usr/bin/env python3
"""Reddit RSS feed fetcher (no API key required).

Reddit closed self-service OAuth app creation and blocked anonymous JSON access.
Public RSS feeds remain available for search, subreddit listings, and comments.
"""

from __future__ import annotations

import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "LLM-Micro-Cap-trading-bot/1.0 (social sentiment research; Reddit RSS reader)"
)
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
REDDIT_BASE = "https://www.reddit.com"
SUBREDDIT_FROM_LINK = re.compile(r"reddit\.com/r/([^/]+)/", re.IGNORECASE)
POST_ID_FROM_LINK = re.compile(r"/comments/([a-z0-9]+)/", re.IGNORECASE)

# Hot feeds from these subs are warmed once per social_sentiment job (not per ticker).
SENTIMENT_RSS_SUBREDDITS = [
    "wallstreetbets",
    "stocks",
    "investing",
    "StockMarket",
    "pennystocks",
    "options",
    "Shortsqueeze",
    "microcap",
]


def _rss_min_interval_seconds() -> float:
    raw = os.getenv("REDDIT_RSS_MIN_INTERVAL", "8").strip()
    try:
        return max(float(raw), 2.0)
    except ValueError:
        return 8.0


def _rss_cooldown_seconds() -> float:
    raw = os.getenv("REDDIT_RSS_COOLDOWN_SECONDS", "90").strip()
    try:
        return max(float(raw), 10.0)
    except ValueError:
        return 90.0


def _rss_cache_ttl_seconds() -> float:
    raw = os.getenv("REDDIT_RSS_CACHE_TTL_SECONDS", "3300").strip()
    try:
        return max(float(raw), 60.0)
    except ValueError:
        return 3300.0


@dataclass
class RedditRssFetchResult:
    """Result of fetching a Reddit RSS feed."""

    status_code: int
    items: list[dict[str, Any]]
    rate_limited: bool


@dataclass
class RedditRssWarmStats:
    """Summary of a feed-cache warm pass."""

    subs_requested: int
    subs_fetched: int
    subs_rate_limited: int
    posts_cached: int
    skipped_cooldown: bool = False


class RedditRssRateLimiter:
    """Process-wide spacing and cooldown for Reddit RSS HTTP requests."""

    def __init__(self) -> None:
        self._last_request_at = 0.0
        self._cooldown_until = 0.0

    def in_cooldown(self) -> bool:
        return time.time() < self._cooldown_until

    def seconds_until_ready(self) -> float:
        now = time.time()
        wait_for_spacing = max(0.0, _rss_min_interval_seconds() - (now - self._last_request_at))
        wait_for_cooldown = max(0.0, self._cooldown_until - now)
        return max(wait_for_spacing, wait_for_cooldown)

    def wait_before_request(self) -> None:
        delay = self.seconds_until_ready()
        if delay > 0:
            logger.debug("Reddit RSS spacing: sleeping %.1fs", delay)
            time.sleep(delay)
        self._last_request_at = time.time()

    def note_rate_limited(self) -> None:
        self._cooldown_until = time.time() + _rss_cooldown_seconds()
        logger.warning(
            "Reddit RSS entering cooldown for %.0fs after 429",
            _rss_cooldown_seconds(),
        )

    def reset(self) -> None:
        self._last_request_at = 0.0
        self._cooldown_until = 0.0


_rss_rate_limiter = RedditRssRateLimiter()


def get_rss_rate_limiter() -> RedditRssRateLimiter:
    return _rss_rate_limiter


def reset_rss_rate_limiter() -> None:
    _rss_rate_limiter.reset()


def build_search_rss_url(query: str, *, sort: str = "relevance", time_filter: str = "week") -> str:
    params = {"q": query, "sort": sort, "t": time_filter}
    return f"{REDDIT_BASE}/search.rss?{urlencode(params)}"


def build_subreddit_search_rss_url(
    subreddit: str,
    query: str,
    *,
    sort: str = "new",
    time_filter: str = "week",
) -> str:
    params = {"q": query, "restrict_sr": "1", "sort": sort, "t": time_filter}
    return f"{REDDIT_BASE}/r/{subreddit}/search.rss?{urlencode(params)}"


def build_subreddit_rss_url(
    subreddit: str,
    *,
    sort: str = "hot",
    time_filter: str | None = None,
) -> str:
    path = f"/r/{subreddit}/{sort}.rss"
    if time_filter and sort in {"top", "controversial"}:
        return f"{REDDIT_BASE}{path}?{urlencode({'t': time_filter})}"
    return f"{REDDIT_BASE}{path}"


def build_comments_rss_url(post_id: str) -> str:
    return f"{REDDIT_BASE}/comments/{post_id}.rss"


def _parse_pub_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError, IndexError):
        return None


def _strip_html(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", cleaned).strip()


def _extract_subreddit(link: str) -> str:
    match = SUBREDDIT_FROM_LINK.search(link)
    return match.group(1) if match else ""


def _extract_post_id(link: str) -> str:
    match = POST_ID_FROM_LINK.search(link)
    return match.group(1) if match else ""


def post_mentions_ticker(post: dict[str, Any], ticker: str) -> bool:
    """Return True when title/body contains cashtag or word-boundary ticker."""
    full_text = (str(post.get("title", "")) + " " + str(post.get("selftext", ""))).upper()
    cashtag_pattern = r"\$" + re.escape(ticker) + r"\b"
    ticker_pattern = r"\b" + re.escape(ticker) + r"\b"
    return bool(
        re.search(cashtag_pattern, full_text, re.IGNORECASE)
        or re.search(ticker_pattern, full_text, re.IGNORECASE)
    )


def filter_posts_for_ticker(
    posts: list[dict[str, Any]],
    ticker: str,
    cutoff_time: datetime,
    *,
    allowed_subreddits: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Filter cached RSS posts to recent ticker mentions in allowed subs."""
    matched: list[dict[str, Any]] = []
    for post in posts:
        subreddit = str(post.get("subreddit", ""))
        if allowed_subreddits and subreddit.lower() not in allowed_subreddits:
            continue
        created_utc = post.get("created_utc", 0)
        if not created_utc:
            continue
        try:
            post_dt = datetime.fromtimestamp(float(created_utc), tz=UTC)
        except (TypeError, ValueError, OSError):
            continue
        if post_dt < cutoff_time:
            continue
        if post_mentions_ticker(post, ticker):
            matched.append(post)
    return matched


def _parse_rss_items(content: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(content)
    if root.tag == "rss":
        channel = root.find("channel")
        if channel is None:
            return []
        raw_items = channel.findall("item")
    elif root.tag.endswith("feed"):
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        raw_items = root.findall("atom:entry", ns)
    else:
        return []

    items: list[dict[str, Any]] = []
    for item in raw_items:
        if root.tag == "rss":
            title = str(item.findtext("title") or "").strip()
            link = str(item.findtext("link") or "").strip()
            description = str(item.findtext("description") or "")
            content_encoded = str(
                item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or ""
            )
            body = _strip_html(content_encoded or description)
            pub_date = _parse_pub_date(item.findtext("pubDate"))
            author = str(
                item.findtext("{http://www.w3.org/2005/Atom}author/{http://www.w3.org/2005/Atom}name")
                or ""
            ).strip()
        else:
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            title = str(item.findtext("atom:title", default="", namespaces=ns) or "").strip()
            link_elem = item.find('atom:link[@rel="alternate"]', ns)
            link = (link_elem.get("href") if link_elem is not None else "") or ""
            summary_text = str(item.findtext("atom:summary", default="", namespaces=ns) or "")
            content_text = str(item.findtext("atom:content", default="", namespaces=ns) or "")
            body = _strip_html(content_text or summary_text)
            updated = str(item.findtext("atom:updated", default="", namespaces=ns) or "")
            pub_date = _parse_pub_date(updated)
            author = str(item.findtext("atom:author/atom:name", default="", namespaces=ns) or "").strip()

        if not title and not link:
            continue

        created_utc = pub_date.timestamp() if pub_date else 0.0
        subreddit = _extract_subreddit(link)
        post_id = _extract_post_id(link)
        items.append(
            {
                "title": title,
                "selftext": body,
                "score": 0,
                "ups": 0,
                "num_comments": 0,
                "created_utc": created_utc,
                "url": link,
                "subreddit": subreddit,
                "permalink": link.replace(REDDIT_BASE, "") if link.startswith(REDDIT_BASE) else "",
                "id": post_id,
                "author": author,
            }
        )
    return items


def rss_items_to_listing_payload(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert RSS items into a Reddit JSON listing-shaped payload."""
    return {
        "data": {
            "children": [{"data": item} for item in items],
        }
    }


def fetch_reddit_rss(
    url: str,
    *,
    user_agent: str = BROWSER_USER_AGENT,
    timeout: int = 20,
    rate_limiter: RedditRssRateLimiter | None = None,
) -> RedditRssFetchResult:
    """Fetch and parse a Reddit RSS feed with shared spacing/cooldown."""
    limiter = rate_limiter or _rss_rate_limiter
    if limiter.in_cooldown():
        logger.info("Reddit RSS skip (cooldown active): %s", url)
        return RedditRssFetchResult(status_code=429, items=[], rate_limited=True)

    limiter.wait_before_request()
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning("Reddit RSS request failed for %s: %s", url, exc)
        return RedditRssFetchResult(status_code=0, items=[], rate_limited=False)

    if response.status_code == 429:
        limiter.note_rate_limited()
        logger.warning(
            "Reddit RSS rate limited url=%s (%s)",
            url,
            response.headers.get("Retry-After", "no Retry-After"),
        )
        return RedditRssFetchResult(status_code=429, items=[], rate_limited=True)

    if response.status_code != 200:
        logger.warning("Reddit RSS failed url=%s status=%s", url, response.status_code)
        return RedditRssFetchResult(
            status_code=response.status_code,
            items=[],
            rate_limited=False,
        )

    try:
        items = _parse_rss_items(response.content)
    except ET.ParseError as exc:
        logger.warning("Reddit RSS parse error for %s: %s", url, exc)
        return RedditRssFetchResult(status_code=response.status_code, items=[], rate_limited=False)

    return RedditRssFetchResult(status_code=200, items=items, rate_limited=False)


def path_to_rss_url(path: str, params: dict[str, Any] | None = None) -> str | None:
    """Map a Reddit JSON API path to the equivalent RSS URL."""
    params = params or {}
    normalized = path if path.startswith("/") else f"/{path}"

    if normalized == "/search" or normalized == "/search.json":
        query = str(params.get("q", "")).strip()
        if not query:
            return None
        return build_search_rss_url(
            query,
            sort=str(params.get("sort", "relevance")),
            time_filter=str(params.get("t", "week")),
        )

    sub_search = re.match(
        r"^/r/([^/]+)/search(?:\.json)?$",
        normalized,
        re.IGNORECASE,
    )
    if sub_search:
        query = str(params.get("q", "")).strip()
        if not query:
            return None
        return build_subreddit_search_rss_url(
            sub_search.group(1),
            query,
            sort=str(params.get("sort", "new")),
            time_filter=str(params.get("t", "week")),
        )

    sub_match = re.match(r"^/r/([^/]+)/(hot|new|top|rising)(?:\.json)?$", normalized, re.IGNORECASE)
    if sub_match:
        subreddit = sub_match.group(1)
        sort = sub_match.group(2).lower()
        time_filter = str(params.get("t")) if params.get("t") else None
        return build_subreddit_rss_url(subreddit, sort=sort, time_filter=time_filter)

    comments_match = re.match(r"^/comments/([a-z0-9]+)(?:\.json)?$", normalized, re.IGNORECASE)
    if comments_match:
        return build_comments_rss_url(comments_match.group(1))

    return None


@dataclass
class RedditFeedCache:
    """In-memory cache of recent posts from finance subreddit RSS feeds."""

    user_agent: str = BROWSER_USER_AGENT
    ttl_seconds: float = field(default_factory=_rss_cache_ttl_seconds)
    _posts: list[dict[str, Any]] = field(default_factory=list)
    _warmed_at: float = 0.0
    _last_stats: RedditRssWarmStats | None = None

    def is_fresh(self) -> bool:
        if not self._posts or self._warmed_at <= 0:
            return False
        return (time.time() - self._warmed_at) < self.ttl_seconds

    @property
    def last_stats(self) -> RedditRssWarmStats | None:
        return self._last_stats

    def warm(
        self,
        subreddits: list[str] | None = None,
        *,
        sort: str = "hot",
        force: bool = False,
    ) -> RedditRssWarmStats:
        """Fetch hot RSS feeds for finance subs (once per job, not per ticker)."""
        if not force and self.is_fresh():
            return RedditRssWarmStats(
                subs_requested=0,
                subs_fetched=0,
                subs_rate_limited=0,
                posts_cached=len(self._posts),
            )

        if _rss_rate_limiter.in_cooldown():
            stats = RedditRssWarmStats(
                subs_requested=len(subreddits or SENTIMENT_RSS_SUBREDDITS),
                subs_fetched=0,
                subs_rate_limited=0,
                posts_cached=len(self._posts),
                skipped_cooldown=True,
            )
            self._last_stats = stats
            return stats

        targets = subreddits or SENTIMENT_RSS_SUBREDDITS
        fetched = 0
        rate_limited = 0
        merged: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for subreddit in targets:
            if _rss_rate_limiter.in_cooldown():
                logger.warning("Reddit RSS warm stopped early — cooldown after r/%s", subreddit)
                break

            url = build_subreddit_rss_url(subreddit, sort=sort)
            result = fetch_reddit_rss(url, user_agent=self.user_agent)
            if result.rate_limited:
                rate_limited += 1
                continue
            if result.status_code != 200:
                continue

            fetched += 1
            for post in result.items:
                post_url = str(post.get("url", ""))
                if post_url and post_url in seen_urls:
                    continue
                if post_url:
                    seen_urls.add(post_url)
                merged.append(post)

        if merged:
            self._posts = merged
            self._warmed_at = time.time()

        stats = RedditRssWarmStats(
            subs_requested=len(targets),
            subs_fetched=fetched,
            subs_rate_limited=rate_limited,
            posts_cached=len(self._posts),
        )
        self._last_stats = stats
        logger.info(
            "Reddit RSS cache warm: %s/%s subs, %s posts cached (%s rate-limited)",
            fetched,
            len(targets),
            len(self._posts),
            rate_limited,
        )
        return stats

    def get_posts_for_ticker(
        self,
        ticker: str,
        cutoff_time: datetime,
        *,
        allowed_subreddits: set[str],
    ) -> list[dict[str, Any]]:
        return filter_posts_for_ticker(
            self._posts,
            ticker,
            cutoff_time,
            allowed_subreddits=allowed_subreddits,
        )

    def reset(self) -> None:
        self._posts = []
        self._warmed_at = 0.0
        self._last_stats = None
