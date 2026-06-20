#!/usr/bin/env python3
"""
Research Utilities
==================

Helper functions for extracting and processing research articles.
"""

import logging
import re
import os
import time
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from urllib.parse import urlparse

try:
    import trafilatura
except ImportError:
    trafilatura = None
    logging.warning("trafilatura not installed - article extraction will fail")

logger = logging.getLogger(__name__)

RESEARCH_FLARESOLVERR_MAX_TIMEOUT_MS = int(
    os.getenv("RESEARCH_FLARESOLVERR_MAX_TIMEOUT_MS", "45000")
)
RESEARCH_DIRECT_FETCH_TIMEOUT_SECONDS = float(
    os.getenv("RESEARCH_DIRECT_FETCH_TIMEOUT_SECONDS", "25")
)
RESEARCH_ARCHIVE_FETCH_TIMEOUT_SECONDS = float(
    os.getenv("RESEARCH_ARCHIVE_FETCH_TIMEOUT_SECONDS", "20")
)
RESEARCH_DEFAULT_EXTRACTION_BUDGET_SECONDS = float(
    os.getenv("RESEARCH_DEFAULT_EXTRACTION_BUDGET_SECONDS", "120")
)

ACCESS_CHALLENGE_PATTERNS = [
    r"access to this page has been denied",
    r"before we continue",
    r"press\s*&?\s*hold to confirm you are\s*a human",
    r"reference id [a-f0-9-]{8,}",
    r"checking your browser before accessing",
    r"verify you are human",
    r"please enable javascript and cookies to continue",
]


def contains_access_challenge(content: str) -> bool:
    """Detect anti-bot / access challenge pages that are not valid article content."""
    if not content:
        return False

    content_lower = content.lower()

    # Strong indicators: a single match is enough
    strong_indicators = [
        "access to this page has been denied",
        "press & hold to confirm you are a human",
        "press and hold to confirm you are a human",
    ]
    if any(indicator in content_lower for indicator in strong_indicators):
        return True

    # Weaker indicators require at least two matches to reduce false positives
    matches = 0
    for pattern in ACCESS_CHALLENGE_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            matches += 1
            if matches >= 2:
                return True

    return False


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



