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
web_dashboard_path = project_root / 'web_dashboard'

if not web_dashboard_path.exists():
    raise ImportError(
        f"web_dashboard directory not found at {web_dashboard_path}. "
        f"Ensure this script is run from the project root directory."
    )

sys.path.insert(0, str(web_dashboard_path))

# Validate that the required module can be imported
try:
    from webai_cookie_client_legacy import WebAICookieClientLegacy
except ImportError as e:
    raise ImportError(
        f"Failed to import WebAICookieClientLegacy from web_dashboard. "
        f"Path added: {web_dashboard_path}. "
        f"Original error: {e}"
    )


def get_webai_client() -> WebAICookieClientLegacy:
    """
    Get a WebAI client instance, automatically finding the cookie file.
    
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


def query_webai(prompt: str) -> str:
    """
    Simple function to query WebAI.
    
    Args:
        prompt: The query/prompt to send
        
    Returns:
        Response text from WebAI
        
    Raises:
        FileNotFoundError: If cookie file not found
        RuntimeError: If query fails
    """
    client = get_webai_client()
    
    # Test authentication first
    if not client.test_authentication():
        raise RuntimeError("Authentication failed. Your cookies may have expired.")
    
    response = client.query(prompt)
    if not response:
        raise RuntimeError("Failed to get response from WebAI")
    
    return response


if __name__ == "__main__":
    # Simple test
    if len(sys.argv) < 2:
        print("Usage: python webai_helper_legacy.py 'Your query here'")
        sys.exit(1)
    
    query = " ".join(sys.argv[1:])
    try:
        response = query_webai(query)
        print("\n" + "=" * 60)
        print("WEBAI RESPONSE:")
        print("=" * 60)
        print(response)
        print("=" * 60)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

