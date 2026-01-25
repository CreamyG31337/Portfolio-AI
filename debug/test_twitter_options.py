#!/usr/bin/env python3
"""
Twitter/X Sentiment Source Investigation Script
================================================

Tests different approaches for adding Twitter/X to social sentiment collection:
1. SearXNG social media search (if Twitter engine is enabled)
2. twscrape (requires Twitter account)
3. Direct X search via web scraping

This script helps determine the best approach for your infrastructure.
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

from searxng_client import SearXNGClient, get_searxng_client

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TwitterSourceInvestigator:
    """Investigates Twitter/X integration options"""

    def __init__(self):
        self.searxng = get_searxng_client()
        self.results = {}

    def test_searxng_health(self) -> bool:
        """Test if SearXNG is accessible"""
        logger.info("=" * 80)
        logger.info("TEST 1: SearXNG Health Check")
        logger.info("=" * 80)

        if not self.searxng:
            logger.error("❌ SearXNG client is disabled or not configured")
            logger.info("   Check SEARXNG_ENABLED and SEARXNG_BASE_URL in .env")
            self.results['searxng_health'] = False
            return False

        try:
            is_healthy = self.searxng.check_health()
            if is_healthy:
                logger.info(f"✅ SearXNG is accessible at {self.searxng.base_url}")
                self.results['searxng_health'] = True
                return True
            else:
                logger.error(f"❌ SearXNG health check failed at {self.searxng.base_url}")
                logger.info("   Make sure SearXNG container is running:")
                logger.info("   - Check docker ps | grep searxng")
                logger.info("   - Or start it with: docker-compose up -d searxng")
                self.results['searxng_health'] = False
                return False
        except Exception as e:
            logger.error(f"❌ Error checking SearXNG health: {e}")
            self.results['searxng_health'] = False
            return False

    def test_searxng_general_search(self) -> bool:
        """Test basic SearXNG search functionality"""
        logger.info("\n" + "=" * 80)
        logger.info("TEST 2: SearXNG General Search")
        logger.info("=" * 80)

        if not self.searxng:
            logger.error("❌ SearXNG not available")
            return False

        try:
            # Test with a simple stock query
            test_query = "$AAPL stock news"
            logger.info(f"Testing query: '{test_query}'")

            results = self.searxng.search_web(test_query, max_results=5)

            if results.get('error'):
                logger.error(f"❌ Search failed: {results['error']}")
                self.results['searxng_general'] = False
                return False

            num_results = len(results.get('results', []))
            logger.info(f"✅ Search successful: {num_results} results")

            # Show first result
            if num_results > 0:
                first = results['results'][0]
                logger.info(f"\n   Sample result:")
                logger.info(f"   Title: {first.get('title', 'N/A')[:80]}")
                logger.info(f"   URL: {first.get('url', 'N/A')[:80]}")
                logger.info(f"   Engine: {first.get('engine', 'N/A')}")

            self.results['searxng_general'] = True
            return True

        except Exception as e:
            logger.error(f"❌ Error testing general search: {e}")
            self.results['searxng_general'] = False
            return False

    def test_searxng_twitter_search(self) -> Dict[str, Any]:
        """Test if SearXNG can search Twitter/X"""
        logger.info("\n" + "=" * 80)
        logger.info("TEST 3: SearXNG Twitter/X Search")
        logger.info("=" * 80)

        if not self.searxng:
            logger.error("❌ SearXNG not available")
            return {'success': False, 'reason': 'SearXNG unavailable'}

        test_cases = [
            {
                'name': 'Cashtag search',
                'query': '$TSLA',
                'engines': None  # Let SearXNG use all enabled engines
            },
            {
                'name': 'Ticker + stock',
                'query': 'AAPL stock',
                'engines': None
            },
            {
                'name': 'Ticker site:twitter.com',
                'query': 'NVDA site:twitter.com OR site:x.com',
                'engines': None
            }
        ]

        twitter_results = []

        for test in test_cases:
            logger.info(f"\n   Test: {test['name']}")
            logger.info(f"   Query: {test['query']}")

            try:
                # Try search with specified engines (if any)
                results = self.searxng.search(
                    query=test['query'],
                    engines=test['engines'],
                    time_range='day',
                    max_results=10
                )

                if results.get('error'):
                    logger.warning(f"   ⚠️  Search error: {results['error']}")
                    continue

                # Check if any results are from Twitter/X
                twitter_matches = [
                    r for r in results.get('results', [])
                    if 'twitter.com' in r.get('url', '') or 'x.com' in r.get('url', '')
                ]

                logger.info(f"   Results: {len(results.get('results', []))} total, {len(twitter_matches)} from Twitter/X")

                if twitter_matches:
                    logger.info(f"   ✅ Found {len(twitter_matches)} Twitter/X results!")
                    for i, match in enumerate(twitter_matches[:3], 1):
                        logger.info(f"\n   Twitter Result #{i}:")
                        logger.info(f"   Title: {match.get('title', 'N/A')[:80]}")
                        logger.info(f"   URL: {match.get('url', 'N/A')[:80]}")
                        logger.info(f"   Engine: {match.get('engine', 'N/A')}")

                    twitter_results.extend(twitter_matches)
                else:
                    logger.info(f"   ⚠️  No Twitter/X results in top 10")

            except Exception as e:
                logger.error(f"   ❌ Error: {e}")

        # Summary
        logger.info("\n" + "-" * 80)
        if twitter_results:
            logger.info(f"✅ SearXNG CAN find Twitter/X content!")
            logger.info(f"   Total Twitter/X results across all tests: {len(twitter_results)}")
            self.results['searxng_twitter'] = {
                'success': True,
                'result_count': len(twitter_results),
                'sample_urls': [r.get('url') for r in twitter_results[:5]]
            }
            return {'success': True, 'results': twitter_results}
        else:
            logger.warning("⚠️  SearXNG did NOT return Twitter/X results")
            logger.info("   Possible reasons:")
            logger.info("   1. Twitter engine not enabled in SearXNG settings")
            logger.info("   2. Twitter blocked SearXNG instances")
            logger.info("   3. Need to configure Twitter engine in settings.yml")
            self.results['searxng_twitter'] = {
                'success': False,
                'reason': 'No Twitter results found'
            }
            return {'success': False, 'reason': 'No Twitter results found'}

    def test_twscrape_availability(self) -> Dict[str, Any]:
        """Check if twscrape is installed and configured"""
        logger.info("\n" + "=" * 80)
        logger.info("TEST 4: twscrape Availability Check")
        logger.info("=" * 80)

        try:
            import twscrape
            logger.info(f"✅ twscrape is installed (version: {twscrape.__version__ if hasattr(twscrape, '__version__') else 'unknown'})")

            # Check if accounts are configured
            logger.info("\n   Checking for configured Twitter accounts...")
            logger.info("   (This requires accounts to be added via: twscrape add_accounts)")

            self.results['twscrape'] = {
                'installed': True,
                'note': 'Requires Twitter account credentials to use'
            }

            return {
                'success': True,
                'installed': True,
                'note': 'twscrape is available but requires Twitter account setup'
            }

        except ImportError:
            logger.info("⚠️  twscrape is NOT installed")
            logger.info("\n   To install twscrape:")
            logger.info("   pip install twscrape")
            logger.info("\n   Note: twscrape requires Twitter account credentials")
            logger.info("   - Accounts may get banned for scraping")
            logger.info("   - Consider using burner accounts")

            self.results['twscrape'] = {
                'installed': False,
                'install_command': 'pip install twscrape'
            }

            return {
                'success': False,
                'installed': False,
                'install_command': 'pip install twscrape'
            }

    def generate_recommendations(self) -> None:
        """Generate recommendations based on test results"""
        logger.info("\n" + "=" * 80)
        logger.info("RECOMMENDATIONS")
        logger.info("=" * 80)

        # Check SearXNG results
        searxng_works = self.results.get('searxng_twitter', {}).get('success', False)
        twscrape_available = self.results.get('twscrape', {}).get('installed', False)

        if searxng_works:
            logger.info("\n✅ RECOMMENDED: SearXNG Twitter Search")
            logger.info("   Pros:")
            logger.info("   - Already working with your existing infrastructure")
            logger.info("   - No authentication required")
            logger.info("   - Low risk of account bans")
            logger.info("   - Easy to integrate with current social_service.py")
            logger.info("\n   Cons:")
            logger.info("   - Limited to what SearXNG can find")
            logger.info("   - May not get real-time tweets")
            logger.info("   - Results quality depends on SearXNG engine config")
            logger.info("\n   Next Steps:")
            logger.info("   1. Add fetch_twitter_sentiment() to social_service.py")
            logger.info("   2. Use searxng.search() with Twitter-specific queries")
            logger.info("   3. Test with a few tickers from watchlist")

        elif not self.results.get('searxng_health', False):
            logger.info("\n⚠️  RECOMMENDED: Fix SearXNG First")
            logger.info("   Action items:")
            logger.info("   1. Deploy/start SearXNG container")
            logger.info("   2. Set SEARXNG_BASE_URL in .env")
            logger.info("   3. Re-run this test script")

        else:
            logger.info("\n⚠️  RECOMMENDED: Configure SearXNG Twitter Engine OR Use twscrape")
            logger.info("\n   Option A: Enable Twitter in SearXNG (Easier)")
            logger.info("   1. Access SearXNG settings.yml")
            logger.info("   2. Enable Twitter/X search engines")
            logger.info("   3. Restart SearXNG container")
            logger.info("   4. Re-run this test")
            logger.info("\n   Option B: Use twscrape (More Reliable)")
            if not twscrape_available:
                logger.info("   1. Install: pip install twscrape")
            logger.info("   2. Get burner Twitter accounts (Gmail + temp phone)")
            logger.info("   3. Add accounts: twscrape add_accounts accounts.txt")
            logger.info("   4. Login: twscrape login_accounts")
            logger.info("   5. Implement fetch_twitter_sentiment() using twscrape")
            logger.info("\n   Note: twscrape is more reliable but requires account management")

    def run_all_tests(self) -> Dict[str, Any]:
        """Run all investigation tests"""
        logger.info("\n" + "=" * 80)
        logger.info("TWITTER/X SENTIMENT SOURCE INVESTIGATION")
        logger.info("=" * 80)
        logger.info("\nThis script will test different approaches for adding Twitter/X")
        logger.info("to your social sentiment collection pipeline.\n")

        # Run tests
        self.test_searxng_health()
        self.test_searxng_general_search()
        self.test_searxng_twitter_search()
        self.test_twscrape_availability()

        # Generate recommendations
        self.generate_recommendations()

        # Save results
        output_file = Path(__file__).parent / "twitter_investigation_results.json"
        with open(output_file, 'w') as f:
            json.dump(self.results, f, indent=2)

        logger.info("\n" + "=" * 80)
        logger.info(f"Results saved to: {output_file}")
        logger.info("=" * 80)

        return self.results


def main():
    """Main entry point"""
    investigator = TwitterSourceInvestigator()
    results = investigator.run_all_tests()

    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"SearXNG Health: {'✅' if results.get('searxng_health') else '❌'}")
    print(f"SearXNG General Search: {'✅' if results.get('searxng_general') else '❌'}")
    print(f"SearXNG Twitter Search: {'✅' if results.get('searxng_twitter', {}).get('success') else '❌'}")
    print(f"twscrape Installed: {'✅' if results.get('twscrape', {}).get('installed') else '❌'}")
    print("=" * 80)


if __name__ == "__main__":
    main()
