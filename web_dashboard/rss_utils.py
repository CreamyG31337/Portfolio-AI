#!/usr/bin/env python3
"""
RSS Feed Utilities
==================

Fetch and parse RSS/Atom feeds for the "Push" strategy.
Includes junk filtering heuristics to improve article quality.
"""

import logging
import os
import re
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# FlareSolverr configuration (for bypassing Cloudflare)
# Default: host.docker.internal for Docker containers
# Override: FLARESOLVERR_URL env variable for local testing (e.g., Tailscale)
FLARESOLVERR_URL = os.getenv("FLARESOLVERR_URL", "http://host.docker.internal:8191")

# Junk filter patterns (case-insensitive)
SPAM_PHRASES = [
    "sign up now",
    "click here",
    "subscribe today",
    "limited time offer",
    "act now",
    "buy now",
    "sponsored content",
    "advertisement",
]

# Financial/market keywords for relevance checking
FINANCIAL_KEYWORDS = [
    # Market terms
    "stock", "stocks", "share", "shares", "market", "markets", "trading", "trader",
    "investor", "investment", "portfolio", "equity", "equities",
    # Financial metrics
    "earnings", "revenue", "profit", "loss", "eps", "ebitda", "cashflow",
    "sales", "margin", "growth", "valuation", "p/e", "price target",
    # Corporate actions
    "ipo", "merger", "acquisition", "buyback", "dividend", "split",
    # Financial entities
    "sec", "nasdaq", "nyse", "tsx", "exchange", "fund", "etf", "index",
    "s&p", "dow", "russell", "ticker", "symbol",
    # Crypto (often covered by financial feeds)
    "bitcoin", "crypto", "cryptocurrency", "blockchain",
    # General business/finance
    "ceo", "cfo", "executive", "quarter", "quarterly", "fiscal", "guidance",
    "analyst", "forecast", "estimate", "rating", "upgrade", "downgrade",
]

# Minimum content length (characters)
MIN_CONTENT_LENGTH = 100

# Minimum financial keyword matches required
MIN_FINANCIAL_KEYWORD_MATCHES = 1


