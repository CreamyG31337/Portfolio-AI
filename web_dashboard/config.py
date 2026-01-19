"""Web Dashboard Configuration

Configuration constants for web dashboard paths and settings.
Uses environment variables with sensible defaults for Docker deployments.
"""

import os
from pathlib import Path

# Shared cookies directory (used in Docker containers with volume mounts)
# Can be overridden via SHARED_COOKIES_DIR environment variable for local development
SHARED_COOKIES_DIR = os.getenv("SHARED_COOKIES_DIR", "/shared/cookies")

# Cookie file paths
WEBAI_COOKIES_FILE = os.path.join(SHARED_COOKIES_DIR, "webai_cookies.json")
COOKIE_REFRESH_LOG_FILE = os.path.join(SHARED_COOKIES_DIR, "cookie_refresher.log")
AI_SERVICE_CONFIG_FILE = os.path.join(SHARED_COOKIES_DIR, "ai_service_config.json")

# Path objects for convenience
SHARED_COOKIES_PATH = Path(SHARED_COOKIES_DIR)
WEBAI_COOKIES_PATH = Path(WEBAI_COOKIES_FILE)
COOKIE_REFRESH_LOG_PATH = Path(COOKIE_REFRESH_LOG_FILE)
AI_SERVICE_CONFIG_PATH = Path(AI_SERVICE_CONFIG_FILE)
