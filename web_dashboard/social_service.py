#!/usr/bin/env python3
"""
Social Sentiment Service
========================

Service for fetching and storing social sentiment data from StockTwits and Reddit.
Part of Phase 2: Social Sentiment Tracking.
"""

import os
import json
import logging
import time
import re
import requests
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from settings import get_summarizing_model
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from web_dashboard/.env
# Try web_dashboard/.env first (when running from project root)
# Then fall back to .env in current directory
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()  # Fallback to current directory

logger = logging.getLogger(__name__)

# FlareSolverr configuration (for bypassing Cloudflare on StockTwits)
# Default: host.docker.internal for Docker containers
# Override: FLARESOLVERR_URL env variable for local testing (e.g., Tailscale)
FLARESOLVERR_URL = os.getenv("FLARESOLVERR_URL", "http://host.docker.internal:8191")

# Import clients
from postgres_client import PostgresClient
from supabase_client import SupabaseClient
from ollama_client import OllamaClient, get_ollama_client


class SocialSentimentService:
    """Service for fetching and storing social sentiment metrics"""
    
    def __init__(
        self,
        postgres_client: Optional[PostgresClient] = None,
        supabase_client: Optional[SupabaseClient] = None,
        ollama_client: Optional[OllamaClient] = None
    ):
        """Initialize social sentiment service
        
        Args:
            postgres_client: Optional PostgresClient instance
            supabase_client: Optional SupabaseClient instance
            ollama_client: Optional OllamaClient instance
        """
        try:
            self.postgres = postgres_client or PostgresClient()
            self.supabase = supabase_client or SupabaseClient()
            self.ollama = ollama_client or get_ollama_client()
            
            # Rate limiting state
            self.last_reddit_request_time = 0
            
        except Exception as e:
            logger.error(f"Failed to initialize PostgresClient: {e}")
            raise
        
        try:
            self.supabase = supabase_client or SupabaseClient(use_service_role=True)
        except Exception as e:
            logger.error(f"Failed to initialize SupabaseClient: {e}")
            raise
        
        self.ollama = ollama_client or get_ollama_client()
        
        # FlareSolverr URL (can be overridden per instance if needed)
        self.flaresolverr_url = FLARESOLVERR_URL
    
    def _wait_for_reddit_rate_limit(self, min_interval: float = 2.0) -> None:
        """Enforce rate limit between Reddit requests.

        Args:
            min_interval: Minimum seconds between requests (default: 2.0)
        """
        now = time.time()
        elapsed = now - getattr(self, 'last_reddit_request_time', 0)
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self.last_reddit_request_time = time.time()

    def make_flaresolverr_request(self, url: str) -> Optional[Dict[str, Any]]:
        """Make a request through FlareSolverr to bypass Cloudflare protection.
        
        Args:
            url: Target URL to fetch via FlareSolverr
            
        Returns:
            Dictionary with parsed JSON data if successful, None if failed
        """
        try:
            flaresolverr_endpoint = f"{self.flaresolverr_url}/v1"
            
            payload = {
                "cmd": "request.get",
                "url": url,
                "maxTimeout": 60000  # 60 seconds
            }
            
            logger.debug(f"Requesting via FlareSolverr: {url}")
            response = requests.post(
                flaresolverr_endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=70  # Slightly longer than maxTimeout
            )
            
            response.raise_for_status()
            flaresolverr_data = response.json()
            
            # Check FlareSolverr status
            if flaresolverr_data.get("status") != "ok":
                error_msg = flaresolverr_data.get("message", "Unknown error")
                logger.warning(f"FlareSolverr returned error status: {error_msg}")
                return None
            
            # Extract solution
            solution = flaresolverr_data.get("solution", {})
            if not solution:
                logger.warning("FlareSolverr response missing solution")
                return None
            
            # Get the actual HTTP status from the solution
            http_status = solution.get("status", 0)
            response_body = solution.get("response", "")
            
            # Check if the target site returned an error
            if http_status != 200:
                logger.warning(f"Target site returned HTTP {http_status} via FlareSolverr")
                # Log first 200 chars of response for debugging
                if response_body:
                    preview = response_body[:200] if len(response_body) > 200 else response_body
                    logger.debug(f"Response preview: {preview}")
                return None
            
            # Check if response body is empty
            if not response_body or not response_body.strip():
                logger.warning("FlareSolverr returned empty response body")
                return None
            
            # Parse the response body (should be JSON for StockTwits API)
            # FlareSolverr may return HTML with JSON inside, so try to extract JSON
            try:
                # Try parsing as-is first
                data = json.loads(response_body)
                logger.debug(f"Successfully fetched data via FlareSolverr (status: {http_status}, {len(response_body)} bytes)")
                return data
            except json.JSONDecodeError:
                # If direct parse fails, try to extract JSON from HTML
                # FlareSolverr sometimes wraps JSON in HTML (e.g., <pre> tags)
                import re
                # Look for JSON object in the response (starts with { and ends with })
                json_match = re.search(r'\{.*\}', response_body, re.DOTALL)
                if json_match:
                    try:
                        json_str = json_match.group(0)
                        data = json.loads(json_str)
                        logger.debug(f"Successfully extracted JSON from HTML response via FlareSolverr")
                        return data
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse extracted JSON from FlareSolverr response: {e}")
                else:
                    # Log first 500 chars to help debug what we got
                    preview = response_body[:500] if len(response_body) > 500 else response_body
                    logger.warning(f"Failed to find JSON in FlareSolverr response")
                    logger.debug(f"Response preview (first 500 chars): {preview}")
                    # Check if it looks like HTML (Cloudflare challenge page)
                    if response_body.strip().startswith('<') or 'cloudflare' in response_body.lower():
                        logger.warning("Response appears to be HTML (Cloudflare challenge) - FlareSolverr may need more time")
                return None
                
        except requests.exceptions.ConnectionError:
            logger.debug(f"FlareSolverr unavailable at {self.flaresolverr_url} - will fallback to direct request")
            return None
        except requests.exceptions.Timeout:
            logger.warning(f"FlareSolverr request timed out - will fallback to direct request")
            return None
        except requests.exceptions.RequestException as e:
            logger.warning(f"FlareSolverr request failed: {e} - will fallback to direct request")
            return None
        except Exception as e:
            logger.warning(f"Unexpected error with FlareSolverr: {e} - will fallback to direct request")
            return None
    
    def get_watched_tickers(self) -> List[str]:
        """Get list of active tickers from watched_tickers table
        
        Returns:
            List of ticker symbols to monitor
        """
        try:
            result = self.supabase.supabase.table("watched_tickers")\
                .select("ticker")\
                .eq("is_active", True)\
                .execute()
            
            tickers = [row['ticker'] for row in result.data if row.get('ticker')]
            logger.debug(f"Found {len(tickers)} active watched tickers")
            return tickers
            
        except Exception as e:
            logger.error(f"Error fetching watched tickers: {e}")
            return []
    
    def fetch_stocktwits_sentiment(self, ticker: str) -> Dict[str, Any]:
        """Fetch sentiment data from StockTwits API
        
        Args:
            ticker: Ticker symbol to fetch
            
        Returns:
            Dictionary with:
            - volume: Post count in last 60 minutes
            - bull_bear_ratio: Ratio of Bullish to Bearish posts (0.0 to 1.0)
            - raw_data: Top 3 posts as JSONB
        """
        url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
        
        # Try FlareSolverr first to bypass Cloudflare protection
        data = None
        try:
            data = self.make_flaresolverr_request(url)
        except Exception as e:
            logger.debug(f"FlareSolverr request failed for {ticker}: {e}")
        
        # Fallback to direct request if FlareSolverr failed or unavailable
        if data is None:
            logger.debug(f"Falling back to direct request for {ticker}")
            # Use browser-like User-Agent (required by StockTwits)
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9"
            }
            
            try:
                response = requests.get(url, headers=headers, timeout=10)
                
                # Handle 403 Forbidden (may be rate limiting or IP blocking)
                if response.status_code == 403:
                    logger.warning(f"StockTwits API returned 403 Forbidden for {ticker} (direct request).")
                    logger.warning("  FlareSolverr may be unavailable or Cloudflare blocking persists.")
                    return {
                        'volume': 0,
                        'bull_bear_ratio': 0.0,
                        'raw_data': None
                    }
                
                response.raise_for_status()
                data = response.json()
            except requests.exceptions.RequestException as e:
                logger.warning(f"Direct StockTwits API request failed for {ticker}: {e}")
                return {
                    'volume': 0,
                    'bull_bear_ratio': 0.0,
                    'raw_data': None
                }
        
        # Process the data (from either FlareSolverr or direct request)
        if not data:
            return {
                'volume': 0,
                'bull_bear_ratio': 0.0,
                'raw_data': None
            }
        
        try:
            messages = data.get('messages', [])
            if not messages:
                logger.debug(f"No messages found for {ticker} on StockTwits")
                return {
                    'volume': 0,
                    'bull_bear_ratio': 0.0,
                    'raw_data': None
                }
            
            # Filter messages by created_at (last 60 minutes)
            cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=60)
            recent_messages = []
            bull_count = 0
            bear_count = 0
            
            for msg in messages:
                created_at_str = msg.get('created_at')
                if not created_at_str:
                    continue
                
                try:
                    # Parse timestamp (StockTwits uses ISO format like "2024-01-15T10:30:00Z")
                    msg_dt = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                    
                    if msg_dt >= cutoff_time:
                        recent_messages.append(msg)
                        
                        # Check sentiment entities
                        entities = msg.get('entities', {})
                        sentiment = entities.get('sentiment')
                        if sentiment and isinstance(sentiment, dict):
                            basic = sentiment.get('basic')
                            if basic == 'Bullish':
                                bull_count += 1
                            elif basic == 'Bearish':
                                bear_count += 1
                except (ValueError, AttributeError) as e:
                    logger.debug(f"Could not parse timestamp for message: {e}")
                    continue
            
            # Calculate bull/bear ratio
            total_labeled = bull_count + bear_count
            if total_labeled > 0:
                bull_bear_ratio = bull_count / total_labeled
            else:
                bull_bear_ratio = 0.0
            
            # Get top 3 posts for raw_data
            top_posts = recent_messages[:3]
            raw_data = None
            if top_posts:
                raw_data = [
                    {
                        'id': msg.get('id'),
                        'body': msg.get('body', ''),
                        'created_at': msg.get('created_at', ''),
                        'user': msg.get('user', {}).get('username', 'Unknown')
                    }
                    for msg in top_posts
                ]
            
            logger.debug(f"StockTwits {ticker}: volume={len(recent_messages)}, ratio={bull_bear_ratio:.2f}")
            
            return {
                'volume': len(recent_messages),
                'bull_bear_ratio': bull_bear_ratio,
                'raw_data': raw_data
            }
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"StockTwits API request failed for {ticker}: {e}")
            return {
                'volume': 0,
                'bull_bear_ratio': 0.0,
                'raw_data': None
            }
        except Exception as e:
            logger.error(f"Error fetching StockTwits sentiment for {ticker}: {e}", exc_info=True)
            return {
                'volume': 0,
                'bull_bear_ratio': 0.0,
                'raw_data': None
            }
    
    def fetch_reddit_sentiment(self, ticker: str, max_duration: Optional[float] = None) -> Dict[str, Any]:
        """Fetch sentiment data from Reddit using public JSON endpoint
        
        Uses Reddit's public search API without authentication.
        Only searches whitelisted stock-related subreddits.
        Respects rate limits with 2-second delay between requests.
        
        Args:
            ticker: Ticker symbol to fetch
            max_duration: Optional maximum duration in seconds for this fetch (default: None, no limit)
            
        Returns:
            Dictionary with:
            - volume: Post count in last week
            - sentiment_label: AI-categorized label (EUPHORIC, BULLISH, NEUTRAL, BEARISH, FEARFUL)
            - sentiment_score: Numeric score mapped from label (-2.0 to 2.0)
            - raw_data: Top 3 posts/comments as JSONB
        """
        fetch_start = time.time()
        try:
            # Use browser-like User-Agent to avoid 429 errors
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            # Whitelist of stock-related subreddits (prioritize most active ones first)
            STOCK_SUBREDDITS = [
                'wallstreetbets',  # Most active, check first
                'stocks',
                'investing',
                'StockMarket',
                'pennystocks',
                'Shortsqueeze',
                'options',
                'robinhood',
                'stock_picks',
                'investments',
                'RobinHoodPennyStocks',
                'microcap',
                'biotechplays',
                'securityanalysis',
                'valueinvesting',
                'CanadianPennyStocks',
                'Undervalued',
                'BayStreetBets',
                'SPACs',
                'dividends',
                'weedstocks',
                'CryptoCurrency'  # Sometimes discusses stock tickers
            ]
            
            # Define common words that are also tickers (noisy plain text search)
            common_words = {
                'AI', 'CAT', 'GOOD', 'FOR', 'ARE', 'ALL', 'CAN', 'NEW', 'ONE', 'OUT', 
                'RUN', 'SEE', 'TWO', 'NOW', 'BIT', 'KEY', 'USA', 'EAT', 'BIG', 'LOW', 
                'FAT', 'HOT', 'FUN', 'PLAY', 'LOVE', 'GET', 'SET', 'GO', 'CAR', 'DOG'
            }
            
            # Determine search queries
            # Always search for cashtag ($TICKER) - High signal
            search_queries = [f"${ticker}"]
            
            # Only search plain text (TICKER) if safe
            if ticker not in common_words:
                # For 1-2 letter tickers, NEVER search plain text (too noisy)
                if len(ticker) >= 3:
                     search_queries.append(ticker)
            
            all_posts = []
            cutoff_time = datetime.now(timezone.utc) - timedelta(days=7)  # Last week
            ENOUGH_POSTS = 10  # Early termination if we have enough posts
            
            # Search each whitelisted subreddit
            for subreddit_name in STOCK_SUBREDDITS:
                # Check timeout before processing each subreddit
                if max_duration:
                    elapsed = time.time() - fetch_start
                    if elapsed > max_duration:
                        logger.debug(f"Reddit fetch timeout for {ticker} after {elapsed:.1f}s (found {len(all_posts)} posts)")
                        break
                
                # Early termination if we have enough posts
                if len(all_posts) >= ENOUGH_POSTS:
                    logger.debug(f"Early termination for {ticker}: found {len(all_posts)} posts (enough for analysis)")
                    break
                for query in search_queries:
                    try:
                        # Search within specific subreddit using relevance sort and last week
                        # Format: /r/subreddit/search.json?q=query&sort=relevance&t=week&limit=25&restrict_sr=1
                        url = f"https://www.reddit.com/r/{subreddit_name}/search.json?q={query}&sort=relevance&t=week&limit=25&restrict_sr=1"
                        
                        # Rate limiting before request
                        self._wait_for_reddit_rate_limit()

                        response = requests.get(url, headers=headers, timeout=10)
                        
                        # Handle rate limiting
                        if response.status_code == 429:
                            logger.warning(f"Reddit rate limit hit for {ticker} in r/{subreddit_name}. Waiting longer...")
                            time.sleep(5)  # Wait longer if rate limited
                            continue
                        
                        response.raise_for_status()
                        data = response.json()
                        
                        # Parse nested JSON structure: response['data']['children'][i]['data']
                        if 'data' in data and 'children' in data['data']:
                            for child in data['data']['children']:
                                if 'data' not in child:
                                    continue
                                
                                post_data = child['data']
                                
                                # Extract fields
                                title = post_data.get('title', '')
                                selftext = post_data.get('selftext', '')
                                ups = post_data.get('ups', 0)  # upvotes
                                num_comments = post_data.get('num_comments', 0)
                                created_utc = post_data.get('created_utc', 0)
                                url = post_data.get('url', '')
                                subreddit = post_data.get('subreddit', '')
                                
                                # Convert created_utc (Unix timestamp) to datetime
                                if created_utc:
                                    post_dt = datetime.fromtimestamp(created_utc, tz=timezone.utc)
                                    
                                    # Filter posts from last week
                                    if post_dt >= cutoff_time:
                                        
                                        # CRITICAL: Validate that post actually mentions the ticker
                                        # Combine title and text for validation
                                        full_text = (title + " " + selftext).upper()
                                        
                                        # Check for cashtag mention ($TICKER)
                                        cashtag_pattern = r'\$' + re.escape(ticker) + r'\b'
                                        has_cashtag = bool(re.search(cashtag_pattern, full_text, re.IGNORECASE))
                                        
                                        # Check for plain ticker mention with word boundaries
                                        # Only accept if it's clearly a stock ticker (not part of another word)
                                        ticker_pattern = r'\b' + re.escape(ticker) + r'\b'
                                        has_ticker = bool(re.search(ticker_pattern, full_text, re.IGNORECASE))
                                        
                                        # Only accept posts that actually mention the ticker
                                        if has_cashtag or has_ticker:
                                            all_posts.append({
                                                'title': title,
                                                'selftext': selftext,
                                                'score': ups,  # Use upvotes as score
                                                'num_comments': num_comments,
                                                'created_utc': created_utc,
                                                'url': url,
                                                'subreddit': subreddit
                                            })
                                        else:
                                            # Log filtered posts for debugging
                                            logger.debug(f"Filtered out post for {ticker} in r/{subreddit_name}: '{title[:50]}...' (no ticker mention)")
                        
                    except requests.exceptions.HTTPError as e:
                        if e.response.status_code == 429:
                            logger.warning(f"Reddit rate limit for {ticker} in r/{subreddit_name}. Skipping.")
                            time.sleep(5)
                        else:
                            logger.debug(f"HTTP error searching r/{subreddit_name} for {query}: {e}")
                        continue
                    except Exception as e:
                        logger.debug(f"Error searching r/{subreddit_name} for {query}: {e}")
                        continue
            
            # Deduplicate by URL
            seen_urls = set()
            unique_posts = []
            for post in all_posts:
                if post['url'] not in seen_urls:
                    seen_urls.add(post['url'])
                    unique_posts.append(post)
            
            # Sort by score (upvotes) and take top 5 for AI analysis
            unique_posts.sort(key=lambda x: x['score'], reverse=True)
            top_5_posts = unique_posts[:5]
            
            # Combine post titles and bodies for AI analysis
            texts_for_ai = []
            for post in top_5_posts:
                text = f"{post['title']}\n{post['selftext'][:500]}"
                texts_for_ai.append(text)
            
            # Analyze sentiment with Ollama
            sentiment_label = 'NEUTRAL'
            sentiment_score = 0.0
            reasoning = ""
            
            if texts_for_ai and self.ollama:
                try:
                    result = self.ollama.analyze_crowd_sentiment(texts_for_ai, ticker)
                    sentiment_label = result.get('sentiment', 'NEUTRAL')
                    reasoning = result.get('reasoning', '')
                    sentiment_score = self.map_sentiment_label_to_score(sentiment_label)
                except Exception as e:
                    logger.warning(f"Ollama sentiment analysis failed for {ticker}: {e}")
            
            # Prepare raw_data (top 3 posts)
            raw_data = None
            if unique_posts:
                raw_data = [
                    {
                        'title': post['title'],
                        'selftext': post['selftext'][:500],  # Limit length
                        'score': post['score'],
                        'num_comments': post['num_comments'],
                        'subreddit': post['subreddit'],
                        'url': post['url']
                    }
                    for post in unique_posts[:3]
                ]
            
            logger.debug(f"Reddit {ticker}: volume={len(unique_posts)}, sentiment={sentiment_label} ({sentiment_score:.1f})")
            
            return {
                'volume': len(unique_posts),
                'sentiment_label': sentiment_label,
                'sentiment_score': sentiment_score,
                'raw_data': raw_data
            }
            
        except Exception as e:
            logger.error(f"Error fetching Reddit sentiment for {ticker}: {e}", exc_info=True)
            return {
                'volume': 0,
                'sentiment_label': 'NEUTRAL',
                'sentiment_score': 0.0,
                'raw_data': None
            }
    
    def map_sentiment_label_to_score(self, label: str) -> float:
        """Map sentiment label to numeric score
        
        Args:
            label: Sentiment label (EUPHORIC, BULLISH, NEUTRAL, BEARISH, FEARFUL)
            
        Returns:
            Numeric score from -2.0 to 2.0
        """
        mapping = {
            "EUPHORIC": 2.0,
            "BULLISH": 1.0,
            "NEUTRAL": 0.0,
            "BEARISH": -1.0,
            "FEARFUL": -2.0
        }
        return mapping.get(label.upper(), 0.0)
    
    def save_metrics(self, ticker: str, platform: str, metrics: Dict[str, Any]) -> None:
        """Save social sentiment metrics to database
        
        Args:
            ticker: Ticker symbol
            platform: 'stocktwits' or 'reddit'
            metrics: Dictionary with metric data
        """
        try:
            # Prepare raw_data as JSONB
            raw_data_json = None
            if metrics.get('raw_data'):
                raw_data_json = json.dumps(metrics['raw_data'])
            
            # Build query based on platform
            if platform == 'stocktwits':
                query = """
                    INSERT INTO social_metrics 
                    (ticker, platform, volume, bull_bear_ratio, raw_data, created_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                """
                params = (
                    ticker,
                    platform,
                    metrics.get('volume', 0),
                    metrics.get('bull_bear_ratio', 0.0),
                    raw_data_json
                )
            elif platform == 'reddit':
                query = """
                    INSERT INTO social_metrics 
                    (ticker, platform, volume, sentiment_label, sentiment_score, raw_data, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                """
                params = (
                    ticker,
                    platform,
                    metrics.get('volume', 0),
                    metrics.get('sentiment_label', 'NEUTRAL'),
                    metrics.get('sentiment_score', 0.0),
                    raw_data_json
                )
            else:
                logger.error(f"Unknown platform: {platform}")
                return
            
            self.postgres.execute_update(query, params)
            logger.debug(f"Saved {platform} metrics for {ticker}")
            
        except Exception as e:
            logger.error(f"Error saving {platform} metrics for {ticker}: {e}", exc_info=True)
            raise

    def scan_subreddit_opportunities(self, subreddit: str, limit: int = 20, min_score: int = 50) -> List[Dict[str, Any]]:
        """Scan a subreddit for high-conviction investment opportunities
        
        Fetches top posts, their top comments, and uses AI to identify
        tickers being pitched with significant due diligence.
        
        Args:
            subreddit: Name of subreddit (e.g., 'pennystocks')
            limit: Max posts to scan
            min_score: Minimum upvotes to consider
            
        Returns:
            List of opportunities (ticker, title, url, reasoning, confidence)
        """
        opportunities = []
        
        try:
            logger.info(f"🔎 Scanning r/{subreddit} for opportunities...")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            # Fetch top posts with rate limiting
            url = f"https://www.reddit.com/r/{subreddit}/top.json?t=day&limit={limit}"
            self._wait_for_reddit_rate_limit()
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 429:
                logger.warning(f"Rate limited scanning r/{subreddit}")
                return []
                
            response.raise_for_status()
            data = response.json()
            
            if 'data' not in data or 'children' not in data['data']:
                logger.warning(f"Invalid response format from r/{subreddit}")
                return []
            
            posts = data['data']['children']
            logger.info(f"Found {len(posts)} posts in r/{subreddit}")
            
            for child in posts:
                post = child.get('data', {})
                if not post or post.get('score', 0) < min_score:
                    continue
                
                # Check duplication (skip if URL already analyzed?)
                # Ideally check DB here, but job will handle dedupe
                
                post_id = post.get('id')
                title = post.get('title', '')
                selftext = post.get('selftext', '')
                score = post.get('score', 0)
                url = post.get('url', '')
                
                # Fetch comments for context (Deep Dive)
                comments_text = ""
                try:
                    # Rate limit for comment fetch
                    comments_url = f"https://www.reddit.com/comments/{post_id}.json?sort=top&limit=10"
                    self._wait_for_reddit_rate_limit()
                    
                    c_resp = requests.get(comments_url, headers=headers, timeout=10)
                    
                    if c_resp.status_code == 200:
                        c_data = c_resp.json()
                        # Reddit comment structure is [post_listing, comment_listing]
                        if isinstance(c_data, list) and len(c_data) > 1:
                            comment_listing = c_data[1]
                            if 'data' in comment_listing and 'children' in comment_listing['data']:
                                for c in comment_listing['data']['children']:
                                    c_body = c.get('data', {}).get('body', '')
                                    if c_body:
                                        comments_text += f"- {c_body[:500]}...\n"
                except Exception as e:
                    logger.debug(f"Failed to fetch comments for {post_id}: {e}")
                
                # Prepare AI Prompt
                # 8k context is ~32k characters. We can afford to be generous.
                full_text = f"TITLE: {title}\n\nBODY: {selftext[:8000]}\n\nTOP COMMENTS:\n{comments_text}"
                
                if not self.ollama:
                    continue
                    
                # Analyze with Ollama
                try:
                    system_prompt = """You are an expert investment analyst hunting for microcap opportunities.
                    
TASK:
Analyze this Reddit post to see if it is a "Due Diligence" (DD) pitch for a specific stock ticker.
Ignore memes, "to the moon" hype, or general market discussion.

OUTPUT JSON ONLY:
{
    "is_opportunity": true/false,
    "ticker": "TICKER",
    "confidence": 0.0-1.0,
    "reasoning": "Why this is a valid lookup (e.g. 'Detailed analysis of earnings', 'New contract announcement')"
}"""
                    
                    user_prompt = f"Analyze this post from r/{subreddit}:\n\n{full_text}"
                    
                    # Call Ollama (reusing query_ollama logic or direct call)
                    # We'll use query_ollama from client
                    response_text = ""
                    for chunk in self.ollama.query_ollama(
                        prompt=user_prompt, 
                        model="granite3.3:8b", # Explicitly use Granite for analysis
                        system_prompt=system_prompt,
                        json_mode=True,
                        temperature=0.1,
                        stream=True
                    ):
                        response_text += chunk
                    
                    # Parse
                    import json
                    result = json.loads(response_text)
                    
                    if result.get('is_opportunity') and result.get('ticker'):
                        # Normalize ticker
                        ticker = result['ticker'].upper().replace('$', '').strip()
                        
                        # Basic validation (length, etc.)
                        if 2 <= len(ticker) <= 5:
                            opportunities.append({
                                'ticker': ticker,
                                'title': title,
                                'url': f"https://www.reddit.com{post.get('permalink')}",
                                'reasoning': result.get('reasoning'),
                                'confidence': result.get('confidence', 0.5),
                                'score': score,
                                'subreddit': subreddit,
                                'full_text': full_text  # Return full context for UI
                            })
                            logger.info(f"💎 Found opportunity in r/{subreddit}: {ticker} ({result.get('confidence')})")
                            
                except Exception as e:
                    logger.warning(f"Error analyzing post {post_id}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error scanning r/{subreddit}: {e}")
            
        return opportunities
    
    def extract_posts_from_raw_data(self) -> Dict[str, int]:
        """Extract individual posts from social_metrics.raw_posts JSONB into social_posts table
        
        Migrates existing raw_data to structured format for AI analysis.
        
        Returns:
            Dictionary with counts of processed records
        """
        try:
            logger.info("🔄 Starting post extraction from raw_data...")
            
            # Get metrics with raw_data data that haven't been processed
            query = """
                SELECT id, ticker, platform, raw_data, created_at
                FROM social_metrics 
                WHERE raw_data IS NOT NULL 
                  AND raw_data != '{}'
                  AND id NOT IN (SELECT DISTINCT metric_id FROM social_posts)
                ORDER BY created_at DESC
                LIMIT 100  -- Process in batches
            """
            metrics = self.postgres.execute_query(query)
            
            if not metrics:
                logger.info("✅ No new raw_data data to extract")
                return {'processed': 0, 'posts_created': 0}
            
            posts_created = 0
            posts_filtered = 0
            
            for metric in metrics:
                metric_id = metric['id']
                ticker = metric['ticker']
                platform = metric['platform']
                raw_posts = metric['raw_data'] or []
                
                for post_data in raw_posts:
                    try:
                        # Extract post fields based on platform
                        if platform == 'stocktwits':
                            content = post_data.get('body', '')
                            # StockTwits posts are already filtered by ticker, so accept all
                            post_record = {
                                'metric_id': metric_id,
                                'platform': platform,
                                'post_id': post_data.get('id'),  # StockTwits now captures IDs
                                'content': content,
                                'author': post_data.get('user', ''),
                                'posted_at': post_data.get('created_at'),
                                'engagement_score': 0,  # Not available in current StockTwits data
                                'url': f"https://stocktwits.com/{post_data.get('user', 'Unknown')}/message/{post_data.get('id')}" if post_data.get('id') else None,
                                'extracted_tickers': self._extract_tickers_basic(content)
                            }
                        elif platform == 'reddit':
                            title = post_data.get('title', '')
                            selftext = post_data.get('selftext', '')
                            content = title + '\n\n' + selftext
                            full_text = content.upper()
                            
                            # Validate that post actually mentions the ticker
                            cashtag_pattern = r'\$' + re.escape(ticker) + r'\b'
                            ticker_pattern = r'\b' + re.escape(ticker) + r'\b'
                            
                            has_cashtag = bool(re.search(cashtag_pattern, full_text, re.IGNORECASE))
                            has_ticker = bool(re.search(ticker_pattern, full_text, re.IGNORECASE))
                            
                            # If post doesn't mention ticker, skip it
                            if not (has_cashtag or has_ticker):
                                posts_filtered += 1
                                logger.debug(f"Filtered out post for {ticker}: '{title[:50]}...' (no ticker mention)")
                                continue
                            
                            post_record = {
                                'metric_id': metric_id,
                                'platform': platform,
                                'post_id': post_data.get('id') or str(hash(post_data.get('url', ''))),
                                'content': content,
                                'author': 'u/' + post_data.get('author', 'unknown'),
                                'posted_at': datetime.fromtimestamp(post_data.get('created_utc', 0), tz=timezone.utc).isoformat(),
                                'engagement_score': (post_data.get('score', 0) + post_data.get('num_comments', 0) * 2),
                                'url': post_data.get('url', ''),
                                'extracted_tickers': self._extract_tickers_basic(title + ' ' + selftext)
                            }
                        
                        # Insert post record
                        insert_query = """
                            INSERT INTO social_posts 
                            (metric_id, platform, post_id, content, author, posted_at, 
                             engagement_score, url, extracted_tickers)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """
                        self.postgres.execute_update(insert_query, (
                            post_record['metric_id'], post_record['platform'], post_record['post_id'],
                            post_record['content'], post_record['author'], post_record['posted_at'],
                            post_record['engagement_score'], post_record['url'], post_record['extracted_tickers']
                        ))
                        
                        posts_created += 1
                        
                    except Exception as e:
                        logger.warning(f"Error extracting post for metric {metric_id}: {e}")
                        continue
            
            if posts_filtered > 0:
                logger.info(f"⚠️  Filtered out {posts_filtered} posts that didn't mention their ticker")
            
            logger.info(f"✅ Post extraction complete: processed {len(metrics)} metrics, created {posts_created} posts")
            return {'processed': len(metrics), 'posts_created': posts_created}
            
        except Exception as e:
            logger.error(f"❌ Error during post extraction: {e}", exc_info=True)
            raise
    
    def _extract_tickers_basic(self, text: str) -> List[str]:
        """Basic ticker extraction using regex patterns
        
        Args:
            text: Text content to extract tickers from
            
        Returns:
            List of extracted ticker symbols
        """
        import re
        
        if not text:
            return []
        
        # Common patterns: $TICKER, TICKER, (TICKER)
        patterns = [
            r'\$([A-Z]{1,5})(?:\W|$)',  # $TICKER
            r'\b([A-Z]{1,5})\b',        # TICKER (word boundaries)
        ]
        
        tickers = set()
        for pattern in patterns:
            matches = re.findall(pattern, text.upper())
            for match in matches:
                # Filter out common false positives
                if match not in ['THE', 'AND', 'FOR', 'ARE', 'BUT', 'NOT', 'YOU', 'ALL', 'CAN', 'HER', 'WAS', 'ONE', 'OUR', 'HAD', 'BY', 'HOT', 'BUT', 'FOR', 'ARE', 'BUT', 'NOT', 'YOU', 'ALL', 'CAN', 'HER', 'WAS', 'ONE', 'OUR', 'HAD', 'BY', 'HOT']:
                    tickers.add(match)
        
        return list(tickers)
    
    def create_sentiment_sessions(self) -> Dict[str, int]:
        """Create sentiment analysis sessions by grouping related posts
        
        Groups posts within time windows similar to congress trades sessions.
        Uses 4-hour windows for social sentiment (more frequent than 7-day congress windows).
        
        Returns:
            Dictionary with counts of sessions created
        """
        try:
            logger.info("🎯 Creating sentiment analysis sessions...")
            
            # Get posts that haven't been assigned to sessions yet
            query = """
                SELECT sp.id, sp.metric_id, sm.ticker, sp.platform, sp.posted_at, sp.engagement_score
                FROM social_posts sp
                JOIN social_metrics sm ON sp.metric_id = sm.id
                WHERE sp.id NOT IN (
                    SELECT DISTINCT sp2.id
                    FROM social_posts sp2
                    JOIN sentiment_sessions ss ON ss.ticker = (
                        SELECT sm2.ticker FROM social_metrics sm2 WHERE sm2.id = sp2.metric_id
                    ) AND ss.platform = sp2.platform
                    AND sp2.posted_at >= ss.session_start 
                    AND sp2.posted_at <= ss.session_end
                )
                ORDER BY sp.posted_at DESC
                LIMIT 500  -- Process in batches
            """
            unassigned_posts = self.postgres.execute_query(query)
            
            if not unassigned_posts:
                logger.info("✅ No new posts to assign to sessions")
                return {'sessions_created': 0, 'posts_assigned': 0}
            
            sessions_created = 0
            posts_assigned = 0
            
            # Group posts by ticker-platform and 4-hour windows
            from collections import defaultdict
            session_groups = defaultdict(list)
            
            for post in unassigned_posts:
                ticker = post['ticker']
                platform = post['platform']
                posted_at = post['posted_at']
                
                if isinstance(posted_at, str):
                    posted_at = datetime.fromisoformat(posted_at.replace('Z', '+00:00'))
                
                # Round to 4-hour window
                window_start = posted_at.replace(hour=posted_at.hour // 4 * 4, minute=0, second=0, microsecond=0)
                window_end = window_start + timedelta(hours=4)
                
                key = (ticker, platform, window_start, window_end)
                session_groups[key].append(post)
            
            # Create sessions for each group
            for (ticker, platform, start, end), posts in session_groups.items():
                try:
                    # Calculate session metrics
                    post_count = len(posts)
                    total_engagement = sum(p['engagement_score'] or 0 for p in posts)
                    
                    # Create session
                    insert_query = """
                        INSERT INTO sentiment_sessions 
                        (ticker, platform, session_start, session_end, post_count, total_engagement)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """
                    result = self.postgres.execute_query(insert_query, (
                        ticker, platform, start, end, post_count, total_engagement
                    ))
                    
                    if result:
                        session_id = result[0]['id']
                        
                        # Update social_metrics with session_id
                        if posts:
                            metric_ids = tuple(p['metric_id'] for p in posts)
                            update_query = """
                                UPDATE social_metrics 
                                SET analysis_session_id = %s, has_ai_analysis = FALSE
                                WHERE id IN %s
                            """
                            self.postgres.execute_update(update_query, (session_id, metric_ids))
                        
                        sessions_created += 1
                        posts_assigned += post_count
                        
                except Exception as e:
                    logger.warning(f"Error creating session for {ticker}-{platform}: {e}")
                    continue
            
            logger.info(f"✅ Session creation complete: {sessions_created} sessions, {posts_assigned} posts assigned")
            return {'sessions_created': sessions_created, 'posts_assigned': posts_assigned}
            
        except Exception as e:
            logger.error(f"❌ Error during session creation: {e}", exc_info=True)
            raise
    
    def analyze_sentiment_session(self, session_id: int) -> Optional[Dict[str, Any]]:
        """Perform AI analysis on a sentiment session
        
        Similar to congress trades analysis but for social sentiment.
        Uses Ollama to analyze post content and extract insights.
        
        Args:
            session_id: ID of the sentiment session to analyze
            
        Returns:
            Dictionary with analysis results or None if failed
        """
        try:
            # Get session details
            session_query = """
                SELECT ss.*, 
                       array_agg(sp.content) as post_contents,
                       json_agg(sp.extracted_tickers) as ticker_arrays
                FROM sentiment_sessions ss
                LEFT JOIN social_posts sp ON sp.metric_id IN (
                    SELECT id FROM social_metrics 
                    WHERE analysis_session_id = ss.id
                )
                WHERE ss.id = %s
                GROUP BY ss.id
            """
            session_data = self.postgres.execute_query(session_query, (session_id,))
            
            if not session_data:
                logger.warning(f"No session found with ID {session_id}")
                return None
            
            session = session_data[0]
            post_contents = session['post_contents'] or []
            ticker_arrays = session['ticker_arrays'] or []
            
            # Combine all post content
            all_content = '\n\n---\n\n'.join([c for c in post_contents if c])
            
            if not all_content.strip():
                logger.warning(f"No content to analyze for session {session_id}")
                return None
            
            # Extract all mentioned tickers
            all_tickers = set()
            for ticker_array in ticker_arrays:
                if ticker_array:
                    all_tickers.update(ticker_array)
            
            # AI Analysis using Ollama
            analysis_prompt = f"""
Analyze these social media posts about {session['ticker']} from {session['platform']}.

Posts:
{all_content[:4000]}  # Limit content length

Provide analysis in JSON format:
{{
    "sentiment_score": -2.0 to 2.0,
    "confidence_score": 0.0 to 1.0,
    "sentiment_label": "EUPHORIC|BULLISH|NEUTRAL|BEARISH|FEARFUL",
    "summary": "Brief summary of overall sentiment",
    "key_themes": ["theme1", "theme2"],
    "reasoning": "Detailed explanation of the analysis"
}}
"""
            
            if not self.ollama:
                logger.warning("Ollama client not available for AI analysis")
                return None
            
            # Get AI analysis
            model_name = get_summarizing_model()
            ai_response = self.ollama.generate_completion(
                prompt=analysis_prompt,
                model=model_name,
                json_mode=True
            )
            
            if not ai_response:
                logger.warning(f"AI analysis failed for session {session_id}")
                return None
            
            try:
                analysis_result = json.loads(ai_response)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON response from AI for session {session_id}")
                return None
            
            # Store analysis results in research DB
            analysis_record = {
                'session_id': session_id,
                'ticker': session['ticker'],
                'platform': session['platform'],
                'sentiment_score': analysis_result.get('sentiment_score'),
                'confidence_score': analysis_result.get('confidence_score'),
                'sentiment_label': analysis_result.get('sentiment_label'),
                'summary': analysis_result.get('summary'),
                'key_themes': analysis_result.get('key_themes', []),
                'reasoning': analysis_result.get('reasoning'),
                'key_themes': analysis_result.get('key_themes', []),
                'reasoning': analysis_result.get('reasoning'),
                'model_used': model_name,
                'analysis_version': 1
            }
            
            # Insert analysis
            insert_query = """
                INSERT INTO social_sentiment_analysis 
                (session_id, ticker, platform, sentiment_score, confidence_score, 
                 sentiment_label, summary, key_themes, reasoning, model_used, analysis_version)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """
            result = self.postgres.execute_query(insert_query, (
                analysis_record['session_id'], analysis_record['ticker'], analysis_record['platform'],
                analysis_record['sentiment_score'], analysis_record['confidence_score'],
                analysis_record['sentiment_label'], analysis_record['summary'], 
                analysis_record['key_themes'], analysis_record['reasoning'],
                analysis_record['model_used'], analysis_record['analysis_version']
            ))
            
            if result:
                analysis_id = result[0]['id']
                
                # Extract and validate tickers with AI
                self._extract_tickers_with_ai(analysis_id, all_content, list(all_tickers))
                
                # Update session as analyzed
                update_query = "UPDATE sentiment_sessions SET needs_ai_analysis = FALSE WHERE id = %s"
                self.postgres.execute_update(update_query, (session_id,))
                
                logger.info(f"✅ AI analysis complete for session {session_id}")
                return analysis_record
            
        except Exception as e:
            logger.error(f"❌ Error during AI analysis of session {session_id}: {e}", exc_info=True)
            return None
    
    def _extract_tickers_with_ai(self, analysis_id: int, content: str, basic_tickers: List[str]) -> None:
        """Use AI to validate and extract tickers with context
        
        Args:
            analysis_id: ID of the analysis record
            content: Full post content
            basic_tickers: Tickers found via basic regex
        """
        try:
            if not basic_tickers:
                return
            
            extraction_prompt = f"""
Analyze this social media content and validate/extract stock tickers.

Content: {content[:2000]}

Basic tickers found: {', '.join(basic_tickers)}

For each ticker, provide JSON validation:
[{{
    "ticker": "SYMBOL",
    "confidence": 0.0-1.0,
    "context": "sentence where mentioned",
    "is_primary": true/false,
    "company_name": "Company Name if obvious"
}}]
"""
            
            model_name = get_summarizing_model()
            ai_response = self.ollama.generate_completion(
                prompt=extraction_prompt,
                model=model_name,
                json_mode=True
            )
            
            if ai_response:
                try:
                    validated_tickers = json.loads(ai_response)
                    
                    for ticker_data in validated_tickers:
                        # Look up company info from Supabase
                        company_info = self._lookup_company_info(ticker_data['ticker'])
                        
                        insert_query = """
                            INSERT INTO extracted_tickers 
                            (analysis_id, ticker, confidence, context, is_primary, 
                             company_name, sector)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """
                        self.postgres.execute_update(insert_query, (
                            analysis_id,
                            ticker_data['ticker'],
                            ticker_data.get('confidence', 0.5),
                            ticker_data.get('context', ''),
                            ticker_data.get('is_primary', False),
                            ticker_data.get('company_name') or company_info.get('company_name'),
                            company_info.get('sector')
                        ))
                        
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"Error parsing AI ticker extraction: {e}")
                    
        except Exception as e:
            logger.warning(f"Error during AI ticker extraction: {e}")
    
    def _lookup_company_info(self, ticker: str) -> Dict[str, str]:
        """Look up company information from Supabase securities table
        
        Args:
            ticker: Ticker symbol to look up
            
        Returns:
            Dictionary with company_name and sector
        """
        try:
            result = self.supabase.supabase.table("securities")\
                .select("company_name, sector")\
                .eq("ticker", ticker.upper())\
                .execute()
            
            if result.data:
                return {
                    'company_name': result.data[0].get('company_name', ''),
                    'sector': result.data[0].get('sector', '')
                }
        except Exception as e:
            logger.warning(f"Error looking up company info for {ticker}: {e}")
        
        return {}
    
    def run_daily_cleanup(self) -> Dict[str, int]:
        """Run enhanced cleanup with new retention policy
        
        Updated policy: 14 days raw_data → 60 days deletion
        Also cleans up old analysis data.
        
        Returns:
            Dictionary with 'rows_updated' and 'rows_deleted' counts
        """
        try:
            logger.info("🧹 Starting enhanced social metrics cleanup...")
            
            # Step 1: Remove heavy data after 14 days (extended from 7)
            logger.info("  Step 1: Removing raw_posts JSON from records older than 14 days...")
            update_query = """
                UPDATE social_metrics 
                SET raw_posts = NULL, collection_metadata = NULL
                WHERE created_at < NOW() - INTERVAL '14 days' 
                  AND raw_posts IS NOT NULL
            """
            rows_updated = self.postgres.execute_update(update_query)
            logger.info(f"  ✅ Removed raw_posts from {rows_updated} records (14+ days old)")
            
            # Step 2: Clean up old analysis data (90 days)
            logger.info("  Step 2: Removing old analysis data (90+ days)...")
            analysis_cleanup = """
                DELETE FROM extracted_tickers 
                WHERE extracted_at < NOW() - INTERVAL '90 days'
            """
            ticker_rows = self.postgres.execute_update(analysis_cleanup)
            
            summary_cleanup = """
                DELETE FROM post_summaries 
                WHERE summarized_at < NOW() - INTERVAL '90 days'
            """
            summary_rows = self.postgres.execute_update(summary_cleanup)
            
            analysis_cleanup = """
                DELETE FROM social_sentiment_analysis 
                WHERE analyzed_at < NOW() - INTERVAL '90 days'
            """
            analysis_rows = self.postgres.execute_update(analysis_cleanup)
            
            logger.info(f"  ✅ Removed {ticker_rows} ticker records, {summary_rows} summaries, {analysis_rows} analyses")
            
            # Step 3: Delete entire social metrics rows after 60 days (reduced from 90)
            logger.info("  Step 3: Deleting social metrics records older than 60 days...")
            delete_query = """
                DELETE FROM social_metrics 
                WHERE created_at < NOW() - INTERVAL '60 days'
            """
            rows_deleted = self.postgres.execute_update(delete_query)
            logger.info(f"  ✅ Deleted {rows_deleted} social metrics records (60+ days old)")
            
            logger.info(f"✅ Enhanced cleanup complete: {rows_updated} updated, {rows_deleted} deleted, {ticker_rows + summary_rows + analysis_rows} analysis records removed")
            
            return {
                'rows_updated': rows_updated,
                'rows_deleted': rows_deleted,
                'analysis_records_removed': ticker_rows + summary_rows + analysis_rows
            }
            
        except Exception as e:
            logger.error(f"❌ Error during enhanced cleanup: {e}", exc_info=True)
            raise
        """Run daily cleanup to implement two-tier retention policy.
        
        Tier 1 (7 days): Remove raw_data JSON from old records (keep metrics)
        Tier 2 (90 days): Delete entire rows older than 90 days
        
        Returns:
            Dictionary with 'rows_updated' and 'rows_deleted' counts
        """
        try:
            logger.info("🧹 Starting social metrics cleanup...")
            
            # Step 1: The Lobotomy (Remove heavy JSON, keep the metrics)
            logger.info("  Step 1: Removing raw_data JSON from records older than 7 days...")
            update_query = """
                UPDATE social_metrics 
                SET raw_data = NULL 
                WHERE created_at < NOW() - INTERVAL '7 days' 
                  AND raw_data IS NOT NULL
            """
            rows_updated = self.postgres.execute_update(update_query)
            logger.info(f"  ✅ Removed raw_data from {rows_updated} records (7+ days old)")
            
            # Step 2: The Grim Reaper (Delete old rows)
            logger.info("  Step 2: Deleting records older than 90 days...")
            delete_query = """
                DELETE FROM social_metrics 
                WHERE created_at < NOW() - INTERVAL '90 days'
            """
            rows_deleted = self.postgres.execute_update(delete_query)
            logger.info(f"  ✅ Deleted {rows_deleted} records (90+ days old)")
            
            logger.info(f"✅ Social metrics cleanup complete: {rows_updated} updated, {rows_deleted} deleted")
            
            return {
                'rows_updated': rows_updated,
                'rows_deleted': rows_deleted
            }
            
        except Exception as e:
            logger.error(f"❌ Error during social metrics cleanup: {e}", exc_info=True)
            raise

