#!/usr/bin/env python3
"""
Twitter/X Sentiment Collection via twscrape
============================================

Test script for integrating Twitter/X sentiment using twscrape.
This approach requires Twitter account credentials but provides the most reliable access.

Setup Instructions:
1. Install twscrape: pip install twscrape
2. Create a burner Twitter account (use temp email + temp phone)
3. Add account: twscrape add_accounts username:password:email:email_password
4. Login: twscrape login_accounts
5. Run this script to test

References:
- GitHub: https://github.com/vladkens/twscrape
- Docs: https://github.com/vladkens/twscrape#readme
"""

import asyncio
import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TwitterSentimentCollector:
    """Collects Twitter/X sentiment using twscrape"""

    def __init__(self):
        self.api = None
        self.initialized = False

    async def initialize(self) -> bool:
        """Initialize twscrape API"""
        try:
            from twscrape import API, gather
            from twscrape.logger import set_log_level

            # Reduce twscrape logging noise
            set_log_level("WARNING")

            self.api = API()
            self.gather = gather

            # Check if accounts are available
            accounts = await self.api.pool.accounts_info()
            if not accounts:
                logger.error("❌ No Twitter accounts configured in twscrape")
                logger.info("\n   Setup Instructions:")
                logger.info("   1. Create burner Twitter account (use temp email/phone)")
                logger.info("   2. Add account:")
                logger.info("      twscrape add_accounts username password email email_password")
                logger.info("   3. Login accounts:")
                logger.info("      twscrape login_accounts")
                logger.info("   4. Re-run this script")
                return False

            logger.info(f"✅ twscrape initialized with {len(accounts)} account(s)")
            self.initialized = True
            return True

        except ImportError:
            logger.error("❌ twscrape not installed")
            logger.info("\n   Install with: pip install twscrape")
            return False
        except Exception as e:
            logger.error(f"❌ Error initializing twscrape: {e}")
            return False

    async def search_ticker(
        self,
        ticker: str,
        max_tweets: int = 20,
        hours_back: int = 24
    ) -> Dict[str, Any]:
        """Search Twitter/X for a ticker symbol

        Args:
            ticker: Ticker symbol to search (e.g., 'AAPL')
            max_tweets: Maximum number of tweets to fetch
            hours_back: How many hours back to search

        Returns:
            Dictionary with tweets and metadata
        """
        if not self.initialized:
            logger.error("twscrape not initialized")
            return {'tweets': [], 'error': 'Not initialized'}

        try:
            # Search for both cashtag and ticker mentions
            # Twitter search syntax: ($AAPL OR AAPL) since:2024-01-25
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
            since_date = cutoff.strftime('%Y-%m-%d')

            # Build search query (cashtag is more precise)
            query = f"(${ticker} OR #{ticker}) since:{since_date}"

            logger.info(f"Searching Twitter for: {query}")
            logger.info(f"Max tweets: {max_tweets}")

            # Search tweets
            tweets_raw = await self.gather(
                self.api.search(query, limit=max_tweets)
            )

            logger.info(f"✅ Found {len(tweets_raw)} tweets")

            # Process tweets
            tweets = []
            for tweet in tweets_raw:
                tweets.append({
                    'id': tweet.id,
                    'text': tweet.rawContent,
                    'created_at': tweet.date.isoformat(),
                    'author': tweet.user.username,
                    'likes': tweet.likeCount or 0,
                    'retweets': tweet.retweetCount or 0,
                    'replies': tweet.replyCount or 0,
                    'views': tweet.viewCount or 0,
                    'url': tweet.url,
                    'engagement_score': (
                        (tweet.likeCount or 0) +
                        (tweet.retweetCount or 0) * 2 +
                        (tweet.replyCount or 0)
                    )
                })

            # Sort by engagement
            tweets.sort(key=lambda x: x['engagement_score'], reverse=True)

            return {
                'ticker': ticker,
                'query': query,
                'tweets': tweets,
                'count': len(tweets),
                'search_window_hours': hours_back
            }

        except Exception as e:
            logger.error(f"❌ Error searching for {ticker}: {e}", exc_info=True)
            return {
                'ticker': ticker,
                'tweets': [],
                'error': str(e)
            }

    async def test_watchlist_tickers(self, tickers: List[str]) -> Dict[str, Any]:
        """Test Twitter search for multiple tickers

        Args:
            tickers: List of ticker symbols to test

        Returns:
            Dictionary with results for each ticker
        """
        logger.info(f"\n{'=' * 80}")
        logger.info(f"Testing Twitter search for {len(tickers)} tickers")
        logger.info(f"{'=' * 80}\n")

        results = {}

        for ticker in tickers:
            logger.info(f"\n--- Testing {ticker} ---")
            result = await self.search_ticker(ticker, max_tweets=10, hours_back=24)
            results[ticker] = result

            if result.get('error'):
                logger.error(f"❌ {ticker}: {result['error']}")
            else:
                count = result['count']
                logger.info(f"✅ {ticker}: {count} tweets")

                # Show top 3 tweets
                for i, tweet in enumerate(result['tweets'][:3], 1):
                    logger.info(f"\n   Tweet #{i}:")
                    logger.info(f"   Author: @{tweet['author']}")
                    logger.info(f"   Text: {tweet['text'][:100]}...")
                    logger.info(f"   Engagement: {tweet['engagement_score']} (L:{tweet['likes']} RT:{tweet['retweets']} R:{tweet['replies']})")
                    logger.info(f"   URL: {tweet['url']}")

            # Rate limiting - wait between searches
            await asyncio.sleep(2)

        return results

    def print_integration_guide(self):
        """Print guide for integrating into social_service.py"""
        logger.info("\n" + "=" * 80)
        logger.info("INTEGRATION GUIDE: Adding Twitter to social_service.py")
        logger.info("=" * 80)
        logger.info("""
Next steps to integrate Twitter/X sentiment into your pipeline:

1. Install twscrape in production:
   pip install twscrape

2. Set up Twitter account(s):
   - Create burner account(s) (use temp email/phone)
   - Add to twscrape: twscrape add_accounts username password email email_password
   - Login: twscrape login_accounts
   - Store credentials securely (consider using .env)

3. Add to social_service.py:

   async def fetch_twitter_sentiment(self, ticker: str) -> Dict[str, Any]:
       '''Fetch sentiment from Twitter/X using twscrape'''
       from twscrape import API, gather

       api = API()

       # Search for ticker (last 24 hours)
       cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
       query = f"(${ticker} OR #{ticker}) since:{cutoff.strftime('%Y-%m-%d')}"

       tweets_raw = await gather(api.search(query, limit=20))

       # Process tweets (similar to Reddit processing)
       tweets = []
       for tweet in tweets_raw:
           tweets.append({
               'text': tweet.rawContent,
               'engagement': tweet.likeCount + tweet.retweetCount * 2,
               'created_at': tweet.date.isoformat(),
               'author': tweet.user.username
           })

       # Analyze sentiment with Ollama (reuse existing pattern)
       texts = [t['text'] for t in tweets[:5]]
       sentiment = self.ollama.analyze_crowd_sentiment(texts, ticker)

       return {
           'volume': len(tweets),
           'sentiment_label': sentiment.get('sentiment', 'NEUTRAL'),
           'sentiment_score': self.map_sentiment_label_to_score(sentiment.get('sentiment')),
           'raw_data': tweets[:3]
       }

4. Update social_sentiment_ai_job.py:
   - Call fetch_twitter_sentiment() alongside Reddit/StockTwits
   - Store with platform='twitter'

5. Schema update (if needed):
   - social_metrics table already supports platform field
   - No schema changes needed!

6. Rate limiting considerations:
   - Twitter has aggressive rate limits
   - Rotate accounts if you hit limits
   - Add delays between searches (2-5 seconds)
   - Monitor account health (check for suspensions)

7. Data quality tips:
   - Filter by engagement (min likes/retweets)
   - Validate ticker mentions in tweet text
   - Watch for bot accounts (check account age, follower ratio)
   - Consider verified accounts more heavily
""")


