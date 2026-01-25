#!/usr/bin/env python3
"""
Twitter/X Sentiment Collection via FlareSolverr (Backup Option)
================================================================

Fallback approach that uses your existing FlareSolverr infrastructure
to scrape Twitter search results without requiring Twitter accounts.

Pros:
- No Twitter account needed
- Reuses existing FlareSolverr infrastructure
- No risk of account bans

Cons:
- Slower than API approaches
- May get blocked by X's anti-scraping
- Limited to what's visible in search results
- Requires HTML parsing

This is a BACKUP option if twscrape doesn't work.
"""

import os
import sys
import json
import logging
import requests
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# FlareSolverr configuration
FLARESOLVERR_URL = os.getenv("FLARESOLVERR_URL", "http://host.docker.internal:8191")


class TwitterFlareSolverrCollector:
    """Collects Twitter/X sentiment using FlareSolverr"""

    def __init__(self, flaresolverr_url: str = FLARESOLVERR_URL):
        self.flaresolverr_url = flaresolverr_url

    def make_flaresolverr_request(self, url: str) -> Optional[str]:
        """Make request through FlareSolverr to bypass Cloudflare

        Args:
            url: Target URL to fetch

        Returns:
            HTML content if successful, None otherwise
        """
        try:
            flaresolverr_endpoint = f"{self.flaresolverr_url}/v1"

            payload = {
                "cmd": "request.get",
                "url": url,
                "maxTimeout": 60000
            }

            logger.debug(f"Requesting via FlareSolverr: {url}")
            response = requests.post(
                flaresolverr_endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=70
            )

            response.raise_for_status()
            data = response.json()

            if data.get("status") != "ok":
                logger.warning(f"FlareSolverr error: {data.get('message')}")
                return None

            solution = data.get("solution", {})
            if not solution:
                logger.warning("FlareSolverr response missing solution")
                return None

            http_status = solution.get("status", 0)
            if http_status != 200:
                logger.warning(f"Target site returned HTTP {http_status}")
                return None

            html_content = solution.get("response", "")
            return html_content if html_content else None

        except requests.exceptions.ConnectionError:
            logger.error(f"❌ FlareSolverr unavailable at {self.flaresolverr_url}")
            logger.info("   Make sure FlareSolverr container is running:")
            logger.info("   docker ps | grep flaresolverr")
            return None
        except Exception as e:
            logger.error(f"FlareSolverr request failed: {e}")
            return None

    def scrape_twitter_search(self, ticker: str, max_results: int = 20) -> Dict[str, Any]:
        """Scrape Twitter search results for a ticker

        Args:
            ticker: Ticker symbol to search
            max_results: Maximum number of tweets to collect

        Returns:
            Dictionary with tweets and metadata
        """
        logger.info(f"Scraping Twitter for {ticker}...")

        # Build Twitter search URL
        # Format: https://twitter.com/search?q=$AAPL&src=typed_query&f=live
        query = f"${ticker}"
        twitter_search_url = f"https://twitter.com/search?q={query}&src=typed_query&f=live"

        # Try to fetch via FlareSolverr
        html = self.make_flaresolverr_request(twitter_search_url)

        if not html:
            logger.error(f"❌ Failed to fetch Twitter search results for {ticker}")
            return {
                'ticker': ticker,
                'tweets': [],
                'error': 'Failed to fetch HTML'
            }

        # Parse HTML to extract tweets
        # NOTE: Twitter's HTML structure changes frequently
        # This is a simplified example - you may need to adjust selectors
        try:
            soup = BeautifulSoup(html, 'html.parser')

            # Twitter embeds data in <script> tags as JSON
            # Look for initial state data
            script_tags = soup.find_all('script')

            tweets = []

            # Try to find tweet data in script tags
            for script in script_tags:
                if script.string and 'tweet' in script.string.lower():
                    # This is a simplified extraction
                    # Real implementation would need to parse JSON structure
                    logger.debug("Found potential tweet data in script tag")
                    # TODO: Parse JSON and extract tweet objects

            # Fallback: Look for tweet text in HTML
            # (This is VERY fragile and will likely need updates)
            tweet_containers = soup.find_all('article', {'role': 'article'})

            for container in tweet_containers[:max_results]:
                try:
                    # Extract tweet text (this selector will likely break)
                    text_elem = container.find('div', {'lang': True})
                    if text_elem:
                        text = text_elem.get_text(strip=True)

                        # Basic validation - check if ticker is mentioned
                        if ticker.upper() in text.upper() or f"${ticker}" in text:
                            tweets.append({
                                'text': text,
                                'created_at': datetime.now(timezone.utc).isoformat(),
                                'engagement_score': 0  # Can't get engagement from HTML easily
                            })

                except Exception as e:
                    logger.debug(f"Error parsing tweet container: {e}")
                    continue

            logger.info(f"✅ Scraped {len(tweets)} tweets for {ticker}")

            return {
                'ticker': ticker,
                'query': query,
                'tweets': tweets,
                'count': len(tweets),
                'method': 'flaresolverr_scraping'
            }

        except Exception as e:
            logger.error(f"❌ Error parsing HTML for {ticker}: {e}")
            return {
                'ticker': ticker,
                'tweets': [],
                'error': f'Parsing error: {str(e)}'
            }

    def test_flaresolverr_health(self) -> bool:
        """Test if FlareSolverr is accessible"""
        logger.info("Testing FlareSolverr health...")

        try:
            # Try a simple request
            html = self.make_flaresolverr_request("https://www.google.com")
            if html:
                logger.info(f"✅ FlareSolverr is accessible at {self.flaresolverr_url}")
                return True
            else:
                logger.error(f"❌ FlareSolverr request failed")
                return False
        except Exception as e:
            logger.error(f"❌ FlareSolverr health check failed: {e}")
            return False


