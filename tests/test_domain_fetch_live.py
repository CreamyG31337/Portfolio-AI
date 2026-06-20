"""
Live canary tests for domain fetch strategies.

Three-layer testing (run in CI vs. on a schedule):

1. **Unit** (``tests/test_domain_fetch_strategies.py``) — strategy matching + headers
2. **Fixtures** (same file) — saved HTML proves extraction/paywall detection logic
3. **Live canaries** (this file, opt-in) — real publisher URLs

Live canaries split into:

- **Transport** (default with ``RUN_LIVE_FETCH=1``): HTTP fetch succeeds, no bot
  blockpage, HTML returned. Does *not* require beating the paywall.
- **Extraction** (``LIVE_FETCH_STRICT=1``): full ``extract_article_content`` success.
  Hard paywalls (NYT, FT) may fail even when headers are correct — that failure
  is signal to refresh fixtures/strategies or rely on archive fallback.

Commands:

    # Weekly/canary job — verifies publishers still respond to our headers
    RUN_LIVE_FETCH=1 pytest tests/test_domain_fetch_live.py -m live_fetch -v

    # Stricter check — fails if paywall not bypassed (often fails for NYT/FT)
    RUN_LIVE_FETCH=1 LIVE_FETCH_STRICT=1 pytest tests/test_domain_fetch_live.py -m live_fetch -v

Override stale URLs:

    LIVE_FETCH_NYT_URL=...
    LIVE_FETCH_FT_URL=...
"""

from __future__ import annotations

import os

import pytest
import requests

from web_dashboard import research_utils
from web_dashboard.domain_fetch_strategies import (
    LIVE_CANARY_MIN_CONTENT_LEN,
    apply_domain_fetch_headers,
    match_domain_fetch_strategy,
)
from web_dashboard.paywall_detector import detect_paywall

RUN_LIVE_FETCH = os.getenv("RUN_LIVE_FETCH", "").lower() in ("1", "true", "yes")
LIVE_FETCH_STRICT = os.getenv("LIVE_FETCH_STRICT", "").lower() in ("1", "true", "yes")

DEFAULT_LIVE_URLS: dict[str, str] = {
    "nytimes_googlebot": (
        "https://www.nytimes.com/2024/03/15/business/stock-market-record-high.html"
    ),
    "ft_social_referer": (
        "https://www.ft.com/content/5348ec64-010e-40f4-a27e-6d1252a0c537"
    ),
}

ENV_URL_KEYS: dict[str, str] = {
    "nytimes_googlebot": "LIVE_FETCH_NYT_URL",
    "ft_social_referer": "LIVE_FETCH_FT_URL",
}

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _require_live_fetch() -> None:
    if not RUN_LIVE_FETCH:
        pytest.skip(
            "Live publisher canaries are opt-in. Set RUN_LIVE_FETCH=1 to run them."
        )


def _live_url(strategy_id: str) -> str:
    env_key = ENV_URL_KEYS[strategy_id]
    return os.getenv(env_key, DEFAULT_LIVE_URLS[strategy_id]).strip()


def _assert_strategy_for_url(strategy_id: str, url: str) -> None:
    strategy = match_domain_fetch_strategy(url)
    assert strategy is not None, f"No strategy registered for {url}"
    assert strategy.id == strategy_id


def _assert_live_transport(strategy_id: str, url: str) -> None:
    _assert_strategy_for_url(strategy_id, url)
    headers = apply_domain_fetch_headers(BASE_HEADERS, url)
    try:
        response = requests.get(url, headers=headers, timeout=45)
        response.raise_for_status()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        if strategy_id == "nytimes_googlebot" and status == 403:
            pytest.skip(
                "NYT returned 403 to Googlebot headers from this network — "
                "strategy may only work via FlareSolverr or from other IPs"
            )
        raise

    html = response.text

    assert len(html) >= 500, f"HTML too short for {strategy_id} ({len(html)} bytes)"
    assert not research_utils.contains_access_challenge(html), (
        f"Bot/access challenge page for {strategy_id}; headers may be blocked"
    )


def _assert_live_extraction(strategy_id: str, url: str) -> None:
    _assert_strategy_for_url(strategy_id, url)

    if research_utils.trafilatura is None:
        pytest.fail("trafilatura must be installed for strict live fetch canaries")

    result = research_utils.extract_article_content(url, max_seconds=120.0)

    assert result["success"] is True, (
        f"Live extraction failed for {strategy_id}: "
        f"error={result.get('error')!r} url={url}"
    )

    content = result.get("content") or ""
    min_len = LIVE_CANARY_MIN_CONTENT_LEN[strategy_id]
    assert len(content) >= min_len, (
        f"Extracted content too short for {strategy_id} ({len(content)} < {min_len})"
    )

    paywall = detect_paywall(content, url)
    assert paywall is None, (
        f"Paywall still detected for {strategy_id} ({paywall!r}); strategy may be stale"
    )


@pytest.mark.live_fetch
@pytest.mark.parametrize("strategy_id", ["nytimes_googlebot", "ft_social_referer"])
def test_live_transport_canary(strategy_id: str) -> None:
    """Publisher responds with HTML (not a bot blockpage) when strategy headers are used."""
    _require_live_fetch()
    _assert_live_transport(strategy_id, _live_url(strategy_id))


@pytest.mark.live_fetch
@pytest.mark.parametrize("strategy_id", ["nytimes_googlebot", "ft_social_referer"])
def test_live_extraction_canary(strategy_id: str) -> None:
    """Strict: full article text extracted without paywall (opt-in via LIVE_FETCH_STRICT=1)."""
    _require_live_fetch()
    if not LIVE_FETCH_STRICT:
        pytest.skip(
            "Strict extraction canaries are opt-in. Set LIVE_FETCH_STRICT=1 to run them."
        )
    _assert_live_extraction(strategy_id, _live_url(strategy_id))
