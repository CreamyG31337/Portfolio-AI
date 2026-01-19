#!/usr/bin/env python3
"""
"""
WebAI Cookie-Based Client (Legacy)
==================================

Uses browser cookies to authenticate with Web AI interface.
This allows you to use your account without API access.

Usage:
    1. Extract cookies from your browser (see extract_ai_cookies.py)
    2. Save cookies to a JSON file
    3. Use this client to interact with the service

Example:
    from webai_cookie_client_legacy import WebAICookieClientLegacy
    
    client = WebAICookieClientLegacy(cookies_file="webai_cookies.json")
    response = client.query("What is Python?")
    print(response)
"""

import sys
import json
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

GEMINI_BASE_URL = "https://gemini.google.com"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com"


class WebAICookieClientLegacy:
    """Client for interacting with Web AI interface using browser cookies."""
    
    def __init__(self, cookies_file: Optional[str] = None, cookies_dict: Optional[Dict] = None):
        """
        Initialize the client with cookies.
        
        Args:
            cookies_file: Path to JSON file containing cookies
            cookies_dict: Dictionary of cookies (alternative to file)
        """
        self.session = requests.Session()
        
        # Setup retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Set browser-like headers
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Referer": GEMINI_BASE_URL,
            "Origin": GEMINI_BASE_URL,
        })
        
        # Load cookies
        if cookies_file:
            self.load_cookies_from_file(cookies_file)
        elif cookies_dict:
            self.load_cookies_from_dict(cookies_dict)
        else:
            logger.warning("No cookies provided. Authentication may fail.")
    
    def load_cookies_from_file(self, cookies_file: str) -> None:
        """Load cookies from a JSON file."""
        # If relative path, try both project root and web_dashboard
        cookie_path = Path(cookies_file)
        if not cookie_path.is_absolute():
            # Try project root first
            project_root = Path(__file__).parent.parent
            root_cookie = project_root / cookies_file
            web_cookie = Path(__file__).parent / cookies_file
            
            if root_cookie.exists():
                cookie_path = root_cookie
            elif web_cookie.exists():
                cookie_path = web_cookie
            else:
                # If neither exists, use the original path (will fail with clear error)
                cookie_path = Path(cookies_file)
        
        try:
            with open(cookie_path, 'r', encoding='utf-8') as f:
                cookies_data = json.load(f)
            
            if isinstance(cookies_data, list):
                # Format: [{"name": "...", "value": "...", "domain": "..."}, ...]
                for cookie in cookies_data:
                    self.session.cookies.set(
                        cookie.get("name"),
                        cookie.get("value"),
                        domain=cookie.get("domain", ".google.com")
                    )
            elif isinstance(cookies_data, dict):
                # Format: {"cookie_name": "cookie_value", ...}
                for name, value in cookies_data.items():
                    self.session.cookies.set(name, value, domain=".google.com")
            
            logger.info(f"Loaded cookies from {cookie_path}")
            
        except Exception as e:
            logger.error(f"Failed to load cookies from {cookie_path}: {e}")
            raise
    
    def load_cookies_from_dict(self, cookies_dict: Dict[str, str]) -> None:
        """Load cookies from a dictionary."""
        for name, value in cookies_dict.items():
            self.session.cookies.set(name, value, domain=".google.com")
        logger.info(f"Loaded {len(cookies_dict)} cookies from dictionary")
    
    def _discover_api_endpoint(self) -> Optional[str]:
        """
        Try to discover Gemini's API endpoint by inspecting the main page.
        
        Returns:
            API endpoint URL if found, None otherwise
        """
        try:
            logger.info("Fetching Gemini main page to discover API endpoint...")
            response = self.session.get(GEMINI_BASE_URL, timeout=30)
            response.raise_for_status()
            
            # Look for API endpoints in the HTML/JavaScript
            # Gemini might embed API URLs in script tags or data attributes
            content = response.text
            
            # Common patterns to look for
            import re
            patterns = [
                r'["\']([^"\']*api[^"\']*chat[^"\']*)["\']',
                r'["\']([^"\']*generativelanguage[^"\']*)["\']',
                r'["\']([^"\']*gemini[^"\']*api[^"\']*)["\']',
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                if matches:
                    logger.info(f"Found potential API endpoint: {matches[0]}")
                    return matches[0]
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to discover API endpoint: {e}")
            return None
    
    def query(self, prompt: str, model: str = "gemini-pro") -> Optional[str]:
        """
        Send a query to Gemini and get the response.
        
        Args:
            prompt: The query/prompt to send
            model: Model to use (default: gemini-pro)
            
        Returns:
            Response text if successful, None otherwise
        """
        # Try multiple API endpoint patterns
        # The web interface uses a different endpoint format with cookies
        api_endpoints = [
            # Web interface API (uses cookies, most likely to work)
            f"{GEMINI_BASE_URL}/_/api/generativelanguage/v1beta/models/{model}:generateContent",
            f"{GEMINI_BASE_URL}/_/api/generativelanguage/v1/models/{model}:generateContent",
            # Official API endpoints (may require API key, but try with cookies)
            f"{GEMINI_API_BASE}/v1beta/models/{model}:generateContent?key=",
            f"{GEMINI_API_BASE}/v1/models/{model}:generateContent?key=",
            # Alternative web endpoints
            f"{GEMINI_BASE_URL}/api/generate",
            f"{GEMINI_BASE_URL}/_/api/chat",
        ]
        
        payload = {
            "contents": [{
                "parts": [{
                    "text": prompt
                }]
            }]
        }
        
        for endpoint in api_endpoints:
            try:
                logger.info(f"Trying endpoint: {endpoint}")
                
                # Update headers for API request
                # The web interface may need specific headers
                headers = {
                    **self.session.headers,
                    "Content-Type": "application/json",
                }
                
                # For web interface endpoints, add referer
                if "_/api" in endpoint:
                    headers["Referer"] = f"{GEMINI_BASE_URL}/"
                    headers["X-Goog-AuthUser"] = "0"  # May be needed for some endpoints
                
                response = self.session.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                    timeout=60
                )
                
                logger.info(f"Response status: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    # Extract response text from various possible response formats
                    if "candidates" in data and len(data["candidates"]) > 0:
                        candidate = data["candidates"][0]
                        if "content" in candidate and "parts" in candidate["content"]:
                            parts = candidate["content"]["parts"]
                            if parts and "text" in parts[0]:
                                return parts[0]["text"]
                    
                    # Fallback: return full response for debugging
                    logger.info(f"Response structure: {json.dumps(data, indent=2)[:500]}")
                    return response.text
                
                elif response.status_code == 401:
                    logger.error("Authentication failed. Check your cookies.")
                    return None
                elif response.status_code == 403:
                    logger.error("Access forbidden. Your account may not have access or cookies expired.")
                    return None
                else:
                    logger.warning(f"Unexpected status {response.status_code}: {response.text[:200]}")
                    
            except requests.exceptions.RequestException as e:
                logger.debug(f"Endpoint {endpoint} failed: {e}")
                continue
            except json.JSONDecodeError as e:
                logger.debug(f"Failed to parse JSON response: {e}")
                continue
        
        # If all API endpoints fail, try the web interface approach
        logger.info("API endpoints failed, trying web interface approach...")
        return self._query_via_web_interface(prompt)
    
    def _query_via_web_interface(self, prompt: str) -> Optional[str]:
        """
        Alternative method: interact with Gemini's web interface directly.
        This simulates what happens when you type in the web UI.
        """
        try:
            # First, get the main page to establish session
            logger.info("Loading Gemini web interface...")
            response = self.session.get(GEMINI_BASE_URL, timeout=30)
            response.raise_for_status()
            
            # Look for the chat input and submit mechanism
            # This is more complex and may require JavaScript execution
            # For now, we'll try to find if there's a simpler API endpoint
            
            # Check if there's a streaming endpoint
            stream_endpoint = f"{GEMINI_BASE_URL}/api/stream"
            payload = {"prompt": prompt}
            
            response = self.session.post(
                stream_endpoint,
                json=payload,
                headers={
                    **self.session.headers,
                    "Content-Type": "application/json",
                },
                timeout=60,
                stream=True
            )
            
            if response.status_code == 200:
                # Handle streaming response
                full_response = ""
                for line in response.iter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            if "text" in data:
                                full_response += data["text"]
                        except:
                            pass
                return full_response if full_response else None
            
            return None
            
        except Exception as e:
            logger.error(f"Web interface method failed: {e}")
            return None
    
    def test_authentication(self) -> bool:
        """
        Test if the cookies are valid by making a simple request.
        
        Returns:
            True if authenticated, False otherwise
        """
        try:
            response = self.session.get(GEMINI_BASE_URL, timeout=30)
            # Check if we're redirected to login or if we can access the page
            if response.status_code == 200 and "gemini" in response.url.lower():
                logger.info("Authentication test: SUCCESS")
                return True
            else:
                logger.warning(f"Authentication test: FAILED (status: {response.status_code}, url: {response.url})")
                return False
        except Exception as e:
            logger.error(f"Authentication test error: {e}")
            return False


def main():
    """CLI interface for the WebAI cookie client."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Query WebAI using browser cookies")
    parser.add_argument(
        "--cookies",
        required=True,
        help="Path to JSON file containing cookies"
    )
    parser.add_argument(
        "--query",
        required=True,
        help="Query to send to WebAI"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test authentication only"
    )
    
    args = parser.parse_args()
    
    # Initialize client
    client = WebAICookieClientLegacy(cookies_file=args.cookies)
    
    # Test authentication
    if not client.test_authentication():
        logger.error("Authentication failed. Please check your cookies.")
        return 1
    
    if args.test:
        logger.info("Authentication test passed!")
        return 0
    
    # Send query
    logger.info(f"Sending query: {args.query}")
    response = client.query(args.query)
    
    if response:
        print("\n" + "=" * 60)
        print("RESPONSE:")
        print("=" * 60)
        print(response)
        print("=" * 60)
        return 0
    else:
        logger.error("Failed to get response from Gemini")
        return 1


if __name__ == "__main__":
    sys.exit(main())

