#!/usr/bin/env python3
"""Health check script for Streamlit container."""
import requests
import sys

try:
    response = requests.get('http://localhost:8501/_stcore/health', timeout=5)
    sys.exit(0 if response.status_code == 200 else 1)
except Exception:
    sys.exit(1)
