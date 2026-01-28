#!/usr/bin/env python3
"""
Research Utilities
==================

Helper functions for extracting and processing research articles.
"""

import logging
import re
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from urllib.parse import urlparse

try:
    import trafilatura
except ImportError:
    trafilatura = None
    logging.warning("trafilatura not installed - article extraction will fail")

logger = logging.getLogger(__name__)


def is_domain_blacklisted(url: str, blacklist: list[str]) -> tuple[bool, str]:
    """Check if URL's domain is in the blacklist.
    
    Args:
        url: URL to check
        blacklist: List of blacklisted domains (e.g., ['msn.com', 'reuters.com'])
        
    Returns:
        Tuple of (is_blacklisted, domain)
    """
    domain = extract_source_from_url(url)
    
    # Check if domain matches any blacklisted domain
    for blocked_domain in blacklist:
        # Case-insensitive match
        if domain.lower() == blocked_domain.lower():
            return (True, domain)
    
    return (False, domain)


def extract_article_content(url: str) -> Dict[str, Any]:

    """Extract article content from URL using Trafilatura.
    
    Args:
        url: Article URL to extract content from
        
    Returns:
        Dictionary with keys:
        - title: Article title
        - content: Full article text
        - published_at: Published date (datetime or None)
        - source: Source name extracted from URL
        - success: Boolean indicating success
        - error: Error type if failed ('download_failed', 'extraction_empty', 'extraction_error')
    """
    if not trafilatura:
        logger.error("trafilatura not installed - cannot extract article content")
        return {
            'title': '',
            'content': '',
            'published_at': None,
            'source': extract_source_from_url(url),
            'success': False,
            'error': 'extraction_error'
        }
    
    try:
        # Try FlareSolverr first to bypass Cloudflare protection
        downloaded = None
        try:
            from os import getenv
            import requests
            
            flaresolverr_url = getenv("FLARESOLVERR_URL", "http://host.docker.internal:8191")
            flaresolverr_endpoint = f"{flaresolverr_url}/v1"
            
            payload = {
                "cmd": "request.get",
                "url": url,
                "maxTimeout": 60000  # 60 seconds
            }
            
            logger.debug(f"Attempting to fetch via FlareSolverr: {url}")
            response = requests.post(
                flaresolverr_endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=70  # Slightly longer than maxTimeout
            )
            response.raise_for_status()
            
            flaresolverr_data = response.json()
            
            # Check FlareSolverr status
            if flaresolverr_data.get("status") == "ok":
                solution = flaresolverr_data.get("solution", {})
                if solution:
                    downloaded = solution.get("response", "")
                    if downloaded:
                        logger.debug(f"Successfully fetched via FlareSolverr: {url}")
                    else:
                        logger.debug(f"FlareSolverr returned empty response for: {url}")
                else:
                    logger.debug(f"FlareSolverr response missing solution for: {url}")
            else:
                error_msg = flaresolverr_data.get("message", "Unknown error")
                logger.debug(f"FlareSolverr returned error: {error_msg}")
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            logger.debug(f"FlareSolverr unavailable or timed out: {e}")
        except Exception as e:
            logger.debug(f"FlareSolverr request failed: {e}")
        
        # Fallback to direct trafilatura fetch if FlareSolverr failed or unavailable
        if not downloaded:
            logger.debug(f"Falling back to direct trafilatura fetch: {url}")
            downloaded = trafilatura.fetch_url(url)
        
        if not downloaded:
            logger.warning(f"Failed to download content from {url}")
            return {
                'title': '',
                'content': '',
                'published_at': None,
                'source': extract_source_from_url(url),
                'success': False,
                'error': 'download_failed'
            }
        
        # Extract article data
        extracted = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_links=False,
            include_images=False,
            include_tables=False
        )
        
        if not extracted:
            logger.warning(f"Failed to extract content from {url}")
            return {
                'title': '',
                'content': '',
                'published_at': None,
                'source': extract_source_from_url(url),
                'success': False,
                'error': 'extraction_empty'
            }
        
        # Extract metadata
        metadata = trafilatura.extract_metadata(downloaded)
        
        # Get title
        title = metadata.title if metadata and metadata.title else ''
        
        # Get source for filtering
        source = extract_source_from_url(url)
        
        # Check for paywall using paywall detector
        from paywall_detector import is_paywalled_article, detect_paywall
        paywall_type = detect_paywall(extracted, url)
        
        if paywall_type:
            logger.info(f"Paywall detected ({paywall_type}): {url}")
            
            # Try archive services as fallback
            try:
                from archive_service import check_archived, get_archived_content
                
                logger.info(f"Attempting to find archived version: {url}")
                archived_url = check_archived(url)
                
                if archived_url:
                    logger.info(f"Found archived version: {archived_url}")
                    # Use our custom fetch function with browser-like headers
                    # This avoids rate limiting that trafilatura.fetch_url() might trigger
                    try:
                        import time
                        # Add a small delay to avoid rate limiting
                        time.sleep(1)
                        
                        logger.debug(f"Fetching from archive URL with browser headers: {archived_url}")
                        from archive_service import get_archived_content
                        archived_html = get_archived_content(archived_url)
                        
                        if archived_html:
                            # Re-extract content from archived page
                            archived_extracted = trafilatura.extract(
                                archived_html,
                                include_comments=False,
                                include_links=False,
                                include_images=False,
                                include_tables=False
                            )
                            
                            if archived_extracted and len(archived_extracted) > 200:
                                # Check if archived version also has paywall
                                if not is_paywalled_article(archived_extracted, archived_url):
                                    logger.info(f"Successfully extracted content from archived version")
                                    # Use archived content
                                    extracted = archived_extracted
                                    # Update metadata from archived page if needed
                                    archived_metadata = trafilatura.extract_metadata(archived_html)
                                    if archived_metadata and archived_metadata.title:
                                        title = archived_metadata.title
                                else:
                                    logger.warning(f"Archived version also has paywall, submitting for archiving")
                                    # Archived version also paywalled, submit for archiving
                                    from archive_service import submit_for_archiving
                                    submit_for_archiving(url)
                                    return {
                                        'title': title,
                                        'content': '',
                                        'published_at': None,
                                        'source': source,
                                        'success': False,
                                        'error': 'paid_subscription',
                                        'archive_submitted': True
                                    }
                            else:
                                logger.warning(f"Archived version has insufficient content")
                                # Submit for archiving as fallback
                                from archive_service import submit_for_archiving
                                submit_for_archiving(url)
                                return {
                                    'title': title,
                                    'content': '',
                                    'published_at': None,
                                    'source': source,
                                    'success': False,
                                    'error': 'paid_subscription',
                                    'archive_submitted': True
                                }
                        else:
                            logger.warning(f"Failed to fetch archived content from {archived_url}")
                            # Submit for archiving
                            from archive_service import submit_for_archiving
                            submit_for_archiving(url)
                            return {
                                'title': title,
                                'content': '',
                                'published_at': None,
                                'source': source,
                                'success': False,
                                'error': 'paid_subscription',
                                'archive_submitted': True
                            }
                    except Exception as e:
                        logger.warning(f"Error fetching from archive URL {archived_url}: {e}")
                        # Submit for archiving as fallback
                        from archive_service import submit_for_archiving
                        submit_for_archiving(url)
                        return {
                            'title': title,
                            'content': '',
                            'published_at': None,
                            'source': source,
                            'success': False,
                            'error': 'paid_subscription',
                            'archive_submitted': True
                        }
                else:
                    # Not archived yet, submit for archiving
                    logger.info(f"URL not archived yet, submitting for archiving: {url}")
                    from archive_service import submit_for_archiving
                    submit_for_archiving(url)
                    return {
                        'title': title,
                        'content': '',
                        'published_at': None,
                        'source': source,
                        'success': False,
                        'error': 'paid_subscription',
                        'archive_submitted': True
                    }
            except ImportError:
                logger.warning("Archive service not available, skipping archive fallback")
            except Exception as e:
                logger.error(f"Error during archive fallback: {e}", exc_info=True)
            
            # If archive fallback failed, return paywall error
            return {
                'title': title,
                'content': '',
                'published_at': None,
                'source': source,
                'success': False,
                'error': 'paid_subscription'
            }
        
        # Get published date
        published_at = None
        if metadata and metadata.date:
            try:
                # Try to parse the date
                published_at = datetime.fromisoformat(metadata.date.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                try:
                    # Try alternative parsing (dateutil is optional)
                    try:
                        from dateutil import parser
                        published_at = parser.parse(metadata.date)
                    except ImportError:
                        # dateutil not available, skip date parsing
                        logger.debug("dateutil not available, skipping date parsing")
                except Exception:
                    logger.debug(f"Could not parse date: {metadata.date}")
        
        return {
            'title': title,
            'content': extracted,
            'published_at': published_at,
            'source': source,
            'success': True,
            'error': None
        }
        
    except Exception as e:
        logger.error(f"Error extracting content from {url}: {e}")
        return {
            'title': '',
            'content': '',
            'published_at': None,
            'source': extract_source_from_url(url),
            'success': False,
            'error': 'extraction_error'
        }


def extract_source_from_url(url: str) -> str:
    """Extract source name from URL.
    
    Args:
        url: Article URL
        
    Returns:
        Clean source name (e.g., "yahoo.com" from "https://finance.yahoo.com/...")
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
        
    except Exception as e:
        logger.warning(f"Error extracting source from URL {url}: {e}")
        return "unknown"


def validate_ticker_format(ticker: Optional[str], max_length: int = 20) -> bool:
    """Validate ticker symbol format.
    
    Args:
        ticker: Ticker symbol to validate
        max_length: Maximum allowed length (default 20, database limit)
        
    Returns:
        True if valid format, False otherwise
    """
    if not ticker or not isinstance(ticker, str):
        return False
    
    ticker = ticker.strip().upper()
    if not ticker:
        return False
    
    # Strip trailing '?' (AI uses this to mark uncertain inferred tickers)
    # e.g., "RKLB?" -> "RKLB" for validation
    if ticker.endswith('?'):
        ticker = ticker[:-1]
        if not ticker:
            return False
    
    # Check length
    if len(ticker) > max_length:
        return False
    
    # Valid tickers: start with a letter; allow letters/digits/dot/dash afterwards
    # No spaces allowed
    pattern = r"^[A-Z][A-Z0-9\.-]*$"
    if not re.fullmatch(pattern, ticker):
        return False
    
    # Additional checks: reject if looks like a company name
    # - Contains multiple words (spaces would be caught by pattern, but check for common words)
    # - Too long (already checked)
    # - Contains common company name words
    company_name_indicators = ['LIMITED', 'INC', 'CORP', 'CORPORATION', 'LLC', 'LTD', 'HOLDINGS', 'GROUP', 'COMPANY']
    ticker_upper = ticker.upper()
    if any(indicator in ticker_upper for indicator in company_name_indicators):
        return False
    
    return True


def normalize_ticker(ticker: Optional[str]) -> Optional[str]:
    """Normalize a ticker symbol for storage.
    
    - Strips whitespace
    - Converts to uppercase
    - Removes trailing '?' (AI uncertainty marker)
    
    Args:
        ticker: Raw ticker from AI extraction
        
    Returns:
        Normalized ticker string, or None if invalid
    """
    if not ticker or not isinstance(ticker, str):
        return None
    
    ticker = ticker.strip().upper()
    
    # Strip trailing '?' (AI uses this to mark uncertain inferred tickers)
    if ticker.endswith('?'):
        ticker = ticker[:-1]
    
    if not ticker:
        return None
    
    return ticker


def validate_ticker_in_content(ticker: Optional[str], content: str) -> bool:
    """Validate that ticker appears in article content.
    
    Args:
        ticker: Ticker symbol to validate
        content: Full article content to search
        
    Returns:
        True if ticker appears in content (case-insensitive), False otherwise
    """
    if not ticker or not content:
        return False
    
    # Case-insensitive search for ticker in content
    return ticker.upper() in content.upper()


def normalize_relationship(source: str, target: str, rel_type: str) -> Tuple[str, str, str]:
    """Normalize relationship direction using Option A (Industry Standard).
    
    Option A: Supplier → Buyer direction
    - SUPPLIER: [Supplier] -> SUPPLIER -> [Buyer] (e.g., TSM -> SUPPLIER -> AAPL)
    - CUSTOMER relationships are converted to SUPPLIER with supplier as source, buyer as target
    
    Args:
        source: Source ticker or company name
        target: Target ticker or company name
        rel_type: Relationship type (SUPPLIER, CUSTOMER, COMPETITOR, PARTNER, PARENT, SUBSIDIARY, LITIGATION)
        
    Returns:
        Tuple of (normalized_source, normalized_target, normalized_type)
        
    Examples:
        >>> normalize_relationship("TSM", "AAPL", "SUPPLIER")
        ("TSM", "AAPL", "SUPPLIER")
        >>> normalize_relationship("AAPL", "TSM", "CUSTOMER")
        ("TSM", "AAPL", "SUPPLIER")
        >>> normalize_relationship("AAPL", "MSFT", "COMPETITOR")
        ("AAPL", "MSFT", "COMPETITOR")
    """
    rel_type_upper = rel_type.upper().strip()
    source_upper = source.upper().strip()
    target_upper = target.upper().strip()
    
    # Handle CUSTOMER relationships: flip to SUPPLIER with supplier as source
    if rel_type_upper == "CUSTOMER":
        # "Apple is a customer of TSMC" → TSM -> SUPPLIER -> AAPL
        return (target_upper, source_upper, "SUPPLIER")
    
    # SUPPLIER relationships: already in correct direction (Supplier -> Buyer)
    # Other types (COMPETITOR, PARTNER, LITIGATION, PARENT, SUBSIDIARY): keep as-is
    return (source_upper, target_upper, rel_type_upper)


def escape_markdown(text: str) -> str:
    """Escape markdown special characters to prevent formatting issues in Streamlit.
    
    Escapes:
    - $ (LaTeX math)
    - * (Bold/Italic)
    - _ (Italic)
    - ` (Code)
    - [ ] (Links)
    
    Args:
        text: Input text
        
    Returns:
        Escaped text safe for display
    """
    if not text:
        return ""
        
    # Order matters: replace backslash first if we were escaping backslashes (but we aren't here)
    # We mainly want to prevent unintended formatting
    
    # Simple replacements
    chars_to_escape = {
        '$': '\\$',
        '*': '\\*',
        '_': '\\_',
        '`': '\\`',
        '[': '\\[',
        ']': '\\]',
    }
    
    # Use a loop or simple replacements
    # For a small set of characters, simple replace is fine and readable
    escaped = text
    for char, replacement in chars_to_escape.items():
        escaped = escaped.replace(char, replacement)
        
    return escaped