class RSSClient:
    """Client for fetching and parsing RSS/Atom feeds."""
    
    def __init__(self, timeout: int = 10):
        """Initialize RSS client.
        
        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout
        
        # Create session with retry strategy and browser-like headers
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Set browser-like headers to avoid 403 errors
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/rss+xml, application/xml, text/xml, */*',
            'Accept-Language': 'en-US,en;q=0.9',
        })
    
    def _fetch_via_flaresolverr(self, url: str) -> Optional[bytes]:
        """Fetch RSS feed content via FlareSolverr to bypass Cloudflare protection.
        
        Args:
            url: RSS feed URL
            
        Returns:
            Feed content as bytes, or None if failed
        """
        try:
            flaresolverr_endpoint = f"{FLARESOLVERR_URL}/v1"
            payload = {
                "cmd": "request.get",
                "url": url,
                "maxTimeout": 60000,  # 60 seconds
                # Add headers to request RSS/XML content specifically
                "headers": {
                    "Accept": "application/rss+xml, application/xml, text/xml, */*",
                    "Accept-Language": "en-US,en;q=0.9",
                }
            }
            
            logger.debug(f"Requesting RSS feed via FlareSolverr: {url}")
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
            
            # Get the actual HTTP status and response body
            http_status = solution.get("status", 0)
            response_body = solution.get("response", "")
            response_headers = solution.get("headers", {})
            
            # Check if the target site returned an error
            if http_status != 200:
                logger.warning(f"Target site returned HTTP {http_status} via FlareSolverr")
                return None
            
            # Check Content-Type to see if we got XML or HTML
            content_type = response_headers.get("content-type", "").lower()
            logger.debug(f"FlareSolverr response Content-Type: {content_type}, size: {len(response_body) if isinstance(response_body, str) else len(str(response_body))} bytes")
            
            # Convert response body to bytes if it's a string
            if isinstance(response_body, str):
                # NOTE: FlareSolverr uses a headless browser (Chrome via Selenium), so when it loads
                # an XML/RSS feed, the browser renders it as HTML (wrapping XML in HTML structure).
                # This is why we see HTML with XML wrapped in <pre> tags and HTML-escaped, even though
                # the raw HTTP response (visible in F12) is pure XML. This is expected browser behavior.
                # We extract and unescape the XML from the HTML to get the original feed content.
                if "html" in content_type or response_body.strip().startswith("<html"):
                    logger.debug("Response appears to be HTML, attempting to extract XML...")
                    import re
                    from html import unescape
                    
                    # Try to find XML content in HTML (e.g., in <pre> tags)
                    # Look for <pre> tags that might contain XML
                    pre_match = re.search(r'<pre[^>]*>(.*?)</pre>', response_body, re.DOTALL | re.IGNORECASE)
                    if pre_match:
                        pre_content = pre_match.group(1)
                        # Unescape HTML entities (e.g., &lt; -> <)
                        unescaped = unescape(pre_content)
                        # Check if it looks like XML
                        if unescaped.strip().startswith("<?xml") or unescaped.strip().startswith("<rss"):
                            logger.debug(f"Found XML content within HTML <pre> tag, unescaping... (extracted {len(unescaped)} chars)")
                            # Verify it's valid XML by checking structure
                            if "</rss>" in unescaped or "</feed>" in unescaped:
                                return unescaped.encode('utf-8')
                            else:
                                logger.warning("Extracted content doesn't appear to be complete XML (missing closing tag)")
                    
                    # Also try direct XML extraction (in case it's not in <pre>)
                    xml_match = re.search(r'(<\?xml[^>]*>.*?</rss>)', response_body, re.DOTALL | re.IGNORECASE)
                    if xml_match:
                        logger.debug("Found XML content within HTML response")
                        return xml_match.group(1).encode('utf-8')
                    
                    # If we have HTML-escaped XML (e.g., &lt;?xml), try unescaping the whole thing
                    if "&lt;?xml" in response_body or "&lt;rss" in response_body:
                        logger.debug("Found HTML-escaped XML, unescaping entire response...")
                        unescaped = unescape(response_body)
                        # Try to extract XML after unescaping
                        xml_match = re.search(r'(<\?xml[^>]*>.*?</rss>)', unescaped, re.DOTALL | re.IGNORECASE)
                        if xml_match:
                            logger.debug("Successfully extracted XML after unescaping")
                            return xml_match.group(1).encode('utf-8')
                
                return response_body.encode('utf-8')
            elif isinstance(response_body, bytes):
                return response_body
            else:
                logger.warning(f"Unexpected response body type from FlareSolverr: {type(response_body)}")
                return None
                
        except requests.exceptions.ConnectionError:
            logger.debug(f"FlareSolverr unavailable at {FLARESOLVERR_URL} - will fallback to direct request")
            return None
        except requests.exceptions.Timeout:
            logger.warning("FlareSolverr request timed out - will fallback to direct request")
            return None
        except Exception as e:
            logger.warning(f"FlareSolverr request failed: {e} - will fallback to direct request")
            return None
    
    def fetch_feed(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch and parse an RSS/Atom feed.
        
        Tries FlareSolverr first (if available) to bypass Cloudflare protection,
        then falls back to direct request.
        
        Args:
            url: RSS feed URL
            
        Returns:
            Dictionary with 'items' list and feed metadata, or None on error
        """
        try:
            logger.info(f"Fetching RSS feed: {url}")
            
            # Try FlareSolverr first to bypass Cloudflare protection
            feed_content = None
            try:
                feed_content = self._fetch_via_flaresolverr(url)
                if feed_content:
                    logger.debug(f"Successfully fetched RSS feed via FlareSolverr: {url}")
            except Exception as e:
                logger.debug(f"FlareSolverr attempt failed for {url}: {e}")
            
            # Fallback to direct request if FlareSolverr failed or unavailable
            if feed_content is None:
                logger.debug(f"Attempting direct request for RSS feed: {url}")
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                feed_content = response.content
            
            # Parse XML
            root = ET.fromstring(feed_content)
            
            # Detect feed type (RSS 2.0 or Atom)
            if root.tag == 'rss':
                return self._parse_rss(root, url)
            elif root.tag.endswith('feed'):  # Atom feeds use namespace
                return self._parse_atom(root, url)
            else:
                logger.warning(f"Unknown feed format for {url}: {root.tag}")
                return None
                
        except requests.exceptions.Timeout:
            logger.error(f"❌ Timeout fetching RSS feed: {url}")
            return None
        except requests.exceptions.HTTPError as e:
            logger.error(f"❌ HTTP error fetching RSS feed {url}: {e}")
            return None
        except ET.ParseError as e:
            logger.error(f"❌ XML parse error for {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Error fetching RSS feed {url}: {e}")
            return None
    
    def _parse_rss(self, root: ET.Element, feed_url: str) -> Dict[str, Any]:
        """Parse RSS 2.0 feed.
        
        Args:
            root: XML root element
            feed_url: Original feed URL
            
        Returns:
            Dictionary with parsed feed data including items and filter stats
        """
        channel = root.find('channel')
        if channel is None:
            logger.warning(f"No channel found in RSS feed: {feed_url}")
            return {'items': [], 'feed_url': feed_url, 'junk_filtered': 0, 'total_items': 0}
        
        items = []
        total_items = 0
        junk_filtered = 0
        
        for item in channel.findall('item'):
            total_items += 1
            parsed_item = self._parse_rss_item(item, feed_url)
            if parsed_item:
                items.append(parsed_item)
            else:
                junk_filtered += 1
        
        logger.info(f"✅ Parsed {len(items)} items from RSS feed (filtered {junk_filtered} junk): {feed_url}")
        return {
            'items': items,
            'feed_url': feed_url,
            'title': self._get_text(channel, 'title'),
            'link': self._get_text(channel, 'link'),
            'junk_filtered': junk_filtered,
            'total_items': total_items,
        }
    
    def _parse_rss_item(self, item: ET.Element, feed_url: str) -> Optional[Dict[str, Any]]:
        """Parse a single RSS item.
        
        Args:
            item: XML item element
            feed_url: Original feed URL
            
        Returns:
            Dictionary with item data, or None if filtered out
        """
        title = self._get_text(item, 'title')
        link = self._get_text(item, 'link')
        description = self._get_text(item, 'description')
        
        # Try content:encoded for fuller content (common in WordPress feeds)
        content = self._get_text(item, '{http://purl.org/rss/1.0/modules/content/}encoded') or description
        
        # Get publication date
        pub_date_str = self._get_text(item, 'pubDate')
        pub_date = self._parse_rfc822_date(pub_date_str) if pub_date_str else None
        
        # Extract tickers from custom tags (StockTwits specific)
        tickers = []
        for symbol_elem in item.findall('symbol'):
            symbol = symbol_elem.text
            if symbol and symbol.strip():
                tickers.append(symbol.strip().upper())
        
        # Get categories/tags
        categories = [cat.text for cat in item.findall('category') if cat.text]
        
        # Apply junk filter
        if not self._passes_junk_filter(title, content, categories):
            logger.debug(f"Filtered out junk article: {title[:50]}...")
            return None
        
        return {
            'title': title,
            'url': link,
            'content': self._strip_html(content) if content else '',
            'description': self._strip_html(description) if description else '',
            'published_at': pub_date,
            'source': self._extract_source_from_url(link or feed_url),
            'tickers': tickers if tickers else None,
            'categories': categories if categories else None,
        }
    
    def _parse_atom(self, root: ET.Element, feed_url: str) -> Dict[str, Any]:
        """Parse Atom feed.
        
        Args:
            root: XML root element
            feed_url: Original feed URL
            
        Returns:
            Dictionary with parsed feed data
        """
        # Atom uses namespaces
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        
        items = []
        for entry in root.findall('atom:entry', ns):
            parsed_item = self._parse_atom_entry(entry, feed_url, ns)
            if parsed_item:
                items.append(parsed_item)
        
        logger.info(f"✅ Parsed {len(items)} items from Atom feed: {feed_url}")
        
        title_elem = root.find('atom:title', ns)
        link_elem = root.find('atom:link[@rel="alternate"]', ns)
        
        return {
            'items': items,
            'feed_url': feed_url,
            'title': title_elem.text if title_elem is not None else None,
            'link': link_elem.get('href') if link_elem is not None else None,
        }
    
    def _parse_atom_entry(self, entry: ET.Element, feed_url: str, ns: dict) -> Optional[Dict[str, Any]]:
        """Parse a single Atom entry.
        
        Args:
            entry: XML entry element
            feed_url: Original feed URL
            ns: XML namespaces
            
        Returns:
            Dictionary with entry data, or None if filtered out
        """
        title_elem = entry.find('atom:title', ns)
        link_elem = entry.find('atom:link[@rel="alternate"]', ns)
        content_elem = entry.find('atom:content', ns)
        summary_elem = entry.find('atom:summary', ns)
        
        title = title_elem.text if title_elem is not None else ''
        link = link_elem.get('href') if link_elem is not None else ''
        content = content_elem.text if content_elem is not None else ''
        summary = summary_elem.text if summary_elem is not None else ''
        
        # Get publication date
        published_elem = entry.find('atom:published', ns) or entry.find('atom:updated', ns)
        pub_date = self._parse_iso_date(published_elem.text) if published_elem is not None else None
        
        # Get categories
        categories = [cat.get('term') for cat in entry.findall('atom:category', ns) if cat.get('term')]
        
        # Apply junk filter
        if not self._passes_junk_filter(title, content or summary, categories):
            logger.debug(f"Filtered out junk article: {title[:50]}...")
            return None
        
        return {
            'title': title,
            'url': link,
            'content': self._strip_html(content) if content else '',
            'description': self._strip_html(summary) if summary else '',
            'published_at': pub_date,
            'source': self._extract_source_from_url(link or feed_url),
            'tickers': None,
            'categories': categories if categories else None,
        }
    
    def _passes_junk_filter(self, title: str, content: str, categories: Optional[List[str]] = None) -> bool:
        """Apply heuristic junk filtering.
        
        Args:
            title: Article title
            content: Article content/description
            categories: Optional list of category tags
            
        Returns:
            True if article passes filter, False if it's junk
        """
        # Check for spam phrases
        combined_text = f"{title} {content}".lower()
        for phrase in SPAM_PHRASES:
            if phrase in combined_text:
                logger.debug(f"Junk filter: Found spam phrase '{phrase}'")
                return False
        
        # Check minimum length
        if content is None or len(content) < MIN_CONTENT_LENGTH:
            logger.debug(f"Junk filter: Content too short ({len(content) if content else 0} < {MIN_CONTENT_LENGTH})")
            return False
        
        # Filter out irrelevant categories if present
        if categories:
            # Example: filter out "Sponsored" or "Press Release" categories
            irrelevant_categories = ['sponsored', 'advertisement', 'press release', 'promo']
            for cat in categories:
                if any(ic in cat.lower() for ic in irrelevant_categories):
                    logger.debug(f"Junk filter: Irrelevant category '{cat}'")
                    return False
        
        # NEW: Check for financial/market relevance
        # Count how many financial keywords are present
        keyword_matches = 0
        for keyword in FINANCIAL_KEYWORDS:
            if keyword in combined_text:
                keyword_matches += 1
                # Early exit if we've found enough keywords
                if keyword_matches >= MIN_FINANCIAL_KEYWORD_MATCHES:
                    break
        
        if keyword_matches < MIN_FINANCIAL_KEYWORD_MATCHES:
            logger.debug(f"Junk filter: Not financially relevant (found {keyword_matches} keywords, need {MIN_FINANCIAL_KEYWORD_MATCHES})")
            logger.debug(f"Title: {title[:80]}...")
            return False
        
        return True
    
    def _get_text(self, element: ET.Element, tag: str) -> Optional[str]:
        """Safely get text from XML element.
        
        Args:
            element: Parent XML element
            tag: Tag name to find
            
        Returns:
            Text content or None
        """
        child = element.find(tag)
        return child.text if child is not None and child.text else None
    
    def _strip_html(self, text: str) -> str:
        """Strip HTML tags from text.
        
        Args:
            text: HTML text
            
        Returns:
            Plain text
        """
        # Simple HTML tag removal (for basic cleanup)
        return re.sub(r'<[^>]+>', '', text).strip()
    
    def _parse_rfc822_date(self, date_str: str) -> Optional[datetime]:
        """Parse RFC 822 date format (used in RSS).
        
        Args:
            date_str: Date string
            
        Returns:
            datetime object or None
        """
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_str)
        except Exception as e:
            logger.debug(f"Error parsing RFC 822 date '{date_str}': {e}")
            return None
    
    def _parse_iso_date(self, date_str: str) -> Optional[datetime]:
        """Parse ISO 8601 date format (used in Atom).
        
        Args:
            date_str: Date string
            
        Returns:
            datetime object or None
        """
        try:
            # Handle both with and without timezone
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except Exception as e:
            logger.debug(f"Error parsing ISO date '{date_str}': {e}")
            return None
    
    def _extract_source_from_url(self, url: str) -> str:
        """Extract source name from URL.
        
        Args:
            url: Article URL
            
        Returns:
            Clean source name
        """
        try:
            parsed = urlparse(url)
            hostname = parsed.netloc or parsed.path
            
            # Remove www. prefix
            if hostname.startswith('www.'):
                hostname = hostname[4:]
            
            # Remove port if present
            if ':' in hostname:
                hostname = hostname.split(':')[0]
            
            return hostname
        except Exception:
            return "unknown"


# Global client instance
_rss_client: Optional[RSSClient] = None


def get_rss_client() -> RSSClient:
    """Get or create global RSS client instance.
    
    Returns:
        RSSClient instance
    """
    global _rss_client
    if _rss_client is None:
        _rss_client = RSSClient()
    return _rss_client
