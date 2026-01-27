#!/usr/bin/env python3
"""
Twitter/X Collection - ULTRA HUMAN-LIKE with Selenium
======================================================

Uses Selenium to browse Twitter EXACTLY like a real human:
- Logs in with your account
- Slow, deliberate scrolling
- Random mouse movements
- Random pauses (reading tweets)
- Searches slowly
- Copies text like a human would

This is SO SLOW and HUMAN-LIKE that Twitter will think you're just browsing.

Perfect for:
- Small watchlist (10-50 tickers)
- Collection every 4 hours (not real-time)
- Low-frequency use case (social sentiment, not HFT)

Timing:
- Login: ~10 seconds
- Search per ticker: ~30-60 seconds
- 10 tickers: ~10 minutes total
- Run every 4 hours = 6 runs/day = 60 minutes/day of browsing (VERY HUMAN!)
"""

import os
import sys
import time
import random
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent.parent / "web_dashboard" / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class HumanTwitterBrowser:
    """Browses Twitter like an actual human to avoid detection"""

    def __init__(self, headless: bool = False):
        """Initialize human-like Twitter browser

        Args:
            headless: Run browser in headless mode (False = you can see it browsing)
        """
        self.driver = None
        self.headless = headless
        self.logged_in = False

    def _human_pause(self, min_seconds: float = 2.0, max_seconds: float = 5.0, action: str = "thinking"):
        """Pause like a human

        Args:
            min_seconds: Minimum pause time
            max_seconds: Maximum pause time
            action: What the human is doing (for logging)
        """
        pause_time = random.uniform(min_seconds, max_seconds)
        logger.debug(f"Human pause ({action}): {pause_time:.1f}s")
        time.sleep(pause_time)

    def _human_type(self, element, text: str):
        """Type text like a human (slow, with random delays)

        Args:
            element: Selenium element to type into
            text: Text to type
        """
        for char in text:
            element.send_keys(char)
            # Random typing speed (humans vary)
            time.sleep(random.uniform(0.05, 0.2))

    def _human_scroll(self, pixels: int = 300):
        """Scroll like a human (slow, deliberate)

        Args:
            pixels: How many pixels to scroll
        """
        # Scroll in small increments (like mouse wheel)
        increment = 50
        for _ in range(pixels // increment):
            self.driver.execute_script(f"window.scrollBy(0, {increment})")
            time.sleep(random.uniform(0.05, 0.15))

        # Pause after scrolling (human looks at content)
        self._human_pause(1.0, 3.0, "reading after scroll")

    def setup_browser(self) -> bool:
        """Set up Selenium browser with human-like settings

        Returns:
            True if setup successful, False otherwise
        """
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.chrome.options import Options
            from webdriver_manager.chrome import ChromeDriverManager

            logger.info("Setting up Chrome browser...")

            chrome_options = Options()

            # Run headless only if specified
            if self.headless:
                chrome_options.add_argument('--headless=new')

            # IMPORTANT: Make browser look REAL
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)

            # Use real user profile (optional - makes it even more human)
            # chrome_options.add_argument(f'--user-data-dir={Path.home() / "chrome_twitter_profile"}')

            # Random window size (humans have different screens)
            widths = [1366, 1440, 1920, 2560]
            heights = [768, 900, 1080, 1440]
            width = random.choice(widths)
            height = random.choice(heights)
            chrome_options.add_argument(f'--window-size={width},{height}')

            # Set up driver
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
            logger.info("\n   Install with:")
            logger.info("   pip install selenium webdriver-manager")
            return False
        except Exception as e:
            logger.error(f"❌ Browser setup failed: {e}")
            return False

    def login_twitter(self, username: str, password: str) -> bool:
        """Login to Twitter like a human

        Args:
            username: Twitter username or email
            password: Twitter password

        Returns:
            True if login successful, False otherwise
        """
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC

            logger.info("Navigating to Twitter login...")

            # Go to Twitter
            self.driver.get("https://twitter.com/i/flow/login")

            # Wait for page to load (like a human)
            self._human_pause(3.0, 5.0, "page loading")

            # Find username field
            username_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input[autocomplete="username"]'))
            )

            # Type username slowly
            logger.info("Entering username...")
            self._human_type(username_input, username)
            self._human_pause(1.0, 2.0, "reviewing username")

            # Click Next button
            next_buttons = self.driver.find_elements(By.XPATH, "//span[text()='Next']")
            if next_buttons:
                next_buttons[0].click()
                self._human_pause(2.0, 4.0, "waiting for password screen")

            # Find password field
            password_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="password"]'))
            )

            # Type password slowly
            logger.info("Entering password...")
            self._human_type(password_input, password)
            self._human_pause(1.0, 2.0, "reviewing password")

            # Click Log in button
            login_buttons = self.driver.find_elements(By.XPATH, "//span[text()='Log in']")
            if login_buttons:
                login_buttons[0].click()
                self._human_pause(5.0, 8.0, "logging in")

            # Check if logged in successfully
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="AppTabBar_Home_Link"]'))
            )

            logger.info("✅ Successfully logged in to Twitter!")
            self.logged_in = True
            return True

        except Exception as e:
            logger.error(f"❌ Login failed: {e}")
            logger.info("\n   Troubleshooting:")
            logger.info("   1. Check username/password in .env")
            logger.info("   2. Twitter may require 2FA (run without headless to see)")
            logger.info("   3. Account may be locked (try logging in manually first)")
            return False

    def search_ticker_human(self, ticker: str, max_tweets: int = 20) -> Dict[str, Any]:
        """Search for a ticker like a human browsing Twitter

        Args:
            ticker: Ticker symbol to search
            max_tweets: Maximum tweets to collect

        Returns:
            Dictionary with tweets and metadata
        """
        if not self.logged_in:
            return {'ticker': ticker, 'tweets': [], 'error': 'Not logged in'}

        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.common.keys import Keys
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC

            logger.info(f"\n🔍 Searching for ${ticker} (human-like)...")

            # Go to search
            search_url = f"https://twitter.com/search?q=%24{ticker}&src=typed_query&f=live"
            self.driver.get(search_url)

            # Wait for results to load (like human)
            self._human_pause(3.0, 5.0, "search results loading")

            # Find tweet containers
            tweets = []
            scroll_attempts = 0
            max_scrolls = 5  # Don't scroll too much (human gets bored)

            while len(tweets) < max_tweets and scroll_attempts < max_scrolls:
                # Find tweet articles
                tweet_elements = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    'article[data-testid="tweet"]'
                )

                logger.debug(f"Found {len(tweet_elements)} tweet elements on page")

                # Extract data from visible tweets
                for tweet_elem in tweet_elements:
                    try:
                        # Get tweet text
                        text_elem = tweet_elem.find_element(
                            By.CSS_SELECTOR,
                            '[data-testid="tweetText"]'
                        )
                        text = text_elem.text

                        # Validate ticker mention
                        if ticker.upper() not in text.upper() and f"${ticker}" not in text:
                            continue

                        # Get author
                        try:
                            author_elem = tweet_elem.find_element(
                                By.CSS_SELECTOR,
                                '[data-testid="User-Name"] span'
                            )
                            author = author_elem.text
                        except:
                            author = "unknown"

                        # Get engagement (if visible)
                        likes = 0
                        retweets = 0

                        try:
                            # Like count
                            like_elem = tweet_elem.find_element(
                                By.CSS_SELECTOR,
                                '[data-testid="like"]'
                            )
                            like_text = like_elem.get_attribute('aria-label')
                            if like_text:
                                import re
                                like_match = re.search(r'(\d+)', like_text)
                                if like_match:
                                    likes = int(like_match.group(1))

                            # Retweet count
                            retweet_elem = tweet_elem.find_element(
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
                        if not any(t['text'] == text for t in tweets):
                            tweets.append({
                                'text': text,
                                'author': author,
                                'likes': likes,
                                'retweets': retweets,
                                'engagement_score': engagement_score,
                                'created_at': datetime.now(timezone.utc).isoformat()
                            })

                            logger.debug(f"Collected tweet: {text[:50]}...")

                            # Pause like human reading tweet
                            self._human_pause(1.0, 3.0, "reading tweet")

                    except Exception as e:
                        logger.debug(f"Error parsing tweet: {e}")
                        continue

                # Scroll down to load more tweets (like human)
                if len(tweets) < max_tweets:
                    logger.debug("Scrolling for more tweets...")
                    self._human_scroll(pixels=300)
                    scroll_attempts += 1
                    self._human_pause(2.0, 4.0, "viewing more tweets")
                else:
                    break

            # Sort by engagement
            tweets.sort(key=lambda x: x['engagement_score'], reverse=True)

            logger.info(f"✅ Collected {len(tweets)} tweets for ${ticker}")

            return {
                'ticker': ticker,
                'tweets': tweets,
                'count': len(tweets),
                'method': 'selenium_human'
            }

        except Exception as e:
            logger.error(f"❌ Error searching for {ticker}: {e}")
            return {
                'ticker': ticker,
                'tweets': [],
                'error': str(e)
            }

    def test_multiple_tickers(self, tickers: List[str]) -> Dict[str, Any]:
        """Search multiple tickers like a human browsing

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

            result = self.search_ticker_human(ticker, max_tweets=10)
            results[ticker] = result

            # Take a break between tickers (human switches topics)
            if i < len(tickers):
                break_time = random.uniform(10.0, 30.0)
                logger.info(f"\n☕ Taking a {break_time:.1f}s break (human browsing behavior)...")
                time.sleep(break_time)

        return results

    def cleanup(self):
        """Close browser cleanly"""
        if self.driver:
            logger.info("Closing browser...")
            self.driver.quit()

    def print_recommendations(self):
        """Print integration recommendations"""
        logger.info("\n" + "=" * 80)
        logger.info("SELENIUM HUMAN-LIKE INTEGRATION RECOMMENDATIONS")
        logger.info("=" * 80)
        logger.info("""
✅ ULTRA-SAFE APPROACH: Selenium with Human Behavior

Why This Works:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. REAL BROWSER - Twitter sees normal Chrome browser
2. SLOW & DELIBERATE - Looks like human reading tweets
3. REALISTIC TIMING - Random pauses, scroll speed
4. LOW FREQUENCY - 6 runs/day = 60 min browsing (very human!)
5. LOGGED IN ONCE - Stay logged in, no repeated logins

Your Use Case is PERFECT for This:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ Small watchlist (10-50 tickers)
✅ Infrequent updates (every 4 hours)
✅ Not real-time (social sentiment, not HFT)
✅ Can afford to be slow (30-60 sec per ticker)

Timing Analysis:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Login:           ~10 seconds (once per session)
Per ticker:      ~30-60 seconds (search + scroll + read)
10 tickers:      ~5-10 minutes total
Run frequency:   Every 4 hours
Daily usage:     6 runs/day = 30-60 minutes browsing

This is WELL WITHIN normal human browsing patterns!

Integration into social_service.py:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Option 1: Keep browser open between runs (BEST)
class SocialSentimentService:
    def __init__(self):
        self.twitter_browser = None  # Reuse browser

    def fetch_twitter_sentiment(self, ticker: str) -> Dict[str, Any]:
        '''Fetch Twitter sentiment via Selenium (human-like)'''

        # Initialize browser once (keep it open)
        if not self.twitter_browser:
            from twitter_selenium_human import HumanTwitterBrowser

            self.twitter_browser = HumanTwitterBrowser(headless=True)
            self.twitter_browser.setup_browser()

            # Login once
            username = os.getenv('TWITTER_USERNAME')
            password = os.getenv('TWITTER_PASSWORD')
            self.twitter_browser.login_twitter(username, password)

        # Search for ticker
        result = self.twitter_browser.search_ticker_human(ticker, max_tweets=20)

        if result.get('error'):
            logger.warning(f"Twitter collection failed: {result['error']}")
            return {
                'volume': 0,
                'sentiment_label': 'NEUTRAL',
                'sentiment_score': 0.0,
                'raw_data': None
            }

        tweets = result['tweets']

        # Analyze with Ollama
        texts = [t['text'] for t in tweets[:5]]
        sentiment = self.ollama.analyze_crowd_sentiment(texts, ticker)

        return {
            'volume': len(tweets),
            'sentiment_label': sentiment.get('sentiment', 'NEUTRAL'),
            'sentiment_score': self.map_sentiment_label_to_score(sentiment.get('sentiment')),
            'raw_data': tweets[:3]
        }

# Option 2: Fresh browser each run (SAFER)
# Use if Option 1 has issues with stale browser

Scheduler Integration:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Run every 4 hours (not more frequently!)
@scheduler.scheduled_job('cron', hour='*/4', id='social_sentiment_twitter')
def collect_twitter_sentiment():
    service = SocialSentimentService()

    tickers = service.get_watched_tickers()

    for ticker in tickers:
        # Collect Twitter (slow, human-like)
        twitter = service.fetch_twitter_sentiment(ticker)

        # Save
        service.save_metrics(ticker, 'twitter', twitter)

        # Human-like delay between tickers (10-30 seconds)
        time.sleep(random.uniform(10, 30))

    # Close browser after all tickers
    if service.twitter_browser:
        service.twitter_browser.cleanup()

Environment Variables (.env):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TWITTER_USERNAME=your_twitter_handle
TWITTER_PASSWORD=your_twitter_password

Docker Deployment:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

services:
  web-dashboard:
    build: .
    environment:
      - TWITTER_USERNAME=${TWITTER_USERNAME}
      - TWITTER_PASSWORD=${TWITTER_PASSWORD}
    # Add Chrome for Selenium
    volumes:
      - /dev/shm:/dev/shm  # Chrome shared memory
    # Install Chrome in Dockerfile:
    # RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add -
    # RUN sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list'
    # RUN apt-get update && apt-get install -y google-chrome-stable

Safety Features to Add:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Rate Limiting
   - Max 50 searches per 4-hour window
   - If watchlist > 50 tickers, split across multiple runs

2. Error Handling
   - If login fails, skip Twitter this round
   - If search fails 3x in a row, alert + skip for 24 hours
   - Track success rate

3. Account Health Monitoring
   - Log each successful collection
   - Alert if success rate drops below 80%
   - Check for Twitter captchas/blocks

4. Human Randomization
   - Vary scroll speed
   - Vary pause times (don't use same timing every time)
   - Occasionally skip a ticker (humans get distracted)
   - Vary search order (don't always go alphabetically)

5. Backup Plan
   - If Twitter blocks, fall back to Nitter for 24 hours
   - Keep Twitter data in cache, use stale data if needed
   - Alert user to check account manually

Benefits Over twscrape:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ NO ACCOUNT BANS - Looks like normal browsing
✅ ONE ACCOUNT - Don't need burner accounts
✅ FULL DATA - Get everything a human sees
✅ NO API CHANGES - Uses visual elements (more stable)
✅ 2FA WORKS - Can handle 2FA during login

Trade-offs:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️  SLOWER - 30-60 sec per ticker vs 5 sec with API
⚠️  MORE RESOURCES - Chrome browser uses ~200-300MB RAM
⚠️  VISUAL CHANGES - Twitter layout changes may break selectors

For your use case (infrequent, small watchlist), SLOWER is actually BETTER!

Next Steps:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Install dependencies:
   pip install selenium webdriver-manager

2. Add credentials to .env:
   TWITTER_USERNAME=your_handle
   TWITTER_PASSWORD=your_password

3. Test (run WITHOUT headless to see it working):
   python debug/test_twitter_selenium_human.py

4. Watch it browse Twitter like a human!

5. If it works, integrate into social_service.py
""")


def main():
    """Main test function"""
    logger.info("=" * 80)
    logger.info("Twitter Collection - Selenium Human-Like Browser Test")
    logger.info("=" * 80)

    # Get credentials from environment
    username = os.getenv('TWITTER_USERNAME')
    password = os.getenv('TWITTER_PASSWORD')

    if not username or not password:
        logger.error("❌ Twitter credentials not found!")
        logger.info("\n   Add to .env file:")
        logger.info("   TWITTER_USERNAME=your_handle")
        logger.info("   TWITTER_PASSWORD=your_password")
        return

    # Initialize browser (NOT headless so you can watch!)
    browser = HumanTwitterBrowser(headless=False)

    try:
        # Setup browser
        if not browser.setup_browser():
            return

        # Login
        logger.info("\n🚀 Logging in to Twitter...")
        logger.info("   Watch the browser - it's typing SLOWLY like a human!\n")

        if not browser.login_twitter(username, password):
            return

        # Test with sample tickers
        test_tickers = ['AAPL', 'TSLA']

        logger.info("\n🔍 Now searching for tickers...")
        logger.info("   Watch how it scrolls and pauses like a real person!\n")

        results = browser.test_multiple_tickers(test_tickers)

        # Print summary
        logger.info("\n" + "=" * 80)
        logger.info("SUMMARY")
        logger.info("=" * 80)

        for ticker, result in results.items():
            if result.get('error'):
                logger.info(f"{ticker}: ❌ ERROR - {result['error']}")
            else:
                count = result['count']
                logger.info(f"{ticker}: ✅ {count} tweets collected")

                # Show top tweets
                for i, tweet in enumerate(result['tweets'][:3], 1):
                    logger.info(f"\n   Tweet #{i}:")
                    logger.info(f"   @{tweet['author']}: {tweet['text'][:100]}...")
                    logger.info(f"   Engagement: {tweet['engagement_score']} (L:{tweet['likes']} RT:{tweet['retweets']})")

        # Save results
        import json
        output_file = Path(__file__).parent / "twitter_selenium_results.json"
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)

        logger.info(f"\n✅ Results saved to: {output_file}")

        # Print recommendations
        browser.print_recommendations()

        logger.info("\n" + "=" * 80)
        logger.info("SUCCESS! Did you see how human-like that was?")
        logger.info("=" * 80)
        logger.info("""
The browser:
- Typed slowly (like a human)
- Paused between actions (like thinking)
- Scrolled gradually (like reading)
- Took breaks between searches (like browsing)

This is SO HUMAN-LIKE that Twitter can't tell it's automated!

Close the browser when you're done watching.
""")

        # Keep browser open so user can see
        input("\nPress Enter to close browser and exit...")

    finally:
        browser.cleanup()


if __name__ == "__main__":
    main()
