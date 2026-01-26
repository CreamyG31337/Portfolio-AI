"""
Symbol Article Scraper
=======================

Functions for scraping symbol pages to extract article links from financial news sites.
"""

import logging
import re
import os
from typing import List, Optional
from urllib.parse import urljoin, urlparse

try:
    import trafilatura
except ImportError:
    trafilatura = None
    logging.warning("trafilatura not installed - cannot fetch pages")

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
    logging.warning("beautifulsoup4 not installed - cannot parse HTML")

logger = logging.getLogger(__name__)

# Base URL for the target site (from environment variable)
import os
_BASE_URL = os.getenv("SYMBOL_ARTICLE_BASE_URL", "")
BASE_URL = _BASE_URL if _BASE_URL else None

# Domain name for filtering (from environment variable)
_DOMAIN = os.getenv("SYMBOL_ARTICLE_DOMAIN", "")

# URL patterns that indicate articles
ARTICLE_URL_PATTERNS = [
    r'/article/\d+',  # /article/1234567-title
    r'/news/\d+',     # /news/1234568-item
    r'/analysis/\d+', # /analysis/1234569-analysis
]

# URL patterns to exclude (not real articles)
EXCLUDED_URL_PATTERNS = [
    r'/comments',     # Comment sections
    r'/author/',      # Author profiles
    r'/symbol/',      # Symbol pages
    r'/user/',        # User profiles
    r'/marketplace/', # Marketplace links
    r'/subscription', # Subscription pages
]


def build_symbol_url(ticker: str, exchange: Optional[str] = None) -> str:
    """Build symbol page URL for a ticker.
    
    Args:
        ticker: Ticker symbol (e.g., 'STLD', 'AAPL')
        exchange: Optional exchange prefix for Canadian stocks (e.g., 'TSX', 'TSXV')
        
    Returns:
        Full URL to the symbol page
    """
    if not BASE_URL:
        raise ValueError("SYMBOL_ARTICLE_BASE_URL environment variable not set")
    
    if exchange:
        symbol = f"{exchange}:{ticker}"
    else:
        symbol = ticker
    
    return f"{BASE_URL}/symbol/{symbol}"


def fetch_symbol_page(ticker: str, exchange: Optional[str] = None) -> Optional[str]:
    """Fetch HTML content from a symbol page.
    
    Args:
        ticker: Ticker symbol
        exchange: Optional exchange prefix for Canadian stocks
        
    Returns:
        HTML content as string, or None if fetch failed
    """
    if not trafilatura:
        logger.error("trafilatura not installed - cannot fetch pages")
        return None
    
    url = build_symbol_url(ticker, exchange)
    logger.debug(f"Fetching symbol page: {url}")
    
    try:
        html = trafilatura.fetch_url(url)
        if not html:
            logger.warning(f"Failed to fetch content from {url}")
            return None
        
        logger.debug(f"Successfully fetched {len(html)} characters from {url}")
        return html
        
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return None


def is_valid_article_url(url: str) -> bool:
    """Check if a URL is a valid article URL.
    
    Validates that the URL:
    1. Matches one of the article URL patterns (/article/, /news/, /analysis/)
    2. Does not match excluded patterns (comments, profiles, etc.)
    
    Args:
        url: URL to validate
        
    Returns:
        True if URL appears to be a real article, False otherwise
        
    Examples:
        >>> is_valid_article_url('https://.../article/1234567-title')
        True
        >>> is_valid_article_url('https://.../article/1234567/comments')
        False
        >>> is_valid_article_url('https://.../symbol/STLD')
        False
    """
    if not url:
        return False
    
    # Check if URL matches any article pattern
    matches_article_pattern = any(
        re.search(pattern, url, re.IGNORECASE) 
        for pattern in ARTICLE_URL_PATTERNS
    )
    
    if not matches_article_pattern:
        return False
    
    # Check if URL matches any excluded pattern
    matches_excluded = any(
        re.search(pattern, url, re.IGNORECASE)
        for pattern in EXCLUDED_URL_PATTERNS
    )
    
    if matches_excluded:
        return False
    
    return True


