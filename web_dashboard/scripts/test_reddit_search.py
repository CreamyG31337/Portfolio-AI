#!/usr/bin/env python3
"""Manual Reddit search smoke test (RSS by default, OAuth if configured)."""

import sys
import time
from datetime import datetime
from pathlib import Path

current_dir = Path(__file__).resolve().parent
web_dashboard = current_dir.parent
if str(web_dashboard) not in sys.path:
    sys.path.insert(0, str(web_dashboard))

from reddit_client import check_reddit_connectivity, get_reddit_client, reset_reddit_client


def test_reddit_search(ticker: str) -> None:
    print(f"\n{'=' * 50}")
    print(f"Testing Reddit Search for: {ticker}")
    print(f"{'=' * 50}")

    client = get_reddit_client()
    queries = [f"${ticker}", ticker]

    for query in queries:
        print(f"\nQuery: '{query}'")
        print("-" * 30)

        result = client.get_json(
            "/search",
            params={"q": query, "sort": "new", "t": "day", "limit": 5},
        )

        transport = "rss" if result.used_rss else "oauth"
        if result.rate_limited or result.status_code == 429:
            print("Error: 429 rate limited")
            continue
        if result.payload is None:
            print(f"Error: HTTP {result.status_code} (transport={transport})")
            continue

        posts = []
        children = (result.payload.get("data") or {}).get("children") or []
        for child in children:
            post = child.get("data", {})
            if not post:
                continue
            posts.append(
                {
                    "title": post.get("title", "N/A")[:80],
                    "subreddit": post.get("subreddit", "N/A"),
                    "score": post.get("score", 0),
                    "created": datetime.fromtimestamp(post.get("created_utc", 0)).strftime(
                        "%H:%M:%S"
                    ),
                    "url": post.get("url", ""),
                }
            )

        if not posts:
            print("   (No results found)")
        else:
            for post in posts:
                print(f"   [r/{post['subreddit']}] {post['title']}...")
                print(f"    Score: {post['score']} | Time: {post['created']} | via {transport}")

        time.sleep(2)


if __name__ == "__main__":
    reset_reddit_client()
    status = check_reddit_connectivity()
    if not status.ok:
        print(f"Reddit connectivity failed: {status.message}")
        sys.exit(1)

    print(f"Reddit OK: {status.message}")
    for ticker in ["LUNR", "NVDA", "CAT", "AI", "GOOD"]:
        test_reddit_search(ticker)
