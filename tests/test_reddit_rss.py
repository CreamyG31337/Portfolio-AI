"""Tests for Reddit RSS feed cache and rate limiting."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

WEB_DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "web_dashboard"
if str(WEB_DASHBOARD_PATH) not in sys.path:
    sys.path.insert(0, str(WEB_DASHBOARD_PATH))


@pytest.fixture(autouse=True)
def _reset_rss_state():
    from reddit_rss import reset_rss_rate_limiter

    reset_rss_rate_limiter()
    yield
    reset_rss_rate_limiter()


def test_filter_posts_for_ticker_matches_cashtag_and_subreddit():
    from reddit_rss import filter_posts_for_ticker

    now = datetime.now(UTC)
    posts = [
        {
            "title": "Big $NVDA breakout",
            "selftext": "",
            "subreddit": "stocks",
            "created_utc": now.timestamp(),
            "url": "https://example.com/1",
        },
        {
            "title": "NVDA mentioned in gardening",
            "selftext": "",
            "subreddit": "gardening",
            "created_utc": now.timestamp(),
            "url": "https://example.com/2",
        },
        {
            "title": "Old NVDA post",
            "selftext": "",
            "subreddit": "stocks",
            "created_utc": (now - timedelta(days=10)).timestamp(),
            "url": "https://example.com/3",
        },
    ]
    matched = filter_posts_for_ticker(
        posts,
        "NVDA",
        now - timedelta(days=7),
        allowed_subreddits={"stocks"},
    )
    assert len(matched) == 1
    assert matched[0]["url"] == "https://example.com/1"


def test_feed_cache_warm_dedupes_and_reuses_fresh_cache():
    from reddit_rss import RedditFeedCache, RedditRssFetchResult

    cache = RedditFeedCache(ttl_seconds=3600)

    def fake_fetch(url: str, **kwargs):
        return RedditRssFetchResult(
            status_code=200,
            items=[
                {
                    "title": "post",
                    "selftext": "",
                    "subreddit": "stocks",
                    "created_utc": datetime.now(UTC).timestamp(),
                    "url": url,
                }
            ],
            rate_limited=False,
        )

    with patch("reddit_rss.fetch_reddit_rss", side_effect=fake_fetch):
        stats1 = cache.warm(["stocks", "investing"])
        stats2 = cache.warm(["stocks", "investing"])

    assert stats1.subs_fetched == 2
    assert stats1.posts_cached == 2
    assert stats2.subs_requested == 0
    assert cache.is_fresh()


def test_rate_limiter_cooldown_blocks_immediate_retry():
    from reddit_rss import RedditRssRateLimiter, fetch_reddit_rss, reset_rss_rate_limiter

    reset_rss_rate_limiter()
    limiter = RedditRssRateLimiter()
    limiter.note_rate_limited()

    with patch("reddit_rss._rss_rate_limiter", limiter), patch("reddit_rss.requests.get") as get_mock:
        result = fetch_reddit_rss("https://www.reddit.com/r/stocks/hot.rss")

    assert result.rate_limited is True
    get_mock.assert_not_called()


def test_warm_sentiment_feed_cache_on_client(monkeypatch):
    from reddit_client import RedditClient, reset_reddit_client

    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    reset_reddit_client()
    client = RedditClient(min_interval=0)

    with patch.object(client.feed_cache, "warm") as warm_mock:
        warm_mock.return_value.subs_fetched = 3
        warm_mock.return_value.subs_requested = 8
        warm_mock.return_value.subs_rate_limited = 0
        warm_mock.return_value.posts_cached = 40
        warm_mock.return_value.skipped_cooldown = False
        stats = client.warm_sentiment_feed_cache()

    warm_mock.assert_called_once()
    assert stats.posts_cached == 40


def test_path_to_rss_url_maps_search_and_subreddit_paths():
    from reddit_rss import path_to_rss_url

    search_url = path_to_rss_url("/search", {"q": "$NVDA", "sort": "relevance", "t": "week"})
    assert search_url is not None
    assert "search.rss" in search_url
    assert "NVDA" in search_url

    sub_search = path_to_rss_url(
        "/r/stocks/search",
        {"q": "$NVDA", "sort": "new", "t": "week", "restrict_sr": "1"},
    )
    assert sub_search is not None
    assert "/r/stocks/search.rss" in sub_search

    hot_url = path_to_rss_url("/r/wallstreetbets/hot", {})
    assert hot_url == "https://www.reddit.com/r/wallstreetbets/hot.rss"
