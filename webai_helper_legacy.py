#!/usr/bin/env python3
"""
WebAI Helper for Console App
==============================

Simple helper to use WebAI from the console trading app.
"""

import sys
from pathlib import Path

# Add web_dashboard to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / 'web_dashboard'))

from webai_cookie_client_legacy import WebAICookieClientLegacy


def get_gemini_client() -> WebAICookieClientLegacy:
    """
    Get a Gemini client instance, automatically finding the cookie file.
    
    Returns:
        WebAICookieClientLegacy instance
        
    Raises:
        FileNotFoundError: If cookie file not found
    """
    # Try project root first, then web_dashboard
    root_cookie = project_root / "webai_cookies.json"
    web_cookie = project_root / "web_dashboard" / "webai_cookies.json"
    
    if root_cookie.exists():
        return WebAICookieClientLegacy(cookies_file=str(root_cookie))
    elif web_cookie.exists():
        return WebAICookieClientLegacy(cookies_file=str(web_cookie))
    else:
        raise FileNotFoundError(
            f"webai_cookies.json not found. Checked:\n"
            f"  - {root_cookie}\n"
            f"  - {web_cookie}\n"
            f"\nExtract cookies with: python web_dashboard/extract_ai_cookies.py --browser manual"
        )


def query_gemini(prompt: str) -> str:
    """
    Simple function to query Gemini.
    
    Args:
        prompt: The query/prompt to send
        
    Returns:
        Response text from Gemini
        
    Raises:
        FileNotFoundError: If cookie file not found
        RuntimeError: If query fails
    """
    client = get_gemini_client()
    
    # Test authentication first
    if not client.test_authentication():
        raise RuntimeError("Authentication failed. Your cookies may have expired.")
    
    response = client.query(prompt)
    if not response:
        raise RuntimeError("Failed to get response from Gemini")
    
    return response


if __name__ == "__main__":
    # Simple test
    if len(sys.argv) < 2:
        print("Usage: python gemini_helper.py 'Your query here'")
        sys.exit(1)
    
    query = " ".join(sys.argv[1:])
    try:
        response = query_gemini(query)
        print("\n" + "=" * 60)
        print("GEMINI RESPONSE:")
        print("=" * 60)
        print(response)
        print("=" * 60)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

