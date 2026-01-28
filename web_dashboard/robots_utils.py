"""
Robots.txt Enforcement Utilities
=================================

Helper module for checking robots.txt compliance before making HTTP requests.
Controlled by ENABLE_ROBOTS_TXT_CHECKS environment variable.

When ENABLE_ROBOTS_TXT_CHECKS is set to a truthy value (e.g., "1", "true", "yes"),
jobs will check robots.txt before fetching URLs and abort if disallowed.

When unset (default), all robots.txt checks are skipped and jobs run normally.
"""

import os
import logging
from typing import List
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

logger = logging.getLogger(__name__)

# In-memory cache for parsed robots.txt files (per domain)
_robots_cache: dict[str, RobotFileParser] = {}

# User agent string for robots.txt checks
USER_AGENT = "LLM-Micro-Cap-Trading-Bot/1.0"


class RobotsNotAllowedError(Exception):
    """Raised when a URL is disallowed by robots.txt."""
    
    def __init__(self, job_name: str, url: str, robots_url: str):
        self.job_name = job_name
        self.url = url
        self.robots_url = robots_url
        message = (
            f"Job '{job_name}' aborted: robots.txt disallows access to {url}. "
            f"See robots.txt at {robots_url}"
        )
        super().__init__(message)


def is_robots_enforced() -> bool:
    """
    Check if robots.txt enforcement is enabled via environment variable.
    
    Returns:
        True if ENABLE_ROBOTS_TXT_CHECKS is set to a truthy value, False otherwise.
    """
    value = os.getenv("ENABLE_ROBOTS_TXT_CHECKS", "").lower().strip()
    return value in ("1", "true", "yes", "on", "enabled")


def _get_robots_url(url: str) -> str:
    """Get the robots.txt URL for a given URL."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/robots.txt"


def _get_robots_parser(robots_url: str) -> RobotFileParser:
    """
    Get or create a RobotFileParser for a domain, with caching.
    
    Args:
        robots_url: Full URL to robots.txt file
        
    Returns:
        RobotFileParser instance (cached per domain)
    """
    parsed = urlparse(robots_url)
    domain = parsed.netloc
    
    if domain not in _robots_cache:
        parser = RobotFileParser()
        parser.set_url(robots_url)
        
        # Fetch and parse robots.txt
        try:
            parser.read()
            logger.debug(f"Fetched and parsed robots.txt from {robots_url}")
        except Exception as e:
            # If robots.txt can't be fetched, assume all access is allowed
            # (per robots.txt spec: if file doesn't exist, everything is allowed)
            logger.warning(f"Could not fetch robots.txt from {robots_url}: {e}. Assuming all access allowed.")
            parser.set_url(None)  # Disable parser
        
        _robots_cache[domain] = parser
    
    return _robots_cache[domain]


def check_url_allowed(url: str) -> bool:
    """
    Check if a single URL is allowed by robots.txt.
    
    This function is a no-op (returns True) if ENABLE_ROBOTS_TXT_CHECKS is not set.
    
    Args:
        url: URL to check
        
    Returns:
        True if URL is allowed (or robots.txt enforcement is disabled), False if disallowed
    """
    if not is_robots_enforced():
        return True
    
    if not url or not url.startswith(("http://", "https://")):
        # Invalid URL, assume allowed
        return True
    
    robots_url = _get_robots_url(url)
    parser = _get_robots_parser(robots_url)
    
    # Check if access is allowed
    if parser.url is None:
        # Parser was disabled (robots.txt couldn't be fetched), assume allowed
        return True
    
    return parser.can_fetch(USER_AGENT, url)


def check_or_raise(job_name: str, urls: List[str]) -> None:
    """
    Check if all URLs are allowed by robots.txt, raising RobotsNotAllowedError if any are disallowed.
    
    This function is a no-op if ENABLE_ROBOTS_TXT_CHECKS is not set.
    
    Args:
        job_name: Name of the job (for error messages)
        urls: List of URLs that will be accessed by this job
        
    Raises:
        RobotsNotAllowedError: If any URL is disallowed by robots.txt
    """
    if not is_robots_enforced():
        return
    
    if not urls:
        return
    
    logger.info(f"Checking robots.txt compliance for {len(urls)} URL(s) in job '{job_name}'")
    
    for url in urls:
        if not check_url_allowed(url):
            robots_url = _get_robots_url(url)
            raise RobotsNotAllowedError(job_name, url, robots_url)


def clear_cache() -> None:
    """Clear the robots.txt cache (useful for testing)."""
    global _robots_cache
    _robots_cache.clear()
