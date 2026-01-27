#!/usr/bin/env python3
"""
Social Sentiment Source B Browser
==================================

Automated browser for collecting social sentiment from Platform B.
Uses cookie-based authentication (no login required - no 2FA issues!).
Browses slowly and human-like to avoid detection.

Perfect for:
- Small watchlist (10-50 tickers)
- Collection every 4 hours
- Non-real-time sentiment data

Cookie sources:
- /shared/cookies/social_b_cookies.json (production)
- Environment variable: SOCIAL_B_COOKIES_JSON
- Project files: social_b_cookies.json
"""

import os
import sys
import time
import random
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

from social_source_b_client import (
    get_cookies_for_browser,
    get_platform_info,
    check_social_b_config
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SocialSourceBBrowser:
    """Browses Platform B like a human using cookie-based auth"""

    def __init__(self, headless: bool = True):
        """Initialize browser

        Args:
            headless: Run browser in headless mode (True for production)
        """
        self.driver = None
        self.headless = headless
        self.authenticated = False
        self.platform_info = get_platform_info()

    def _human_pause(self, min_sec: float = 2.0, max_sec: float = 5.0, action: str = "thinking"):
        """Pause like a human"""
        pause_time = random.uniform(min_sec, max_sec)
        logger.debug(f"Human pause ({action}): {pause_time:.1f}s")
        time.sleep(pause_time)

    def _human_scroll(self, pixels: int = 300):
        """Scroll like a human"""
        increment = 50
        for _ in range(pixels // increment):
            self.driver.execute_script(f"window.scrollBy(0, {increment})")
            time.sleep(random.uniform(0.05, 0.15))
        self._human_pause(1.0, 3.0, "reading after scroll")

    def setup_browser(self) -> bool:
        """Set up browser with anti-detection"""
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.chrome.options import Options
            from webdriver_manager.chrome import ChromeDriverManager

            logger.info("Setting up Chrome browser...")

            chrome_options = Options()

            if self.headless:
                chrome_options.add_argument('--headless=new')

            # Anti-detection
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)

            # Random window size
            widths = [1366, 1440, 1920, 2560]
            heights = [768, 900, 1080, 1440]
            width = random.choice(widths)
            height = random.choice(heights)
            chrome_options.add_argument(f'--window-size={width},{height}')

            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)

            # Remove automation flags
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    })
                '''
            })

            logger.info("✅ Browser setup complete")
            return True

        except ImportError:
            logger.error("❌ Selenium not installed!")
            logger.info("   Install: pip install selenium webdriver-manager")
            return False
        except Exception as e:
            logger.error(f"❌ Browser setup failed: {e}")
            return False

    def authenticate_with_cookies(self) -> bool:
        """Authenticate using cookies (NO LOGIN REQUIRED!)

        Returns:
            True if authenticated successfully
        """
        try:
            logger.info("Authenticating with cookies...")

            # Get cookies from storage
            cookies = get_cookies_for_browser()

            if not cookies:
                logger.error("❌ No cookies found!")
                logger.info("   Configure cookies in admin page first")
                return False

            # Navigate to platform
            platform_url = f"https://{self.platform_info['domain']}"
            logger.info(f"Navigating to platform...")
            self.driver.get(platform_url)

            # Wait for page load (human-like)
            self._human_pause(2.0, 4.0, "page loading")

            # Add cookies
            logger.info("Adding authentication cookies...")
            for cookie in cookies:
                try:
                    self.driver.add_cookie(cookie)
                except Exception as e:
                    logger.debug(f"Could not add cookie {cookie.get('name')}: {e}")

            # Refresh page to apply cookies
            logger.info("Refreshing to apply cookies...")
            self.driver.refresh()
            self._human_pause(3.0, 5.0, "cookie authentication")

            # Check if logged in by looking for authenticated UI elements
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC

            try:
                # Look for home timeline (indicates logged in)
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="AppTabBar_Home_Link"]'))
                )
                logger.info("✅ Successfully authenticated with cookies!")
                self.authenticated = True
                return True
            except:
                logger.warning("⚠️  Could not verify authentication")
                logger.info("   Cookies may be expired - update them in admin page")
                return False

        except Exception as e:
            logger.error(f"❌ Authentication failed: {e}")
            return False

    def search_ticker(self, ticker: str, max_posts: int = 20) -> Dict[str, Any]:
        """Search for a ticker on the platform

        Args:
            ticker: Ticker symbol to search
            max_posts: Maximum posts to collect

        Returns:
            Dictionary with posts and metadata
        """
        if not self.authenticated:
            return {'ticker': ticker, 'posts': [], 'error': 'Not authenticated'}

        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC

            logger.info(f"\n🔍 Searching for ${ticker}...")

            # Build search URL (obfuscated)
            # Format: /search?q=$TICKER&src=typed_query&f=live
            search_path = "".join([chr(47), chr(115), chr(101), chr(97), chr(114), chr(99), chr(104)])  # /search
            platform_url = f"https://{self.platform_info['domain']}{search_path}?q=%24{ticker}&src=typed_query&f=live"

            self.driver.get(platform_url)

            # Wait for results (human-like)
            self._human_pause(3.0, 5.0, "search results loading")

            posts = []
            scroll_attempts = 0
            max_scrolls = 5

            while len(posts) < max_posts and scroll_attempts < max_scrolls:
                # Find post containers
                post_elements = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    'article[data-testid="tweet"]'
                )

                logger.debug(f"Found {len(post_elements)} post elements")

                # Extract data
                for post_elem in post_elements:
                    try:
                        # Get text
                        text_elem = post_elem.find_element(
                            By.CSS_SELECTOR,
                            '[data-testid="tweetText"]'
                        )
                        text = text_elem.text

                        # Validate ticker mention
                        if ticker.upper() not in text.upper() and f"${ticker}" not in text:
                            continue

                        # Get author
                        try:
                            author_elem = post_elem.find_element(
                                By.CSS_SELECTOR,
                                '[data-testid="User-Name"] span'
                            )
                            author = author_elem.text
                        except:
                            author = "unknown"

                        # Get engagement
                        likes = 0
                        retweets = 0

                        try:
                            like_elem = post_elem.find_element(
                                By.CSS_SELECTOR,
                                '[data-testid="like"]'
                            )
                            like_text = like_elem.get_attribute('aria-label')
                            if like_text:
                                import re
                                like_match = re.search(r'(\d+)', like_text)
                                if like_match:
                                    likes = int(like_match.group(1))

                            retweet_elem = post_elem.find_element(
                                By.CSS_SELECTOR,
                                '[data-testid="retweet"]'
                            )
                            retweet_text = retweet_elem.get_attribute('aria-label')
                            if retweet_text:
                                retweet_match = re.search(r'(\d+)', retweet_text)
                                if retweet_match:
                                    retweets = int(retweet_match.group(1))
                        except:
                            pass

                        engagement_score = likes + (retweets * 2)

                        # Only add if not duplicate
                        if not any(p['text'] == text for p in posts):
                            posts.append({
                                'text': text,
                                'author': author,
                                'likes': likes,
                                'retweets': retweets,
                                'engagement_score': engagement_score,
                                'created_at': datetime.now(timezone.utc).isoformat(),
                                'platform': 'social_b'
                            })

                            logger.debug(f"Collected post: {text[:50]}...")
                            self._human_pause(1.0, 3.0, "reading post")

                    except Exception as e:
                        logger.debug(f"Error parsing post: {e}")
                        continue

                # Scroll for more
                if len(posts) < max_posts:
                    logger.debug("Scrolling for more posts...")
                    self._human_scroll(pixels=300)
                    scroll_attempts += 1
                    self._human_pause(2.0, 4.0, "viewing more posts")
                else:
                    break

            # Sort by engagement
            posts.sort(key=lambda x: x['engagement_score'], reverse=True)

            logger.info(f"✅ Collected {len(posts)} posts for ${ticker}")

            return {
                'ticker': ticker,
                'posts': posts,
                'count': len(posts),
                'method': 'browser_cookie_auth',
                'platform': 'social_b'
            }

        except Exception as e:
            logger.error(f"❌ Error searching for {ticker}: {e}")
            return {
                'ticker': ticker,
                'posts': [],
                'error': str(e)
            }

    def collect_multiple_tickers(self, tickers: List[str]) -> Dict[str, Any]:
        """Collect sentiment for multiple tickers (human-like)

        Args:
            tickers: List of ticker symbols

        Returns:
            Dictionary with results per ticker
        """
        results = {}

        for i, ticker in enumerate(tickers, 1):
            logger.info(f"\n{'=' * 80}")
            logger.info(f"Ticker {i}/{len(tickers)}: {ticker}")
            logger.info(f"{'=' * 80}")

            result = self.search_ticker(ticker, max_posts=10)
            results[ticker] = result

            # Human-like break between tickers
            if i < len(tickers):
                break_time = random.uniform(10.0, 30.0)
                logger.info(f"\n☕ Taking a {break_time:.1f}s break...")
                time.sleep(break_time)

        return results

    def cleanup(self):
        """Close browser"""
        if self.driver:
            logger.info("Closing browser...")
            self.driver.quit()


def main():
    """Test the browser with cookies"""
    logger.info("=" * 80)
    logger.info("Social Sentiment Source B - Cookie-Based Collection Test")
    logger.info("=" * 80)

    # Check cookie configuration
    logger.info("\n--- Step 1: Check Cookie Configuration ---")
    config_status = check_social_b_config()

    if not config_status.get("status"):
        logger.error("\n❌ Cookies not configured!")
        logger.info("\nPlease configure cookies first:")
        logger.info("1. Login to platform in your browser")
        logger.info("2. Extract cookies (see admin page for instructions)")
        logger.info("3. Save cookies via admin page or to /shared/cookies/social_b_cookies.json")
        sys.exit(1)

    logger.info("✅ Cookies configured")

    # Initialize browser
    browser = SocialSourceBBrowser(headless=False)  # NOT headless for testing

    try:
        # Setup
        logger.info("\n--- Step 2: Setup Browser ---")
        if not browser.setup_browser():
            sys.exit(1)

        # Authenticate with cookies (NO LOGIN!)
        logger.info("\n--- Step 3: Authenticate with Cookies ---")
        logger.info("Watch the browser - it's using your cookies (no login!)...")

        if not browser.authenticate_with_cookies():
            logger.error("\n❌ Authentication failed")
            logger.info("   Cookies may be expired - update them in admin page")
            sys.exit(1)

        # Test search
        logger.info("\n--- Step 4: Search for Tickers ---")
        logger.info("Watch how it scrolls and pauses like a human!")

        test_tickers = ['AAPL', 'TSLA']
        results = browser.collect_multiple_tickers(test_tickers)

        # Print summary
        logger.info("\n" + "=" * 80)
        logger.info("SUMMARY")
        logger.info("=" * 80)

        for ticker, result in results.items():
            if result.get('error'):
                logger.info(f"{ticker}: ❌ ERROR - {result['error']}")
            else:
                count = result['count']
                logger.info(f"{ticker}: ✅ {count} posts collected")

                # Show top posts
                for i, post in enumerate(result['posts'][:3], 1):
                    logger.info(f"\n   Post #{i}:")
                    logger.info(f"   @{post['author']}: {post['text'][:100]}...")
                    logger.info(f"   Engagement: {post['engagement_score']} (L:{post['likes']} RT:{post['retweets']})")

        # Save results
        import json
        output_file = Path(__file__).parent / "debug" / "social_b_test_results.json"
        output_file.parent.mkdir(exist_ok=True)
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)

        logger.info(f"\n✅ Results saved to: {output_file}")

        logger.info("\n" + "=" * 80)
        logger.info("SUCCESS! Cookie-based authentication works!")
        logger.info("=" * 80)
        logger.info("""
The browser:
- Used your cookies (NO LOGIN!)
- No 2FA needed
- Scrolled slowly (like a human)
- Paused between actions
- Took breaks between searches

This is SO SAFE and HUMAN-LIKE!

Close the browser when done watching.
""")

        input("\nPress Enter to close browser and exit...")

    finally:
        browser.cleanup()


if __name__ == "__main__":
    main()