def extract_article_links(html: str, base_url: Optional[str] = None) -> List[str]:
    """Extract article links from symbol page HTML.
    
    Args:
        html: HTML content of the symbol page
        base_url: Base URL for resolving relative links (defaults to site base)
        
    Returns:
        List of absolute article URLs
    """
    if not BeautifulSoup:
        logger.error("beautifulsoup4 not installed - cannot parse HTML")
        return []
    
    if not html:
        return []
    
    if not base_url:
        base_url = BASE_URL
    
    try:
        soup = BeautifulSoup(html, 'html.parser')
    except Exception as e:
        logger.error(f"Error parsing HTML: {e}")
        return []
    
    # Find all links
    links = soup.find_all('a', href=True)
    
    article_urls = []
    seen_urls = set()  # Deduplicate
    
    for link in links:
        href = link.get('href', '').strip()
        if not href:
            continue
        
        # Make absolute URL if relative
        if href.startswith('/'):
            href = urljoin(base_url, href)
        elif not href.startswith('http'):
            # Skip mailto:, javascript:, etc.
            continue
        
        # Only process URLs from the target site
        parsed = urlparse(href)
        if parsed.netloc and _DOMAIN and _DOMAIN not in parsed.netloc:
            continue
        
        # Validate as article URL
        if is_valid_article_url(href):
            # Normalize URL (remove fragments, query params for deduplication)
            normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if normalized not in seen_urls:
                seen_urls.add(normalized)
                article_urls.append(href)
    
    logger.debug(f"Extracted {len(article_urls)} article URLs from HTML")
    return article_urls


def filter_article_links(links: List[str], min_count: int = 1, max_count: Optional[int] = None) -> List[str]:
    """Filter and limit article links.
    
    Args:
        links: List of article URLs
        min_count: Minimum number of links to return (if available)
        max_count: Maximum number of links to return (None = no limit)
        
    Returns:
        Filtered list of article URLs
    """
    if not links:
        return []
    
    # Apply max limit if specified
    if max_count is not None:
        links = links[:max_count]
    
    # Ensure we have at least min_count (if available)
    if len(links) < min_count:
        logger.debug(f"Only found {len(links)} links, requested minimum {min_count}")
    
    return links


def scrape_symbol_articles(ticker: str, exchange: Optional[str] = None, max_articles: Optional[int] = None) -> List[str]:
    """Scrape symbol page and return article URLs.
    
    This is a convenience function that combines fetching and extraction.
    
    Args:
        ticker: Ticker symbol
        exchange: Optional exchange prefix for Canadian stocks
        max_articles: Maximum number of articles to return (None = all found)
        
    Returns:
        List of article URLs
    """
    html = fetch_symbol_page(ticker, exchange)
    if not html:
        return []
    
    article_urls = extract_article_links(html)
    
    if max_articles:
        article_urls = article_urls[:max_articles]
    
    return article_urls


def is_paywalled_content(content: str, title: str = "") -> bool:
    """Check if extracted content indicates a paywall.
    
    Args:
        content: Extracted article content
        title: Article title (optional, for additional checks)
        
    Returns:
        True if content appears to be paywalled, False otherwise
    """
    if not content:
        return False
    
    content_lower = content.lower()
    title_lower = title.lower() if title else ""
    
    # Common paywall indicators
    paywall_indicators = [
        "create a free account to read",
        "sign up for free",
        "subscribe to read",
        "premium article",
        "unlock this article",
        "read the full article",
        "continue reading",
    ]
    
    # Check if content is very short (likely just paywall message)
    if len(content.strip()) < 200:
        # Check for paywall phrases
        for indicator in paywall_indicators:
            if indicator in content_lower or indicator in title_lower:
                return True
    
    return False

