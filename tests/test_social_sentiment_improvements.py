"""Tests for social sentiment runtime and logging improvements."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path


WEB_DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "web_dashboard"
if str(WEB_DASHBOARD_PATH) not in sys.path:
    sys.path.insert(0, str(WEB_DASHBOARD_PATH))


def test_reddit_search_parser_filters_to_whitelisted_recent_ticker_mentions():
    from social_service import SocialSentimentService

    service = SocialSentimentService.__new__(SocialSentimentService)
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=7)
    payload = {
        "data": {
            "children": [
                {
                    "data": {
                        "title": "Big $AAPL breakout",
                        "selftext": "Apple momentum looks strong",
                        "ups": 12,
                        "num_comments": 3,
                        "created_utc": now.timestamp(),
                        "url": "https://example.com/aapl",
                        "subreddit": "stocks",
                    }
                },
                {
                    "data": {
                        "title": "AAPL from an off-topic sub",
                        "selftext": "",
                        "ups": 99,
                        "num_comments": 1,
                        "created_utc": now.timestamp(),
                        "url": "https://example.com/offtopic",
                        "subreddit": "gardening",
                    }
                },
                {
                    "data": {
                        "title": "Market thread",
                        "selftext": "No target ticker here",
                        "ups": 5,
                        "num_comments": 0,
                        "created_utc": now.timestamp(),
                        "url": "https://example.com/no-mention",
                        "subreddit": "stocks",
                    }
                },
                {
                    "data": {
                        "title": "$AAPL old post",
                        "selftext": "",
                        "ups": 7,
                        "num_comments": 0,
                        "created_utc": (now - timedelta(days=10)).timestamp(),
                        "url": "https://example.com/old",
                        "subreddit": "stocks",
                    }
                },
            ]
        }
    }

    posts = service._parse_reddit_search_posts(payload, "AAPL", cutoff)

    assert len(posts) == 1
    assert posts[0]["url"] == "https://example.com/aapl"
    assert posts[0]["subreddit"] == "stocks"


def test_get_last_processed_at_returns_none_for_missing_tickers():
    from social_service import SocialSentimentService

    timestamp = datetime(2026, 5, 21, 12, 0, 0)

    class FakePostgres:
        def execute_query(self, query, params):
            assert "MAX(created_at)" in query
            assert params == (["AAPL", "MSFT"],)
            return [{"ticker": "AAPL", "last_processed": timestamp}]

    service = SocialSentimentService.__new__(SocialSentimentService)
    service.postgres = FakePostgres()

    result = service.get_last_processed_at(["AAPL", "MSFT"])

    assert result == {"AAPL": timestamp, "MSFT": None}


def test_sort_tickers_oldest_first_handles_never_seen_and_naive_datetimes():
    from web_dashboard.scheduler.jobs_social import _sort_tickers_oldest_first

    old_naive = datetime(2026, 5, 18, 9, 0, 0)
    newer_aware = datetime(2026, 5, 20, 9, 0, 0, tzinfo=UTC)

    sorted_tickers, never_count, oldest_existing = _sort_tickers_oldest_first(
        ["MSFT", "AAPL", "ZZZ"],
        {"MSFT": newer_aware, "AAPL": old_naive, "ZZZ": None},
    )

    assert sorted_tickers == ["ZZZ", "AAPL", "MSFT"]
    assert never_count == 1
    assert oldest_existing == old_naive.replace(tzinfo=UTC)


def test_social_sentiment_summary_distinguishes_deferred_from_timeouts():
    from web_dashboard.scheduler.jobs_social import _build_social_sentiment_summary

    summary = _build_social_sentiment_summary(
        total_tickers=107,
        attempted_count=24,
        success_count=24,
        error_count=0,
        no_data_count=0,
        per_ticker_timeout_count=0,
        skipped_count=83,
        reddit_429_count=0,
        reddit_auth_fail_count=0,
        duration_min=50.5,
    )

    assert summary == (
        "Social sentiment: 24/107 attempted in 50.5m "
        "(24 ok, 0 errors, 0 no-data, 0 per-ticker-timeouts). "
        "Job cap reached - 83 tickers deferred to next run"
    )


def test_social_sentiment_summary_includes_reddit_failure_counts():
    from web_dashboard.scheduler.jobs_social import _build_social_sentiment_summary

    summary = _build_social_sentiment_summary(
        total_tickers=10,
        attempted_count=10,
        success_count=5,
        error_count=0,
        no_data_count=5,
        per_ticker_timeout_count=0,
        skipped_count=0,
        reddit_429_count=3,
        reddit_auth_fail_count=1,
        duration_min=12.0,
    )

    assert "reddit 429=3" in summary
    assert "reddit auth_fail=1" in summary


def test_fetch_reddit_sentiment_uses_rss_cache_without_global_search():
    from datetime import UTC, datetime, timedelta
    from unittest.mock import MagicMock

    from reddit_rss import RedditFeedCache, RedditRssWarmStats
    from social_service import SocialSentimentService

    service = SocialSentimentService.__new__(SocialSentimentService)
    service.ollama = None

    now = datetime.now(UTC)
    cache = RedditFeedCache(ttl_seconds=3600)
    cache._posts = [
        {
            "title": "NVDA earnings beat",
            "selftext": "",
            "subreddit": "stocks",
            "created_utc": now.timestamp(),
            "url": "https://reddit.com/r/stocks/comments/abc/nvda",
            "ups": 0,
            "num_comments": 0,
        }
    ]
    cache._warmed_at = now.timestamp()

    warm_mock = MagicMock(
        return_value=RedditRssWarmStats(
            subs_requested=0,
            subs_fetched=0,
            subs_rate_limited=0,
            posts_cached=1,
        )
    )
    get_json_mock = MagicMock()

    class FakeReddit:
        oauth_enabled = False
        rss_enabled = True
        feed_cache = cache
        warm_sentiment_feed_cache = warm_mock
        get_json = get_json_mock

        @staticmethod
        def check_robots_allowed(_url: str) -> bool:
            return True

    service.reddit = FakeReddit()
    result = service.fetch_reddit_sentiment("NVDA", max_duration=30)

    assert result["volume"] == 1
    get_json_mock.assert_not_called()
    warm_mock.assert_called_once()
