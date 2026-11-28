#!/usr/bin/env python3
"""
SearXNG API Client
=================

HTTP client for interacting with SearXNG metasearch engine.
Supports web search, news search, and result formatting.
"""

import os
import json
import logging
from typing import Optional, List, Dict, Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

# Load environment variables from .env file (if it exists)
load_dotenv()

logger = logging.getLogger(__name__)

# Default configuration from environment variables
# Priority: Docker env vars > .env file > Python defaults
SEARXNG_BASE_URL = os.getenv("SEARXNG_BASE_URL", "http://host.docker.internal:8080")
SEARXNG_ENABLED = os.getenv("SEARXNG_ENABLED", "true").lower() == "true"
SEARXNG_TIMEOUT = int(os.getenv("SEARXNG_TIMEOUT", "10"))


class SearXNGClient:
    """Client for interacting with SearXNG API."""
    
    def __init__(self, base_url: Optional[str] = None, timeout: Optional[int] = None):
        """Initialize SearXNG client.
        
        Args:
            base_url: SearXNG API base URL (defaults to environment variable)
            timeout: Request timeout in seconds (defaults to environment variable)
        """
        # Auto-detect correct host if running locally
        if base_url is None:
            # Default to env var or docker internal
            candidate_url = SEARXNG_BASE_URL
            
            # If default is host.docker.internal but we can't resolve it (running on host), try localhost
            if "host.docker.internal" in candidate_url:
                import socket
                try:
                    socket.gethostbyname("host.docker.internal")
                except socket.gaierror:
                    logger.info("Could not resolve host.docker.internal, falling back to localhost for SearXNG")
                    candidate_url = candidate_url.replace("host.docker.internal", "localhost")
            
            self.base_url = candidate_url
        else:
            self.base_url = base_url

        self.timeout = timeout or SEARXNG_TIMEOUT
        self.enabled = SEARXNG_ENABLED
        
        logger.info(f"SearXNG client initialized: base_url={self.base_url}, timeout={self.timeout}s, enabled={self.enabled}")
        
        # Create session with retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # Zero-retry session for health probes so page loads never stall 20s
        self._probe_session = requests.Session()
        probe_adapter = HTTPAdapter(max_retries=0)
        self._probe_session.mount("http://", probe_adapter)
        self._probe_session.mount("https://", probe_adapter)
    
    def check_health(self) -> bool:
        """Check if SearXNG API is available.
        
        Returns:
            True if SearXNG is reachable, False otherwise
        """
        if not self.enabled:
            logger.debug("SearXNG health check skipped: disabled")
            return False
        
        try:
            logger.debug(f"Checking SearXNG health at {self.base_url}...")
            # Try a simple search query to verify the API is working
            response = self._probe_session.get(
                f"{self.base_url}/search",
                params={"q": "test", "format": "json"},
                timeout=(2.0, 3.0)
            )
            if response.status_code == 200:
                logger.info(f"✅ SearXNG health check successful: {self.base_url}")
                return True
            else:
                logger.warning(f"SearXNG health check failed: HTTP {response.status_code}")
                return False
        except Exception as e:
            logger.warning(f"❌ SearXNG health check failed: {e}")
            return False
    
    def search(
        self,
        query: str,
        categories: Optional[List[str]] = None,
        engines: Optional[List[str]] = None,
        time_range: Optional[str] = None,
        max_results: int = 10
    ) -> Dict[str, Any]:
        """Perform a web search using SearXNG.
        
        Args:
            query: Search query string
            categories: Optional list of categories (e.g., ['news', 'general'])
            engines: Optional list of search engines to use
            time_range: Optional time range filter (e.g., 'day', 'week', 'month', 'year')
            max_results: Maximum number of results to return (default: 10)
            
        Returns:
            Dictionary containing search results with keys:
            - 'results': List of result dictionaries
            - 'query': The search query used
            - 'number_of_results': Total number of results
        """
        if not self.enabled:
            logger.warning("SearXNG search rejected: disabled")
            return {
                'results': [],
                'query': query,
                'number_of_results': 0,
                'error': 'SearXNG is disabled'
            }
        
        try:
            # Build search parameters
            params = {
                'q': query,
                'format': 'json'
            }
            
            if categories:
                params['categories'] = ','.join(categories)
            
            if engines:
                params['engines'] = ','.join(engines)
            
            if time_range:
                params['time_range'] = time_range
            
            logger.info(f"SearXNG search: query='{query}', categories={categories}, time_range={time_range}")
            
            response = self.session.get(
                f"{self.base_url}/search",
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            data = response.json()
            
            # Limit results to max_results
            results = data.get('results', [])[:max_results]
            
            logger.info(f"SearXNG search completed: {len(results)} results")
            
            return {
                'results': results,
                'query': data.get('query', query),
                'number_of_results': data.get('number_of_results') or len(results),
                'answers': data.get('answers', []),
                'corrections': data.get('corrections', [])
            }
            
        except requests.exceptions.Timeout:
            logger.error(f"❌ SearXNG request timed out after {self.timeout}s")
            return {
                'results': [],
                'query': query,
                'number_of_results': 0,
                'error': 'Request timed out'
            }
        except requests.exceptions.ConnectionError as e:
            logger.error(f"❌ Cannot connect to SearXNG API at {self.base_url}: {e}")
            return {
                'results': [],
                'query': query,
                'number_of_results': 0,
                'error': 'Cannot connect to SearXNG'
            }
        except requests.exceptions.HTTPError as e:
            logger.error(f"❌ SearXNG API HTTP error: {e}")
            return {
                'results': [],
                'query': query,
                'number_of_results': 0,
                'error': f'HTTP error: {str(e)}'
            }
        except Exception as e:
            logger.error(f"❌ Unexpected error querying SearXNG: {e}", exc_info=True)
            return {
                'results': [],
                'query': query,
                'number_of_results': 0,
                'error': f'An error occurred: {str(e)}'
            }
    
    def search_news(
        self,
        query: str,
        time_range: Optional[str] = 'day',
        max_results: int = 10
    ) -> Dict[str, Any]:
        """Perform a news search using SearXNG.
        
        Args:
            query: Search query string
            time_range: Time range filter (default: 'day' for recent news)
            max_results: Maximum number of results to return
            
        Returns:
            Dictionary containing news search results
        """
        return self.search(
            query=query,
            categories=['news'],
            time_range=time_range,
            max_results=max_results
        )
    
    def search_web(
        self,
        query: str,
        time_range: Optional[str] = None,
        max_results: int = 10
    ) -> Dict[str, Any]:
        """Perform a general web search using SearXNG.
        
        Args:
            query: Search query string
            time_range: Optional time range filter
            max_results: Maximum number of results to return
            
        Returns:
            Dictionary containing web search results
        """
        return self.search(
            query=query,
            categories=['general'],
            time_range=time_range,
            max_results=max_results
        )


# Global client instance
_searxng_client: Optional[SearXNGClient] = None


def get_searxng_client() -> Optional[SearXNGClient]:
    """Get or create global SearXNG client instance.
    
    Returns:
        SearXNGClient instance or None if disabled
    """
    global _searxng_client
    if _searxng_client is None:
        _searxng_client = SearXNGClient()
    return _searxng_client if _searxng_client.enabled else None


def check_searxng_health() -> bool:
    """Check if SearXNG is available.
    
    Returns:
        True if SearXNG is reachable
    """
    client = get_searxng_client()
    return client.check_health() if client else False

