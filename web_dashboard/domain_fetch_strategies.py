#!/usr/bin/env python3
"""
Domain-specific HTTP fetch strategies for research article extraction.

Inspired by community paywall-proxy rules (e.g. ladder-rules) but limited to
server-side header/cookie tricks that work without a browser rendering step.

Each strategy is covered by:
- unit tests (header selection),
- HTML fixture tests (extraction pipeline),
- opt-in live canaries (``pytest -m live_fetch`` with ``RUN_LIVE_FETCH=1``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional
from urllib.parse import urlparse

# Minimum extracted plain-text length for live canary tests per strategy.
LIVE_CANARY_MIN_CONTENT_LEN: dict[str, int] = {
    "nytimes_googlebot": 400,
    "ft_social_referer": 400,
}


@dataclass(frozen=True)
class DomainFetchStrategy:
    """Extra request headers to apply when fetching a matching publisher."""

    id: str
    domain_suffixes: tuple[str, ...]
    extra_headers: Mapping[str, str]


DOMAIN_FETCH_STRATEGIES: tuple[DomainFetchStrategy, ...] = (
    DomainFetchStrategy(
        id="nytimes_googlebot",
        domain_suffixes=("nytimes.com", "time.com"),
        extra_headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; Googlebot/2.1; "
                "+http://www.google.com/bot.html)"
            ),
            "Referer": "https://www.google.com/",
            "Cookie": "nyt-a=; nyt-gdpr=0; nyt-geo=DE; nyt-privacy=1",
        },
    ),
    DomainFetchStrategy(
        id="ft_social_referer",
        domain_suffixes=("ft.com",),
        extra_headers={
            "Referer": "https://t.co/x?amp=1",
        },
    ),
)


def normalize_hostname(url_or_host: str) -> str:
    """Return lowercase hostname without ``www.`` or port."""
    value = url_or_host.strip()
    if "://" in value:
        value = urlparse(value).netloc or value
    value = value.lower()
    if value.startswith("www."):
        value = value[4:]
    if ":" in value:
        value = value.split(":", 1)[0]
    return value


def match_domain_fetch_strategy(url: str) -> Optional[DomainFetchStrategy]:
    """Return the fetch strategy for ``url``, or ``None`` if no preset applies."""
    host = normalize_hostname(url)
    if not host:
        return None

    for strategy in DOMAIN_FETCH_STRATEGIES:
        for suffix in strategy.domain_suffixes:
            if host == suffix or host.endswith(f".{suffix}"):
                return strategy
    return None


def apply_domain_fetch_headers(
    base_headers: Mapping[str, str],
    url: str,
) -> dict[str, str]:
    """Merge domain-specific headers onto ``base_headers`` when a strategy matches."""
    merged = dict(base_headers)
    strategy = match_domain_fetch_strategy(url)
    if strategy is not None:
        merged.update(strategy.extra_headers)
    return merged
