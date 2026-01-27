#!/usr/bin/env python3
"""
Twitter/X Sentiment Collection - Human-Like Browsing Approach
==============================================================

This approach simulates a REAL HUMAN browsing Twitter to avoid bans:
- No authentication required (no account bans!)
- Slow, deliberate requests (looks like real browsing)
- Random delays between actions (human-like)
- User-Agent rotation (looks like different browsers)
- Uses public Twitter endpoints (no login needed)

Perfect for social sentiment where you don't need real-time data.

Strategy:
1. Use Playwright/Selenium to actually browse Twitter like a human
2. Fallback to Nitter instances (privacy-focused Twitter frontends)
3. Aggressive rate limiting (5-10 seconds between searches)
4. Random "think time" between actions
"""

import os
import sys
import time
import random
import logging
import requests
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class HumanLikeTwitterCollector:
    """Collects Twitter data by simulating human browsing patterns"""

    def __init__(self):
        self.last_request_time = 0
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ]

        # Active Nitter instances (as of Jan 2026)
        # These are privacy-focused Twitter frontends that don't require login
        self.nitter_instances = [
            'https://nitter.net',
            'https://nitter.poast.org',
            'https://nitter.privacydev.net',
            'https://nitter.lunar.icu',
            'https://nitter.1d4.us',
            'https://nitter.kavin.rocks',
            'https://nitter.unixfox.eu',
            'https://nitter.bus-hit.me'
        ]

        # Track which Nitter instances are working
        self.working_instances = []

    def _human_delay(self, min_seconds: float = 3.0, max_seconds: float = 8.0) -> None:
        """Wait like a human between actions

        Args:
            min_seconds: Minimum wait time
            max_seconds: Maximum wait time
        """
        # Enforce minimum time between requests
        now = time.time()
        elapsed = now - self.last_request_time
        min_interval = min_seconds

        if elapsed < min_interval:
            additional_wait = min_interval - elapsed
            time.sleep(additional_wait)

        # Add random "think time" like a human
        think_time = random.uniform(0, max_seconds - min_seconds)
        time.sleep(think_time)

        self.last_request_time = time.time()

        logger.debug(f"Human-like delay: {min_interval + think_time:.1f}s")

    def _get_random_user_agent(self) -> str:
        """Get a random User-Agent to rotate browsers"""
        return random.choice(self.user_agents)

    def search_nitter(self, ticker: str, max_tweets: int = 20) -> Dict[str, Any]:
        """Search Twitter via Nitter instances (no auth required!)

        Nitter is a privacy-focused Twitter frontend that:
        - Doesn't require login
        - Has RSS feeds
        - Multiple public instances
        - Less aggressive rate limiting

        Args:
            ticker: Ticker symbol to search
            max_tweets: Maximum tweets to collect

        Returns:
            Dictionary with tweets and metadata
        """
        logger.info(f"Searching Nitter for ${ticker}...")

        # Build search query
        query = f"${ticker}"
        tweets = []

        # Try Nitter instances until one works
        for instance in self.nitter_instances:
            try:
                # Human-like delay before request
                self._human_delay(min_seconds=3.0, max_seconds=8.0)

                # Build Nitter search URL
                search_url = f"{instance}/search?f=tweets&q={quote_plus(query)}"

                headers = {
                    'User-Agent': self._get_random_user_agent(),
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1'
                }

                logger.debug(f"Trying Nitter instance: {instance}")

                response = requests.get(
                    search_url,
                    headers=headers,
                    timeout=15
                )

                if response.status_code == 200:
                    logger.info(f"✅ Nitter instance working: {instance}")

                    # Parse HTML
                    soup = BeautifulSoup(response.text, 'html.parser')

                    # Find tweet containers
                    tweet_containers = soup.find_all('div', class_='timeline-item')

                    logger.debug(f"Found {len(tweet_containers)} tweet containers")

                    for container in tweet_containers[:max_tweets]:
                        try:
                            # Extract tweet data from Nitter HTML
                            tweet_content = container.find('div', class_='tweet-content')
                            if not tweet_content:
                                continue

                            text = tweet_content.get_text(strip=True)

                            # Validate ticker mention
                            if ticker.upper() not in text.upper() and f"${ticker}" not in text:
                                continue

                            # Extract metadata
                            username_elem = container.find('a', class_='username')
                            username = username_elem.get_text(strip=True) if username_elem else 'unknown'

                            date_elem = container.find('span', class_='tweet-date')
                            date_text = date_elem.get_text(strip=True) if date_elem else ''

                            # Extract engagement (Nitter shows this)
                            stats = container.find('div', class_='tweet-stats')
                            likes = 0
                            retweets = 0

                            if stats:
                                # Parse stats (format: "X replies • Y retweets • Z likes")
                                stats_text = stats.get_text()
                                likes_match = re.search(r'(\d+)\s*likes?', stats_text)
                                retweets_match = re.search(r'(\d+)\s*retweets?', stats_text)

                                if likes_match:
                                    likes = int(likes_match.group(1))
                                if retweets_match:
                                    retweets = int(retweets_match.group(1))

                            engagement_score = likes + (retweets * 2)

                            tweets.append({
                                'text': text,
                                'author': username,
                                'date': date_text,
                                'likes': likes,
                                'retweets': retweets,
                                'engagement_score': engagement_score,
                                'source': 'nitter',
                                'instance': instance
                            })

                        except Exception as e:
                            logger.debug(f"Error parsing tweet container: {e}")
                            continue

                    if tweets:
                        logger.info(f"✅ Collected {len(tweets)} tweets from Nitter")
                        self.working_instances.append(instance)

                        return {
                            'ticker': ticker,
                            'tweets': tweets,
                            'count': len(tweets),
                            'method': 'nitter',
                            'instance': instance
                        }

                else:
                    logger.debug(f"Nitter instance returned {response.status_code}: {instance}")

            except requests.exceptions.Timeout:
                logger.debug(f"Timeout on Nitter instance: {instance}")
                continue
            except Exception as e:
                logger.debug(f"Error with Nitter instance {instance}: {e}")
                continue

        # All instances failed
        logger.warning(f"⚠️  All Nitter instances failed for {ticker}")
        return {
            'ticker': ticker,
            'tweets': [],
            'count': 0,
            'error': 'All Nitter instances unavailable'
        }

    def search_twitter_public(self, ticker: str, max_tweets: int = 20) -> Dict[str, Any]:
        """Search Twitter using public endpoints (no login required)

        Twitter allows some public searches without authentication.
        This uses guest tokens which are temporary and don't require an account.

        Args:
            ticker: Ticker symbol to search
            max_tweets: Maximum tweets to collect

        Returns:
            Dictionary with tweets and metadata
        """
        logger.info(f"Searching Twitter public API for ${ticker}...")

        try:
            # Human-like delay
            self._human_delay(min_seconds=5.0, max_seconds=10.0)

            # Get guest token (Twitter allows this without auth)
            guest_token_url = "https://api.twitter.com/1.1/guest/activate.json"

            headers = {
                'User-Agent': self._get_random_user_agent(),
                'Authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA'
            }

            response = requests.post(guest_token_url, headers=headers, timeout=10)

            if response.status_code == 200:
                guest_token = response.json().get('guest_token')

                if not guest_token:
                    logger.warning("Failed to get guest token")
                    return {'ticker': ticker, 'tweets': [], 'error': 'No guest token'}

                logger.debug(f"Got guest token: {guest_token[:20]}...")

                # Search with guest token
                self._human_delay(min_seconds=3.0, max_seconds=6.0)

                search_url = "https://api.twitter.com/2/search/adaptive.json"
                query = f"${ticker}"

                search_headers = {
                    **headers,
                    'x-guest-token': guest_token
                }

                params = {
                    'q': query,
                    'count': max_tweets,
                    'query_source': 'typed_query',
                    'pc': '1',
                    'spelling_corrections': '1'
                }

                search_response = requests.get(
                    search_url,
                    headers=search_headers,
                    params=params,
                    timeout=15
                )

                if search_response.status_code == 200:
                    data = search_response.json()
                    # Parse tweets from response
                    # NOTE: Twitter's response format changes frequently
                    logger.info("✅ Got response from Twitter public API")
                    logger.debug(f"Response keys: {data.keys()}")

                    # This would need to be updated based on current Twitter API structure
                    return {
                        'ticker': ticker,
                        'tweets': [],
                        'count': 0,
                        'method': 'twitter_public',
                        'note': 'Need to parse Twitter API response structure'
                    }
                else:
                    logger.warning(f"Twitter search failed: {search_response.status_code}")

            else:
                logger.warning(f"Failed to get guest token: {response.status_code}")

        except Exception as e:
            logger.error(f"Error with Twitter public API: {e}")

        return {
            'ticker': ticker,
            'tweets': [],
            'error': 'Twitter public API failed'
        }

    def test_multiple_tickers(self, tickers: List[str]) -> Dict[str, Any]:
        """Test human-like collection for multiple tickers

        Args:
            tickers: List of ticker symbols

        Returns:
            Dictionary with results per ticker
        """
        logger.info(f"\n{'=' * 80}")
        logger.info(f"Testing Human-Like Twitter Collection")
        logger.info(f"{'=' * 80}\n")

        results = {}

        for i, ticker in enumerate(tickers, 1):
            logger.info(f"\n--- Ticker {i}/{len(tickers)}: {ticker} ---")

            # Try Nitter first (most reliable, no auth needed)
            result = self.search_nitter(ticker, max_tweets=10)

            if result.get('count', 0) > 0:
                logger.info(f"✅ {ticker}: {result['count']} tweets via Nitter")
            else:
                logger.warning(f"⚠️  {ticker}: No tweets found")

            results[ticker] = result

            # Human-like delay between different ticker searches
            # Simulate browsing from one ticker to another
            if i < len(tickers):
                delay = random.uniform(5.0, 15.0)
                logger.info(f"Taking a {delay:.1f}s break (like a human browsing)...")
                time.sleep(delay)

        return results

    def print_human_like_recommendations(self):
        """Print recommendations for human-like integration"""
        logger.info("\n" + "=" * 80)
        logger.info("HUMAN-LIKE TWITTER COLLECTION - RECOMMENDATIONS")
        logger.info("=" * 80)
        logger.info("""
✅ SAFEST APPROACH: Nitter Instances

Why Nitter is perfect for you:
1. NO AUTHENTICATION - No accounts = no bans!
2. PRIVACY-FOCUSED - Built for this exact use case
3. RATE LIMIT FRIENDLY - More lenient than Twitter
4. MULTIPLE INSTANCES - Rotate between them
5. RSS FEEDS - Can even use RSS for some queries

Integration Strategy:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Use Nitter as Primary Source
   - Rotate between instances
   - 5-10 second delays between requests
   - Random User-Agent rotation
   - Monitor instance health

2. Rate Limiting (Human-Like)
   - 5-10 seconds between ticker searches
   - Random "think time" (3-8 seconds)
   - Don't search same ticker too frequently (4+ hours)
   - Simulate browsing patterns

3. Fallback Strategy
   ┌─────────────────────────────────────────┐
   │ 1. Try Nitter instances (rotating)       │
   │     ↓ if all fail                        │
   │ 2. Try self-hosted Nitter (if deployed) │
   │     ↓ if still failing                   │
   │ 3. Skip ticker this round                │
   │     (try again in 4 hours)              │
   └─────────────────────────────────────────┘

4. Self-Host Nitter (Optional - Best Reliability)
   Docker setup:

   services:
     nitter:
       image: zedeus/nitter:latest
       container_name: nitter
       ports:
         - "8081:8080"
       volumes:
         - ./nitter.conf:/src/nitter.conf:ro
       restart: unless-stopped

   Then point to http://localhost:8081 instead of public instances

5. Integration into social_service.py:

   def fetch_twitter_sentiment(self, ticker: str) -> Dict[str, Any]:
       '''Fetch Twitter sentiment via Nitter (human-like, no auth)'''
       from twitter_human_like import HumanLikeTwitterCollector

       collector = HumanLikeTwitterCollector()

       # Search Nitter (with human delays built-in)
       result = collector.search_nitter(ticker, max_tweets=20)

       if result.get('error'):
           logger.warning(f"Twitter collection failed for {ticker}: {result['error']}")
           return {
               'volume': 0,
               'sentiment_label': 'NEUTRAL',
               'sentiment_score': 0.0,
               'raw_data': None
           }

       tweets = result['tweets']

       # Analyze with Ollama (same as Reddit)
       texts = [t['text'] for t in tweets[:5]]
       sentiment = self.ollama.analyze_crowd_sentiment(texts, ticker)

       return {
           'volume': len(tweets),
           'sentiment_label': sentiment.get('sentiment', 'NEUTRAL'),
           'sentiment_score': self.map_sentiment_label_to_score(sentiment.get('sentiment')),
           'raw_data': tweets[:3]
       }

6. Scheduler Considerations:
   - Run every 4 hours (not real-time)
   - Stagger ticker searches (don't batch all at once)
   - If collection fails, skip and try next round
   - Keep track of successful instances

7. Monitoring:
   - Track which Nitter instances are working
   - Log request success rates
   - Alert if all instances fail for 24+ hours
   - Monitor for patterns that might look bot-like

Benefits of This Approach:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ NO ACCOUNT BANS - You're not using accounts!
✅ LOOKS HUMAN - Slow, random delays
✅ LOW RISK - Public data, privacy-focused frontend
✅ RELIABLE - Multiple instances, self-host option
✅ SIMPLE - Just HTTP requests, no Selenium needed
✅ FITS YOUR USE CASE - You don't need real-time data

Limitations:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️  Public instances can be slow/down
⚠️  Less complete data than authenticated API
⚠️  May not get ALL tweets (just recent visible ones)
⚠️  Nitter itself could be blocked by Twitter (though rare)

Solution: Self-host your own Nitter instance for 100% reliability!

Next Steps:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Test Nitter with your tickers:
   python debug/test_twitter_human_like.py

2. If it works, integrate into social_service.py

3. (Optional) Deploy self-hosted Nitter for reliability

4. Monitor and adjust delays as needed
""")


