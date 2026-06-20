#!/usr/bin/env python3
"""Health check script for Flask dashboard container."""
import sys

import requests

try:
    response = requests.get("http://localhost:5001/", timeout=5, allow_redirects=False)
    # 200 (home) or 302 (auth redirect) means the app is up
    sys.exit(0 if response.status_code in (200, 302) else 1)
except Exception:
    sys.exit(1)
