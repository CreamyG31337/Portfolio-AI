#!/usr/bin/env python3
"""Live timing benchmark for Reddit RSS job paths.

Run: python web_dashboard/scripts/reddit_rss_timing_benchmark.py
"""

from __future__ import annotations

import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WEB))

from reddit_client import RedditClient, reset_reddit_client  # noqa: E402
from reddit_rss import (  # noqa: E402
    SENTIMENT_RSS_SUBREDDITS,
    fetch_reddit_rss,
    reset_rss_rate_limiter,
)
from social_service import STOCK_SUBREDDIT_SET, SocialSentimentService  # noqa: E402


def _sec(start: float) -> float:
    return round(time.time() - start, 2)


def main() -> None:
    if sys.platform == "win32":
        import io

        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print("=== Reddit RSS timing benchmark ===\n")
    reset_reddit_client()
    reset_rss_rate_limiter()
    client = RedditClient()

    print(f"OAuth enabled: {client.oauth_enabled}")
    print(f"RSS enabled:   {client.rss_enabled}")
    print(f"Client min_interval: {client.min_interval}s")
    print(f"Subs in cache warm: {len(SENTIMENT_RSS_SUBREDDITS)}\n")

    # 1) Cache warm (social_sentiment job start)
    t0 = time.time()
    warm = client.warm_sentiment_feed_cache(force=True)
    warm_elapsed = _sec(t0)
    print(
        f"[1] Cache warm: {warm_elapsed}s | "
        f"fetched {warm.subs_fetched}/{warm.subs_requested} subs, "
        f"{warm.posts_cached} posts, {warm.subs_rate_limited} rate-limited, "
        f"cooldown_skip={warm.skipped_cooldown}"
    )

    # 2) Per-ticker local filter (10 tickers, should be instant)
    tickers = ["NVDA", "AAPL", "TSLA", "AMD", "MSFT", "GOOGL", "META", "AMZN", "PLTR", "SOFI"]
    cutoff = datetime.now(UTC) - timedelta(days=7)
    t0 = time.time()
    hits = 0
    for ticker in tickers:
        posts = client.feed_cache.get_posts_for_ticker(
            ticker, cutoff, allowed_subreddits=STOCK_SUBREDDIT_SET
        )
        hits += len(posts)
        client.warm_sentiment_feed_cache()  # mirrors fetch_reddit_sentiment per-ticker call
    filter_elapsed = _sec(t0)
    print(f"[2] 10 tickers cache filter + redundant warm calls: {filter_elapsed}s | {hits} total post hits")

    # 3) fetch_reddit_sentiment for 3 tickers (full service path)
    svc = SocialSentimentService.__new__(SocialSentimentService)
    svc.reddit = client
    svc.ollama = None
    t0 = time.time()
    svc_results = []
    for ticker in tickers[:3]:
        t1 = time.time()
        result = svc.fetch_reddit_sentiment(ticker, max_duration=120)
        svc_results.append((ticker, _sec(t1), result.get("volume", 0), result.get("reddit_error_codes", [])))
    svc_elapsed = _sec(t0)
    print(f"[3] fetch_reddit_sentiment x3: {svc_elapsed}s total")
    for ticker, elapsed, volume, errors in svc_results:
        print(f"    {ticker}: {elapsed}s volume={volume} errors={errors}")

    # 4) Double-spacing check: get_json vs direct fetch_reddit_rss
    reset_rss_rate_limiter()
    url = "https://www.reddit.com/r/stocks/hot.rss"
    t0 = time.time()
    client.get_json("/r/stocks/hot", params={"limit": 5})
    get_json_elapsed = _sec(t0)
    t0 = time.time()
    fetch_reddit_rss(url)
    direct_elapsed = _sec(t0)
    print(
        f"[4] Single /r/stocks/hot request: get_json={get_json_elapsed}s, "
        f"direct fetch_reddit_rss={direct_elapsed}s (double-spacing if get_json >> direct)"
    )

    # 5) Subreddit scanner slice: one sub listing + up to 3 comment fetches
    reset_rss_rate_limiter()
    t0 = time.time()
    listing = client.get_json("/r/pennystocks/top", params={"t": "day", "limit": 5})
    listing_elapsed = _sec(t0)
    comment_times: list[float] = []
    post_ids: list[str] = []
    if listing.payload and listing.payload.get("data", {}).get("children"):
        for child in listing.payload["data"]["children"][:3]:
            pid = child.get("data", {}).get("id")
            if pid:
                post_ids.append(pid)
    for pid in post_ids:
        t1 = time.time()
        client.get_json(f"/comments/{pid}", params={"sort": "top", "limit": 5})
        comment_times.append(_sec(t1))
    scanner_slice_elapsed = _sec(t0)
    print(
        f"[5] Scanner slice (pennystocks top + {len(post_ids)} comment fetches): "
        f"{scanner_slice_elapsed}s (listing={listing_elapsed}s, comments={comment_times})"
    )

    # 6) Extrapolate full scanner (8 subs, 15 posts, 15 comments each - worst case)
    extrapolated_8_subs = (listing_elapsed + sum(comment_times)) * 8
    rss_comment_cap = 3
    extrapolated_rss_scanner = (listing_elapsed + (rss_comment_cap * (sum(comment_times) / max(len(comment_times), 1)))) * 8
    print(
        f"[6] Extrapolated 8-sub scanner: oauth-worst ~{extrapolated_8_subs:.0f}s | "
        f"rss-capped ({rss_comment_cap} comments/sub) ~{extrapolated_rss_scanner:.0f}s"
    )

    print("\n=== Summary ===")
    print(f"social_sentiment Reddit HTTP (warm once): ~{warm_elapsed}s")
    print(f"social_sentiment per-ticker (cache hit path): ~{filter_elapsed / 10:.3f}s avg over 10 tickers")
    print(f"subreddit_scanner (measured slice): {scanner_slice_elapsed}s for 1 sub + {len(post_ids)} comments")


if __name__ == "__main__":
    main()
