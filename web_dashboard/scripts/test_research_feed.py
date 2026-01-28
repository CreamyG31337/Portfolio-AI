#!/usr/bin/env python3
"""Test financial research RSS feed parsing."""

import sys
import os
import base64
import logging
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from rss_utils import get_rss_client, FLARESOLVERR_URL
import requests

# Configure logging to see debug messages
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')

# URL obfuscation (same pattern as jobs_congress.py)
_FEED_URL_ENCODED = "aHR0cHM6Ly9obnRyYnJrLmNvbS9mZWVkLw=="

def check_flaresolverr():
    """Check if FlareSolverr is available."""
    try:
        health_response = requests.get(f"{FLARESOLVERR_URL}/health", timeout=5)
        if health_response.status_code == 200:
            print(f"FlareSolverr is available at {FLARESOLVERR_URL}")
            return True
        else:
            print(f"FlareSolverr health check returned {health_response.status_code}")
            return False
    except Exception as e:
        print(f"FlareSolverr not available at {FLARESOLVERR_URL}: {e}")
        return False

def test_feed():
    # Decode feed URL
    feed_url = base64.b64decode(_FEED_URL_ENCODED).decode('utf-8')
    
    print(f"Testing financial research RSS feed...")
    print(f"FlareSolverr URL: {FLARESOLVERR_URL}")
    print()
    
    # Check FlareSolverr availability
    flaresolverr_available = check_flaresolverr()
    print()
    
    client = get_rss_client()
    
    # First, let's see what the direct request would get (if it works)
    print("Testing direct request (without FlareSolverr)...")
    try:
        import requests
        direct_response = requests.get(feed_url, 
                                     headers={'Accept': 'application/rss+xml, application/xml, text/xml, */*'},
                                     timeout=10)
        if direct_response.status_code == 200:
            print(f"   Direct request: SUCCESS (status {direct_response.status_code})")
            print(f"   Content-Type: {direct_response.headers.get('Content-Type', 'N/A')}")
            print(f"   First 200 chars: {direct_response.text[:200]}")
        else:
            print(f"   Direct request: FAILED (status {direct_response.status_code})")
    except Exception as e:
        print(f"   Direct request: ERROR - {e}")
    print()
    
    # Now test via FlareSolverr
    print("Testing via FlareSolverr...")
    feed = client.fetch_feed(feed_url)
    
    if feed:
        print("SUCCESS: Feed fetched successfully!")
        print(f"   Title: {feed.get('title', 'N/A')}")
        print(f"   Items found: {len(feed.get('items', []))}")
        if feed.get('items'):
            print(f"\n   Sample items:")
            for i, item in enumerate(feed['items'][:3], 1):
                print(f"   {i}. {item.get('title', 'N/A')[:70]}...")
                print(f"      URL: {item.get('url', 'N/A')}")
    else:
        print("FAILED: Could not fetch feed")
        if not flaresolverr_available:
            print("   Note: FlareSolverr is not available - direct request may be blocked by Cloudflare")

if __name__ == "__main__":
    test_feed()
