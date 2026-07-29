"""Spaced live demo - run with: python web_dashboard/scripts/reddit_rss_live_demo.py"""
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WEB))

from reddit_client import get_reddit_client, reset_reddit_client
from reddit_rss import SENTIMENT_RSS_SUBREDDITS
from social_service import SocialSentimentService


def main() -> None:
    if sys.platform == "win32":
        import io

        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print("=== Reddit RSS cache demo (8s spacing via rate limiter) ===\n")
    print(f"Warming {len(SENTIMENT_RSS_SUBREDDITS)} finance sub feeds once per job...\n")

    reset_reddit_client()
    client = get_reddit_client()
    warm_stats = client.warm_sentiment_feed_cache(force=True)
    print(
        f"Cache warm: {warm_stats.subs_fetched}/{warm_stats.subs_requested} subs, "
        f"{warm_stats.posts_cached} posts ({warm_stats.subs_rate_limited} rate-limited)"
    )
    if warm_stats.skipped_cooldown:
        print("  (cooldown active — using stale cache if any)")

    cutoff = datetime.now(UTC) - timedelta(days=7)
    for ticker in ("NVDA", "AAPL", "TSLA"):
        posts = client.feed_cache.get_posts_for_ticker(
            ticker,
            cutoff,
            allowed_subreddits={s.lower() for s in SENTIMENT_RSS_SUBREDDITS},
        )
        print(f"\n{ticker}: {len(posts)} posts from cache (no per-ticker HTTP)")
        for post in posts[:3]:
            print(f"  - r/{post.get('subreddit')} | {post.get('title', '')[:65]}")

    print("\n=== fetch_reddit_sentiment('NVDA') via service ===")
    svc = SocialSentimentService.__new__(SocialSentimentService)
    svc.reddit = client
    svc.ollama = None
    result = svc.fetch_reddit_sentiment("NVDA", max_duration=120)
    print(
        f"volume={result.get('volume')} sentiment={result.get('sentiment_label')} "
        f"errors={result.get('reddit_error_codes')}"
    )
    for post in result.get("raw_data") or []:
        print(f"  - r/{post.get('subreddit')} | {post.get('title', '')[:65]}")

    useful = warm_stats.posts_cached > 0 and (result.get("volume") or 0) >= 0
    print(
        f"\nVERDICT: {'Useful - cache-based RSS avoids per-ticker search 429s' if useful else 'Limited - rate limited or empty cache'}"
    )


if __name__ == "__main__":
    main()