def _fetch_direct_html(url: str, timeout_seconds: float) -> Optional[str]:
    """Fetch article HTML with domain strategy headers."""
    from web_fetch_client import get_web_fetch_client

    try:
        return get_web_fetch_client().fetch_direct_html(
            url,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        logger.debug("Direct article fetch failed: %s", exc)
        return None


def _remaining_timeout(deadline: Optional[float], default_seconds: float) -> float:
    """Return a timeout bounded by the remaining article extraction budget."""
    if deadline is None:
        return default_seconds

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("article extraction budget exhausted")
    return max(1.0, min(default_seconds, remaining))


def _extraction_error_response(url: str, error: str) -> Dict[str, Any]:
    return {
        'title': '',
        'content': '',
        'published_at': None,
        'source': extract_source_from_url(url),
        'success': False,
        'error': error,
    }


def extract_article_content(
    url: str,
    max_seconds: Optional[float] = None,
) -> Dict[str, Any]:

    """Extract article content from URL using Trafilatura.
    
    Args:
        url: Article URL to extract content from
        max_seconds: Optional wall-clock budget for network fetch and extraction.
        
    Returns:
        Dictionary with keys:
        - title: Article title
        - content: Full article text
        - published_at: Published date (datetime or None)
        - source: Source name extracted from URL
        - success: Boolean indicating success
        - error: Error type if failed ('download_failed', 'extraction_empty',
          'extraction_error', 'access_challenge')
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
        budget_seconds = (
            RESEARCH_DEFAULT_EXTRACTION_BUDGET_SECONDS if max_seconds is None else max_seconds
        )
        if budget_seconds <= 0:
            return _extraction_error_response(url, 'extraction_timeout')
        deadline = time.monotonic() + budget_seconds if budget_seconds > 0 else None

        # Try FlareSolverr first, then direct fetch with domain strategy headers.
        downloaded = None
        try:
            from web_fetch_client import get_web_fetch_client

            flaresolverr_timeout = _remaining_timeout(
                deadline,
                (RESEARCH_FLARESOLVERR_MAX_TIMEOUT_MS / 1000.0) + 5.0,
            )
            flaresolverr_max_timeout_ms = max(
                1000,
                min(
                    RESEARCH_FLARESOLVERR_MAX_TIMEOUT_MS,
                    int(max(1.0, flaresolverr_timeout - 1.0) * 1000),
                ),
            )

            logger.debug("Attempting to fetch via FlareSolverr: %s", url)
            downloaded = get_web_fetch_client().fetch_via_flaresolverr_text(
                url,
                max_timeout_ms=flaresolverr_max_timeout_ms,
                request_timeout_seconds=flaresolverr_timeout,
            )
            if downloaded:
                logger.debug("Successfully fetched via FlareSolverr: %s", url)
        except TimeoutError as e:
            logger.warning(
                "Article extraction budget exhausted before FlareSolverr fetch: %s", e
            )
            return _extraction_error_response(url, "extraction_timeout")
        except Exception as e:
            logger.debug("FlareSolverr request failed: %s", e)

        if not downloaded:
            logger.debug("Falling back to direct timed fetch: %s", url)
            try:
                downloaded = _fetch_direct_html(
                    url,
                    _remaining_timeout(deadline, RESEARCH_DIRECT_FETCH_TIMEOUT_SECONDS),
                )
            except TimeoutError as e:
                logger.warning(
                    "Article extraction budget exhausted before direct fetch: %s", e
                )
                return _extraction_error_response(url, "extraction_timeout")
        
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

        _remaining_timeout(deadline, 1.0)

        # Reject anti-bot challenge pages before extraction
        if contains_access_challenge(downloaded):
            logger.warning(f"Access challenge detected in downloaded HTML: {url}")
            return {
                'title': '',
                'content': '',
                'published_at': None,
                'source': extract_source_from_url(url),
                'success': False,
                'error': 'access_challenge'
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

        # Reject challenge text that survived extraction
        if contains_access_challenge(extracted):
            logger.warning(f"Access challenge detected in extracted content: {url}")
            return {
                'title': '',
                'content': '',
                'published_at': None,
                'source': extract_source_from_url(url),
                'success': False,
                'error': 'access_challenge'
            }
        
        _remaining_timeout(deadline, 1.0)

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
                _remaining_timeout(deadline, 1.0)
                archived_url = check_archived(
                    url,
                    timeout=int(_remaining_timeout(deadline, 10.0)),
                )
                
                if archived_url:
                    logger.info(f"Found archived version: {archived_url}")
                    # Use our custom fetch function with browser-like headers
                    # This avoids rate limiting that trafilatura.fetch_url() might trigger
                    try:
                        # Add a small delay to avoid rate limiting
                        time.sleep(min(1.0, _remaining_timeout(deadline, 1.0)))
                        
                        logger.debug(
                            "Fetching from archive URL with browser headers: %s",
                            archived_url,
                        )
                        from archive_service import get_archived_content
                        archived_html = get_archived_content(
                            archived_url,
                            timeout=int(
                                _remaining_timeout(
                                    deadline,
                                    RESEARCH_ARCHIVE_FETCH_TIMEOUT_SECONDS,
                                )
                            ),
                        )
                        
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
                                    logger.info(
                                        "Successfully extracted content from archived version"
                                    )
                                    # Use archived content
                                    extracted = archived_extracted
                                    # Update metadata from archived page if needed
                                    archived_metadata = trafilatura.extract_metadata(archived_html)
                                    if archived_metadata and archived_metadata.title:
                                        title = archived_metadata.title
                                else:
                                    logger.warning(
                            "Archived version also has paywall, "
                            "submitting for archiving"
                                    )
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
                                logger.warning("Archived version has insufficient content")
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
                    submit_for_archiving(
                        url,
                        timeout=int(_remaining_timeout(deadline, 10.0)),
                    )
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
        
    except TimeoutError as e:
        logger.warning(f"Timed out extracting content from {url}: {e}")
        return _extraction_error_response(url, 'extraction_timeout')
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
    company_name_indicators = [
        'LIMITED',
        'INC',
        'CORP',
        'CORPORATION',
        'LLC',
        'LTD',
        'HOLDINGS',
        'GROUP',
        'COMPANY',
    ]
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
    
    Checks the full ticker, the base symbol (without exchange suffix like .TO, .L),
    and common company name associations.
    
    Args:
        ticker: Ticker symbol to validate (e.g. "CCO.TO", "AMZN")
        content: Full article content to search
        
    Returns:
        True if ticker or its base symbol appears in content, False otherwise
    """
    if not ticker or not content:
        return False
    
    upper_content = content.upper()
    upper_ticker = ticker.upper().strip()
    
    # Direct match (e.g. "AMZN" in text)
    if upper_ticker in upper_content:
        return True
    
    # Strip exchange suffix and check base symbol
    # Handles: CCO.TO, BBD.B, RY.TO, SHOP.V, ADEN.SW, etc.
    base = upper_ticker.split(".")[0].split(":")[0]
    if base and base != upper_ticker and base in upper_content:
        return True
    
    return False


def normalize_relationship(source: str, target: str, rel_type: str) -> Tuple[str, str, str]:
    """Normalize relationship direction using Option A (Industry Standard).
    
    Option A: Supplier → Buyer direction
    - SUPPLIER: [Supplier] -> SUPPLIER -> [Buyer] (e.g., TSM -> SUPPLIER -> AAPL)
    - CUSTOMER relationships are converted to SUPPLIER with supplier as source, buyer as target
    
    Args:
        source: Source ticker or company name
        target: Target ticker or company name
        rel_type: Relationship type (SUPPLIER, CUSTOMER, COMPETITOR, PARTNER,
            PARENT, SUBSIDIARY, LITIGATION)
        
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
