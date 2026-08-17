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
from typing import Any, Dict, Iterator, List, Optional
from datetime import datetime, timezone, timedelta
from settings import get_summarizing_model
from ollama_client import collect_with_summary_model_chain
from env_loader import load_project_dotenv

load_project_dotenv()

logger = logging.getLogger(__name__)


STOCK_SUBREDDITS = [
    "wallstreetbets",
    "stocks",
    "investing",
    "StockMarket",
    "pennystocks",
    "Shortsqueeze",
    "options",
    "robinhood",
    "stock_picks",
    "investments",
    "RobinHoodPennyStocks",
    "microcap",
    "biotechplays",
    "securityanalysis",
    "valueinvesting",
    "CanadianPennyStocks",
    "Undervalued",
    "BayStreetBets",
    "SPACs",
    "dividends",
    "weedstocks",
    "CryptoCurrency",
]

STOCK_SUBREDDIT_SET = {subreddit.lower() for subreddit in STOCK_SUBREDDITS}

COMMON_TICKER_WORDS = {
    "AI",
    "CAT",
    "GOOD",
    "FOR",
    "ARE",
    "ALL",
    "CAN",
    "NEW",
    "ONE",
    "OUT",
    "RUN",
    "SEE",
    "TWO",
    "NOW",
    "BIT",
    "KEY",
    "USA",
    "EAT",
    "BIG",
    "LOW",
    "FAT",
    "HOT",
    "FUN",
    "PLAY",
    "LOVE",
    "GET",
    "SET",
    "GO",
    "CAR",
    "DOG",
}


def _strip_json_markdown_fence(text: str) -> str:
    """Remove optional ```json ... ``` wrapping from model output."""
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


