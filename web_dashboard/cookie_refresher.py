#!/usr/bin/env python3
"""
Cookie Refresher Service
========================

Automatically refreshes WebAI cookies using a headless browser.
Runs as a sidecar container that stays running independently of the main app.

This service:
1. Periodically checks if cookies need refreshing
2. Uses Playwright to visit the web AI service with existing cookies
3. Extracts fresh cookies (especially __Secure-1PSIDTS which expires frequently)
4. Writes cookies to a shared volume for the main app to use

Security Note:
- Uses existing cookies to maintain session continuity
- Runs from the same IP address as the original login (reduces 2FA risk)
- Uses stealth browser fingerprinting to appear as a real browser
- Detects and logs security challenges if they occur
"""

import sys
import json
import os
import time
import logging
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime, timedelta

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

try:
    from playwright.sync_api import sync_playwright, Browser, Page, TimeoutError as PlaywrightTimeout
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    print("[ERROR] Playwright not installed. Install with: pip install playwright && playwright install chromium")
    sys.exit(1)

# Setup logging
# Log to both file (in shared volume) and stdout
LOG_FILE = os.getenv("COOKIE_REFRESH_LOG_FILE", "/shared/cookies/cookie_refresher.log")
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
LOG_BACKUP_COUNT = 3

# Create formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Setup root logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Clear any existing handlers
logger.handlers = []