def main():
    """Main test function"""
    logger.info("=" * 80)
    logger.info("Twitter/X Sentiment via FlareSolverr (Backup Option)")
    logger.info("=" * 80)

    collector = TwitterFlareSolverrCollector()

    # Test FlareSolverr health
    logger.info("\n--- Step 1: FlareSolverr Health Check ---")
    if not collector.test_flaresolverr_health():
        logger.error("\n❌ FlareSolverr is not accessible")
        logger.info("   This backup option requires FlareSolverr to be running.")
        logger.info("   Consider using twscrape instead (test_twscrape_twitter.py)")
        return

    # Test scraping a ticker
    logger.info("\n--- Step 2: Test Twitter Scraping ---")
    test_ticker = "AAPL"
    result = collector.scrape_twitter_search(test_ticker, max_results=10)

    # Print results
    logger.info("\n" + "=" * 80)
    logger.info("RESULTS")
    logger.info("=" * 80)

    if result.get('error'):
        logger.error(f"❌ Error: {result['error']}")
    else:
        logger.info(f"✅ Found {result['count']} tweets for {test_ticker}")

        for i, tweet in enumerate(result['tweets'][:5], 1):
            logger.info(f"\nTweet #{i}:")
            logger.info(f"Text: {tweet['text'][:150]}...")

    # Save results
    output_file = Path(__file__).parent / "twitter_flaresolverr_results.json"
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2, default=str)

    logger.info(f"\n✅ Results saved to: {output_file}")

    # Print warning
    logger.info("\n" + "=" * 80)
    logger.info("WARNING: FlareSolverr Scraping Limitations")
    logger.info("=" * 80)
    logger.info("""
This approach has significant limitations:

1. FRAGILE - Twitter HTML structure changes frequently
   - Selectors will break with Twitter updates
   - Requires constant maintenance

2. SLOW - FlareSolverr uses headless browser
   - 10-30 seconds per request
   - Not suitable for real-time data

3. LIMITED - Can't access:
   - Full engagement metrics (likes, retweets)
   - User profiles
   - Tweet timestamps
   - Replies and threads

4. BLOCKED RISK - X actively blocks scrapers
   - May return empty results
   - IP could get rate limited

RECOMMENDATION: Use twscrape instead
- More reliable
- Faster
- Better data quality
- Active maintenance

Only use this as a FALLBACK if twscrape accounts get banned.
""")


if __name__ == "__main__":
    main()