def main():
    """Main test function"""
    logger.info("=" * 80)
    logger.info("Twitter Collection - Human-Like Browsing Test")
    logger.info("=" * 80)

    collector = HumanLikeTwitterCollector()

    # Test with sample tickers
    test_tickers = ['AAPL', 'TSLA', 'NVDA']

    logger.info("\n🚶 Simulating human browsing behavior...")
    logger.info("   - Random delays (5-15 seconds)")
    logger.info("   - User-Agent rotation")
    logger.info("   - No authentication required")
    logger.info("   - Using Nitter (privacy-focused Twitter frontend)\n")

    results = collector.test_multiple_tickers(test_tickers)

    # Print summary
    logger.info("\n" + "=" * 80)
    logger.info("SUMMARY")
    logger.info("=" * 80)

    for ticker, result in results.items():
        if result.get('error'):
            logger.info(f"{ticker}: ❌ ERROR - {result['error']}")
        else:
            count = result['count']
            instance = result.get('instance', 'unknown')
            logger.info(f"{ticker}: ✅ {count} tweets (via {instance})")

    # Show working instances
    if collector.working_instances:
        logger.info(f"\n✅ Working Nitter instances:")
        for instance in collector.working_instances:
            logger.info(f"   - {instance}")

    # Save results
    import json
    output_file = Path(__file__).parent / "twitter_human_like_results.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    logger.info(f"\n✅ Results saved to: {output_file}")

    # Print recommendations
    collector.print_human_like_recommendations()


if __name__ == "__main__":
    main()