# File handler (with rotation)
try:
    from logging.handlers import RotatingFileHandler
    # Ensure log directory exists
    log_path = Path(LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create placeholder log file if it doesn't exist
    if not log_path.exists():
        try:
            log_path.touch()
            print(f"[INFO] Created log file: {log_path}")
        except Exception as touch_error:
            print(f"[WARNING] Could not create log file: {touch_error}")
    
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    print(f"[INFO] File logging configured: {LOG_FILE}")
except Exception as e:
    # If file logging fails, continue with stdout only
    print(f"[WARNING] Could not setup file logging: {e}")
    print(f"[WARNING] Log file location: {LOG_FILE}")
    print(f"[WARNING] Continuing with stdout-only logging")

# Console handler (stdout)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Configuration
REFRESH_INTERVAL = int(os.getenv("COOKIE_REFRESH_INTERVAL", "1800"))  # 30 minutes default (__Secure-1PSIDTS expires frequently)
COOKIE_GRACE_PERIOD_HOURS = int(os.getenv("COOKIE_GRACE_PERIOD_HOURS", "2"))  # 2 hours default (2x refresh cycles)
COOKIE_GRACE_PERIOD = COOKIE_GRACE_PERIOD_HOURS * 3600  # Convert to seconds
COOKIE_OUTPUT_FILE = os.getenv("COOKIE_OUTPUT_FILE", "/shared/cookies/webai_cookies.json")
COOKIE_INPUT_FILE = os.getenv("COOKIE_INPUT_FILE", "/shared/cookies/webai_cookies.json")  # Read existing cookies
MAX_RETRIES = 3
RETRY_DELAY = 60  # seconds


def get_service_url() -> str:
    """Get the web AI service URL from shared config file, environment variable, or keys file."""
    # Try shared config file first (for Docker containers - no restart needed)
    config_file = Path("/shared/cookies/ai_service_config.json")
    if config_file.exists():
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                url = config.get("AI_SERVICE_WEB_URL")
                if url and not url.startswith("https://example") and "webai.google.com" not in url:
                    logger.info(f"✅ Using service URL from shared config file: {url}")
                    return url
                elif url:
                    logger.warning(f"Shared config file contains placeholder URL: {url}")
        except Exception as e:
            logger.debug(f"Could not load URL from config file: {e}")
    
    # Try environment variable (fallback for backwards compatibility)
    env_url = os.getenv("AI_SERVICE_WEB_URL")
    logger.info(f"AI_SERVICE_WEB_URL env var: {'SET' if env_url else 'NOT SET'}")
    if env_url:
        logger.info(f"AI_SERVICE_WEB_URL value: {env_url}")
        # Reject placeholders (both old and new)
        if "webai.google.com" in env_url or env_url.startswith("https://example"):
            logger.error(f"AI_SERVICE_WEB_URL is set to placeholder URL: {env_url}")
            logger.error("  → Update Woodpecker secret 'ai_service_web_url' to the actual service URL")
        elif env_url and not env_url.startswith("https://example"):  # Ignore placeholder
            logger.info(f"✅ Using service URL from environment variable: {env_url}")
            return env_url
        else:
            logger.warning(f"AI_SERVICE_WEB_URL is set to placeholder URL - ignoring")
    
    # Try keys file (for local development and production)
    try:
        from ai_service_keys import get_service_url as get_url_from_keys
        url = get_url_from_keys("WEB_BASE_URL")
        if url and not url.startswith("https://example"):  # Ignore placeholder
            logger.info(f"Loaded service URL from keys file")
            return url
    except (ImportError, FileNotFoundError, KeyError, ValueError) as e:
        logger.debug(f"Could not load URL from keys file: {e}")
    
    # If all else fails, raise an error instead of using hardcoded URL
    error_msg = (
        "AI_SERVICE_WEB_URL not set correctly. "
        "Set it in /shared/cookies/ai_service_config.json, AI_SERVICE_WEB_URL environment variable, "
        "or ensure ai_service.keys.json exists with WEB_BASE_URL key."
    )
    raise ValueError(error_msg)


def validate_service_url(url: str) -> None:
    """Validate that the service URL is properly formatted and secure."""
    if not url:
        raise ValueError("Service URL cannot be empty")
    
    if not url.startswith("https://"):
        raise ValueError(f"Service URL must use HTTPS: {url}")
    
    # Check for placeholder URLs
    if "example.com" in url.lower() or "webai.google.com" in url:
        raise ValueError(f"Service URL appears to be a placeholder: {url}")


def load_existing_cookies() -> Optional[Dict[str, str]]:
    """Load existing cookies from the shared volume."""
    cookie_path = Path(COOKIE_INPUT_FILE)
    
    if not cookie_path.exists():
        logger.warning(f"Cookie file not found: {cookie_path}")
        return None
    
    try:
        with open(cookie_path, 'r', encoding='utf-8') as f:
            cookies = json.load(f)
        
        if not isinstance(cookies, dict):
            logger.error(f"Invalid cookie file format: expected dict, got {type(cookies)}")
            return None
        
        logger.info(f"Loaded existing cookies from {cookie_path}")
        return cookies
    except Exception as e:
        logger.error(f"Failed to load existing cookies: {e}")
        return None


def should_skip_refresh(cookies: Optional[Dict[str, str]]) -> tuple[bool, Optional[str]]:
    """
    Check if refresh should be skipped due to recent manual update.
    
    Returns:
        Tuple of (should_skip, reason_message)
    """
    if not cookies:
        return (False, None)
    
    # Check if cookies were manually set by admin UI
    if cookies.get("_updated_by") != "admin_ui":
        return (False, None)
    
    # Check when they were last updated
    updated_at_str = cookies.get("_updated_at")
    if not updated_at_str:
        return (False, None)
    
    try:
        # Parse timestamp (handle both with and without Z suffix)
        updated_at_str = updated_at_str.rstrip("Z")
        updated_at = datetime.fromisoformat(updated_at_str)
        
        # Calculate age
        age_seconds = (datetime.utcnow() - updated_at).total_seconds()
        age_hours = age_seconds / 3600
        
        # Skip if within grace period
        if age_seconds < COOKIE_GRACE_PERIOD:
            grace_hours = COOKIE_GRACE_PERIOD / 3600
            return (True, f"Cookies manually updated {age_hours:.1f} hours ago (grace period: {grace_hours:.1f} hours)")
        
        return (False, None)
    except (ValueError, TypeError) as e:
        logger.warning(f"Could not parse _updated_at timestamp: {updated_at_str}, error: {e}")
        return (False, None)


def save_cookies(cookies: Dict[str, str]) -> bool:
    """Save cookies to the shared volume with timestamp metadata."""
    cookie_path = Path(COOKIE_OUTPUT_FILE)
    
    # Ensure directory exists
    cookie_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        # Only save the cookies we need + metadata
        output = {
            "__Secure-1PSID": cookies.get("__Secure-1PSID", ""),
            "__Secure-1PSIDTS": cookies.get("__Secure-1PSIDTS", ""),
            "_refreshed_at": datetime.utcnow().isoformat() + "Z",
            "_refresh_count": cookies.get("_refresh_count", 0) + 1
        }
        
        # Preserve admin metadata if it exists (from manual updates)
        if "_updated_by" in cookies:
            output["_updated_by"] = cookies["_updated_by"]
        if "_updated_at" in cookies:
            output["_updated_at"] = cookies["_updated_at"]
        
        # Remove empty cookie values (keep metadata)
        output = {k: v for k, v in output.items() if v or k.startswith("_")}
        
        with open(cookie_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2)
        
        logger.info(f"Saved cookies to {cookie_path}")
        logger.info(f"  __Secure-1PSID: {output.get('__Secure-1PSID', 'MISSING')[:50]}...")
        logger.info(f"  __Secure-1PSIDTS: {output.get('__Secure-1PSIDTS', 'MISSING')[:50] if output.get('__Secure-1PSIDTS') else 'MISSING'}...")
        return True
    except Exception as e:
        logger.error(f"Failed to save cookies: {e}")
        return False


def refresh_cookies_with_browser(existing_cookies: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """
    Use Playwright to refresh cookies by visiting the web AI service.
    
    Args:
        existing_cookies: Existing cookies to use for authentication
        
    Returns:
        Dictionary of refreshed cookies, or None if failed
    """
    service_url = get_service_url()
    
    # Validate URL format and security
    try:
        validate_service_url(service_url)
    except ValueError as e:
        logger.error(f"Invalid service URL: {e}")
        return None
    
    logger.info(f"Refreshing cookies by visiting {service_url}")
    
    with sync_playwright() as p:
        browser = None
        try:
            # Launch browser in headless mode with stealth options
            # Use more realistic browser fingerprinting to avoid detection
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-blink-features=AutomationControlled',  # Hide automation
                    '--disable-dev-shm-usage',
                    '--disable-web-security',
                    '--disable-features=IsolateOrigins,site-per-process',
                ]
            )
            
            # Create context with realistic browser fingerprinting
            # This makes the browser look more like a real user session
            context_options = {
                "viewport": {"width": 1920, "height": 1080},
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "locale": "en-US",
                "timezone_id": "America/Los_Angeles",
                "permissions": ["geolocation"],
                "geolocation": {"latitude": 37.7749, "longitude": -122.4194},  # San Francisco
                "color_scheme": "light",
                "extra_http_headers": {
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Sec-Fetch-User": "?1",
                }
            }
            
            context = browser.new_context(**context_options)
            
            # Add script to hide webdriver property (common bot detection)
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                // Override plugins to look more realistic
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
                // Override languages
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en']
                });
            """)
            
            # Add existing cookies if we have them
            if existing_cookies:
                # Extract domain from URL and format with leading dot
                from urllib.parse import urlparse
                parsed = urlparse(service_url)
                
                # Use leading dot for domain to ensure cookies work across subdomains
                # e.g., ".google.com" instead of "gemini.google.com"
                base_domain = ".".join(parsed.netloc.split(".")[-2:])
                domain = f".{base_domain}"
                
                logger.info(f"Setting cookies with domain: {domain}")
                
                # Log what cookies we're trying to set
                cookie_names = [k for k in existing_cookies.keys() if not k.startswith("_")]
                logger.info(f"Attempting to set cookies: {', '.join(cookie_names)}")
                
                # Add cookies to context (skip metadata fields)
                cookie_list = []
                for name, value in existing_cookies.items():
                    # Skip metadata fields
                    if name.startswith("_"):
                        continue
                    
                    # Validate cookie value is not empty
                    if not value or not value.strip():
                        logger.warning(f"Skipping empty cookie: {name}")
                        continue
                    
                    # Try both domain formats - sometimes cookies need exact domain match
                    domains_to_try = [
                        domain,  # .google.com
                        parsed.netloc,  # gemini.google.com (exact match)
                    ]
                    
                    for cookie_domain in domains_to_try:
                        cookie_list.append({
                            "name": name,
                            "value": value,
                            "domain": cookie_domain,
                            "path": "/",
                            "secure": True,
                            "httpOnly": True,
                            "sameSite": "Lax"
                        })
                
                if cookie_list:
                    try:
                        context.add_cookies(cookie_list)
                        logger.info(f"Added {len(cookie_list)} cookie entries to browser context")
                    except Exception as e:
                        logger.error(f"Failed to add cookies to context: {e}")
                        # Continue anyway - might still work
                else:
                    logger.warning("No valid cookies to add to browser context")
            
            # Create page and navigate
            page = context.new_page()
            detected_challenges = []  # Initialize for later use
            
            logger.info(f"Navigating to {service_url}...")
            try:
                # Navigate with realistic timing
                page.goto(service_url, wait_until="networkidle", timeout=30000)
            except PlaywrightTimeout:
                logger.warning("Navigation timeout, but continuing...")
                # Wait a bit for page to load
                time.sleep(3)
            
            # Check for 2FA or security challenges
            try:
                page_content = page.content()
                page_url = page.url
                
                # Detect common 2FA/security challenge indicators
                security_indicators = [
                    "verify", "verification", "two-factor", "2fa", "2-step",
                    "security check", "unusual activity", "suspicious",
                    "confirm your identity", "enter code", "send code"
                ]
                
                page_text_lower = page_content.lower()
                detected_challenges = [indicator for indicator in security_indicators if indicator in page_text_lower]
                
                if detected_challenges:
                    logger.warning(f"⚠️  Security challenge detected: {', '.join(detected_challenges)}")
                    logger.warning("The service may require manual verification. Cookie refresh may fail.")
                    logger.warning(f"Current URL: {page_url}")
                    # Continue anyway - might still get cookies
            except Exception as e:
                logger.debug(f"Could not check for security challenges: {e}")
            
            # Wait for page to fully load and cookies to be set
            logger.info("Waiting for page to load and cookies to be set...")
            # Simulate human-like behavior: small random delay
            import random
            time.sleep(3 + random.uniform(0, 2))
            
            # Try to interact with page naturally (scroll, mouse movement simulation)
            try:
                page.evaluate("window.scrollTo(0, 100)")
                time.sleep(0.5)
                page.evaluate("window.scrollTo(0, 0)")
            except:
                pass  # Ignore if page doesn't support scrolling
            
            # Extract all cookies from the context
            all_cookies = context.cookies()
            logger.info(f"Extracted {len(all_cookies)} cookies from browser")
            
            # Log what cookies we actually found (for debugging)
            if all_cookies:
                cookie_names = [c.get("name", "unknown") for c in all_cookies]
                logger.info(f"Found cookies: {', '.join(cookie_names)}")
            
            # Also try to get cookies from the page URL specifically
            # Sometimes cookies are domain-specific and need to be queried by URL
            try:
                page_cookies = page.context.cookies([service_url])
                if page_cookies:
                    logger.info(f"Found {len(page_cookies)} cookies for page URL")
                    # Merge page cookies with context cookies
                    for cookie in page_cookies:
                        # Check if we already have this cookie
                        existing = next((c for c in all_cookies if c.get("name") == cookie.get("name")), None)
                        if not existing:
                            all_cookies.append(cookie)
            except Exception as e:
                logger.debug(f"Could not get page-specific cookies: {e}")
            
            # Convert to dictionary format
            cookies_dict = {}
            for cookie in all_cookies:
                cookies_dict[cookie["name"]] = cookie["value"]
            
            # Log all cookie names found (for debugging)
            if cookies_dict:
                logger.info(f"All cookie names: {list(cookies_dict.keys())}")
            
            # Check if we got the required cookies
            if "__Secure-1PSID" not in cookies_dict:
                logger.error("Failed to get __Secure-1PSID cookie")
                logger.error(f"Available cookies: {list(cookies_dict.keys())}")
                
                # Check if existing cookies were loaded
                if existing_cookies:
                    existing_names = [k for k in existing_cookies.keys() if not k.startswith("_")]
                    logger.error(f"Existing cookies that were loaded: {existing_names}")
                    if "__Secure-1PSID" in existing_cookies:
                        logger.error("⚠️  __Secure-1PSID was in existing cookies but not found after refresh")
                        logger.error("   This suggests the cookies may be expired or invalid")
                        logger.error("   You may need to manually extract fresh cookies")
                
                if detected_challenges:
                    logger.error("⚠️  This may be due to a security challenge (2FA/verification required)")
                    logger.error("   You may need to manually extract fresh cookies and update the Woodpecker secret")
                return None
            
            if "__Secure-1PSIDTS" not in cookies_dict:
                logger.warning("__Secure-1PSIDTS not found - may need manual login or security challenge")
                if detected_challenges:
                    logger.warning("⚠️  Security challenge detected - cookies may not refresh automatically")
                # Continue anyway, as __Secure-1PSID might be enough
            
            # Preserve metadata from existing cookies if present
            if existing_cookies:
                if "_refresh_count" in existing_cookies:
                    cookies_dict["_refresh_count"] = existing_cookies["_refresh_count"]
                # Preserve admin metadata
                if "_updated_by" in existing_cookies:
                    cookies_dict["_updated_by"] = existing_cookies["_updated_by"]
                if "_updated_at" in existing_cookies:
                    cookies_dict["_updated_at"] = existing_cookies["_updated_at"]
            
            return cookies_dict
            
        except Exception as e:
            logger.error(f"Error refreshing cookies: {e}")
            import traceback
            traceback.print_exc()
            return None
        finally:
            # Always close browser to prevent resource leaks
            if browser:
                try:
                    browser.close()
                except Exception as e:
                    logger.warning(f"Error closing browser: {e}")


def refresh_cookies() -> bool:
    """
    Main function to refresh cookies with retry logic.
    
    Returns:
        True if successful or skipped, False otherwise
    """
    logger.info("Starting cookie refresh...")
    
    # Load existing cookies first
    existing_cookies = load_existing_cookies()
    
    if not existing_cookies:
        logger.error("No existing cookies found. Cannot refresh without initial cookies.")
        logger.error("Please set initial cookies manually or via Woodpecker secret.")
        return False
    
    # Check if refresh should be skipped due to recent manual update
    should_skip, skip_reason = should_skip_refresh(existing_cookies)
    if should_skip:
        logger.info(f"⏭️  Skipping refresh: {skip_reason}")
        logger.info("   Cookies will be refreshed after grace period expires")
        return True  # Return success so main loop continues normally
    
    # Try to refresh with browser (reload cookies on each attempt)
    for attempt in range(MAX_RETRIES):
        logger.info(f"Refresh attempt {attempt + 1}/{MAX_RETRIES}")
        
        # Reload existing cookies on each attempt for freshness
        existing_cookies = load_existing_cookies()
        
        if not existing_cookies:
            logger.error("No existing cookies found. Cannot refresh without initial cookies.")
            logger.error("Please set initial cookies manually or via Woodpecker secret.")
            return False
        
        # Check again (in case cookies were updated between attempts)
        should_skip, skip_reason = should_skip_refresh(existing_cookies)
        if should_skip:
            logger.info(f"⏭️  Skipping refresh: {skip_reason}")
            return True
        
        refreshed_cookies = refresh_cookies_with_browser(existing_cookies)
        
        if refreshed_cookies:
            # Save the refreshed cookies
            if save_cookies(refreshed_cookies):
                logger.info("Cookie refresh successful!")
                return True
            else:
                logger.error("Failed to save refreshed cookies")
                return False
        else:
            if attempt < MAX_RETRIES - 1:
                logger.warning(f"Refresh failed, retrying in {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)
            else:
                logger.error("All refresh attempts failed")
                return False
    
    return False


def main():
    """Main loop - runs continuously, refreshing cookies periodically."""
    logger.info("Cookie Refresher Service starting...")
    logger.info(f"  Refresh interval: {REFRESH_INTERVAL} seconds")
    logger.info(f"  Cookie output: {COOKIE_OUTPUT_FILE}")
    logger.info(f"  Cookie input: {COOKIE_INPUT_FILE}")
    
    if not HAS_PLAYWRIGHT:
        logger.error("Playwright not available. Exiting.")
        sys.exit(1)
    
    # Add startup delay to prevent rapid crash loops
    logger.info("Waiting 60 seconds before initial refresh to ensure system stability...")
    time.sleep(60)
    
    # Initial refresh on startup
    logger.info("Performing initial cookie refresh...")
    refresh_cookies()
    
    # Main loop
    while True:
        try:
            logger.info(f"Sleeping for {REFRESH_INTERVAL} seconds until next refresh...")
            time.sleep(REFRESH_INTERVAL)
            
            logger.info("Starting scheduled cookie refresh...")
            refresh_cookies()
            
        except KeyboardInterrupt:
            logger.info("Received shutdown signal, exiting...")
            break
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")
            import traceback
            traceback.print_exc()
            # Continue running despite errors
            time.sleep(60)  # Wait a bit before retrying


if __name__ == "__main__":
    main()