async def main():
    """Main test function"""
    logger.info("=" * 80)
    logger.info("Twitter/X Sentiment Collection Test (twscrape)")
    logger.info("=" * 80)

    collector = TwitterSentimentCollector()

    # Initialize
    logger.info("\n--- Step 1: Initialize twscrape ---")
    if not await collector.initialize():
        logger.error("\n❌ Failed to initialize. Follow setup instructions above.")
        sys.exit(1)

    # Test with sample tickers
    test_tickers = ['AAPL', 'TSLA', 'NVDA', 'AMD', 'PLTR']

    logger.info("\n--- Step 2: Test Twitter search ---")
    results = await collector.test_watchlist_tickers(test_tickers)

    # Save results
    output_file = Path(__file__).parent / "twitter_test_results.json"
    with open(output_file, 'w') as f:
        # Convert datetime objects to strings for JSON serialization
        json.dump(results, f, indent=2, default=str)

    logger.info(f"\n✅ Results saved to: {output_file}")

    # Print summary
    logger.info("\n" + "=" * 80)
    logger.info("SUMMARY")
    logger.info("=" * 80)
    for ticker, result in results.items():
        if result.get('error'):
            logger.info(f"{ticker}: ❌ ERROR - {result['error']}")
        else:
            count = result['count']
            logger.info(f"{ticker}: ✅ {count} tweets found")

    # Print integration guide
    collector.print_integration_guide()


if __name__ == "__main__":
    asyncio.run(main())