def _iter_raw_json_values(t: str, opener: str) -> Iterator[Any]:
    """Yield successfully decoded JSON values starting at each ``opener`` (``{`` or ``[``).

    Uses :meth:`json.JSONDecoder.raw_decode` so each value is one balanced structure,
    not a greedy ``\\{.*\\}`` span that breaks when multiple JSON blobs appear.
    """
    dec = json.JSONDecoder()
    for i, ch in enumerate(t):
        if ch != opener:
            continue
        try:
            val, _end = dec.raw_decode(t, i)
        except json.JSONDecodeError:
            continue
        yield val


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Parse a JSON object from model output; tolerate fences and leading prose."""
    if not text or not str(text).strip():
        return None
    t = str(text).strip()
    for candidate in (t, _strip_json_markdown_fence(t)):
        if not candidate:
            continue
        try:
            out = json.loads(candidate)
            if isinstance(out, dict):
                return out
        except json.JSONDecodeError:
            continue
    for val in _iter_raw_json_values(t, "{"):
        if isinstance(val, dict):
            return val
    return None


def _extract_json_array(text: str) -> Optional[List[Any]]:
    """Parse a JSON array from model output; tolerate fences and leading prose."""
    if not text or not str(text).strip():
        return None
    t = str(text).strip()
    for candidate in (t, _strip_json_markdown_fence(t)):
        if not candidate:
            continue
        try:
            out = json.loads(candidate)
            if isinstance(out, list):
                return out
        except json.JSONDecodeError:
            continue
    for val in _iter_raw_json_values(t, "["):
        if isinstance(val, list):
            return val
    return None


# FlareSolverr configuration (for bypassing Cloudflare on StockTwits)
from web_fetch_client import get_web_fetch_client
from reddit_client import RedditClient, get_reddit_client

# Import clients
from postgres_client import PostgresClient
from supabase_client import SupabaseClient
from ollama_client import OllamaClient, get_ollama_client
from prompt_safety import prepare_untrusted_for_prompt, sanitize_for_llm
try:
    from web_dashboard.watchlist_access import get_active_watchlist_tickers
except ImportError:
    from watchlist_access import get_active_watchlist_tickers


class SocialSentimentService:
    """Service for fetching and storing social sentiment metrics"""
    
    def __init__(
        self,
        postgres_client: Optional[PostgresClient] = None,
        supabase_client: Optional[SupabaseClient] = None,
        ollama_client: Optional[OllamaClient] = None,
        reddit_client: Optional[RedditClient] = None,
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
            self.reddit = reddit_client or get_reddit_client()
            
        except Exception as e:
            logger.error(f"Failed to initialize PostgresClient: {e}")
            raise
        
        try:
            self.supabase = supabase_client or SupabaseClient(use_service_role=True)
        except Exception as e:
            logger.error(f"Failed to initialize SupabaseClient: {e}")
            raise
        
        self.ollama = ollama_client or get_ollama_client()
        self.web_fetch = get_web_fetch_client()
    
    def _reddit_search_queries(self, ticker: str) -> List[str]:
        """Build high-signal Reddit search queries for a ticker."""

        queries = [f"${ticker}"]
        if ticker not in COMMON_TICKER_WORDS and len(ticker) >= 3:
            queries.append(ticker)
        return queries

    def _parse_reddit_search_posts(
        self,
        payload: Dict[str, Any],
        ticker: str,
        cutoff_time: datetime,
        *,
        restrict_to_stock_subreddits: bool = True,
    ) -> List[Dict[str, Any]]:
        """Parse Reddit search JSON and retain recent, whitelisted, ticker-relevant posts."""

        posts: List[Dict[str, Any]] = []
        children = (payload.get("data") or {}).get("children") if isinstance(payload, dict) else None
        if not isinstance(children, list):
            return posts

        for child in children:
            post_data = child.get("data") if isinstance(child, dict) else None
            if not isinstance(post_data, dict):
                continue

            subreddit = str(post_data.get("subreddit", ""))
            if restrict_to_stock_subreddits and subreddit.lower() not in STOCK_SUBREDDIT_SET:
                continue

            title = post_data.get("title", "")
            selftext = post_data.get("selftext", "")
            created_utc = post_data.get("created_utc", 0)
            if not created_utc:
                continue

            try:
                post_dt = datetime.fromtimestamp(float(created_utc), tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                continue
            if post_dt < cutoff_time:
                continue

            full_text = (str(title) + " " + str(selftext)).upper()
            cashtag_pattern = r"\$" + re.escape(ticker) + r"\b"
            ticker_pattern = r"\b" + re.escape(ticker) + r"\b"
            has_cashtag = bool(re.search(cashtag_pattern, full_text, re.IGNORECASE))
            has_ticker = bool(re.search(ticker_pattern, full_text, re.IGNORECASE))
            if not (has_cashtag or has_ticker):
                logger.debug(
                    "Filtered out Reddit post for %s in r/%s: '%s...' (no ticker mention)",
                    ticker,
                    subreddit,
                    str(title)[:50],
                )
                continue

            posts.append(
                {
                    "title": str(title),
                    "selftext": str(selftext),
                    "score": post_data.get("ups", 0),
                    "num_comments": post_data.get("num_comments", 0),
                    "created_utc": created_utc,
                    "url": post_data.get("url", ""),
                    "subreddit": subreddit,
                }
            )

        return posts

    def _dedupe_reddit_posts(self, posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Deduplicate Reddit posts by URL while preserving first occurrence."""

        seen_urls = set()
        unique_posts = []
        for post in posts:
            url = post.get("url")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            unique_posts.append(post)
        return unique_posts

    def make_flaresolverr_request(self, url: str) -> Optional[Dict[str, Any]]:
        """Make a request through FlareSolverr to bypass Cloudflare protection."""
        return self.web_fetch.fetch_json_via_flaresolverr(url)
    
    def get_watched_tickers(self, fund: Optional[str] = None) -> List[str]:
        """Get active tickers from fund-scoped watchlist (with legacy fallback).
        
        Returns:
            List of ticker symbols to monitor
        """
        try:
            tickers = get_active_watchlist_tickers(self.supabase, fund=fund)
            logger.debug(f"Found {len(tickers)} active watched tickers")
            return tickers
            
        except Exception as e:
            logger.error(f"Error fetching watched tickers: {e}")
            return []

    def get_last_processed_at(self, tickers: List[str]) -> Dict[str, Optional[datetime]]:
        """Return latest social_metrics timestamp for each ticker.

        Missing tickers are returned with ``None`` so callers can sort never-seen symbols first.
        """

        result: Dict[str, Optional[datetime]] = {ticker: None for ticker in tickers}
        if not tickers:
            return result

        query = """
            SELECT ticker, MAX(created_at) AS last_processed
            FROM social_metrics
            WHERE ticker = ANY(%s)
            GROUP BY ticker
        """
        try:
            rows = self.postgres.execute_query(query, (tickers,))
        except Exception as exc:
            logger.warning("Failed to load last social sentiment timestamps: %s", exc)
            return result

        for row in rows:
            ticker = row.get("ticker")
            if ticker in result:
                result[ticker] = row.get("last_processed")
        return result
    
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
        reddit_errors: List[str] = []
        try:
            all_posts: List[Dict[str, Any]] = []
            cutoff_time = datetime.now(timezone.utc) - timedelta(days=7)  # Last week

            if self.reddit.rss_enabled:
                warm_stats = self.reddit.warm_sentiment_feed_cache()
                if warm_stats.skipped_cooldown:
                    reddit_errors.append("429")
                    logger.warning(
                        "Reddit RSS cache warm skipped — cooldown active (%s posts in stale cache)",
                        warm_stats.posts_cached,
                    )
                elif warm_stats.subs_rate_limited and warm_stats.subs_fetched == 0:
                    reddit_errors.append("429")

                cache_posts = self.reddit.feed_cache.get_posts_for_ticker(
                    ticker,
                    cutoff_time,
                    allowed_subreddits=STOCK_SUBREDDIT_SET,
                )
                all_posts.extend(cache_posts)

                # Fallback: subreddit-restricted search on top subs (avoid global search.rss).
                if not all_posts and not self.reddit.feed_cache.is_fresh():
                    search_queries = self._reddit_search_queries(ticker)
                    fallback_subs = ["wallstreetbets", "stocks", "investing", "pennystocks"]
                    for subreddit in fallback_subs:
                        for query in search_queries[:1]:
                            if max_duration and (time.time() - fetch_start) > max_duration:
                                break
                            result = self.reddit.get_json(
                                f"/r/{subreddit}/search",
                                params={"q": query, "sort": "new", "t": "week", "limit": 25},
                            )
                            if result.rate_limited:
                                reddit_errors.append("429")
                                break
                            if result.payload is None:
                                continue
                            all_posts.extend(
                                self._parse_reddit_search_posts(
                                    result.payload,
                                    ticker,
                                    cutoff_time,
                                    restrict_to_stock_subreddits=True,
                                )
                            )
            else:
                search_queries = self._reddit_search_queries(ticker)
                for query in search_queries:
                    if max_duration:
                        elapsed = time.time() - fetch_start
                        if elapsed > max_duration:
                            logger.debug(
                                "Reddit fetch timeout for %s after %.1fs (found %s posts)",
                                ticker,
                                elapsed,
                                len(all_posts),
                            )
                            break

                    try:
                        if not self.reddit.check_robots_allowed("https://www.reddit.com/search.json"):
                            logger.warning("Reddit search blocked by robots.txt policy for %s", ticker)
                            reddit_errors.append("robots_txt_blocked")
                            continue

                        result = self.reddit.get_json(
                            "/search",
                            params={"q": query, "sort": "relevance", "t": "week", "limit": 100},
                        )

                        if result.rate_limited:
                            logger.warning(
                                "Reddit rate limit hit for %s query=%s oauth=%s status=429",
                                ticker,
                                query,
                                result.used_oauth,
                            )
                            reddit_errors.append("429")
                            time.sleep(5)
                            continue

                        if result.payload is None:
                            log_fn = (
                                logger.error
                                if result.used_oauth and result.status_code in (401, 403, 429)
                                else logger.warning
                            )
                            log_fn(
                                "Reddit search failed for %s query=%s status=%s oauth=%s",
                                ticker,
                                query,
                                result.status_code,
                                result.used_oauth,
                            )
                            if result.status_code in (401, 403):
                                reddit_errors.append("auth_failed")
                            elif result.status_code == 429:
                                reddit_errors.append("429")
                            else:
                                reddit_errors.append(str(result.status_code))
                            continue

                        all_posts.extend(
                            self._parse_reddit_search_posts(
                                result.payload,
                                ticker,
                                cutoff_time,
                                restrict_to_stock_subreddits=True,
                            )
                        )
                    except Exception as e:
                        logger.debug("Error searching Reddit for %s query=%s: %s", ticker, query, e)
                        reddit_errors.append(type(e).__name__)
                        continue

            if not all_posts and reddit_errors:
                transport = (
                    "rss"
                    if self.reddit.rss_enabled
                    else "cookies"
                    if self.reddit.cookie_enabled
                    else "oauth"
                )
                if "429" in reddit_errors:
                    logger.error(
                        "Reddit rate limited for %s (transport=%s): %s",
                        ticker,
                        transport,
                        ", ".join(sorted(set(reddit_errors))),
                    )
                elif "auth_failed" in reddit_errors:
                    logger.error(
                        "Reddit auth failed for %s: %s",
                        ticker,
                        ", ".join(sorted(set(reddit_errors))),
                    )
                else:
                    logger.error(
                        "Reddit returned no data for %s (transport=%s): %s",
                        ticker,
                        transport,
                        ", ".join(sorted(set(reddit_errors))),
                    )
            
            # Deduplicate by URL
            unique_posts = self._dedupe_reddit_posts(all_posts)
            
            # Sort by engagement score when available; RSS feeds have no scores.
            if self.reddit.rss_enabled:
                unique_posts.sort(key=lambda x: x.get("created_utc", 0), reverse=True)
            else:
                unique_posts.sort(key=lambda x: x['score'], reverse=True)
            top_5_posts = unique_posts[:5]
            
            # Combine post titles and bodies for AI analysis.
            texts_for_ai = []
            for post in top_5_posts:
                title = sanitize_for_llm(post.get("title", ""), max_chars=300)
                body = sanitize_for_llm(post.get("selftext", ""), max_chars=500)
                text = f"{title}\n{body}"
                texts_for_ai.append(text)
            
            # Analyze sentiment with Ollama
            sentiment_label = 'NEUTRAL'
            sentiment_score = 0.0
            
            if texts_for_ai and self.ollama:
                try:
                    # Attach top Reddit post context so AI audit logs show source URL/title.
                    if top_5_posts:
                        try:
                            from ai_audit import set_audit_context

                            top_post = top_5_posts[0]
                            set_audit_context(
                                article_url=top_post.get("url"),
                                article_title=top_post.get("title"),
                            )
                        except Exception:
                            pass

                    result = self.ollama.analyze_crowd_sentiment(texts_for_ai, ticker)
                    sentiment_label = result.get('sentiment', 'NEUTRAL')
                    sentiment_score = self.map_sentiment_label_to_score(sentiment_label)
                except Exception as e:
                    logger.warning(f"Ollama sentiment analysis failed for {ticker}: {e}")
                finally:
                    try:
                        from ai_audit import clear_audit_context

                        clear_audit_context()
                    except Exception:
                        pass
            
            # Prepare raw_data (top 3 posts)
            raw_data = None
            if unique_posts:
                raw_data = [
                    {
                        'title': post.get('title', ''),
                        'selftext': str(post.get('selftext', ''))[:500],
                        'score': post.get('score', 0),
                        'num_comments': post.get('num_comments', 0),
                        'subreddit': post.get('subreddit', ''),
                        'url': post.get('url', ''),
                    }
                    for post in unique_posts[:3]
                ]
            
            logger.debug(f"Reddit {ticker}: volume={len(unique_posts)}, sentiment={sentiment_label} ({sentiment_score:.1f})")
            
            return {
                'volume': len(unique_posts),
                'sentiment_label': sentiment_label,
                'sentiment_score': sentiment_score,
                'raw_data': raw_data,
                'reddit_error_codes': sorted(set(reddit_errors)),
            }
            
        except Exception as e:
            logger.error(f"Error fetching Reddit sentiment for {ticker}: {e}", exc_info=True)
            return {
                'volume': 0,
                'sentiment_label': 'NEUTRAL',
                'sentiment_score': 0.0,
                'raw_data': None,
                'reddit_error_codes': ['exception'],
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
            
            listing_url = f"https://www.reddit.com/r/{subreddit}/top.json"
            if not self.reddit.check_robots_allowed(listing_url):
                logger.warning("Subreddit scan blocked by robots.txt policy for r/%s", subreddit)
                return []

            result = self.reddit.get_json(
                f"/r/{subreddit}/top",
                params={"t": "day", "limit": limit},
            )

            if result.rate_limited:
                logger.warning(f"Rate limited scanning r/{subreddit}")
                return []

            if result.payload is None:
                transport = (
                    "rss"
                    if result.used_rss
                    else "cookies"
                    if result.used_cookies
                    else "oauth"
                )
                logger.warning(
                    "Subreddit scan failed for r/%s status=%s transport=%s",
                    subreddit,
                    result.status_code,
                    transport,
                )
                return []

            data = result.payload
            
            if 'data' not in data or 'children' not in data['data']:
                logger.warning(f"Invalid response format from r/{subreddit}")
                return []
            
            posts = data['data']['children']
            logger.info(f"Found {len(posts)} posts in r/{subreddit}")
            using_rss = self.reddit.rss_enabled
            comment_fetches_remaining = 3 if using_rss else limit

            for child in posts:
                post = child.get('data', {})
                if not post:
                    continue
                score = post.get('score', 0)
                if not using_rss and score < min_score:
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
                    if comment_fetches_remaining <= 0:
                        logger.debug(
                            "Skipping comment fetch for %s (RSS comment budget exhausted)",
                            post_id,
                        )
                    else:
                        comments_url = f"https://www.reddit.com/comments/{post_id}.json"
                        if not self.reddit.check_robots_allowed(comments_url):
                            logger.debug("Comment fetch blocked by robots.txt for post %s", post_id)
                        else:
                            comment_fetches_remaining -= 1
                            comment_result = self.reddit.get_json(
                                f"/comments/{post_id}",
                                params={"sort": "top", "limit": 10},
                            )
                            if comment_result.payload is not None:
                                c_data = comment_result.payload
                                # Reddit comment structure is [post_listing, comment_listing]
                                if isinstance(c_data, list) and len(c_data) > 1:
                                    comment_listing = c_data[1]
                                    if 'data' in comment_listing and 'children' in comment_listing['data']:
                                        for c in comment_listing['data']['children']:
                                            c_body = c.get('data', {}).get('body', '')
                                            if c_body:
                                                comments_text += f"- {c_body[:500]}...\n"
                                elif isinstance(c_data, dict):
                                    comment_children = (c_data.get("data") or {}).get("children") or []
                                    for c in comment_children[1:]:
                                        c_data_item = c.get("data", {})
                                        c_body = (
                                            c_data_item.get("body")
                                            or c_data_item.get("selftext")
                                            or c_data_item.get("title")
                                            or ""
                                        )
                                        if c_body:
                                            comments_text += f"- {str(c_body)[:500]}...\n"
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
                    
                    opportunity_model = get_summarizing_model()
                    response_text, opportunity_model = collect_with_summary_model_chain(
                        self.ollama,
                        prompt=user_prompt,
                        requested_model=opportunity_model,
                        system_prompt=system_prompt,
                        json_mode=True,
                        temperature=0.1,
                        stream=True,
                        response_ok=lambda s: _extract_json_object(s) is not None,
                        function_name="opportunity_discovery",
                        audit_extra={"subreddit": subreddit, "post_id": post_id},
                    )
                    if not response_text:
                        logger.warning(
                            "Opportunity scan: all summarization models failed for post %s",
                            post_id,
                        )
                        continue

                    result = _extract_json_object(response_text)
                    if not result:
                        logger.warning(
                            "Could not parse opportunity JSON for post %s (model=%s)",
                            post_id,
                            opportunity_model,
                        )
                        continue
                    
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

            # AI analysis using untrusted social content wrapped in explicit delimiters.
            safe_social_content = prepare_untrusted_for_prompt(
                all_content,
                source="social_posts_db",
                max_chars=4000,
            )
            analysis_prompt = f"""
Analyze these social media posts about {session['ticker']} from {session['platform']}.

Posts:
{safe_social_content}

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
            
            analysis_result = _extract_json_object(ai_response)
            if not analysis_result:
                logger.warning(
                    "Invalid or unrecoverable JSON from AI for session %s", session_id
                )
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

Content:
{prepare_untrusted_for_prompt(content, source="social_posts_extract", max_chars=2000)}

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
                validated_tickers = _extract_json_array(ai_response)
                if not validated_tickers:
                    logger.warning("Could not parse AI ticker extraction as JSON array")
                else:
                    for ticker_data in validated_tickers:
                        if not isinstance(ticker_data, dict):
                            continue
                        sym = ticker_data.get("ticker")
                        if not sym:
                            continue
                        try:
                            company_info = self._lookup_company_info(str(sym))

                            insert_query = """
                                INSERT INTO extracted_tickers
                                (analysis_id, ticker, confidence, context, is_primary,
                                 company_name, sector)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """
                            self.postgres.execute_update(insert_query, (
                                analysis_id,
                                str(sym),
                                ticker_data.get('confidence', 0.5),
                                ticker_data.get('context', ''),
                                ticker_data.get('is_primary', False),
                                ticker_data.get('company_name') or company_info.get('company_name'),
                                company_info.get('sector')
                            ))
                        except Exception as e:
                            logger.warning("Error inserting extracted ticker row: %s", e)

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
            Dictionary with rows_updated, rows_deleted, analysis_records_removed, and optional
            post_summaries_deleted_with_metrics / social_posts_deleted_with_metrics counts.
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
            
            # Step 3: Delete entire social metrics rows after 60 days (reduced from 90).
            # Remove dependent rows first (social_posts FK → social_metrics; post_summaries may FK to social_posts).
            logger.info("  Step 3: Deleting social metrics records older than 60 days (with posts/summaries)...")
            doomed_metrics = "created_at < NOW() - INTERVAL '60 days'"
            delete_post_summaries_for_doomed = f"""
                DELETE FROM post_summaries
                WHERE post_id IN (
                    SELECT id FROM social_posts
                    WHERE metric_id IN (SELECT id FROM social_metrics WHERE {doomed_metrics})
                )
            """
            delete_social_posts_for_doomed = f"""
                DELETE FROM social_posts
                WHERE metric_id IN (SELECT id FROM social_metrics WHERE {doomed_metrics})
            """
            delete_social_metrics_old = f"""
                DELETE FROM social_metrics
                WHERE {doomed_metrics}
            """
            summaries_for_metrics_deleted = 0
            posts_deleted = 0
            rows_deleted = 0
            with self.postgres.get_connection() as conn:
                cur = conn.cursor()
                cur.execute(delete_post_summaries_for_doomed)
                summaries_for_metrics_deleted = cur.rowcount
                cur.execute(delete_social_posts_for_doomed)
                posts_deleted = cur.rowcount
                cur.execute(delete_social_metrics_old)
                rows_deleted = cur.rowcount
            logger.info(
                "  ✅ Step 3 removed %s post_summaries (for doomed metrics), %s social_posts, %s social_metrics",
                summaries_for_metrics_deleted,
                posts_deleted,
                rows_deleted,
            )
            
            logger.info(
                "✅ Enhanced cleanup complete: %s updated, %s metrics deleted, %s analysis records removed",
                rows_updated,
                rows_deleted,
                ticker_rows + summary_rows + analysis_rows,
            )
            
            return {
                'rows_updated': rows_updated,
                'rows_deleted': rows_deleted,
                'analysis_records_removed': ticker_rows + summary_rows + analysis_rows,
                'post_summaries_deleted_with_metrics': summaries_for_metrics_deleted,
                'social_posts_deleted_with_metrics': posts_deleted,
            }
            
        except Exception as e:
            logger.error(f"❌ Error during enhanced cleanup: {e}", exc_info=True)
            raise

