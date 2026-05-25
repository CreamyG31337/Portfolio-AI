#!/usr/bin/env python3
"""
Portfolio Performance Web Dashboard
A Flask web app to display trading bot portfolio performance using Supabase
"""

# Check critical dependencies first
try:
    from flask import Flask, render_template, jsonify, request, redirect, url_for, session, Response, copy_current_request_context
except ImportError as e:
    print(f"❌ ERROR: {e}")
    print("🔔 SOLUTION: Activate the virtual environment first!")
    print("   PowerShell: & '..\\venv\\Scripts\\Activate.ps1'")
    print("   Then run: python app.py")
    print("   You should see (venv) in your prompt when activated.")
    exit(1)

try:
    import pandas as pd
except ImportError:
    print("❌ ERROR: pandas not available")
    print("🔔 SOLUTION: Activate the virtual environment first!")
    print("   PowerShell: & '..\\venv\\Scripts\\Activate.ps1'")
    exit(1)

import json
import math
import os
import re
import secrets
import sys
from datetime import datetime, timedelta, date
from pathlib import Path
import yfinance as yf
import plotly.graph_objs as go
import plotly.utils
from typing import Dict, List, Optional, Tuple, Any
import logging
import requests
import threading
import concurrent.futures
from urllib.parse import urlencode
from flask_cors import CORS

# Ensure repo-level modules (e.g., utils.*) are importable before route imports.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DASHBOARD_ROOT = Path(__file__).resolve().parent
if str(WEB_DASHBOARD_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_DASHBOARD_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask_cache_utils import cache_data, cache_resource
from rate_limiter import rate_limit

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Setup file logging to write to app.log
try:
    from log_handler import setup_logging
    setup_logging()
except ImportError:
    pass  # Fallback to basicConfig if log_handler not available

# Initialize Flask app with template and static folders
# serving static files at /assets to avoid conflict with Streamlit's /static
app = Flask(__name__,
            template_folder='templates',
            static_folder='static',
            static_url_path='/assets')

# Securely handle FLASK_SECRET_KEY
app.secret_key = os.getenv("FLASK_SECRET_KEY")
if not app.secret_key:
    import secrets
    logger.warning("FLASK_SECRET_KEY not set. Generating a random secret. Sessions will be invalidated on restart.")
    app.secret_key = secrets.token_hex(32)

# Apply ProxyFix middleware for proper HTTPS detection behind reverse proxy (Nginx/Docker)
# This makes request.is_secure work correctly when behind a load balancer
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Configure Debug Mode
# WARNING: Setting app.debug = True enables the interactive debugger which allows arbitrary code execution.
# NEVER set this to True in production environment unless strictly protected.
app.debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
app.config['PROPAGATE_EXCEPTIONS'] = True

# CSRF Protection (optional - can be enabled if Flask-WTF is installed)
try:
    from flask_wtf.csrf import CSRFProtect, CSRFError
    csrf = CSRFProtect(app)
    CSRF_ENABLED = True
    logger.info("CSRF protection enabled via Flask-WTF")

    # Disable default CSRF checking so we can manually control it
    app.config['WTF_CSRF_CHECK_DEFAULT'] = False

    # Paths exempt from CSRF protection (external webhooks that use their own auth)
    CSRF_EXEMPT_PATHS = [
        '/api/webhooks/',
    ]

    # Manually protect all state-changing routes in before_request
    @app.before_request
    def csrf_protect_routes():
        """Apply CSRF protection to all routes (except external webhooks)"""
        # Only check CSRF for state-changing methods
        if request.method in app.config.get('WTF_CSRF_METHODS', ['POST', 'PUT', 'PATCH', 'DELETE']):
            # Skip CSRF for external webhook endpoints (they use their own signature verification)
            for exempt_path in CSRF_EXEMPT_PATHS:
                if request.path.startswith(exempt_path):
                    return
            csrf.protect()

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        """Return JSON for CSRF errors so fetch() callers can handle them gracefully."""
        if request.path.startswith('/api/') or request.accept_mimetypes.best == 'application/json':
            return jsonify({"error": "csrf_expired", "message": "Your session token has expired. Retrying..."}), 419
        return e.description, 400

    @app.route('/api/auth/csrf-token', methods=['GET'])
    def get_csrf_token():
        """Return a fresh CSRF token (for pages that have been open a long time)."""
        from flask_wtf.csrf import generate_csrf
        return jsonify({"csrf_token": generate_csrf()})

    logger.info("CSRF protection enabled for all state-changing routes")
except ImportError:
    CSRF_ENABLED = False
    csrf = None
    logger.warning("Flask-WTF not available - CSRF protection disabled. Install with: pip install flask-wtf")

# Make CSRF_ENABLED available to all templates
@app.context_processor
def inject_csrf_enabled():
    """Make CSRF_ENABLED available to all templates"""
    return {'CSRF_ENABLED': CSRF_ENABLED}


@app.before_request
def validate_fund_query_param():
    """Validate ?fund= on page requests and strip invalid values."""
    if request.method != "GET" or "fund" not in request.args:
        return None

    path = request.path or ""
    if path.startswith(("/api/", "/static/", "/assets/")):
        return None

    raw_fund = request.args.get("fund")
    if raw_fund is None:
        return None

    fund_value = str(raw_fund).strip()
    if not fund_value:
        return None

    restricted_all_funds_paths = {"/ai_assistant", "/ticker_details"}
    fund_lower = fund_value.lower()

    if fund_lower in ("all", "all funds"):
        if path in restricted_all_funds_paths:
            logger.warning(
                "[fund-selector] Invalid fund '%s' for path '%s' (all not allowed).",
                fund_value,
                path
            )
        return _redirect_without_fund_param()

    try:
        from flask_data_utils import get_available_funds_flask
        available_funds = get_available_funds_flask()
    except Exception as e:
        logger.warning("[fund-selector] Failed to validate fund '%s': %s", fund_value, e)
        return None

    if available_funds and fund_value not in available_funds:
        logger.warning(
            "[fund-selector] Invalid fund '%s' for user on path '%s'.",
            fund_value,
            path
        )
        return _redirect_without_fund_param()

    def _redirect_without_fund_param():
        args = request.args.to_dict(flat=False)
        args.pop("fund", None)
        query = urlencode(args, doseq=True)
        target = request.path + (f"?{query}" if query else "")
        return redirect(target, code=302)

# Add Security Headers
@app.after_request
def handle_invalid_session(response):
    """Check if Supabase marked the session as invalid and redirect to login"""
    if getattr(request, '_supabase_session_invalid', False):
        # Session is invalid (JWT signature error, etc.) - clear cookies and redirect
        logger.warning("[AUTH] Session invalid - clearing cookies and redirecting to login")
        # For API requests, return 401
        if request.path.startswith('/api/'):
            from flask import jsonify
            resp = jsonify({"error": "Session invalid, please log in again"})
            resp.status_code = 401
            resp.delete_cookie('auth_token')
            resp.delete_cookie('refresh_token')
            resp.delete_cookie('session_token')
            return resp
        # For page requests, redirect to auth page
        resp = redirect('/auth?error=session_invalid')
        resp.delete_cookie('auth_token')
        resp.delete_cookie('refresh_token')
        resp.delete_cookie('session_token')
        return resp
    return response


@app.after_request
def add_security_headers(response):
    """Add security headers to response"""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'

    # Strict Transport Security (HSTS)
    # 1 year duration, include subdomains
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'

    # Permissions Policy
    # Disable features not used by the dashboard
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=(), payment=(), usb=()'

    # Content Security Policy (CSP)
    # Allows scripts/styles from self and trusted CDNs
    # 'unsafe-inline' and 'unsafe-eval' are required for current template/library architecture
    # but restricting domains still provides significant security benefit over no CSP
    connect_src = "'self' https://cdn.jsdelivr.net"
    supabase_url = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    if supabase_url:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(supabase_url)
            if parsed.scheme and parsed.netloc:
                connect_src += f" {parsed.scheme}://{parsed.netloc}"
        except Exception:
            pass
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://static.cloudflareinsights.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
        "font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com data:; "
        "img-src 'self' data: https://assets.parqet.com https://s.yimg.com https://unavatar.io; "
        f"connect-src {connect_src}; "
        "frame-ancestors 'self';"
    )
    response.headers['Content-Security-Policy'] = csp

    return response

# Configure CORS to allow credentials from Vercel deployment
CORS(app,
     supports_credentials=True,
     origins=["https://webdashboard-hazel.vercel.app", "http://localhost:5000"],
     allow_headers=["Content-Type", "Authorization", "X-CSRFToken"],
     expose_headers=["Content-Type"])

# Initialize Flask-Caching for data caching (similar to Streamlit's @st.cache_data)
# This provides TTL-based caching for data-heavy operations
try:
    from flask_caching import Cache
    cache = Cache(config={
        'CACHE_TYPE': 'SimpleCache',  # In-memory cache (can be upgraded to Redis/Memcached)
        'CACHE_DEFAULT_TIMEOUT': 300,  # Default 5 minutes
    })
    cache.init_app(app)
    # NOTE: Don't manually set app.extensions['cache'] - Flask-Caching handles this internally
    # Flask-Caching stores the cache backend in a special way that we shouldn't overwrite
    logger.info("Flask-Caching initialized successfully")
except ImportError:
    logger.warning("Flask-Caching not available. Using fallback cache from flask_cache_utils.")
    cache = None

# Set JWT secret for auth system
jwt_secret = os.getenv("JWT_SECRET")
if not jwt_secret:
    import secrets
    # Only log warning if not already set (avoid duplicate logs if app reloads)
    if "JWT_SECRET" not in os.environ:
        logger.warning("JWT_SECRET not set. Generating a random secret. Sessions will be invalidated on restart.")
    jwt_secret = secrets.token_hex(32)
    os.environ["JWT_SECRET"] = jwt_secret

# NOTE: CONTEXT_DATA_CACHE removed - now using flask_cache_utils.cache_data() decorator
# See _get_context_data_packet() function for cached context building

# Global error handler to expose tracebacks in response
@app.errorhandler(500)
def internal_server_error(e):
    import traceback
    # Only expose traceback in debug mode
    if app.debug:
        tb = traceback.format_exc()
        message = str(e)
    else:
        tb = "Traceback hidden (app.debug is False)"
        message = "An internal server error occurred."

    # Return JSON for API requests
    if request.path.startswith('/api/') or request.is_json:
        response_data = {
            "error": "Internal Server Error",
            "message": message
        }
        if app.debug:
            response_data["traceback"] = tb

        return jsonify(response_data), 500

    # Return HTML for browser requests (visible on screen)
    if app.debug:
        return f"""
        <html>
            <head>
                <title>500 Internal Server Error</title>
                <style>
                    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; padding: 2rem; line-height: 1.5; background-color: #1a1b26; color: #a9b1d6; }}
                    h1 {{ color: #f7768e; border-bottom: 1px solid #414868; padding-bottom: 0.5rem; }}
                    pre {{ background: #24283b; padding: 1.5rem; border-radius: 0.5rem; overflow-x: auto; font-size: 0.9em; border: 1px solid #414868; color: #c0caf5; }}
                    .error-msg {{ font-size: 1.25rem; font-weight: 600; margin-bottom: 1rem; color: #f7768e; }}
                </style>
            </head>
            <body>
                <h1>500 Internal Server Error</h1>
                <div class="error-msg">{str(e)}</div>
                <pre>{tb}</pre>
            </body>
        </html>
        """, 500
    else:
        return render_template("error.html", error=e) if os.path.exists(os.path.join(app.root_path, 'templates', 'error.html')) else f"""
        <html>
            <head><title>500 Internal Server Error</title></head>
            <body style="font-family: sans-serif; padding: 2rem; text-align: center; background-color: #1a1b26; color: #a9b1d6;">
                <h1 style="color: #f7768e;">500 Internal Server Error</h1>
                <p>An unexpected error occurred. Please contact the administrator.</p>
            </body>
        </html>
        """, 500

@app.errorhandler(Exception)
def handle_exception(e):
    # Pass through HTTP errors
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e

    # Handle non-HTTP exceptions (like 500s)
    import traceback
    logger.error(f"Unhandled exception: {e}", exc_info=True)

    # Only expose traceback in debug mode
    if app.debug:
        tb = traceback.format_exc()
        message = str(e)
    else:
        tb = "Traceback hidden (app.debug is False)"
        message = "An unexpected error occurred."

    # Return JSON for API requests
    if request.path.startswith('/api/') or request.is_json:
        response_data = {
            "error": "Unhandled Exception",
            "message": message
        }
        if app.debug:
            response_data["traceback"] = tb

        return jsonify(response_data), 500

    # Return HTML for browser requests (visible on screen)
    if app.debug:
        return f"""
        <html>
            <head>
                <title>Application Error</title>
                <style>
                    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; padding: 2rem; line-height: 1.5; background-color: #1a1b26; color: #a9b1d6; }}
                    h1 {{ color: #f7768e; border-bottom: 1px solid #414868; padding-bottom: 0.5rem; }}
                    pre {{ background: #24283b; padding: 1.5rem; border-radius: 0.5rem; overflow-x: auto; font-size: 0.9em; border: 1px solid #414868; color: #c0caf5; }}
                    .error-msg {{ font-size: 1.25rem; font-weight: 600; margin-bottom: 1rem; color: #f7768e; }}
                </style>
            </head>
            <body>
                <h1>Unhandled Exception</h1>
                <div class="error-msg">{str(e)}</div>
                <pre>{tb}</pre>
            </body>
        </html>
        """, 500
    else:
        return render_template("error.html", error=e) if os.path.exists(os.path.join(app.root_path, 'templates', 'error.html')) else f"""
        <html>
            <head><title>Application Error</title></head>
            <body style="font-family: sans-serif; padding: 2rem; text-align: center; background-color: #1a1b26; color: #a9b1d6;">
                <h1 style="color: #f7768e;">Application Error</h1>
                <p>An unexpected error occurred. Please contact the administrator.</p>
            </body>
        </html>
        """, 500

# Import Supabase client, auth, and repository system
try:
    from supabase_client import SupabaseClient
    from auth import auth_manager, require_auth, require_admin, get_user_funds, is_admin
    SUPABASE_AVAILABLE = True
except ImportError as e:
    logger.error(f"Failed to import required modules: {e}")
    logger.error("🔔 SOLUTION: Activate the virtual environment first!")
    logger.error("   PowerShell: & '..\\venv\\Scripts\\Activate.ps1'")
    logger.error("   Then run: python app.py")
    SUPABASE_AVAILABLE = False

# Import repository system (optional - only needed for portfolio routes)
try:
    from data.repositories.repository_factory import RepositoryFactory
    REPOSITORY_AVAILABLE = True
except ImportError:
    RepositoryFactory = None
    REPOSITORY_AVAILABLE = False
    logger.debug("Repository system not available (optional for Settings page)")

def get_supabase_client() -> Optional[SupabaseClient]:
    """Get Supabase client instance with user authentication"""
    if not SUPABASE_AVAILABLE:
        return None
    
    try:
        # Get user token from cookies to respect RLS policies
        from flask_auth_utils import get_supabase_access_token
        user_token = get_supabase_access_token()
        
        return SupabaseClient(user_token=user_token) if user_token else SupabaseClient()
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {e}", exc_info=True)
        return None


@app.context_processor
def inject_build_timestamp():
    """Make BUILD_TIMESTAMP available to all templates"""
    build_timestamp = os.getenv("BUILD_TIMESTAMP")
    if build_timestamp:
        # Convert UTC timestamp to user's preferred timezone with 12-hour format
        try:
            from user_preferences import format_timestamp_in_user_timezone
            build_timestamp = format_timestamp_in_user_timezone(build_timestamp, format="%Y-%m-%d %I:%M %p %Z")
        except ImportError:
            # Fallback if user_preferences not available - parse and convert manually
            try:
                from zoneinfo import ZoneInfo
                timestamp_clean = build_timestamp.replace(" UTC", "").strip()
                dt_utc = datetime.strptime(timestamp_clean, "%Y-%m-%d %H:%M")
                dt_utc = dt_utc.replace(tzinfo=ZoneInfo("UTC"))
                dt_pst = dt_utc.astimezone(ZoneInfo("America/Vancouver"))
                build_timestamp = dt_pst.strftime("%Y-%m-%d %I:%M %p %Z")
            except Exception:
                # Final fallback - just replace UTC with PST
                if "UTC" in build_timestamp:
                    build_timestamp = build_timestamp.replace(" UTC", " PST")
    if not build_timestamp:
        # Fallback: generate timestamp in user's timezone (or PST) with 12-hour format
        try:
            from user_preferences import get_user_timezone
            from zoneinfo import ZoneInfo
            user_tz_str = get_user_timezone() or "America/Vancouver"
            user_tz = ZoneInfo(user_tz_str)
            now = datetime.now(user_tz)
            build_timestamp = now.strftime("%Y-%m-%d %I:%M %p %Z")
        except (ImportError, Exception):
            # If zoneinfo not available (Python < 3.9) or other error, use simple format
            build_timestamp = datetime.now().strftime("%Y-%m-%d %I:%M %p")

    return {'build_timestamp': build_timestamp}


@app.template_filter('fmt_date')
def fmt_date_filter(value):
    """Format a datetime for display on the research page.

    Rules:
    - None → 'Unknown Date'
    - datetime with time 00:00:00 → date only  (e.g. '2026-02-09')
    - datetime with real time     → date + HH:MM (e.g. '2026-02-09 19:29')
    - string fallback             → strip microseconds / tz suffix
    """
    if value is None:
        return "Unknown Date"
    if isinstance(value, datetime):
        if value.hour == 0 and value.minute == 0 and value.second == 0:
            return value.strftime("%Y-%m-%d")
        return value.strftime("%Y-%m-%d %H:%M")
    # String fallback — strip microseconds and +00:00
    s = str(value)
    # Remove microseconds  (.123456)
    import re as _re
    s = _re.sub(r'\.\d+', '', s)
    # Remove timezone offset (+00:00 or +00)
    s = _re.sub(r'[+-]\d{2}:\d{2}$', '', s)
    s = _re.sub(r'[+-]\d{2}$', '', s)
    # Remove seconds if they are :00
    s = _re.sub(r':00$', '', s)
    return s.strip()


def get_navigation_context(current_page: str = None) -> Dict[str, Any]:
    """Get navigation context for Flask templates"""
    try:
        from shared_navigation import (
            ensure_flask_sidebar_navigation_links,
            get_navigation_links,
            is_page_migrated,
        )
        from user_preferences import get_user_preference
        from flask_auth_utils import get_user_email_flask

        # Get navigation links (defensive merge for Flask-only migrated pages)
        links = ensure_flask_sidebar_navigation_links(get_navigation_links())
        # Default True: Flask is the primary UI; migrated sidebar links should appear unless
        # the user explicitly opted out (v2_enabled stored as false).
        is_v2_enabled = get_user_preference('v2_enabled', default=True)

        # If we're on a v2 page (current_page is migrated), assume v2 is enabled for navigation
        # This ensures menu is populated when viewing v2 pages
        if current_page and is_page_migrated(current_page):
            is_v2_enabled = True

        # Build navigation context
        # Migrated pages follow v2_enabled (Streamlit vs Flask routing), except sector_insights:
        # that page is Flask-only with no Streamlit fallback — always show when migrated.
        nav_links = []
        for link in links:
            show = True
            if is_page_migrated(link["page"]):
                show = is_v2_enabled
                if link["page"] == "sector_insights":
                    show = True

            url = link["url"]
            if is_page_migrated(link["page"]) and (is_v2_enabled or link["page"] == "sector_insights"):
                url = link["url"]

            nav_links.append({
                'name': link['name'],
                'page': link['page'],
                'url': url,
                'icon': link['icon'],
                'show': show,
                'active': current_page == link['page'],
            })

        # Get available funds for the sidebar selector (Flask-compatible)
        try:
            from flask_data_utils import get_available_funds_flask
            available_funds = get_available_funds_flask()
        except Exception as e:
            logger.warning(f"Could not load available funds: {e}")
            available_funds = []

        # Check if user is admin (actually check the role, not just authentication)
        is_admin_value = False

        try:
            from flask_auth_utils import get_user_id_flask
            from auth import is_admin

            user_id = None
            if hasattr(request, 'user_id') and request.user_id:
                user_id = request.user_id
            else:
                user_id = get_user_id_flask()

            if user_id:
                # Actually check admin status via the is_admin() function
                is_admin_value = is_admin()
        except Exception as e:
            logger.debug(f"Error checking admin status for navigation: {e}")
            is_admin_value = False

        # Get currently selected fund from user preference
        selected_fund = None
        try:
            from user_preferences import get_user_selected_fund
            selected_fund = get_user_selected_fund()
        except Exception:
            pass

        # Determine if "All Funds" is allowed for this page
        # Restrict on pages where aggregate view doesn't make sense or isn't supported
        restricted_all_funds_pages = ['ai_assistant', 'ticker_details']
        allow_all_funds = True

        if current_page in restricted_all_funds_pages:
            allow_all_funds = False

            # If "All Funds" is selected but not allowed, default to first available fund
            # This ensures the selector shows a valid option for the context
            if not selected_fund or str(selected_fund).lower() == 'all':
                if available_funds:
                    selected_fund = available_funds[0]
                else:
                    selected_fund = ""

        # Get scheduler status globally for the menu badge
        scheduler_status = 'stopped'
        try:
            from scheduler.scheduler_core import is_scheduler_running
            if is_scheduler_running():
                scheduler_status = 'running'
        except Exception:
            # Check if we can get status from admin utility as fallback
            try:
                from admin_utils import get_scheduler_status_cached
                status = get_scheduler_status_cached()
                if status and status.get('running'):
                    scheduler_status = 'running'
            except Exception:
                pass

        # Get user theme so base.html can set data-theme on <html>
        user_theme = 'system'
        try:
            from user_preferences import get_user_theme
            user_theme = get_user_theme() or 'system'
        except Exception:
            pass

        impersonation_ctx: Dict[str, Any] = {"impersonating": False}
        try:
            from flask_auth_utils import get_impersonation_banner_context
            impersonation_ctx = get_impersonation_banner_context()
        except Exception:
            pass

        return {
            'navigation_links': nav_links,
            'is_admin': is_admin_value,
            'available_funds': available_funds,
            'selected_fund': selected_fund,
            'allow_all_funds': allow_all_funds,
            'scheduler_status': scheduler_status,
            'current_page': current_page,
            'user_theme': user_theme,
            'impersonation': impersonation_ctx,
        }
    except Exception as e:
        logger.warning(f"Error building navigation context: {e}")
        return {
            'navigation_links': [],
            'is_admin': False,
            'available_funds': [],
            'current_page': None,
            'user_theme': 'system',
            'impersonation': {'impersonating': False},
        }







# Register Blueprints
try:
    from routes.dashboard_routes import dashboard_bp
    app.register_blueprint(dashboard_bp)
    logger.info("✅ Registered Dashboard Blueprint")
except Exception as e:
    logger.error(f"Failed to register Dashboard Blueprint: {e}", exc_info=True)

try:
    from routes.research_routes import research_bp
    app.register_blueprint(research_bp)
    logger.info("✅ Registered Research Blueprint")
except Exception as e:
    logger.error(f"Failed to register Research Blueprint: {e}", exc_info=True)

try:
    from routes.etf_routes import etf_bp
    app.register_blueprint(etf_bp)
    logger.info("✅ Registered ETF Blueprint")
except Exception as e:
    logger.error(f"Failed to register ETF Blueprint: {e}", exc_info=True)

try:
    from routes.social_sentiment_routes import social_sentiment_bp
    app.register_blueprint(social_sentiment_bp)
    logger.info("✅ Registered Social Sentiment Blueprint")
except Exception as e:
    logger.error(f"Failed to register Social Sentiment Blueprint: {e}", exc_info=True)

try:
    from routes.signals_routes import signals_bp
    app.register_blueprint(signals_bp)
    logger.info("✅ Registered Signals Blueprint")
except Exception as e:
    logger.error(f"Failed to register Signals Blueprint: {e}", exc_info=True)

try:
    from routes.fund_routes import fund_bp
    app.register_blueprint(fund_bp, url_prefix='/api/v2')
    logger.info("✅ Registered Fund Blueprint")
except Exception as e:
    logger.error(f"Failed to register Fund Blueprint: {e}", exc_info=True)

try:
    from routes.admin_routes import admin_bp
    app.register_blueprint(admin_bp)
    logger.info("✅ Registered Admin Blueprint")
except Exception as e:
    logger.error(f"Failed to register Admin Blueprint: {e}", exc_info=True)

try:
    from routes.color_test_routes import color_test_bp
    app.register_blueprint(color_test_bp)
    logger.info("✅ Registered Color Test Blueprint")
except Exception as e:
    logger.error(f"Failed to register Color Test Blueprint: {e}", exc_info=True)

try:
    from routes.ai_routes import ai_bp
    app.register_blueprint(ai_bp)
    logger.info("✅ Registered AI Blueprint")
except Exception as e:
    logger.error(f"Failed to register AI Blueprint: {e}", exc_info=True)

try:
    from routes.digest_routes import digest_bp
    app.register_blueprint(digest_bp)
    logger.info("Registered Digest Blueprint")
except Exception as e:
    logger.error(f"Failed to register Digest Blueprint: {e}", exc_info=True)

# Auto-start scheduler on module load (not waiting for first request)
def _start_scheduler_background():
    """Start scheduler in background thread on Flask app initialization."""
    import threading
    import os
    from scheduler.scheduler_core import start_scheduler, is_scheduler_running

    # Global reference to keep thread alive
    _scheduler_thread = None

    def _scheduler_init_thread():
        global _scheduler_thread
        thread_name = threading.current_thread().name
        thread_id = threading.current_thread().ident
        process_id = os.getpid() if hasattr(os, 'getpid') else 'N/A'

        import sys
        import time

        # Log to both logger and stderr for maximum visibility
        def log_both(level, msg):
            """Log to both logger and stderr for visibility even if logging system fails"""
            print(f"[SCHEDULER-INIT] {msg}", file=sys.stderr, flush=True)
            try:
                if level == 'info':
                    logger.info(f"[PID:{process_id} TID:{thread_id}] {msg}")
                elif level == 'error':
                    logger.error(f"[PID:{process_id} TID:{thread_id}] {msg}")
                elif level == 'warning':
                    logger.warning(f"[PID:{process_id} TID:{thread_id}] {msg}")
                elif level == 'debug':
                    logger.debug(f"[PID:{process_id} TID:{thread_id}] {msg}")
            except:
                pass  # If logger fails, at least stderr worked

        try:
            log_both('info', f"[{thread_name}] Starting scheduler initialization...")

            # Retry configuration
            MAX_RETRIES = 3
            RETRY_DELAYS = [0.5, 2.0, 5.0]  # Exponential backoff

            for attempt in range(MAX_RETRIES):
                try:
                    # Wait before attempting (increases with each retry)
                    delay = RETRY_DELAYS[attempt]
                    log_both('info', f"Attempt {attempt + 1}/{MAX_RETRIES}: Waiting {delay}s for Flask initialization...")
                    time.sleep(delay)

                    # Check if scheduler is already running (cross-process check)
                    # On first attempt, be more aggressive - we just cleared stale heartbeat files,
                    # so only trust heartbeat on subsequent attempts where another process might have started it
                    if attempt > 0 and is_scheduler_running():
                        log_both('info', "✅ Scheduler already running (detected via heartbeat), skipping auto-start")
                        break

                    # Attempt to start scheduler
                    log_both('info', f"🚀 Attempting to start scheduler (attempt {attempt + 1}/{MAX_RETRIES})...")
                    result = start_scheduler()

                    if result:
                        log_both('info', "✅ start_scheduler() returned True")

                        # HEALTH CHECK: Verify scheduler is actually running
                        log_both('info', "Verifying scheduler health...")
                        time.sleep(2)  # Wait for scheduler to initialize jobs

                        # Check 1: Verify scheduler reports running
                        if not is_scheduler_running():
                            log_both('error', "❌ Health check failed: is_scheduler_running() returned False after startup")
                            if attempt < MAX_RETRIES - 1:
                                log_both('warning', f"Will retry in {RETRY_DELAYS[attempt + 1]}s...")
                                continue
                            else:
                                log_both('error', "❌ All retries exhausted - scheduler failed health check")
                                break

                        # Check 2: Verify heartbeat file is being updated
                        from scheduler.scheduler_core import _HEARTBEAT_FILE, _check_heartbeat
                        if _HEARTBEAT_FILE.exists():
                            heartbeat_age = time.time() - float(_HEARTBEAT_FILE.read_text().strip())
                            if heartbeat_age > 30:
                                log_both('warning', f"⚠️ Heartbeat file is stale ({heartbeat_age:.1f}s old)")
                            else:
                                log_both('info', f"✅ Heartbeat file is fresh ({heartbeat_age:.1f}s old)")
                        else:
                            log_both('warning', "⚠️ Heartbeat file does not exist yet (may update soon)")

                        # Success!
                        log_both('info', "=" * 60)
                        log_both('info', "✅ SCHEDULER STARTED SUCCESSFULLY ON FLASK INITIALIZATION")
                        log_both('info', "=" * 60)
                        break
                    else:
                        # start_scheduler() returned False — check why before deciding severity
                        if is_scheduler_running():
                            # Another worker/process already owns the scheduler — this is normal
                            log_both('info', "✅ Scheduler already running in another process — startup deferred")
                            break

                        # Genuine failure: no process has the scheduler running
                        log_both('warning', f"⚠️ start_scheduler() returned False on attempt {attempt + 1} and scheduler is not running anywhere")
                        if attempt < MAX_RETRIES - 1:
                            log_both('warning', f"Will retry in {RETRY_DELAYS[attempt + 1]}s...")
                        else:
                            log_both('error', "❌ All retries exhausted - scheduler failed to start")
                            log_both('error', "Check logs above for errors. You can start manually via Jobs page.")

                except Exception as e:
                    log_both('error', f"❌ Exception during scheduler start attempt {attempt + 1}: {e}")
                    import traceback
                    traceback.print_exc(file=sys.stderr)

                    if attempt < MAX_RETRIES - 1:
                        log_both('warning', f"Will retry in {RETRY_DELAYS[attempt + 1]}s...")
                    else:
                        log_both('error', "❌ All retries exhausted due to exceptions")
                        log_both('error', "⚠️ Flask will continue without scheduler - start manually via Jobs page")

            log_both('info', f"[{thread_name}] Scheduler initialization complete")

            # CRITICAL: Thread stays alive to execute scheduler jobs.
            # Also watches for scheduler death and attempts recovery every 90s.
            sleep_count = 0
            while True:
                sleep_count += 1
                time.sleep(90)
                if not is_scheduler_running():
                    log_both('warning', f"⚠️ Scheduler not running (cycle {sleep_count}) — attempting recovery...")
                    try:
                        recovery_result = start_scheduler()
                        if recovery_result:
                            log_both('info', "✅ Scheduler recovered successfully")
                        elif is_scheduler_running():
                            log_both('info', "✅ Scheduler running (started by another process)")
                        else:
                            log_both('error', "❌ Recovery attempt failed — will retry next cycle")
                    except Exception as rec_exc:
                        log_both('error', f"❌ Recovery exception: {rec_exc}")
                else:
                    logger.debug(f"[PID:{process_id} TID:{thread_id}] [{thread_name}] Scheduler alive (cycle {sleep_count})")

        except Exception as e:
            # Catch-all for any unexpected errors
            log_both('error', f"❌ CRITICAL: Unexpected error in scheduler init thread: {e}")
            import traceback
            traceback.print_exc(file=sys.stderr)
            log_both('error', "⚠️ Flask will continue without scheduler - start manually via jobs page")

    # Start scheduler in NON-daemon thread (keeps it alive for job execution)
    process_id = os.getpid() if hasattr(os, 'getpid') else 'N/A'
    _scheduler_thread = threading.Thread(
        target=_scheduler_init_thread,
        name="SchedulerInitThread",
        daemon=False  # Non-daemon: thread stays alive to run scheduler jobs
    )
    _scheduler_thread.start()
    logger.debug(f"[PID:{process_id}] Started scheduler initialization thread (non-daemon - keeps alive)")

# Start scheduler immediately when module loads
# Runtime mode:
# - embedded (default): web process can auto-start scheduler unless DISABLE_SCHEDULER=true
# - external: scheduler is expected to run in a dedicated worker process
scheduler_runtime_mode = os.environ.get("SCHEDULER_RUNTIME_MODE", "embedded").lower()
if scheduler_runtime_mode == "embedded" and os.environ.get('DISABLE_SCHEDULER', '').lower() != 'true':
    # Always attempt startup in embedded mode.
    #
    # Duplicate protection is handled in scheduler_core.start_scheduler() via:
    # - process-local lock
    # - cross-process startup lock
    # - heartbeat detection
    #
    # Relying on WERKZEUG_RUN_MAIN here can incorrectly suppress scheduler startup in
    # non-Werkzeug runtimes (or after restarts), leaving all jobs stale.
    # Clear stale heartbeat so this fresh process doesn't incorrectly defer to a dead one.
    # (Werkzeug reloader kills the child and spawns a new one — the old heartbeat can be
    # up to _HEARTBEAT_TIMEOUT seconds "valid" even though the scheduler is gone.)
    try:
        from scheduler.scheduler_core import _HEARTBEAT_FILE, _HEARTBEAT_TIMEOUT
        import time as _time
        if _HEARTBEAT_FILE.exists():
            _hb_age = _time.time() - float(_HEARTBEAT_FILE.read_text().strip())
            if _hb_age > _HEARTBEAT_TIMEOUT:
                _HEARTBEAT_FILE.unlink()
                logger.info(f"Cleared stale scheduler heartbeat on startup (age: {_hb_age:.1f}s)")
    except Exception:
        pass

    _existing_threads = [t.name for t in threading.enumerate()]
    if "SchedulerInitThread" not in _existing_threads:
        _start_scheduler_background()
    else:
        logger.debug("ℹ️ SchedulerInitThread already running, skipping duplicate start")
else:
    if scheduler_runtime_mode != "embedded":
        logger.info(
            "ℹ️ Scheduler auto-start disabled in web process "
            f"(SCHEDULER_RUNTIME_MODE={scheduler_runtime_mode})"
        )
    else:
        logger.info("ℹ️ Scheduler auto-start disabled via DISABLE_SCHEDULER environment variable")

# Register shutdown handler to gracefully stop scheduler on Flask exit
# This prevents RuntimeError during Flask restarts/reloads
import atexit
def _shutdown_scheduler_on_exit():
    """Gracefully shutdown scheduler when Flask exits"""
    try:
        from scheduler.scheduler_core import shutdown_scheduler, is_scheduler_running
        if is_scheduler_running():
            logger.info("🛑 Flask shutting down - stopping scheduler gracefully...")
            shutdown_scheduler()
            logger.info("✅ Scheduler stopped successfully")
    except Exception as e:
        logger.warning(f"Error during scheduler shutdown: {e}")

atexit.register(_shutdown_scheduler_on_exit)

def load_portfolio_data(fund_name=None) -> Dict:
    """Load and process portfolio data from Supabase (using flask_data_utils)"""
    try:
        from flask_data_utils import (
            get_current_positions_flask,
            get_trade_log_flask,
            get_cash_balances_flask,
            get_available_funds_flask
        )

        # Get available funds first
        available_funds = get_available_funds_flask()

        # Default to first fund if not specified
        if not fund_name and available_funds:
            fund_name = available_funds[0]

        # Load data components using modern utils (parallelized)
        # Use ThreadPoolExecutor to fetch independent data components concurrently
        # reducing total latency from sum(t1,t2,t3) to max(t1,t2,t3)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            # Wrap functions to preserve request context (required for cookies/auth access)
            @copy_current_request_context
            def fetch_positions():
                return get_current_positions_flask(fund=fund_name)

            @copy_current_request_context
            def fetch_trades():
                return get_trade_log_flask(limit=500, fund=fund_name)

            @copy_current_request_context
            def fetch_cash():
                return get_cash_balances_flask(fund=fund_name)

            # Submit tasks
            future_portfolio = executor.submit(fetch_positions)
            future_trades = executor.submit(fetch_trades)
            future_cash = executor.submit(fetch_cash)

            # Gather results (blocking until all complete)
            portfolio_df = future_portfolio.result()
            trades_df = future_trades.result()
            cash_balances = future_cash.result()

        return {
            "portfolio": portfolio_df,
            "trades": trades_df,
            "cash_balances": cash_balances,
            "available_funds": available_funds,
            "current_fund": fund_name,
            "error": None
        }
    except Exception as e:
        logger.error(f"Error loading portfolio data: {e}", exc_info=True)
        return {
            "portfolio": pd.DataFrame(),
            "trades": pd.DataFrame(),
            "cash_balances": {"CAD": 0.0, "USD": 0.0},
            "available_funds": [],
            "current_fund": None,
            "error": str(e)
        }

def calculate_performance_metrics(portfolio_df: pd.DataFrame, trade_df: pd.DataFrame, fund_name=None) -> Dict:
    """Calculate key performance metrics for a specific fund or all funds"""
    try:
        # Optimization: Use passed DataFrames if available to avoid redundant DB fetch
        # This saves ~100-300ms per request by avoiding fetching positions/trades twice
        if not portfolio_df.empty:
            # Market Value
            if 'market_value' in portfolio_df.columns:
                total_value = portfolio_df['market_value'].sum()
            elif 'total_market_value' in portfolio_df.columns:
                total_value = portfolio_df['total_market_value'].sum()
            elif 'total_value' in portfolio_df.columns:
                total_value = portfolio_df['total_value'].sum()
            elif 'Total Value' in portfolio_df.columns:
                # Old CSV format
                current_positions = portfolio_df[portfolio_df.get('Total Value', 0) > 0]
                total_value = current_positions.get('Total Value', pd.Series([0])).sum()
            else:
                # Fallback calculation
                total_value = (portfolio_df.get('shares', 0) * portfolio_df.get('price', 0)).sum()

            # Cost Basis
            if 'cost_basis' in portfolio_df.columns:
                total_cost_basis = portfolio_df['cost_basis'].sum()
            elif 'total_cost_basis' in portfolio_df.columns:
                total_cost_basis = portfolio_df['total_cost_basis'].sum()
            elif 'Cost Basis' in portfolio_df.columns:
                current_positions = portfolio_df[portfolio_df.get('Total Value', 0) > 0]
                total_cost_basis = current_positions.get('Cost Basis', pd.Series([0])).sum()
            else:
                total_cost_basis = 0

            # Unrealized PnL
            if 'unrealized_pnl' in portfolio_df.columns:
                unrealized_pnl = portfolio_df['unrealized_pnl'].sum()
            elif 'total_pnl' in portfolio_df.columns:
                unrealized_pnl = portfolio_df['total_pnl'].sum()
            elif 'pnl' in portfolio_df.columns:
                unrealized_pnl = portfolio_df['pnl'].sum()
            elif 'PnL' in portfolio_df.columns:
                current_positions = portfolio_df[portfolio_df.get('Total Value', 0) > 0]
                unrealized_pnl = current_positions.get('PnL', pd.Series([0])).sum()
            else:
                unrealized_pnl = 0

            performance_pct = (unrealized_pnl / total_cost_basis * 100) if total_cost_basis > 0 else 0

            # Trade statistics
            if not trade_df.empty:
                total_trades = len(trade_df)
                if 'pnl' in trade_df.columns:
                    winning_trades = len(trade_df[trade_df['pnl'] > 0])
                    losing_trades = len(trade_df[trade_df['pnl'] < 0])
                elif 'PnL' in trade_df.columns:
                    winning_trades = len(trade_df[trade_df.get('PnL', 0) > 0])
                    losing_trades = len(trade_df[trade_df.get('PnL', 0) < 0])
                else:
                    winning_trades = 0
                    losing_trades = 0
            else:
                total_trades = winning_trades = losing_trades = 0

            return {
                "total_value": round(float(total_value), 2),
                "total_cost_basis": round(float(total_cost_basis), 2),
                "unrealized_pnl": round(float(unrealized_pnl), 2),
                "performance_pct": round(float(performance_pct), 2),
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades
            }

        # Fallback to Supabase fetch if DataFrame is empty
        client = get_supabase_client()
        if client and fund_name:
            # Get metrics for specific fund
            positions = client.get_current_positions(fund=fund_name)
            trades = client.get_trade_log(limit=1000, fund=fund_name)

            # Use correct column names from latest_positions view
            total_value = sum(float(pos.get("market_value", 0) or 0) for pos in positions)
            total_cost_basis = sum(float(pos.get("cost_basis", 0) or 0) for pos in positions)
            unrealized_pnl = sum(float(pos.get("unrealized_pnl", 0) or 0) for pos in positions)
            performance_pct = (unrealized_pnl / total_cost_basis * 100) if total_cost_basis > 0 else 0

            total_trades = len(trades)
            winning_trades = len([t for t in trades if t["pnl"] > 0])
            losing_trades = len([t for t in trades if t["pnl"] < 0])

            return {
                "total_value": round(total_value, 2),
                "total_cost_basis": round(total_cost_basis, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "performance_pct": round(performance_pct, 2),
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades
            }
        elif client:
            # Use Supabase client for combined metrics (legacy)
            return client.get_performance_metrics()

        return {
            "total_value": 0,
            "total_cost_basis": 0,
            "unrealized_pnl": 0,
            "performance_pct": 0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0
        }
    except Exception as e:
        logger.error(f"Error calculating performance metrics: {e}", exc_info=True)
        return {
            "total_value": 0,
            "total_cost_basis": 0,
            "unrealized_pnl": 0,
            "performance_pct": 0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0
        }

def create_performance_chart(portfolio_df: pd.DataFrame, fund_name: Optional[str] = None) -> str:
    """Create a Plotly performance chart"""
    try:
        client = get_supabase_client()
        if client:
            # Use Supabase for chart data, filtered by fund
            daily_data = client.get_daily_performance_data(days=30, fund=fund_name)
            if not daily_data:
                return json.dumps({})

            df = pd.DataFrame(daily_data)
        else:
            # Fallback to local calculation
            if portfolio_df.empty:
                return json.dumps({})

            # Load exchange rates for currency conversion
            from utils.currency_converter import load_exchange_rates, convert_usd_to_cad, is_us_ticker
            from decimal import Decimal

            # Load exchange rates from common location (USD/CAD rates apply to all funds)
            exchange_rates_path = Path("trading_data/exchange_rates")
            if not exchange_rates_path.exists():
                # Fallback: try to find exchange rates in any fund directory
                funds_dir = Path("trading_data/funds")
                exchange_rates_path = None
                for fund_dir in funds_dir.iterdir():
                    if fund_dir.is_dir():
                        potential_path = fund_dir
                        if (potential_path / "exchange_rates.json").exists():
                            exchange_rates_path = potential_path
                            break
                if not exchange_rates_path:
                    exchange_rates_path = Path("trading_data/funds/Project Chimera")  # Final fallback

            exchange_rates = load_exchange_rates(exchange_rates_path)

            # Group by date and calculate daily totals
            daily_totals = []
            for date, group in portfolio_df.groupby(portfolio_df['Date'].dt.date):
                current_positions = group[group['Total Value'] > 0]
                if not current_positions.empty:
                    # Calculate totals with proper currency conversion
                    total_value_cad = Decimal('0')
                    total_cost_basis_cad = Decimal('0')

                    # Bolt Performance Optimization:
                    # Replacing slow iterrows() with itertuples(name=None) and pre-computed indices.
                    # This avoids Pandas creating a new Series object per row, reducing O(M*N) overhead by 10-100x.
                    ticker_idx = current_positions.columns.get_loc('Ticker')
                    val_idx = current_positions.columns.get_loc('Total Value')
                    cost_idx = current_positions.columns.get_loc('Cost Basis')

                    for pos in current_positions.itertuples(index=False, name=None):
                        ticker = pos[ticker_idx]
                        value = Decimal(str(pos[val_idx]))
                        cost_basis = Decimal(str(pos[cost_idx]))

                        # Convert USD to CAD if needed
                        if is_us_ticker(ticker):
                            value_cad = convert_usd_to_cad(value, exchange_rates)
                            cost_basis_cad = convert_usd_to_cad(cost_basis, exchange_rates)
                        else:
                            value_cad = value
                            cost_basis_cad = cost_basis

                        total_value_cad += value_cad
                        total_cost_basis_cad += cost_basis_cad

                    # Convert back to float for compatibility
                    total_value = float(total_value_cad)
                    total_cost_basis = float(total_cost_basis_cad)
                    performance_pct = ((total_value - total_cost_basis) / total_cost_basis * 100) if total_cost_basis > 0 else 0

                    daily_totals.append({
                        'date': date,
                        'value': total_value,
                        'cost_basis': total_cost_basis,
                        'performance_pct': performance_pct
                    })

            if not daily_totals:
                return json.dumps({})

            # Create DataFrame and sort by date
            df = pd.DataFrame(daily_totals).sort_values('date')
            df['performance_index'] = df['performance_pct'] + 100

        # Create Plotly chart
        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=df['date'],
            y=df['performance_index'],
            mode='lines+markers',
            name='Portfolio Performance',
            line=dict(color='#2E86AB', width=3),
            marker=dict(size=6)
        ))

        # Add break-even line
        fig.add_hline(y=100, line_dash="dash", line_color="gray",
                     annotation_text="Break-even", annotation_position="bottom right")

        fig.update_layout(
            title="Portfolio Performance Over Time",
            xaxis_title="Date",
            yaxis_title="Performance Index (100 = Break-even)",
            hovermode='x unified',
            template='plotly_white',
            height=500
        )

        from plotly_utils import serialize_plotly_figure
        return serialize_plotly_figure(fig)

    except Exception as e:
        logger.error(f"Error creating performance chart: {e}", exc_info=True)
        return json.dumps({})

# Fallback route for dashboard if blueprint registration fails
# This prevents 404 errors and provides helpful error info
@app.route('/dashboard')
def dashboard_fallback():
    """Fallback route when dashboard blueprint fails to register"""
    return f"""
    <html>
        <head>
            <title>Dashboard Unavailable</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                    padding: 2rem;
                    line-height: 1.6;
                    background: #f9fafb;
                }}
                .container {{
                    max-width: 600px;
                    margin: 2rem auto;
                    background: white;
                    padding: 2rem;
                    border-radius: 8px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                }}
                h1 {{
                    color: #dc2626;
                    margin-top: 0;
                    border-bottom: 2px solid #fee2e2;
                    padding-bottom: 0.5rem;
                }}
                .error-icon {{
                    font-size: 3rem;
                    margin-bottom: 1rem;
                }}
                .info {{
                    background: #eff6ff;
                    border-left: 4px solid #3b82f6;
                    padding: 1rem;
                    margin: 1rem 0;
                }}
                .actions {{
                    margin-top: 1.5rem;
                }}
                .action-link {{
                    display: inline-block;
                    padding: 0.5rem 1rem;
                    background: #3b82f6;
                    color: white;
                    text-decoration: none;
                    border-radius: 4px;
                    margin-right: 0.5rem;
                }}
                .action-link:hover {{
                    background: #2563eb;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="error-icon">⚠️</div>
                <h1>Dashboard Unavailable</h1>
                <p>The dashboard route failed to initialize due to a code error.</p>

                <div class="info">
                    <strong>What this means:</strong><br>
                    The dashboard routes are currently unavailable because an error occurred during initialization.
                    This is typically caused by an import error, missing dependency, or runtime error in the code.
                </div>

                <p><strong>What to do:</strong></p>
                <ul>
                    <li>Check the server logs for detailed error information</li>
                    <li>Review recent code changes for syntax or import errors</li>
                    <li>Ensure all required dependencies are installed</li>
                    <li>Try restarting the Flask server</li>
                </ul>

                <div class="actions">
                    <a href="/" class="action-link">Go to Home</a>
                    <a href="/auth" class="action-link">Login Page</a>
                </div>
            </div>
        </body>
    </html>
    """, 503  # Service Unavailable (more appropriate than 404 or 500)


# Root route - redirect to dashboard or auth
@app.route('/')
def index():
    """Redirect to dashboard if authenticated, otherwise to auth page"""
    try:
        from flask_auth_utils import get_auth_token, get_refresh_token
        import base64
        import json as json_lib
        import time

        from flask_auth_utils import get_supabase_access_token
        auth_token = get_supabase_access_token()
        session_token = request.cookies.get('session_token')
        refresh_token = get_refresh_token()

        # Don't delete cookies in root route - just check authentication
        # Check if auth_token is missing or expired, try to refresh if we have refresh_token
        if not auth_token and refresh_token:
            # Missing auth_token but have refresh_token - try to refresh
            from flask_auth_utils import refresh_token_if_needed_flask
            success, new_token, new_refresh, expires_in = refresh_token_if_needed_flask()
            if success and new_token:
                # Refresh succeeded - redirect with new cookies
                is_production = (
                    os.getenv("FLASK_ENV") == "production" or
                    os.getenv("APP_DOMAIN") is not None or
                    request.headers.get('X-Forwarded-Proto') == 'https' or
                    request.is_secure
                )
                samesite_value = 'Lax'
                response = redirect(url_for('dashboard.dashboard_page'))
                response.set_cookie('auth_token', new_token, max_age=expires_in or 3600, httponly=True, secure=is_production, samesite=samesite_value, path='/')
                if new_refresh:
                    response.set_cookie('refresh_token', new_refresh, max_age=86400*30, httponly=True, secure=is_production, samesite=samesite_value, path='/')
                return response

        # Check if auth_token exists and is expired, try to refresh
        if auth_token:
            try:
                token_parts = auth_token.split('.')
                if len(token_parts) >= 2:
                    payload = token_parts[1]
                    payload += '=' * (4 - len(payload) % 4)
                    decoded = base64.urlsafe_b64decode(payload)
                    user_data = json_lib.loads(decoded)
                    exp = user_data.get('exp', 0)
                    if exp > 0 and exp < time.time():
                        # Token expired - try to refresh
                        from flask_auth_utils import refresh_token_if_needed_flask
                        success, new_token, new_refresh, expires_in = refresh_token_if_needed_flask()
                        if success and new_token:
                            # Refresh succeeded - redirect with new cookies
                            is_production = (
                                os.getenv("FLASK_ENV") == "production" or
                                os.getenv("APP_DOMAIN") is not None or
                                request.headers.get('X-Forwarded-Proto') == 'https' or
                                request.is_secure
                            )
                            # Use SameSite=Lax for same-site requests
                            samesite_value = 'Lax'
                            response = redirect(url_for('dashboard.dashboard_page'))
                            response.set_cookie('auth_token', new_token, max_age=expires_in or 3600, httponly=True, secure=is_production, samesite=samesite_value, path='/')
                            if new_refresh:
                                response.set_cookie('refresh_token', new_refresh, max_age=86400*30, httponly=True, secure=is_production, samesite=samesite_value, path='/')
                            return response
                        else:
                            # Refresh failed - token expired and can't refresh
                            # Don't delete cookies - just continue to auth check below
                            logger.warning("[AUTH] Token expired and refresh failed, will redirect to auth")
            except Exception as e:
                logger.warning(f"[AUTH] Error checking auth_token: {e}, will continue to auth check")

        # Check if we have a valid auth_token (required for proper Supabase auth)
        # Also accept session_token as fallback for legacy compatibility
        is_authenticated = False
        token_to_check = auth_token or session_token

        if token_to_check:
            try:
                token_parts = token_to_check.split('.')
                if len(token_parts) >= 2:
                    payload = token_parts[1]
                    payload += '=' * (4 - len(payload) % 4)
                    decoded = base64.urlsafe_b64decode(payload)
                    user_data = json_lib.loads(decoded)
                    exp = user_data.get('exp', 0)
                    # Token is valid if it exists and hasn't expired
                    is_authenticated = exp == 0 or exp > time.time()
            except Exception as e:
                logger.warning(f"[AUTH] Error parsing token in root route: {e}")
                pass

        if is_authenticated:
            logger.info("[AUTH] Root route: User authenticated, redirecting to dashboard")
            return redirect(url_for('dashboard.dashboard_page'))
        else:
            # Serve a stub that preserves URL hash before redirecting to /auth.
            # Supabase may redirect password-reset to Site URL (root) with tokens in the hash;
            # a 302 to /auth would drop the hash, so we send hash-holding users to auth_callback.
            # To have reset links land on the callback directly: Supabase Dashboard → Auth →
            # Email Templates → Recovery: use {{ .RedirectTo }} in the verify link (not SiteURL).
            logger.info("[AUTH] Root route: User not authenticated, serving auth redirect stub")
            return Response(
                """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Redirecting...</title></head>
<body><p>Redirecting...</p>
<script>
(function(){
  var h = window.location.hash;
  if (h && (h.indexOf('access_token=') !== -1 || h.indexOf('error=') !== -1)) {
    window.location.replace('/auth_callback.html' + h);
  } else {
    window.location.replace('/auth');
  }
})();
</script>
</body></html>""",
                mimetype="text/html",
                status=200,
            )
    except Exception as e:
        logger.error(f"Error in root route: {e}", exc_info=True)
        # On error, just redirect to auth - don't delete cookies
        # Cookies might be valid, error might be unrelated to auth
        return redirect('/auth')

@app.route('/auth')
def auth_page():
    """Authentication page. Passes auth config so client can call Supabase directly for
    password reset (avoids Supabase's Cloudflare blocking server-originated requests)."""
    app_domain = os.getenv("APP_DOMAIN")
    supabase_url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    anon_key = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    auth_config = {}
    if app_domain and supabase_url and anon_key:
        auth_config = {
            "supabase_url": supabase_url,
            "supabase_anon_key": anon_key,
            "reset_redirect_url": f"https://{app_domain}/auth_callback.html?type=recovery",
            "magic_link_redirect_url": f"https://{app_domain}/auth_callback.html",
        }
    return render_template("auth.html", auth_config=auth_config)


@app.route('/auth_callback.html')
def auth_callback_page():
    """Serve Supabase auth callback helper (magic links + password reset)."""
    return app.send_static_file('auth_callback.html')


@app.route('/set_cookie.html')
def set_cookie_page():
    """Serve cookie-setting helper (used by Streamlit auth flow)."""
    return app.send_static_file('set_cookie.html')


@app.route('/login.html')
def login_page():
    """Serve login helper page for browser automation."""
    return app.send_static_file('login.html')

@app.route('/auth/debug')
def auth_debug():
    """Unauthenticated debug endpoint to check token state"""
    import base64
    import json as json_lib
    import time

    auth_token = request.cookies.get('auth_token')
    session_token = request.cookies.get('session_token')
    refresh_token = request.cookies.get('refresh_token')

    def decode_token_safe(token):
        if not token:
            return None
        try:
            parts = token.split('.')
            if len(parts) < 2:
                return {"valid": False, "error": "Invalid JWT format"}
            payload = parts[1]
            payload += '=' * (4 - len(payload) % 4)
            decoded = base64.urlsafe_b64decode(payload)
            data = json_lib.loads(decoded)
            # Only return expiry status, not the payload
            exp = data.get('exp', 0)
            is_expired = False
            if exp:
                now = int(time.time())
                is_expired = exp < now

            return {
                "valid": True,
                "expired": is_expired,
                "has_exp": bool(exp)
            }
        except Exception as e:
            return {"valid": False, "error": str(e)}

    return jsonify({
        "auth_token": {
            "present": bool(auth_token),
            "length": len(auth_token) if auth_token else 0,
            "status": decode_token_safe(auth_token)
        },
        "session_token": {
            "present": bool(session_token),
            "length": len(session_token) if session_token else 0,
            "status": decode_token_safe(session_token)
        },
        "refresh_token": {
            "present": bool(refresh_token),
            "length": len(refresh_token) if refresh_token else 0
        },
        "server_time": int(time.time()),
        "server_time_human": time.strftime('%Y-%m-%d %H:%M:%S')
    })

@app.route('/api/auth/login', methods=['POST'])
@rate_limit(limit=5, period=60)
def login():
    """Handle user login"""
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')

        if not email or not password:
            return jsonify({"error": "Email and password required"}), 400

        # Authenticate with Supabase
        response = requests.post(
            f"{os.getenv('SUPABASE_URL')}/auth/v1/token?grant_type=password",
            headers={
                "apikey": os.getenv("SUPABASE_PUBLISHABLE_KEY"),
                "Content-Type": "application/json"
            },
            json={
                "email": email,
                "password": password
            },
            timeout=30
        )

        logger.info(f"Login attempt for {email}: Status {response.status_code}")
        if response.status_code != 200:
            # Log failure but avoid dumping full response body if it's large or sensitive
            try:
                error_body = response.json()
                logger.error(f"Login failed: {error_body.get('msg', 'Unknown error')} ({error_body.get('error_code', 'no_code')})")
            except Exception:
                logger.error(f"Login failed (raw): {response.text[:200]}")

        if response.status_code == 200:
            auth_data = response.json()
            # DEBUG: Log what Supabase actually returns (for debugging refresh_token issues)
            logger.info(f"[LOGIN DEBUG] Supabase response keys: {list(auth_data.keys())}")
            if 'refresh_token' in auth_data:
                logger.info(f"[LOGIN DEBUG] refresh_token length from Supabase: {len(auth_data['refresh_token'])}")
                logger.info(f"[LOGIN DEBUG] refresh_token preview: {auth_data['refresh_token'][:50]}...")
            else:
                logger.warning("[LOGIN DEBUG] refresh_token NOT in Supabase response!")

            user_id = auth_data["user"]["id"]

            # Create session token
            session_token = auth_manager.create_user_session(user_id, email)

            # Create response with cookie
            response = jsonify({
                "token": session_token,
                "user": {
                    "id": user_id,
                    "email": email
                }
            })

            # Set the session token as a cookie (Flask legacy)
            # Use secure cookies for production (HTTPS), allow non-secure for local dev (HTTP)
            # Behind a reverse proxy, request.is_secure is False even on HTTPS
            # Check multiple indicators: FLASK_ENV, APP_DOMAIN (production has this set), or X-Forwarded-Proto header
            # Determine if we're in production/HTTPS environment
            # CRITICAL: If X-Forwarded-Proto is https, we MUST use secure cookies
            x_forwarded_proto = request.headers.get('X-Forwarded-Proto', '').lower()
            is_https = x_forwarded_proto == 'https' or request.is_secure
            has_app_domain = bool(os.getenv("APP_DOMAIN"))
            is_production_env = os.getenv("FLASK_ENV") == "production"

            is_production = is_production_env or has_app_domain or is_https

            # CRITICAL: Always use secure=True if we detect HTTPS (even if is_production is False)
            # Browsers will reject cookies with secure=False on HTTPS sites
            use_secure = is_https or is_production

            # Use SameSite=Lax for same-site requests (works for both production and dev)
            # SameSite=None is only needed for cross-origin requests and requires Secure=True
            # Since we're on the same domain, Lax is the correct choice
            samesite_value = 'Lax'

            response.set_cookie(
                'session_token',
                session_token,
                max_age=86400,
                httponly=True,
                secure=use_secure,  # True for HTTPS, False for localhost HTTP
                samesite=samesite_value,
                path='/'
            )

            # Set the auth token as a cookie (Streamlit/Supabase compatible)
            # This is the REAL Supabase access token required for RLS and auth.uid()
            if "access_token" in auth_data:
                # Default Supabase expiry is 3600s (1 hour)
                expires_in = auth_data.get("expires_in", 3600)

                response.set_cookie(
                    'auth_token',
                    auth_data["access_token"],
                    max_age=expires_in,
                    httponly=True,
                    secure=use_secure,
                    samesite=samesite_value,
                    path='/'
                )

                # Also set refresh token if available so client can refresh if needed
                if "refresh_token" in auth_data:
                    response.set_cookie(
                        'refresh_token',
                        auth_data["refresh_token"],
                        max_age=86400 * 30, # 30 days usually
                        httponly=True,
                        secure=use_secure,
                        samesite=samesite_value,
                        path='/'
                    )

            return response
        else:
            error_data = response.json() if response.text else {}
            error_code = error_data.get("error_code", "")
            error_msg = error_data.get("msg", "Invalid credentials")

            # Handle specific error cases
            if error_code == "email_not_confirmed":
                return jsonify({"error": "Please check your email and click the confirmation link before logging in."}), 401

            # For all other auth errors (invalid_credentials, user_not_found, etc.), return generic message
            # to prevent user enumeration
            logger.warning(f"Login failed for {email}: {error_code} - {error_msg}")
            return jsonify({"error": "Invalid email or password."}), 401

    except Exception as e:
        logger.error(f"Login error: {e}", exc_info=True)
        import traceback
        return jsonify({"error": "Login failed", "message": str(e), "traceback": traceback.format_exc()}), 500

@app.route('/api/debug/cookies')
@require_admin
def debug_cookies():
    """
    Debug endpoint to inspect cookies received by the server.

    Security Note: This endpoint returns all cookies including HttpOnly cookies.
    This is safe because:
    1. Admin-only access: Protected by @require_admin decorator
    2. Returns user's own cookies: Only echoes back cookies the authenticated admin sent
    3. XSS context: If an attacker has XSS, they can already make authenticated requests
       directly - reading cookies via this endpoint doesn't provide additional attack surface
    4. Debugging utility: Full cookie visibility is necessary for troubleshooting auth issues

    This endpoint is intentionally NOT masked to preserve debugging functionality.
    """
    # Use same is_production logic as login route
    is_production = (
        os.getenv("FLASK_ENV") == "production" or
        os.getenv("APP_DOMAIN") is not None or
        request.headers.get('X-Forwarded-Proto') == 'https' or
        request.is_secure
    )

    return jsonify({
        "cookies": dict(request.cookies),
        "cookie_count": len(request.cookies),
        "headers": dict(request.headers),
        "is_production": is_production,
        "flask_env": os.getenv("FLASK_ENV"),
        "app_domain": os.getenv("APP_DOMAIN"),
        "x_forwarded_proto": request.headers.get('X-Forwarded-Proto'),
        "is_secure": request.is_secure,
        "host": request.host
    })

@app.route('/api/debug/refresh-attempt')
@require_auth
def debug_refresh_attempt():
    """Debug endpoint to attempt refresh and show Supabase error response"""
    from flask_auth_utils import get_refresh_token
    import os
    import requests

    refresh_token = get_refresh_token()

    if not refresh_token:
        return jsonify({
            "error": "No refresh_token found",
            "refresh_token_present": False
        })

    # Attempt the refresh and capture the full response
    try:
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

        if not supabase_url or not supabase_key:
            return jsonify({
                "error": "Missing Supabase config",
                "supabase_url": bool(supabase_url),
                "supabase_key": bool(supabase_key)
            })

        response = requests.post(
            f"{supabase_url}/auth/v1/token?grant_type=refresh_token",
            headers={
                "apikey": supabase_key,
                "Content-Type": "application/json"
            },
            json={"refresh_token": refresh_token},
            timeout=10
        )

        result = {
            "refresh_token_length": len(refresh_token),
            "refresh_token_preview": refresh_token[:50] + "..." if len(refresh_token) > 50 else refresh_token,
            "supabase_status_code": response.status_code,
            "supabase_response": response.text,
            "supabase_response_json": response.json() if response.text else None,
            "success": response.status_code == 200
        }

        # If refresh succeeded, save the new tokens to cookies
        if response.status_code == 200:
            auth_data = response.json()
            new_access_token = auth_data.get("access_token")
            new_refresh_token = auth_data.get("refresh_token")
            expires_in = auth_data.get("expires_in", 3600)

            if new_access_token:
                # Use same cookie settings as login route
                x_forwarded_proto = request.headers.get('X-Forwarded-Proto', '').lower()
                is_https = x_forwarded_proto == 'https' or request.is_secure
                has_app_domain = bool(os.getenv("APP_DOMAIN"))
                is_production_env = os.getenv("FLASK_ENV") == "production"
                is_production = is_production_env or has_app_domain or is_https
                use_secure = is_https or is_production
                samesite_value = 'Lax'

                flask_response = jsonify(result)
                flask_response.set_cookie(
                    'auth_token',
                    new_access_token,
                    max_age=expires_in,
                    httponly=True,
                    secure=use_secure,
                    samesite=samesite_value,
                    path='/'
                )
                if new_refresh_token:
                    flask_response.set_cookie(
                        'refresh_token',
                        new_refresh_token,
                        max_age=86400 * 30,  # 30 days
                        httponly=True,
                        secure=use_secure,
                        samesite=samesite_value,
                        path='/'
                    )
                    result["new_refresh_token_saved"] = True
                    result["new_refresh_token_length"] = len(new_refresh_token)
                return flask_response

        return jsonify(result)
    except Exception as e:
        return jsonify({
            "error": str(e),
            "error_type": type(e).__name__
        })

@app.route('/api/debug/auth')
@require_admin
def debug_auth():
    """Debug endpoint to test auth validation logic"""
    from flask_auth_utils import refresh_token_if_needed_flask, get_auth_token, get_refresh_token
    import time
    import json
    import base64

    token = get_auth_token()
    refresh = get_refresh_token()

    token_details = {}
    if token:
        try:
            parts = token.split('.')
            if len(parts) >= 2:
                payload = parts[1]
                payload += '=' * (4 - len(payload) % 4)
                decoded = base64.urlsafe_b64decode(payload)
                token_details = json.loads(decoded)
        except Exception as e:
            token_details = {"error": str(e)}

    success, new_token, new_refresh, expires_in = refresh_token_if_needed_flask()

    return jsonify({
        "success": success,
        "token_present": bool(token),
        "token_preview": token[:20] if token else None,
        "refresh_present": bool(refresh),
        "refresh_preview": refresh[:20] if refresh else None,
        "token_exp": token_details.get("exp"),
        "server_time": int(time.time()),
        "is_expired": token_details.get("exp", 0) < int(time.time()) if "exp" in token_details else None,
        "details": token_details
    })

@app.route('/api/auth/magic-link', methods=['POST'])
@rate_limit(limit=5, period=300)  # 5 requests per 5 minutes - prevents email flooding
def magic_link():
    """Handle magic link login request"""
    try:
        data = request.get_json()
        email = data.get('email')

        if not email:
            return jsonify({"error": "Email required"}), 400

        app_domain = os.getenv("APP_DOMAIN")
        if not app_domain:
            return jsonify({"error": "Server configuration error: APP_DOMAIN missing"}), 500

        # Ensure redirect URL is absolute and correct for auth flow
        redirect_url = f"https://{app_domain}/auth_callback.html"

        # Request magic link from Supabase
        # Note: For the /auth/v1/otp endpoint, use "options.emailRedirectTo" per Supabase docs
        # But the raw REST API uses "redirect_to" at the top level (not inside data)
        response = requests.post(
            f"{os.getenv('SUPABASE_URL')}/auth/v1/otp",
            headers={
                "apikey": os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY"),
                "Content-Type": "application/json"
            },
            json={
                "email": email,
                "create_user": False,
                "redirect_to": redirect_url
            },
            timeout=30
        )

        if response.status_code == 200:
            return jsonify({"message": "Magic link sent to your email"})
        else:
            return jsonify({"error": "Failed to send magic link"}), response.status_code

    except Exception as e:
        logger.error(f"Magic link error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/auth/reset-password-request', methods=['POST'])
@rate_limit(limit=3, period=600)  # 3 requests per 10 minutes - prevents email flooding
def reset_password_request():
    """Handle password reset request"""
    try:
        data = request.get_json()
        email = data.get('email')

        if not email:
            return jsonify({"error": "Email required"}), 400

        app_domain = os.getenv("APP_DOMAIN")
        if not app_domain:
            return jsonify({"error": "Server configuration error: APP_DOMAIN missing"}), 500

        # Recovery redirect URL
        redirect_url = f"https://{app_domain}/auth_callback.html?type=recovery"

        publishable_key = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
        if not publishable_key:
            logger.error("Password reset config error: SUPABASE_PUBLISHABLE_KEY/SUPABASE_ANON_KEY missing")
            return jsonify({"error": "Server configuration error: Supabase key missing"}), 500

        # Request recovery email from Supabase
        response = requests.post(
            f"{os.getenv('SUPABASE_URL')}/auth/v1/recover",
            headers={
                "apikey": publishable_key,
                "Content-Type": "application/json"
            },
            json={
                "email": email,
                "redirect_to": redirect_url
            },
            timeout=30
        )

        if response.status_code >= 400:
            # Log minimal failure context (no secrets) to debug auth issues without spam
            logger.warning(
                "Password reset recover failed: status=%s content_type=%s body_prefix=%s",
                response.status_code,
                response.headers.get("Content-Type"),
                response.text[:200]
            )

        # Supabase returns 200 even if user doesn't exist (security)
        if response.status_code == 200:
            return jsonify({"message": "If an account matches that email, a password reset link has been sent."})
        else:
            error_payload = {"error": "Failed to send reset email"}
            if app.debug:
                try:
                    error_payload["supabase_status"] = response.status_code
                    error_payload["supabase_body"] = response.json() if response.text else response.text
                except ValueError:
                    error_payload["supabase_status"] = response.status_code
                    error_payload["supabase_body"] = response.text
            return jsonify(error_payload), response.status_code

    except Exception as e:
        logger.error(f"Password reset request error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/auth/change-password', methods=['POST'])
@rate_limit(limit=5, period=60)  # 5 requests per minute - prevents brute-force if token stolen
def change_password():
    """Handle password change for authenticated user"""
    try:
        # Get token from cookie or header
        token = (request.cookies.get('auth_token') or
                 request.cookies.get('session_token') or
                 request.headers.get('Authorization', '').replace('Bearer ', ''))

        if not token:
             return jsonify({"error": "Authentication required"}), 401

        data = request.get_json()
        new_password = data.get('password')

        if not new_password or len(new_password) < 6:
            return jsonify({"error": "Password must be at least 6 characters"}), 400

        # Update user in Supabase
        response = requests.put(
            f"{os.getenv('SUPABASE_URL')}/auth/v1/user",
            headers={
                "apikey": os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY"),
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={
                "password": new_password
            },
            timeout=30
        )

        if response.status_code == 200:
            return jsonify({"message": "Password updated successfully"})
        else:
            return jsonify({"error": "Failed to update password"}), response.status_code

    except Exception as e:
        logger.error(f"Password change error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/auth/register', methods=['POST'])
@rate_limit(limit=3, period=3600)  # 3 requests per hour - very strict for registration to prevent spam accounts
def register():
    """Handle user registration"""
    try:
        # Check if registration is enabled via system settings
        from settings import get_system_setting
        registration_enabled = get_system_setting('registration_enabled', default=True)

        if not registration_enabled:
            return jsonify({"error": "New user registration is currently disabled. Please contact an administrator."}), 403

        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        name = data.get('name')

        if not email or not password or not name:
            return jsonify({"error": "Email, password, and name required"}), 400

        # Register with Supabase
        response = requests.post(
            f"{os.getenv('SUPABASE_URL')}/auth/v1/signup",
            headers={
                "apikey": os.getenv("SUPABASE_ANON_KEY"),
                "Content-Type": "application/json"
            },
            json={
                "email": email,
                "password": password,
                "user_metadata": {
                    "full_name": name
                }
            },
            timeout=30
        )

        logger.info(f"Registration attempt for {email}: Status {response.status_code}")
        if response.status_code != 200:
            logger.error(f"Registration failed: {response.text}")

        if response.status_code == 200:
            return jsonify({"message": "Account created successfully! Please check your email and click the confirmation link to activate your account."})
        else:
            error_data = response.json() if response.text else {}
            error_code = error_data.get("error_code", "")
            error_msg = error_data.get("msg", "Registration failed")

            # Handle specific error cases
            if error_code == "email_address_invalid":
                return jsonify({"error": "Please enter a valid email address."}), 400
            elif error_code == "weak_password":
                return jsonify({"error": "Password is too weak. Please use at least 6 characters."}), 400
            elif error_code == "user_already_registered":
                return jsonify({"error": "An account with this email already exists."}), 400
            else:
                return jsonify({"error": error_msg}), 400

    except Exception as e:
        logger.error(f"Registration error: {e}", exc_info=True)
        import traceback
        return jsonify({"error": "Registration failed", "message": str(e), "traceback": traceback.format_exc()}), 500

@app.route('/api/auth/logout', methods=['GET', 'POST'])
def logout():
    """Handle user logout"""
    is_production = request.host != 'localhost:5000' and not request.host.startswith('127.0.0.1')

    # Create redirect response to auth page
    response = redirect(url_for('auth_page'))

    # Clear session_token (Flask login)
    response.set_cookie(
        'session_token',
        '',
        expires=0,
        secure=is_production,
        samesite='Lax',
        path='/'
    )

    # Clear auth_token (Streamlit login) to prevent auto-login loop
    response.set_cookie(
        'auth_token',
        '',
        expires=0,
        secure=is_production,
        samesite='Lax',
        path='/'
    )

    # Clear refresh_token
    response.set_cookie(
        'refresh_token',
        '',
        expires=0,
        secure=is_production,
        samesite='Lax',
        path='/'
    )

    return response

# =====================================================
# ADMIN ROUTES
# =====================================================

@app.route('/admin')
@require_auth
def admin_dashboard():
    """Admin dashboard page"""
    if not is_admin():
        return jsonify({"error": "Admin privileges required"}), 403
    return render_template('admin.html')

@app.route('/admin/funds')
@require_admin
def admin_funds_page():
    """Render the fund management page"""
    from flask import render_template
    from flask_auth_utils import get_user_email_flask, can_modify_data_flask
    from app import get_navigation_context

    user_email = get_user_email_flask()

    # Get navigation context
    nav_context = get_navigation_context(current_page='admin_funds')

    return render_template('funds.html',
                         user_email=user_email,
                         can_modify_data=can_modify_data_flask(),
                         **nav_context)

@app.route('/api/admin/users')
@require_admin
def api_admin_users():
    """Get all users with their fund assignments"""
    try:
        # Get users from user_profiles
        response = requests.post(
            f"{os.getenv('SUPABASE_URL')}/rest/v1/rpc/list_users_with_funds",
            headers={
                "apikey": os.getenv("SUPABASE_ANON_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_ANON_KEY')}",
                "Content-Type": "application/json"
            },
            timeout=30
        )

        if response.status_code == 200:
            users = response.json()

            # Get stats
            stats = {
                "total_users": len(users),
                "total_funds": len(set(fund for user in users for fund in (user.get('funds') or []))),
                "total_assignments": sum(len(user.get('funds') or []) for user in users)
            }

            return jsonify({"users": users, "stats": stats})
        else:
            logger.error(f"Error getting users: {response.text}")
            return jsonify({"users": [], "stats": {"total_users": 0, "total_funds": 0, "total_assignments": 0}})
    except Exception as e:
        logger.error(f"Error in admin users API: {e}")
        return jsonify({"error": "Failed to load users"}), 500

@app.route('/api/admin/funds')
@require_admin
def api_admin_funds():
    """Get all available funds"""
    try:
        # Get unique funds from portfolio_positions
        response = requests.get(
            f"{os.getenv('SUPABASE_URL')}/rest/v1/portfolio_positions",
            headers={
                "apikey": os.getenv("SUPABASE_ANON_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_ANON_KEY')}",
                "Content-Type": "application/json"
            },
            params={"select": "fund"},
            timeout=30
        )

        if response.status_code == 200:
            funds = list(set(row['fund'] for row in response.json()))
            return jsonify({"funds": sorted(funds)})
        else:
            # Fallback to hardcoded funds
            return jsonify({"funds": ["Project Chimera", "RRSP Lance Webull", "TFSA", "TEST"]})
    except Exception as e:
        logger.error(f"Error getting funds: {e}")
        return jsonify({"funds": ["Project Chimera", "RRSP Lance Webull", "TFSA", "TEST"]})

@app.route('/api/admin/assign-fund', methods=['POST'])
@require_admin
def api_admin_assign_fund():
    """Assign a fund to a user"""
    try:
        data = request.get_json()
        user_email = data.get('user_email')
        fund_name = data.get('fund_name')

        if not user_email or not fund_name:
            return jsonify({"error": "User email and fund name required"}), 400

        # Use the database function to assign fund
        response = requests.post(
            f"{os.getenv('SUPABASE_URL')}/rest/v1/rpc/assign_fund_to_user",
            headers={
                "apikey": os.getenv("SUPABASE_ANON_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_ANON_KEY')}",
                "Content-Type": "application/json"
            },
            json={
                "user_email": user_email,
                "fund_name": fund_name
            },
            timeout=30
        )

        if response.status_code == 200:
            result_data = response.json()
            if isinstance(result_data, dict):
                # New JSON response format
                if result_data.get('success'):
                    return jsonify(result_data), 200
                elif result_data.get('already_assigned'):
                    return jsonify(result_data), 200  # Return 200 but with warning info
                else:
                    return jsonify(result_data), 400
            else:
                # Legacy boolean response
                return jsonify({"message": f"Fund '{fund_name}' assigned to {user_email}"}), 200
        else:
            error_msg = response.json().get('message', 'Failed to assign fund') if response.text else 'Failed to assign fund'
            return jsonify({"error": error_msg}), 400

    except Exception as e:
        logger.error(f"Error assigning fund: {e}")
        return jsonify({"error": "Failed to assign fund"}), 500

@app.route('/api/admin/remove-fund', methods=['POST'])
@require_admin
def api_admin_remove_fund():
    """Remove a fund from a user"""
    try:
        data = request.get_json()
        user_email = data.get('user_email')
        fund_name = data.get('fund_name')

        if not user_email or not fund_name:
            return jsonify({"error": "User email and fund name required"}), 400

        # Get user ID first
        user_response = requests.get(
            f"{os.getenv('SUPABASE_URL')}/rest/v1/user_profiles",
            headers={
                "apikey": os.getenv("SUPABASE_ANON_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_ANON_KEY')}",
                "Content-Type": "application/json"
            },
            params={"email": f"eq.{user_email}", "select": "user_id"},
            timeout=30
        )

        if user_response.status_code != 200 or not user_response.json():
            return jsonify({"error": "User not found"}), 404

        user_id = user_response.json()[0]['user_id']

        # Remove fund assignment
        remove_response = requests.delete(
            f"{os.getenv('SUPABASE_URL')}/rest/v1/user_funds",
            headers={
                "apikey": os.getenv("SUPABASE_ANON_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_ANON_KEY')}",
                "Content-Type": "application/json"
            },
            params={"user_id": f"eq.{user_id}", "fund_name": f"eq.{fund_name}"},
            timeout=30
        )

        if remove_response.status_code in [200, 204]:
            return jsonify({"message": f"Fund '{fund_name}' removed from {user_email}"})
        else:
            return jsonify({"error": "Failed to remove fund"}), 400

    except Exception as e:
        logger.error(f"Error removing fund: {e}")
        return jsonify({"error": "Failed to remove fund"}), 500

@app.route('/api/funds')
@require_auth
def api_funds():
    """API endpoint for user's assigned funds"""
    try:
        # Try Supabase first
        client = get_supabase_client()
        if client:
            # Get funds from Supabase
            response = requests.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/portfolio_positions",
                headers={
                    "apikey": os.getenv("SUPABASE_ANON_KEY"),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_ANON_KEY')}",
                    "Content-Type": "application/json"
                },
                timeout=30
            )
            if response.status_code == 200:
                data = response.json()
                funds = list(set([item.get('fund', '') for item in data if item.get('fund')]))
                logger.debug(f"Returning Supabase funds: {funds}")
                return jsonify({"funds": funds})

        # Fallback to CSV configuration
        config_file = Path("../repository_config.json")
        if config_file.exists():
            with open(config_file, 'r') as f:
                config = json.load(f)
            funds = config.get("repository", {}).get("available_funds", [])
            logger.debug(f"Returning CSV config funds: {funds}")
            return jsonify({"funds": funds})

        # Final fallback
        funds = ["Project Chimera", "RRSP Lance Webull", "TFSA", "TEST"]
        logger.debug(f"Returning hardcoded fallback funds: {funds}")
        return jsonify({"funds": funds})

    except Exception as e:
        logger.error(f"Error getting user funds: {e}")
        # Return fallback funds on error
        return jsonify({"funds": ["Project Chimera", "RRSP Lance Webull", "TFSA", "TEST"]})

def _safe_float(value: Any, default: float = 0.0) -> float:
    """Return a JSON-serializable float; NaN/Inf/None become default."""
    if value is None:
        return default
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


@app.route('/api/portfolio')
@require_auth
def api_portfolio():
    """API endpoint for portfolio data"""
    fund = request.args.get('fund')

    # Fund access check disabled for single-user setup
    # All authenticated users can access all funds

    data = load_portfolio_data(fund)
    metrics = calculate_performance_metrics(data['portfolio'], data['trades'], fund)

    # Get current positions
    current_positions = []
    if not data['portfolio'].empty:
        # Handle both Supabase and CSV data formats
        if 'ticker' in data['portfolio'].columns:
            # Supabase format - using latest_positions view with P&L calculations
            for row in data['portfolio'].itertuples(index=False):
                shares = getattr(row, 'shares', 0)
                shares = shares if not pd.isna(shares) else 0

                curr_price = getattr(row, 'current_price', getattr(row, 'price', 0))
                curr_price = curr_price if not pd.isna(curr_price) else 0

                cost_basis = getattr(row, 'cost_basis', 0)
                cost_basis = cost_basis if not pd.isna(cost_basis) else 0

                daily_pnl = getattr(row, 'daily_pnl', 0)
                daily_pnl = daily_pnl if not pd.isna(daily_pnl) else 0

                daily_pnl_pct = getattr(row, 'daily_pnl_pct', 0)
                daily_pnl_pct = daily_pnl_pct if not pd.isna(daily_pnl_pct) else 0

                five_day_pnl = getattr(row, 'five_day_pnl', 0)
                five_day_pnl = five_day_pnl if not pd.isna(five_day_pnl) else 0

                five_day_pnl_pct = getattr(row, 'five_day_pnl_pct', 0)
                five_day_pnl_pct = five_day_pnl_pct if not pd.isna(five_day_pnl_pct) else 0

                currency = getattr(row, 'currency', 'USD')
                currency = currency if not pd.isna(currency) else 'USD'

                market_value = _safe_float(shares) * _safe_float(curr_price)
                total_pnl = market_value - _safe_float(cost_basis)

                current_positions.append({
                    'ticker': getattr(row, 'ticker', ''),
                    'shares': round(_safe_float(shares), 4),
                    'price': round(_safe_float(curr_price), 2),
                    'cost_basis': round(_safe_float(cost_basis), 2),
                    'market_value': round(market_value, 2),
                    'total_pnl': round(total_pnl, 2),
                    'total_pnl_pct': round((_safe_float(total_pnl) / _safe_float(cost_basis, 1) * 100) if _safe_float(cost_basis) > 0 else 0, 2),
                    'daily_pnl': round(_safe_float(daily_pnl), 2),
                    'daily_pnl_pct': round(_safe_float(daily_pnl_pct), 2),
                    'five_day_pnl': round(_safe_float(five_day_pnl), 2),
                    'five_day_pnl_pct': round(_safe_float(five_day_pnl_pct), 2),
                    'currency': currency
                })
        else:
            # CSV format fallback
            current_positions_df = data['portfolio'][data['portfolio'].get('Total Value', 0) > 0]

            renamed_df = current_positions_df.rename(columns={
                'Total Value': 'Total_Value',
                'Cost Basis': 'Cost_Basis'
            })

            for row in renamed_df.itertuples(index=False):
                cost_basis = getattr(row, 'Cost_Basis', 0)
                cost_basis = cost_basis if not pd.isna(cost_basis) else 0

                pnl = getattr(row, 'PnL', 0)
                pnl = pnl if not pd.isna(pnl) else 0

                shares = getattr(row, 'Shares', 0)
                shares = shares if not pd.isna(shares) else 0

                price = getattr(row, 'Price', 0)
                price = price if not pd.isna(price) else 0

                total_value = getattr(row, 'Total_Value', 0)
                total_value = total_value if not pd.isna(total_value) else 0

                pnl_pct = round((pnl / cost_basis * 100), 2) if cost_basis > 0 else 0

                current_positions.append({
                    'ticker': getattr(row, 'Ticker', ''),
                    'shares': round(shares, 4),
                    'price': round(price, 2),
                    'cost_basis': round(cost_basis, 2),
                    'market_value': round(total_value, 2),
                    'pnl': round(pnl, 2),
                    'pnl_pct': pnl_pct
                })

    return jsonify({
        'metrics': metrics,
        'positions': current_positions,
        'cash_balances': data['cash_balances'],
        'available_funds': data.get('available_funds', []),
        'current_fund': data.get('current_fund'),
        'last_updated': datetime.now().isoformat()
    })

@app.route('/api/performance-chart')
@require_auth
def api_performance_chart():
    """API endpoint for performance chart data"""
    fund = request.args.get('fund')

    # Fund access check disabled for single-user setup
    # All authenticated users can access all funds

    data = load_portfolio_data(fund)
    chart_data = create_performance_chart(data['portfolio'], fund)
    return chart_data

@app.route('/api/contributors')
@require_auth
def api_contributors():
    """API endpoint for fund contributors/holders"""
    fund = request.args.get('fund')

    if not fund:
        return jsonify({"error": "Fund parameter required"}), 400

    try:
        # Get contributor data from Supabase
        client = SupabaseClient()

        # Get contributor ownership data
        result = client.supabase.table('contributor_ownership').select('*').eq('fund', fund).execute()

        if not result.data:
            return jsonify([])

        # Format the data for frontend
        contributors = []
        total_net = sum([float(c['net_contribution']) for c in result.data])

        # NOTE: This API returns ownership percentages from the summary view.
        # For accurate per-contributor returns, use NAV-based calculations from:
        # - portfolio/position_calculator.py calculate_ownership_percentages()
        # - web_dashboard/streamlit_utils.py get_user_investment_metrics()
        for contributor in result.data:
            net_contrib = float(contributor['net_contribution'])
            ownership_pct = (net_contrib / total_net * 100) if total_net > 0 else 0

            contributors.append({
                'contributor': contributor['contributor'],
                'email': contributor['email'],
                'net_contribution': net_contrib,
                'total_contributions': float(contributor['total_contributions']),
                'total_withdrawals': float(contributor['total_withdrawals']),
                'ownership_percentage': round(ownership_pct, 2),
                'transaction_count': contributor['transaction_count'],
                'first_contribution': contributor['first_contribution'],
                'last_transaction': contributor['last_transaction']
            })

        # Sort by net contribution (highest first)
        contributors.sort(key=lambda x: x['net_contribution'], reverse=True)

        return jsonify({
            'contributors': contributors,
            'total_contributors': len(contributors),
            'total_net_contributions': total_net
        })

    except Exception as e:
        print(f"Error fetching contributors: {e}")
        return jsonify({"error": "Failed to fetch contributors"}), 500

@app.route('/api/recent-trades')
@require_auth
def api_recent_trades():
    """API endpoint for recent trades"""
    fund = request.args.get('fund')

    # Fund access check disabled for single-user setup
    # All authenticated users can access all funds

    data = load_portfolio_data(fund)

    if data['trades'].empty:
        return jsonify([])

    # Get last 10 trades
    recent_trades = data['trades'].tail(10).to_dict('records')

    # Format the data
    formatted_trades = []
    for trade in recent_trades:
        # Handle both Supabase and CSV formats
        if 'date' in trade:
            # Supabase format
            date_str = trade['date']
            ticker = trade['ticker']
            shares = trade['shares']
            price = trade['price']
            cost_basis = trade['cost_basis']
            pnl = trade['pnl']
            reason = trade['reason']
        else:
            # CSV format
            date_str = trade['Date'].strftime('%Y-%m-%d %H:%M')
            ticker = trade['Ticker']
            shares = trade['Shares']
            price = trade['Price']
            cost_basis = trade['Cost Basis']
            pnl = trade['PnL']
            reason = trade['Reason']

        formatted_trades.append({
            'date': date_str,
            'ticker': ticker,
            'shares': round(shares, 4),
            'price': round(price, 2),
            'cost_basis': round(cost_basis, 2),
            'pnl': round(pnl, 2),
            'reason': reason
        })

    return jsonify(formatted_trades)

# =====================================================
# DEVELOPER/LLM SHARED DATA ACCESS
# =====================================================

@app.route('/dev')
@require_auth
def dev_home():
    """Developer home page"""
    if not is_admin():
        return jsonify({"error": "Admin privileges required"}), 403

    nav_context = get_navigation_context(current_page='dev_home')
    return render_template('dev_home.html', **nav_context)

@app.route('/dev/sql')
@require_auth
def sql_interface():
    """SQL query interface for debugging"""
    if not is_admin():
        return jsonify({"error": "Admin privileges required"}), 403

    nav_context = get_navigation_context(current_page='sql_interface')
    return render_template('sql_interface.html', **nav_context)

@app.route('/api/dev/query', methods=['POST'])
@require_auth
def execute_sql():
    """
    Execute SQL query with admin privileges.

    SECURITY NOTES:
    - This endpoint is protected by @require_auth and is_admin() checks
    - Admins have full SQL access (SELECT, INSERT, UPDATE, DELETE, etc.)
    - All queries are logged with user info for audit trail
    - Use with caution - this provides direct database access

    BEST PRACTICES:
    - Test queries on non-production data first
    - Use transactions for multi-step operations
    - Backup data before running destructive queries
    - Review query logs regularly for suspicious activity
    """
    if not is_admin():
        return jsonify({"error": "Admin privileges required"}), 403

    try:
        from flask_auth_utils import get_user_email_flask

        query = request.json.get('query', '').strip()
        if not query:
            return jsonify({"error": "No query provided"}), 400

        # Get user info for audit logging
        user_email = get_user_email_flask() or "unknown_admin"

        # Improved safety validation (whole-word matching to avoid false positives like 'update_date')
        # Note: This is a warning system, not a blocker - admins need full SQL access
        dangerous_keywords = ['DROP', 'DELETE', 'UPDATE', 'INSERT', 'ALTER', 'CREATE', 'TRUNCATE']
        pattern = r'\b(' + '|'.join(dangerous_keywords) + r')\b'

        is_modification_query = bool(re.search(pattern, query, re.IGNORECASE))

        # Comprehensive audit logging
        if is_modification_query:
            logger.warning(
                f"ADMIN SQL MODIFICATION - User: {user_email} | "
                f"Query: {query[:200]}{'...' if len(query) > 200 else ''} | "
                f"IP: {request.remote_addr}"
            )
        else:
            logger.info(
                f"ADMIN SQL QUERY - User: {user_email} | "
                f"Query: {query[:100]}{'...' if len(query) > 100 else ''}"
            )

        # Execute query
        client = get_supabase_client()
        if not client:
            return jsonify({"error": "Database connection failed"}), 500

        # Use raw SQL execution
        result = client.supabase.rpc('execute_sql', {'query': query}).execute()

        # Log successful execution
        row_count = len(result.data) if result.data else 0
        logger.info(f"ADMIN SQL SUCCESS - User: {user_email} | Rows affected/returned: {row_count}")

        return jsonify({
            "success": True,
            "data": result.data,
            "count": row_count,
            "warning": "Modification query executed" if is_modification_query else None
        })

    except Exception as e:
        logger.error(
            f"ADMIN SQL ERROR - User: {user_email if 'user_email' in locals() else 'unknown'} | "
            f"Query: {query[:100] if 'query' in locals() else 'N/A'} | "
            f"Error: {e}",
            exc_info=True
        )
        return jsonify({"error": f"Query execution failed: {str(e)}"}), 500

# =====================================================
# DATA EXPORT APIs FOR LLM ACCESS
# =====================================================

@app.route('/api/export/portfolio')
@require_auth
def export_portfolio():
    """Export portfolio data as JSON for LLM analysis"""
    if not is_admin():
        return jsonify({"error": "Admin privileges required"}), 403

    try:
        fund = request.args.get('fund')
        limit = int(request.args.get('limit', 1000))

        client = get_supabase_client()
        if not client:
            return jsonify({"error": "Database connection failed"}), 500

        # Get portfolio positions
        query = client.supabase.table("portfolio_positions").select("*")
        if fund:
            query = query.eq("fund", fund)
        query = query.limit(limit)

        result = query.execute()

        return jsonify({
            "success": True,
            "data": result.data,
            "count": len(result.data),
            "fund": fund,
            "timestamp": datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Portfolio export error: {e}")
        return jsonify({"error": f"Export failed: {str(e)}"}), 500

@app.route('/api/export/trades')
@require_auth
def export_trades():
    """Export trade data as JSON for LLM analysis"""
    if not is_admin():
        return jsonify({"error": "Admin privileges required"}), 403

    try:
        fund = request.args.get('fund')
        limit = int(request.args.get('limit', 1000))

        client = get_supabase_client()
        if not client:
            return jsonify({"error": "Database connection failed"}), 500

        # Get trade log
        query = client.supabase.table("trade_log").select("*")
        if fund:
            query = query.eq("fund", fund)
        query = query.order("date", desc=True).limit(limit)

        result = query.execute()

        return jsonify({
            "success": True,
            "data": result.data,
            "count": len(result.data),
            "fund": fund,
            "timestamp": datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Trades export error: {e}")
        return jsonify({"error": f"Export failed: {str(e)}"}), 500

@app.route('/api/export/performance')
@require_auth
def export_performance():
    """Export performance metrics for LLM analysis"""
    if not is_admin():
        return jsonify({"error": "Admin privileges required"}), 403

    try:
        days = int(request.args.get('days', 30))
        fund = request.args.get('fund')

        client = get_supabase_client()
        if not client:
            return jsonify({"error": "Database connection failed"}), 500

        # Get performance data
        performance_data = client.get_performance_metrics()
        daily_data = client.get_daily_performance_data(days, fund=fund)

        return jsonify({
            "success": True,
            "performance": performance_data,
            "daily_data": daily_data,
            "days": days,
            "fund": fund,
            "timestamp": datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Performance export error: {e}")
        return jsonify({"error": f"Export failed: {str(e)}"}), 500

@app.route('/api/export/cash')
@require_auth
def export_cash():
    """Export cash balance data for LLM analysis"""
    if not is_admin():
        return jsonify({"error": "Admin privileges required"}), 403

    try:
        fund = request.args.get('fund')

        client = get_supabase_client()
        if not client:
            return jsonify({"error": "Database connection failed"}), 500

        # Get cash balances
        cash_balances = client.get_cash_balances(fund)

        return jsonify({
            "success": True,
            "data": cash_balances,
            "fund": fund,
            "timestamp": datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Cash export error: {e}")
        return jsonify({"error": f"Export failed: {str(e)}"}), 500

@app.route('/logs/debug')
@require_admin
def logs_debug():
    """Debug endpoint to check admin status (requires admin privileges)"""
    try:
        from flask_auth_utils import get_user_email_flask, get_user_id_flask
        from auth import is_admin
        from supabase_client import SupabaseClient

        user_email = get_user_email_flask()
        user_id = get_user_id_flask()
        request_user_id = getattr(request, 'user_id', None)
        admin_status = is_admin() if hasattr(request, 'user_id') else False

        # Check user profile directly in database
        profile_role = None
        profile_error = None
        try:
            from flask_auth_utils import get_supabase_access_token
            token = get_supabase_access_token()
            if token:
                # Use SupabaseClient with user token (handles auth properly)
                client = SupabaseClient(user_token=token)
                # Query user_profiles table directly
                result = client.supabase.table('user_profiles').select('role, email').eq('user_id', request_user_id).execute()
                if result.data and len(result.data) > 0:
                    profile_role = result.data[0].get('role')
                else:
                    profile_error = "No profile found"
        except Exception as e:
            profile_error = str(e)
            logger.error(f"Error querying user_profiles: {e}", exc_info=True)

        # Try RPC call directly
        rpc_result = None
        rpc_error = None
        try:
            from flask_auth_utils import get_supabase_access_token
            token = get_supabase_access_token()
            if token and request_user_id:
                # Use SupabaseClient with user token (handles auth properly)
                client = SupabaseClient(user_token=token)
                rpc_response = client.supabase.rpc('is_admin', {'user_uuid': request_user_id}).execute()
                rpc_result = rpc_response.data
        except Exception as e:
            rpc_error = str(e)
            logger.error(f"Error calling is_admin RPC: {e}", exc_info=True)

        return jsonify({
            "user_email": user_email,
            "user_id": user_id,
            "request_user_id": request_user_id,
            "is_admin": admin_status,
            "profile_role": profile_role,
            "profile_error": profile_error,
            "rpc_result": rpc_result,
            "rpc_error": rpc_error,
            "auth_token_present": bool(request.cookies.get('auth_token')),
            "session_token_present": bool(request.cookies.get('session_token'))
        })
    except Exception as e:
        logger.error(f"Error in debug endpoint: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500



@cache_data(ttl=5)
def _get_cached_application_logs(level_filter, search, exclude_modules):
    """Get application logs with caching (5s TTL for near real-time)"""
    from log_handler import read_logs_from_file

    try:
        # Get all filtered logs
        all_logs = read_logs_from_file(
            n=None,
            level=level_filter,
            search=search if search else None,
            return_all=True,
            exclude_modules=exclude_modules if exclude_modules else None
        )

        # Convert datetime objects to strings for cache compatibility
        # This ensures the cache can properly serialize/deserialize the data
        serializable_logs = []
        for log in all_logs:
            serializable_log = log.copy()
            if 'timestamp' in serializable_log and hasattr(serializable_log['timestamp'], 'strftime'):
                serializable_log['timestamp'] = serializable_log['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            serializable_logs.append(serializable_log)

        # Reverse for newest first
        return list(reversed(serializable_logs))
    except Exception as e:
        logger.error(f"Error in _get_cached_application_logs: {e}", exc_info=True)
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise

@cache_data(ttl=5)
def _get_cached_ollama_log_lines():
    """Get Ollama log lines with caching (5s TTL for near real-time)"""
    from pathlib import Path

    log_file = Path(__file__).parent / 'logs' / 'ollama.log'

    if not log_file.exists():
        return []

    try:
        # Read up to 5MB from end for efficiency
        file_size = log_file.stat().st_size
        if file_size == 0:
            return []

        buffer_size = min(5 * 1024 * 1024, file_size)
        with open(log_file, 'rb') as f:
            f.seek(max(0, file_size - buffer_size))
            buffer = f.read().decode('utf-8', errors='ignore')

        lines = buffer.split('\n')
        if file_size > buffer_size:
            lines = lines[1:]  # Skip first partial line

        # Reverse for newest first
        return list(reversed(lines))
    except Exception as e:
        logger.error(f"Error reading Ollama log file: {e}")
        return []




@app.route('/api/logs/clear', methods=['POST'])
@require_admin
def api_logs_clear():
    """Clear application logs"""
    try:
        import os
        log_file = os.path.join(os.path.dirname(__file__), 'logs', 'app.log')
        if os.path.exists(log_file):
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write("")
            return jsonify({'success': True, 'message': 'Logs cleared'})
        return jsonify({'success': False, 'error': 'Log file not found'}), 404
    except Exception as e:
        logger.error(f"Error clearing logs: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/settings')
@require_auth
def settings_page():
    """User preferences/settings page (Flask)"""
    try:
        from flask_auth_utils import get_user_email_flask
        from user_preferences import get_user_timezone, get_user_currency, get_user_theme

        user_email = get_user_email_flask()
        current_timezone = get_user_timezone() or 'America/Los_Angeles'
        current_currency = get_user_currency() or 'CAD'
        current_theme = get_user_theme() or 'system'

        # Get navigation context
        nav_context = get_navigation_context(current_page='settings')

        return render_template('settings.html',
                             user_email=user_email,
                             current_timezone=current_timezone,
                             current_currency=current_currency,
                             current_theme=current_theme,
                             **nav_context)
    except Exception as e:
        logger.error(f"Error loading settings page: {e}")
        return jsonify({"error": "Failed to load settings page"}), 500

@app.route('/api/settings/timezone', methods=['POST'])
@require_auth
def update_timezone():
    """Update user timezone preference"""
    try:
        from user_preferences import set_user_timezone
        from flask_auth_utils import get_user_id_flask

        data = request.get_json()
        timezone = data.get('timezone')

        if not timezone:
            return jsonify({"success": False, "error": "Timezone is required"}), 400

        user_id = get_user_id_flask()
        logger.debug(f"Updating timezone for user {user_id} to {timezone}")

        result = set_user_timezone(timezone)
        if result:
            logger.info(f"Successfully updated timezone to {timezone}")
            return jsonify({"success": True})
        else:
            logger.error(f"Failed to update timezone - set_user_timezone returned False for user {user_id}")
            return jsonify({"success": False, "error": "Failed to save timezone. Check server logs for details."}), 500

    except Exception as e:
        logger.error(f"Error updating timezone: {e}", exc_info=True)
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Full traceback: {error_details}")
        return jsonify({"success": False, "error": f"Server error: {str(e)}"}), 500

@app.route('/api/settings/currency', methods=['POST'])
@require_auth
def update_currency():
    """Update user currency preference"""
    try:
        from user_preferences import set_user_currency
        from flask_auth_utils import get_user_id_flask

        data = request.get_json()
        currency = data.get('currency')

        if not currency:
            return jsonify({"success": False, "error": "Currency is required"}), 400

        user_id = get_user_id_flask()
        logger.debug(f"Updating currency for user {user_id} to {currency}")

        result = set_user_currency(currency)
        if result:
            logger.info(f"Successfully updated currency to {currency}")
            return jsonify({"success": True})
        else:
            logger.error(f"Failed to update currency - set_user_currency returned False for user {user_id}")
            return jsonify({"success": False, "error": "Failed to save currency. Check server logs for details."}), 500

    except Exception as e:
        logger.error(f"Error updating currency: {e}", exc_info=True)
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Full traceback: {error_details}")
        return jsonify({"success": False, "error": f"Server error: {str(e)}"}), 500

@app.route('/api/settings/theme', methods=['POST'])
@require_auth
def update_theme():
    """Update user theme preference"""
    try:
        from user_preferences import set_user_theme
        from flask_auth_utils import get_user_id_flask

        data = request.get_json()
        theme = data.get('theme')

        if not theme:
            return jsonify({"success": False, "error": "Theme is required"}), 400

        user_id = get_user_id_flask()
        logger.debug(f"Updating theme for user {user_id} to {theme}")

        result = set_user_theme(theme)
        if result:
            logger.info(f"Successfully updated theme to {theme}")
            return jsonify({"success": True})
        else:
            logger.error(f"Failed to update theme - set_user_theme returned False for user {user_id}")
            return jsonify({"success": False, "error": "Failed to save theme. Check server logs for details."}), 500

    except Exception as e:
        logger.error(f"Error updating theme: {e}", exc_info=True)
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Full traceback: {error_details}")
        return jsonify({"success": False, "error": f"Server error: {str(e)}"}), 500

@app.route('/api/settings/v2_enabled', methods=['POST'])
@require_auth
def update_v2_enabled():
    """Update v2 beta enabled preference"""
    try:
        from user_preferences import set_user_preference
        from flask_auth_utils import get_user_id_flask

        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "Missing request body"}), 400

        enabled = data.get('enabled')

        if enabled is None:
            return jsonify({"success": False, "error": "Missing enabled parameter"}), 400

        user_id = get_user_id_flask()
        logger.debug(f"Updating v2_enabled for user {user_id} to {enabled}")

        # Debug: capture any exception from set_user_preference
        try:
            result = set_user_preference('v2_enabled', enabled)
            logger.debug(f"set_user_preference returned: {result} (type: {type(result)})")
        except Exception as pref_error:
            import traceback
            tb = traceback.format_exc()
            logger.error(f"set_user_preference raised exception: {pref_error}\n{tb}")
            return jsonify({"success": False, "error": f"Preference error: {str(pref_error)}", "traceback": tb}), 500

        if result:
            logger.info(f"Successfully updated v2_enabled to {enabled}")
            return jsonify({"success": True})
        else:
            logger.error(f"Failed to update v2_enabled - set_user_preference returned False")
            return jsonify({"success": False, "error": "set_user_preference returned False - check server logs"}), 500
    except Exception as e:
        logger.error(f"Error updating v2 enabled: {e}", exc_info=True)
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Full traceback: {error_details}")
        return jsonify({"success": False, "error": f"Server error: {str(e)}"}), 500

@app.route('/api/settings/ai_model', methods=['POST'])
@require_auth
def update_ai_model():
    """Update user AI model preference"""
    try:
        from user_preferences import set_user_ai_model
        from flask_auth_utils import get_user_id_flask

        data = request.get_json()
        model = data.get('model')

        if not model:
            return jsonify({"success": False, "error": "Model is required"}), 400

        user_id = get_user_id_flask()
        logger.debug(f"Updating AI model for user {user_id} to {model}")

        result = set_user_ai_model(model)
        if result:
            logger.info(f"Successfully updated AI model to {model}")
            return jsonify({"success": True})
        else:
            logger.error(f"Failed to update AI model - set_user_ai_model returned False")
            return jsonify({"success": False, "error": "Failed to save model preference"}), 500

    except Exception as e:
        logger.error(f"Error updating AI model: {e}", exc_info=True)
        return jsonify({"success": False, "error": f"Server error: {str(e)}"}), 500


@app.route('/api/settings/preferences', methods=['GET'])
@require_auth
def get_preferences():
    """Get all user preferences"""
    try:
        from user_preferences import get_all_user_preferences

        preferences = get_all_user_preferences()
        return jsonify({"success": True, "preferences": preferences})
    except Exception as e:
        logger.error(f"Error getting preferences: {e}", exc_info=True)
        return jsonify({"success": False, "error": f"Server error: {str(e)}"}), 500


@app.route("/api/settings/newsletter-subscription", methods=["GET"])
@require_auth
def get_newsletter_subscription():
    """Portfolio digest opt-in: reads user_newsletter_subscriptions (not preferences JSON)."""
    try:
        from flask_data_utils import get_supabase_client_flask
        from flask_auth_utils import get_user_id_flask

        uid = get_user_id_flask()
        client = get_supabase_client_flask()
        if not client:
            return jsonify({"success": False, "error": "Database client unavailable"}), 503

        nt = (
            client.supabase.table("outbound_newsletter_types")
            .select("id,slug,display_name")
            .eq("slug", "portfolio_digest")
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if not nt.data:
            return jsonify({"success": True, "newsletter_type": None, "subscription": None})

        type_row = nt.data[0]
        tid = type_row["id"]
        subs = (
            client.supabase.table("user_newsletter_subscriptions")
            .select("*")
            .eq("user_id", uid)
            .eq("newsletter_type_id", tid)
            .limit(1)
            .execute()
        )
        sub = subs.data[0] if subs.data else None
        return jsonify({"success": True, "newsletter_type": type_row, "subscription": sub})
    except Exception as e:
        logger.error(f"Error getting newsletter subscription: {e}", exc_info=True)
        return jsonify({"success": False, "error": f"Server error: {str(e)}"}), 500


@app.route("/api/settings/newsletter-subscription", methods=["POST"])
@require_auth
def update_newsletter_subscription():
    """Upsert portfolio_digest subscription row (cadence + is_active)."""
    try:
        from datetime import datetime, timezone

        from flask_data_utils import get_supabase_client_flask
        from flask_auth_utils import get_user_id_flask

        uid = get_user_id_flask()
        client = get_supabase_client_flask()
        if not client:
            return jsonify({"success": False, "error": "Database client unavailable"}), 503

        payload = request.get_json(silent=True) or {}
        is_active = bool(payload.get("is_active", True))
        cadence = str(payload.get("cadence", "weekly")).lower()
        if cadence not in ("daily", "weekly", "biweekly", "monthly"):
            return jsonify({"success": False, "error": "Invalid cadence"}), 400

        nt = (
            client.supabase.table("outbound_newsletter_types")
            .select("id")
            .eq("slug", "portfolio_digest")
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if not nt.data:
            return jsonify({"success": False, "error": "Newsletter type not available"}), 400
        tid = nt.data[0]["id"]

        existing = (
            client.supabase.table("user_newsletter_subscriptions")
            .select("id")
            .eq("user_id", uid)
            .eq("newsletter_type_id", tid)
            .limit(1)
            .execute()
        )
        now = datetime.now(timezone.utc).isoformat()
        if existing.data:
            rid = existing.data[0]["id"]
            client.supabase.table("user_newsletter_subscriptions").update(
                {"is_active": is_active, "cadence": cadence, "updated_at": now}
            ).eq("id", rid).execute()
        else:
            client.supabase.table("user_newsletter_subscriptions").insert(
                {
                    "user_id": uid,
                    "newsletter_type_id": tid,
                    "is_active": is_active,
                    "cadence": cadence,
                }
            ).execute()

        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error updating newsletter subscription: {e}", exc_info=True)
        return jsonify({"success": False, "error": f"Server error: {str(e)}"}), 500

@app.route('/api/settings/selected-fund', methods=['POST'])
@require_auth
def update_selected_fund():
    """Update user's selected fund preference."""
    try:
        from user_preferences import set_user_selected_fund
        from flask_data_utils import get_available_funds_flask

        payload = request.get_json(silent=True) or {}
        fund = str(payload.get("fund", "")).strip()

        if not fund:
            fund = "all"

        if fund.lower() not in ("all", "all funds"):
            available_funds = get_available_funds_flask()
            if available_funds and fund not in available_funds:
                logger.warning("[fund-selector] Rejecting invalid fund preference: %s", fund)
                return jsonify({"success": False, "error": "Invalid fund"}), 400

        result = set_user_selected_fund(fund)
        if not result:
            logger.error("[fund-selector] Failed to set selected fund preference")
            return jsonify({"success": False, "error": "Failed to update fund preference"}), 500

        return jsonify({"success": True, "fund": fund})
    except Exception as e:
        logger.error(f"Error updating selected fund: {e}", exc_info=True)
        return jsonify({"success": False, "error": "Server error"}), 500

@app.route('/api/settings/ai_include_search', methods=['POST'])
@require_auth
def update_ai_include_search():
    """Update user AI include search preference"""
    try:
        from user_preferences import set_user_preference
        from flask_auth_utils import get_user_id_flask

        data = request.get_json()
        include_search = data.get('include_search')

        if include_search is None:
            return jsonify({"success": False, "error": "include_search is required"}), 400

        user_id = get_user_id_flask()
        logger.debug(f"Updating AI include_search for user {user_id} to {include_search}")

        result = set_user_preference('ai_include_search', include_search)
        if result:
            logger.info(f"Successfully updated AI include_search to {include_search}")
            return jsonify({"success": True})
        else:
            logger.error(f"Failed to update AI include_search - set_user_preference returned False")
            return jsonify({"success": False, "error": "Failed to save preference"}), 500

    except Exception as e:
        logger.error(f"Error updating AI include_search: {e}", exc_info=True)
        return jsonify({"success": False, "error": f"Server error: {str(e)}"}), 500

@app.route('/api/settings/ai_include_insider_trades', methods=['POST'])
@require_auth
def update_ai_include_insider_trades():
    """Update user AI include insider trades preference"""
    try:
        from user_preferences import set_user_preference
        from flask_auth_utils import get_user_id_flask

        data = request.get_json()
        include_insider_trades = data.get('include_insider_trades')

        if include_insider_trades is None:
            return jsonify({"success": False, "error": "include_insider_trades is required"}), 400

        user_id = get_user_id_flask()
        logger.debug(f"Updating AI include_insider_trades for user {user_id} to {include_insider_trades}")

        result = set_user_preference('ai_include_insider_trades', include_insider_trades)
        if result:
            logger.info(f"Successfully updated AI include_insider_trades to {include_insider_trades}")
            return jsonify({"success": True})
        else:
            logger.error(f"Failed to update AI include_insider_trades - set_user_preference returned False")
            return jsonify({"success": False, "error": "Failed to save preference"}), 500

    except Exception as e:
        logger.error(f"Error updating AI include_insider_trades: {e}", exc_info=True)
        return jsonify({"success": False, "error": f"Server error: {str(e)}"}), 500

@app.route('/api/settings/ai_include_congress_trades', methods=['POST'])
@require_auth
def update_ai_include_congress_trades():
    """Update user AI include congress trades preference"""
    try:
        from user_preferences import set_user_preference
        from flask_auth_utils import get_user_id_flask

        data = request.get_json()
        include_congress_trades = data.get('include_congress_trades')

        if include_congress_trades is None:
            return jsonify({"success": False, "error": "include_congress_trades is required"}), 400

        user_id = get_user_id_flask()
        logger.debug(f"Updating AI include_congress_trades for user {user_id} to {include_congress_trades}")

        result = set_user_preference('ai_include_congress_trades', include_congress_trades)
        if result:
            logger.info(f"Successfully updated AI include_congress_trades to {include_congress_trades}")
            return jsonify({"success": True})
        else:
            logger.error(f"Failed to update AI include_congress_trades - set_user_preference returned False")
            return jsonify({"success": False, "error": "Failed to save preference"}), 500

    except Exception as e:
        logger.error(f"Error updating AI include_congress_trades: {e}", exc_info=True)
        return jsonify({"success": False, "error": f"Server error: {str(e)}"}), 500

@app.route('/api/settings/ai_include_etf_trades', methods=['POST'])
@require_auth
def update_ai_include_etf_trades():
    """Update user AI include ETF trades preference"""
    try:
        from user_preferences import set_user_preference
        from flask_auth_utils import get_user_id_flask

        data = request.get_json()
        include_etf_trades = data.get('include_etf_trades')

        if include_etf_trades is None:
            return jsonify({"success": False, "error": "include_etf_trades is required"}), 400

        user_id = get_user_id_flask()
        logger.debug(f"Updating AI include_etf_trades for user {user_id} to {include_etf_trades}")

        result = set_user_preference('ai_include_etf_trades', include_etf_trades)
        if result:
            logger.info(f"Successfully updated AI include_etf_trades to {include_etf_trades}")
            return jsonify({"success": True})
        else:
            logger.error(f"Failed to update AI include_etf_trades - set_user_preference returned False")
            return jsonify({"success": False, "error": "Failed to save preference"}), 500

    except Exception as e:
        logger.error(f"Error updating AI include_etf_trades: {e}", exc_info=True)
        return jsonify({"success": False, "error": f"Server error: {str(e)}"}), 500

@app.route('/api/settings/debug', methods=['GET'])
@require_auth
def settings_debug():
    """Debug endpoint to test preference saving"""
    try:
        from user_preferences import set_user_preference, get_user_preference, _get_user_id, _is_authenticated
        from flask_auth_utils import get_user_id_flask, get_supabase_access_token
        from supabase_client import SupabaseClient

        user_id = get_user_id_flask()
        token = get_supabase_access_token()
        is_authenticated = _is_authenticated()

        # Test creating client
        client = None
        client_error = None
        try:
            client = SupabaseClient(user_token=token) if token else SupabaseClient()
        except Exception as e:
            client_error = str(e)

        # Test RPC call
        rpc_result = None
        rpc_error = None
        if client:
            try:
                # Test with a simple preference
                test_result = client.supabase.rpc('set_user_preference', {
                    'pref_key': 'test_key',
                    'pref_value': json.dumps('test_value')
                }).execute()
                rpc_result = test_result.data
            except Exception as e:
                rpc_error = str(e)
                logger.error(f"RPC test failed: {e}", exc_info=True)

        return jsonify({
            "user_id": user_id,
            "token_present": bool(token),
            "token_length": len(token) if token else 0,
            "is_authenticated": is_authenticated,
            "client_created": client is not None,
            "client_error": client_error,
            "rpc_result": rpc_result,
            "rpc_error": rpc_error
        })
    except Exception as e:
        logger.error(f"Error in settings debug: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ============================================================================
# Ticker Details Page (Flask v2)
# ============================================================================

@app.route('/ticker')
@require_auth
def ticker_details_page():
    """Ticker details page (Flask v2)"""
    try:
        from flask_auth_utils import get_user_email_flask
        from ollama_client import load_model_config
        from user_preferences import get_user_ai_model

        user_email = get_user_email_flask()
        ticker = request.args.get('ticker', '').upper().strip()
        default_model = get_user_ai_model()
        model_config = load_model_config()

        # Get navigation context
        nav_context = get_navigation_context(current_page='ticker_details')

        return render_template('ticker_details.html',
                               user_email=user_email,
                               ticker=ticker,
                               default_model=default_model,
                               model_config=model_config,
                               **nav_context)
    except Exception as e:
        logger.error(f"Error loading ticker details page: {e}")
        return jsonify({"error": "Failed to load ticker details page"}), 500

@cache_data(ttl=60)
def _get_all_tickers_cached():
    """Get all unique tickers with caching (60s TTL)"""
    import re
    try:
        logger.info("Starting _get_all_tickers_cached")
        from ticker_utils import get_all_unique_tickers
        tickers = get_all_unique_tickers()
        # Filter out junk tickers that don't start with a letter or number
        valid_ticker_pattern = re.compile(r'^[A-Za-z0-9]')
        tickers = [t for t in (tickers or []) if valid_ticker_pattern.match(t)]
        count = len(tickers) if tickers else 0
        logger.info(f"_get_all_tickers_cached retrieved {count} tickers")
        return sorted(tickers) if tickers else []
    except Exception as e:
        logger.error(f"Error fetching ticker list in _get_all_tickers_cached: {e}", exc_info=True)
        return []


def _normalize_fund_param(fund: Optional[str]) -> Optional[str]:
    if not fund:
        return None
    fund_value = str(fund).strip()
    if not fund_value:
        return None
    if fund_value.lower() in ("all", "all funds"):
        return None
    return fund_value


def _ticker_price_request_params() -> Tuple[str, Optional[int], Optional[int]]:
    """Parse price_source, year_from, year_to from the current request query."""
    ps = (request.args.get("price_source") or "auto").strip().lower()
    if ps not in ("auto", "market"):
        ps = "auto"
    yf = request.args.get("year_from", type=int)
    yt = request.args.get("year_to", type=int)
    if yf is None or yt is None:
        return ps, None, None
    return ps, yf, yt


def _chart_figure_range_label(year_from: Optional[int], year_to: Optional[int]) -> Optional[str]:
    """Legend/title label when using a calendar year range."""
    if year_from is None or year_to is None:
        return None
    a, b = min(year_from, year_to), max(year_from, year_to)
    return f"{a}–{b}"

@app.route('/api/v2/ticker/list')
@require_auth
def api_ticker_list():
    """Get list of all available tickers for dropdown.

    Query Parameters:
        with_names (str): If '1' or 'true', include company names map in response.

    Returns:
        JSON with 'tickers' list, and optionally 'ticker_names' map {ticker: company_name}.
    """
    try:
        tickers = _get_all_tickers_cached()
        result: Dict[str, Any] = {"tickers": tickers}

        # Optionally include company names for enhanced autocomplete
        with_names = request.args.get('with_names', '').lower() in ('1', 'true')
        if with_names and tickers:
            try:
                supabase_client = SupabaseClient()
                cache_version = get_cache_version()
                names_map = get_company_names_map_cached(
                    supabase_client, tuple(tickers), cache_version
                )
                result["ticker_names"] = names_map
            except Exception as e:
                logger.warning(f"Error fetching company names for ticker list: {e}")
                # Non-fatal: return tickers without names

        return jsonify(result)
    except Exception as e:
        logger.error(f"Error fetching ticker list: {e}")
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc(),
            "type": type(e).__name__
        }), 500


@app.route('/api/v2/ticker/search')
@require_auth
def api_ticker_search():
    """Search for tickers by company name or symbol using Yahoo Finance.

    Query Parameters:
        q (str): Search query (company name or ticker symbol).

    Returns:
        JSON with 'results' list of {symbol, name, exchange, type} and 'exact_match' bool.
    """
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({"results": [], "exact_match": False, "error": "No query provided"}), 400

    try:
        # Check if query is an exact ticker match in our database
        known_tickers = _get_all_tickers_cached()
        query_upper = query.upper()
        if query_upper in known_tickers:
            # Try to get company name from securities table
            name = query_upper
            try:
                supabase_client = SupabaseClient()
                sec_resp = supabase_client.client.table("securities").select(
                    "company_name"
                ).eq("ticker", query_upper).limit(1).execute()
                if sec_resp.data and sec_resp.data[0].get("company_name"):
                    name = sec_resp.data[0]["company_name"]
            except Exception:
                pass
            return jsonify({
                "results": [{"symbol": query_upper, "name": name, "exchange": "", "type": "EQUITY"}],
                "exact_match": True
            })

        # Use yfinance Search to find matches
        import yfinance as yf
        search = yf.Search(
            query,
            max_results=10,
            news_count=0,
            enable_fuzzy_query=True
        )
        quotes = search.quotes if hasattr(search, 'quotes') else []

        results = []
        for q_item in quotes:
            # Filter to equities and ETFs only
            quote_type = q_item.get("quoteType", q_item.get("typeDisp", ""))
            if quote_type.upper() not in ("EQUITY", "ETF", "MUTUALFUND", "INDEX"):
                continue
            results.append({
                "symbol": q_item.get("symbol", ""),
                "name": q_item.get("longname") or q_item.get("shortname", ""),
                "exchange": q_item.get("exchDisp", q_item.get("exchange", "")),
                "type": quote_type,
            })

        # Never auto-navigate from yfinance results. The only auto-navigate
        # path is the known-ticker DB check above. If we reached yfinance,
        # always show results so the user can pick.
        return jsonify({"results": results, "exact_match": False})
    except Exception as e:
        logger.error(f"Error in ticker search for '{query}': {e}", exc_info=True)
        return jsonify({"results": [], "exact_match": False, "error": str(e)}), 500


@cache_data(ttl=300)
def _get_ticker_info_cached(
    ticker: str,
    user_is_admin: bool,
    auth_token: Optional[str],
    fund: Optional[str]
):
    """Get ticker info with caching (300s TTL)"""
    from postgres_client import PostgresClient
    from supabase_client import SupabaseClient

    # Initialize Supabase client with appropriate access
    if user_is_admin:
        supabase_client = SupabaseClient(use_service_role=True)
    else:
        supabase_client = SupabaseClient(user_token=auth_token) if auth_token else None

    # Initialize Postgres client
    try:
        postgres_client = PostgresClient()
    except Exception as e:
        logger.warning(f"PostgresClient initialization failed: {e}")
        postgres_client = None

    if not supabase_client and not postgres_client:
        raise ValueError("Unable to connect to databases")

    # Get ticker info
    from ticker_utils import get_ticker_info
    return get_ticker_info(ticker, supabase_client, postgres_client, fund=fund)

@app.route('/api/v2/ticker/info')
@require_auth
def api_ticker_info():
    """Get comprehensive ticker information"""
    try:
        from flask_auth_utils import get_user_id_flask
        from auth import is_admin
        import json as json_lib

        ticker = request.args.get('ticker', '').upper().strip()
        if not ticker:
            return jsonify({"error": "Ticker symbol is required"}), 400

        fund = _normalize_fund_param(request.args.get('fund'))

        # Check if user is admin
        user_is_admin = is_admin()
        from flask_auth_utils import get_supabase_access_token
        auth_token = get_supabase_access_token()

        # Get ticker info (cached)
        try:
            ticker_data = _get_ticker_info_cached(ticker, user_is_admin, auth_token, fund)
        except RecursionError:
            # Handle recursion errors specifically from cache pickling issues
            logger.error(f"RecursionError fetching ticker info for {ticker}", exc_info=True)
            return jsonify({"error": "Data structure too complex (recursion error)"}), 500

        # Helper for safe serialization
        def safe_serialize(obj, visited=None):
            if visited is None:
                visited = set()

            # Primitive types
            if obj is None or isinstance(obj, (bool, int, float, str)):
                return obj

            # Handle dates/times
            if isinstance(obj, (datetime, date, pd.Timestamp)):
                return obj.isoformat()

            # Handle circular references
            obj_id = id(obj)
            if obj_id in visited:
                return f"<Circular Reference: {type(obj).__name__}>"

            visited.add(obj_id)
            try:
                if isinstance(obj, (list, tuple)):
                    return [safe_serialize(item, visited) for item in obj]
                elif isinstance(obj, dict):
                    return {str(k): safe_serialize(v, visited) for k, v in obj.items()}
                elif hasattr(obj, 'to_dict'):  # Pandas/Numpy objects
                    return safe_serialize(obj.to_dict(), visited)
                else:
                    return str(obj)  # Fallback
            finally:
                visited.remove(obj_id)

        # Serialize explicitly
        clean_data = safe_serialize(ticker_data)

        return jsonify(clean_data)

    except Exception as e:
        logger.error(f"Error fetching ticker info: {e}", exc_info=True)
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc(),  # Show stack trace to user
            "type": type(e).__name__
        }), 500

def _serialize_ticker_meta_row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """JSON-serialize dates for ticker_meta_analysis API responses."""
    if not row:
        return None
    out: Dict[str, Any] = {}
    for key, val in row.items():
        if isinstance(val, (datetime, date)):
            out[key] = val.isoformat()
        else:
            out[key] = val
    return out


@app.route('/api/v2/ticker/<ticker>/analysis', methods=['GET'])
@require_auth
def get_ticker_analysis(ticker: str):
    """Get latest AI analysis for a ticker."""
    try:
        from postgres_client import PostgresClient

        ticker_upper = ticker.upper().strip()
        postgres = PostgresClient()

        # Get latest analysis
        result = postgres.execute_query("""
            SELECT
                ticker, analysis_type, analysis_date, data_start_date, data_end_date,
                sentiment, sentiment_score, confidence_score, themes, summary,
                analysis_text, reasoning, input_context,
                etf_changes_count, congress_trades_count, research_articles_count,
                created_at, updated_at, model_used, requested_by
            FROM ticker_analysis
            WHERE ticker = %s
            ORDER BY analysis_date DESC
            LIMIT 1
        """, (ticker_upper,))

        if result:
            analysis = result[0]
            # Convert themes array to list if it's a string
            if isinstance(analysis.get('themes'), str):
                import json
                try:
                    analysis['themes'] = json.loads(analysis['themes'])
                except:
                    analysis['themes'] = []
            return jsonify(analysis)
        else:
            return jsonify({"analysis": None}), 404

    except Exception as e:
        logger.error(f"Error fetching ticker analysis for {ticker}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/v2/ticker/<ticker>/analysis-context', methods=['GET'])
@require_auth
def get_ticker_analysis_context(ticker: str):
    """Build AI analysis context preview from current ticker data."""
    try:
        from ai_skip_list_manager import AISkipListManager
        from postgres_client import PostgresClient
        from supabase_client import SupabaseClient
        from ticker_analysis_service import TickerAnalysisService

        ticker_upper = ticker.upper().strip()
        supabase = SupabaseClient(use_service_role=True)
        postgres = PostgresClient()
        skip_manager = AISkipListManager(supabase)

        service = TickerAnalysisService(None, supabase, postgres, skip_manager)
        data = service.gather_ticker_data(ticker_upper)
        context = service.format_ticker_context(data)

        return jsonify({
            'ticker': ticker_upper,
            'context': context
        })
    except Exception as e:
        logger.error(f"Error building ticker analysis context for {ticker}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/v2/ticker/<ticker>/reanalyze', methods=['POST'])
@require_auth
def request_ticker_reanalysis(ticker: str):
    """Run a manual re-analysis for a ticker."""
    try:
        from flask_auth_utils import get_user_email_flask
        from ai_skip_list_manager import AISkipListManager
        from supabase_client import SupabaseClient
        from postgres_client import PostgresClient
        from ollama_client import get_ollama_client, OllamaClient
        from ticker_analysis_service import TickerAnalysisService
        from user_preferences import get_user_ai_model
        from settings import get_summarizing_model

        ticker_upper = ticker.upper().strip()
        user_email = get_user_email_flask() or 'anonymous'
        request_data = request.get_json(silent=True) or {}

        # Initialize clients
        supabase = SupabaseClient(use_service_role=True)
        postgres = PostgresClient()
        preferred_model = request_data.get('model') or get_user_ai_model() or get_summarizing_model()
        is_glm = str(preferred_model).startswith("glm-")
        is_webai = False
        try:
            from webai_wrapper import is_webai_model
            is_webai = is_webai_model(str(preferred_model))
        except Exception:
            is_webai = False

        ollama = get_ollama_client()
        if not ollama and (is_glm or is_webai):
            # GLM/WebAI routes don't require local Ollama availability.
            ollama = OllamaClient()
        if not ollama:
            return jsonify({'error': 'Ollama is not accessible. Please ensure Ollama is running.'}), 503

        # Remove from skip list if present
        skip_manager = AISkipListManager(supabase)
        skip_manager.remove_from_skip_list(ticker_upper)

        # Run analysis immediately using user's preferred model
        service = TickerAnalysisService(ollama, supabase, postgres, skip_manager)
        service.analyze_ticker(ticker_upper, requested_by=user_email, model_override=preferred_model)

        logger.info(f"Completed manual re-analysis for {ticker_upper} by {user_email}")

        return jsonify({
            'status': 'completed',
            'message': f'Re-analysis completed for {ticker_upper}.'
        })

    except Exception as e:
        logger.error(f"Error running re-analysis for {ticker}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/v2/ticker/<ticker>/meta-analysis', methods=['GET'])
@require_auth
def get_ticker_meta_analysis(ticker: str):
    """Latest per-ticker meta synthesis (reconciles stored AI artifacts)."""
    try:
        from meta_analysis_service import TickerMetaAnalysisService
        from postgres_client import PostgresClient
        from supabase_client import SupabaseClient

        ticker_upper = ticker.upper().strip()
        postgres = PostgresClient()
        supabase = SupabaseClient(use_service_role=True)
        service = TickerMetaAnalysisService(
            ollama=None,
            supabase=supabase,
            postgres=postgres,
        )
        row = service.fetch_meta_row(ticker_upper)
        return jsonify({"meta": _serialize_ticker_meta_row(row)})
    except Exception as e:
        err = str(e).lower()
        if "ticker_meta_analysis" in err or "does not exist" in err:
            logger.warning("ticker_meta_analysis table missing: %s", e)
            return jsonify(
                {
                    "meta": None,
                    "error": "Meta analysis table not installed. Apply database/schema/research/tables/ticker_meta_analysis.sql",
                }
            ), 503
        logger.error("Error fetching meta analysis for %s: %s", ticker, e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/v2/ticker/<ticker>/meta-analysis/rebuild', methods=['POST'])
@require_auth
def rebuild_ticker_meta_analysis(ticker: str):
    """Run meta synthesis now (uses stored artifacts only)."""
    try:
        from flask_auth_utils import get_user_email_flask
        from meta_analysis_service import TickerMetaAnalysisService
        from ollama_client import OllamaClient, get_ollama_client
        from postgres_client import PostgresClient
        from supabase_client import SupabaseClient
        from user_preferences import get_user_ai_model
        from settings import get_summarizing_model

        ticker_upper = ticker.upper().strip()
        user_email = get_user_email_flask() or "anonymous"
        body = request.get_json(silent=True) or {}
        preferred_model = body.get("model") or get_user_ai_model() or get_summarizing_model()
        is_glm = str(preferred_model).startswith("glm-")
        is_webai = False
        try:
            from webai_wrapper import is_webai_model

            is_webai = is_webai_model(str(preferred_model))
        except Exception:
            is_webai = False

        ollama = get_ollama_client()
        if not ollama and (is_glm or is_webai):
            ollama = OllamaClient()
        if not ollama:
            return jsonify({"error": "AI backend not available (Ollama/GLM)."}), 503

        supabase = SupabaseClient(use_service_role=True)
        postgres = PostgresClient()
        service = TickerMetaAnalysisService(ollama, supabase, postgres)
        row = service.run_meta_analysis(
            ticker_upper,
            requested_by=user_email,
            model_override=preferred_model,
            force=True,
        )
        if not row:
            return jsonify(
                {"error": "Meta analysis could not run (no standard ticker_analysis or LLM failure)."}
            ), 400
        return jsonify(
            {
                "status": "completed",
                "meta": _serialize_ticker_meta_row(row),
            }
        )
    except Exception as e:
        err = str(e).lower()
        if "ticker_meta_analysis" in err or "does not exist" in err:
            return jsonify(
                {
                    "error": "Meta analysis table not installed. Apply database/schema/research/tables/ticker_meta_analysis.sql",
                }
            ), 503
        logger.error("Error rebuilding meta analysis for %s: %s", ticker, e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@cache_data(ttl=300)
def _get_ticker_price_history_cached(
    ticker: str,
    days: int,
    user_is_admin: bool,
    auth_token: Optional[str],
    fund: Optional[str],
    price_source: str = "auto",
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
):
    """Get ticker price history with caching (300s TTL)"""
    from supabase_client import SupabaseClient

    if user_is_admin:
        supabase_client = SupabaseClient(use_service_role=True)
    else:
        supabase_client = SupabaseClient(user_token=auth_token) if auth_token else None

    if not supabase_client:
        raise ValueError("Unable to connect to database")

    from ticker_utils import get_ticker_price_history
    return get_ticker_price_history(
        ticker,
        supabase_client,
        days=days,
        fund=fund,
        price_source=price_source,
        year_from=year_from,
        year_to=year_to,
    )

@app.route('/api/v2/ticker/price-history')
@require_auth
def api_ticker_price_history():
    """Get price history for a ticker"""
    try:
        from auth import is_admin

        ticker = request.args.get('ticker', '').upper().strip()
        if not ticker:
            return jsonify({"error": "Ticker symbol is required"}), 400

        from ticker_chart_ranges import normalize_ticker_chart_range, ticker_chart_range_days

        range_param = (request.args.get("range") or "").strip()
        if range_param:
            chart_range = normalize_ticker_chart_range(range_param)
            days = ticker_chart_range_days(chart_range)
        else:
            days = int(request.args.get('days', 90))

        price_source, year_from, year_to = _ticker_price_request_params()

        fund = _normalize_fund_param(request.args.get('fund'))
        user_is_admin = is_admin()
        from flask_auth_utils import get_supabase_access_token
        auth_token = get_supabase_access_token()

        # Get price history (cached)
        price_df = _get_ticker_price_history_cached(
            ticker,
            days,
            user_is_admin,
            auth_token,
            fund,
            price_source=price_source,
            year_from=year_from,
            year_to=year_to,
        )

        # Convert DataFrame to JSON
        if price_df.empty:
            return jsonify({"data": []})

        # Convert dates to ISO strings
        price_df = price_df.copy()
        if 'date' in price_df.columns:
            price_df['date'] = price_df['date'].apply(lambda x: x.isoformat() if hasattr(x, 'isoformat') else str(x))

        return jsonify({"data": price_df.to_dict('records')})
    except Exception as e:
        logger.error(f"Error fetching price history: {e}", exc_info=True)
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc(),
            "type": type(e).__name__
        }), 500

@cache_data(ttl=300)
def _get_ticker_chart_data_cached(
    ticker: str,
    use_solid: bool,
    user_is_admin: bool,
    auth_token: Optional[str],
    fund: Optional[str],
    range: str = '3m',
    price_source: str = 'auto',
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
):
    """Get ticker chart data with caching (300s TTL) - theme applied separately"""
    from supabase_client import SupabaseClient

    if user_is_admin:
        supabase_client = SupabaseClient(use_service_role=True)
    else:
        supabase_client = SupabaseClient(user_token=auth_token) if auth_token else None

    if not supabase_client:
        raise ValueError("Unable to connect to database")

    from ticker_chart_ranges import normalize_ticker_chart_range, ticker_chart_range_days

    chart_range = normalize_ticker_chart_range(range)
    range_days = ticker_chart_range_days(chart_range)
    range_label = _chart_figure_range_label(year_from, year_to)

    from ticker_utils import get_ticker_price_history
    price_df = get_ticker_price_history(
        ticker,
        supabase_client,
        days=range_days,
        fund=fund,
        price_source=price_source,
        year_from=year_from,
        year_to=year_to,
    )

    if price_df.empty:
        # Return empty chart data structure instead of raising error
        return json.dumps({
            "data": [],
            "layout": {
                "title": f"No price data available for {ticker}",
                "annotations": [{
                    "text": "Price history not available for this ticker",
                    "xref": "paper",
                    "yref": "paper",
                    "x": 0.5,
                    "y": 0.5,
                    "showarrow": False,
                    "font": {"size": 16}
                }]
            }
        })

    # Preserve full-resolution data for trade marker alignment
    full_price_df = price_df.copy()

    # Chart span for downsampling and auxiliary queries (prefer actual series dates)
    if not price_df.empty:
        dmin = pd.to_datetime(price_df['date']).min().date()
        dmax = pd.to_datetime(price_df['date']).max().date()
        span_days = max(1, (dmax - dmin).days)
        chart_start_iso = dmin.isoformat()
        chart_end_iso = dmax.isoformat()
    else:
        span_days = range_days
        chart_start_iso = (date.today() - timedelta(days=range_days)).isoformat()
        chart_end_iso = date.today().isoformat()

    # Downsample to maintain ~90 data points
    from chart_utils import downsample_price_data
    price_df = downsample_price_data(price_df, span_days)

    # Fetch congress trades for this ticker within the chart date range
    congress_trades = []
    try:
        from cache_version import get_cache_version
        refresh_key = get_cache_version()

        start_date = chart_start_iso
        end_date = chart_end_iso

        # Fetch congress trades (returns {trades: [...], total, has_more}; we need the list)
        congress_result = get_congress_trades_cached(
            supabase_client,
            refresh_key,
            ticker_filter=ticker,
            start_date=start_date,
            end_date=end_date,
            _postgres_client=None  # Not needed for basic trade data
        )
        congress_trades = congress_result.get("trades", []) if isinstance(congress_result, dict) else []
    except Exception as e:
        logger.warning(f"Error fetching congress trades for chart: {e}")
        # Continue without congress trades if there's an error

    # Fetch user trades for this ticker (no date filter - chart_utils handles
    # alignment via find_closest_price_date which skips out-of-range trades)
    user_trades = []
    try:
        trade_query = supabase_client.supabase.table("trade_log")\
            .select("*")\
            .eq("ticker", ticker)
        if fund:
            trade_query = trade_query.eq("fund", fund)
        trade_result = trade_query.order("date", desc=True).limit(200).execute()

        if trade_result.data:
            user_trades = trade_result.data
            logger.info(f"📊 Chart {ticker}: fetched {len(user_trades)} user trades (fund={fund})")
        else:
            logger.info(f"📊 Chart {ticker}: no user trades found (fund={fund})")
    except Exception as e:
        logger.warning(f"Error fetching user trades for chart: {e}")
        # Continue without user trades if there's an error

    # Fetch ETF trades for this ticker within the chart date range (from Research DB)
    etf_trades = []
    try:
        from postgres_client import PostgresClient
        pc = PostgresClient()

        start_date = chart_start_iso
        end_date = chart_end_iso

        etf_result = pc.execute_query("""
            SELECT * FROM get_etf_holding_trades(%s, %s::date, %s::date)
        """, (ticker, start_date, end_date))

        if etf_result:
            etf_trades = etf_result
    except Exception as e:
        logger.warning(f"Error fetching ETF trades for chart: {e}")
        # Continue without ETF trades if there's an error

    # Create chart WITHOUT template - theme applied post-cache
    # Using theme=None tells create_ticker_price_chart to skip template embedding
    from chart_utils import create_ticker_price_chart
    all_benchmarks = ['sp500', 'qqq', 'russell2000', 'vti']
    fig = create_ticker_price_chart(
        price_df,
        ticker,
        show_benchmarks=all_benchmarks,
        show_weekend_shading=True,
        use_solid_lines=use_solid,
        theme='light',  # Base theme, will be overridden
        congress_trades=congress_trades,
        user_trades=user_trades,
        etf_trades=etf_trades,
        trade_price_df=full_price_df,
        chart_range=chart_range,
        chart_range_label=range_label,
    )

    # Serialize with numpy array conversion for proper JSON encoding
    from plotly_utils import serialize_plotly_figure
    return serialize_plotly_figure(fig)


def _get_ticker_chart_cached(
    ticker: str,
    use_solid: bool,
    user_is_admin: bool,
    auth_token: Optional[str],
    fund: Optional[str],
    theme: Optional[str] = None,
    range: str = '3m',
    price_source: str = 'auto',
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
):
    """Get ticker chart with theme applied dynamically (not cached per theme)"""
    import json

    # Get cached chart data (without theme)
    chart_json_str = _get_ticker_chart_data_cached(
        ticker,
        use_solid,
        user_is_admin,
        auth_token,
        fund,
        range,
        price_source,
        year_from,
        year_to,
    )

    # Parse the JSON
    chart_data = json.loads(chart_json_str)

    # Determine theme to use
    if not theme or theme not in ['dark', 'light', 'midnight-tokyo', 'abyss']:
        try:
            from user_preferences import get_user_theme
            user_theme = get_user_theme() or 'system'
            theme = user_theme if user_theme in ['dark', 'light', 'midnight-tokyo', 'abyss'] else 'light'
        except Exception as e:
            logger.warning(f"Error getting user theme, defaulting to 'light': {e}")
            theme = 'light'

    # Apply theme to the chart data
    from chart_utils import get_chart_theme_config
    theme_config = get_chart_theme_config(theme)

    # Update layout for theme
    if 'layout' in chart_data:
        # Set template name (Plotly.js will look it up)
        chart_data['layout']['template'] = theme_config['template']

        # Explicitly set background colors (these override any embedded template colors)
        chart_data['layout']['paper_bgcolor'] = theme_config['paper_bgcolor']
        chart_data['layout']['plot_bgcolor'] = theme_config['plot_bgcolor']
        chart_data['layout']['font'] = {'color': theme_config['font_color']}

        # Update grid colors for both axes if they exist
        if 'xaxis' in chart_data['layout']:
            chart_data['layout']['xaxis']['gridcolor'] = theme_config['grid_color']
            chart_data['layout']['xaxis']['zerolinecolor'] = theme_config['grid_color']
        if 'yaxis' in chart_data['layout']:
            chart_data['layout']['yaxis']['gridcolor'] = theme_config['grid_color']
            chart_data['layout']['yaxis']['zerolinecolor'] = theme_config['grid_color']

        # Update legend background if it exists
        if 'legend' in chart_data['layout']:
            chart_data['layout']['legend']['bgcolor'] = theme_config['legend_bg_color']

        # Update shapes (baseline line and weekend shading)
        if 'shapes' in chart_data['layout']:
            for shape in chart_data['layout']['shapes']:
                if shape.get('type') == 'line' and shape.get('y0') == shape.get('y1'):
                    # This is the baseline hline
                    if 'line' in shape:
                        shape['line']['color'] = theme_config['baseline_line_color']
                elif shape.get('type') == 'rect' and 'fillcolor' in shape:
                    # This is weekend shading
                    shape['fillcolor'] = theme_config['weekend_shading_color']

    # Convert numpy arrays to Python lists using shared utility
    from plotly_utils import convert_numpy_to_list

    chart_data = convert_numpy_to_list(chart_data)

    # Return as JSON string
    return json.dumps(chart_data)

@cache_data(ttl=300)
def _get_ticker_etf_trades_cached(
    ticker: str,
    user_is_admin: bool,
    auth_token: Optional[str],
    range: str = '3m',
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
):
    """Get ETF holding trades for a ticker within a date range (300s TTL).

    Data is fetched from Research DB (not Supabase).
    """
    from postgres_client import PostgresClient
    from ticker_chart_ranges import normalize_ticker_chart_range, ticker_chart_range_days

    if year_from is not None and year_to is not None:
        yfa = min(year_from, year_to)
        ytb = max(year_from, year_to)
        start_date = date(yfa, 1, 1).isoformat()
        end_cap = date(ytb, 12, 31)
        today_d = date.today()
        end_date = min(end_cap, today_d).isoformat()
    else:
        range_days = ticker_chart_range_days(normalize_ticker_chart_range(range))
        start_date = (date.today() - timedelta(days=range_days)).isoformat()
        end_date = date.today().isoformat()

    pc = PostgresClient()
    result = pc.execute_query("""
        SELECT * FROM get_etf_holding_trades(%s, %s::date, %s::date)
    """, (ticker, start_date, end_date))

    return result or []

@app.route('/api/v2/ticker/chart')
@require_auth
def api_ticker_chart():
    """Get Plotly chart JSON for ticker price history"""
    try:
        from auth import is_admin

        ticker = request.args.get('ticker', '').upper().strip()
        if not ticker:
            return jsonify({"error": "Ticker symbol is required"}), 400

        use_solid = request.args.get('use_solid', 'false').lower() == 'true'
        fund = _normalize_fund_param(request.args.get('fund'))
        # Get theme from request (client detects actual page theme)
        client_theme = request.args.get('theme', '').strip().lower()
        # Get range from request (default: 3m)
        from ticker_chart_ranges import normalize_ticker_chart_range

        chart_range = normalize_ticker_chart_range(request.args.get('range', '3m'))
        price_source, year_from, year_to = _ticker_price_request_params()

        user_is_admin = is_admin()
        from flask_auth_utils import get_supabase_access_token
        auth_token = get_supabase_access_token()

        # Get chart (cached) - use client theme if valid, otherwise fall back to user preference
        chart_json = _get_ticker_chart_cached(
            ticker,
            use_solid,
            user_is_admin,
            auth_token,
            fund,
            theme=client_theme if client_theme in ['dark', 'light'] else None,
            range=chart_range,
            price_source=price_source,
            year_from=year_from,
            year_to=year_to,
        )
        return Response(chart_json, mimetype='application/json')
    except Exception as e:
        logger.error(f"Error generating chart for {ticker}: {e}", exc_info=True)
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc(),
            "type": type(e).__name__
        }), 500

@app.route('/api/v2/ticker/etf-trades')
@require_auth
def api_ticker_etf_trades():
    """Get ETF holding trades for a ticker (range-aware)."""
    try:
        from auth import is_admin

        ticker = request.args.get('ticker', '').upper().strip()
        if not ticker:
            return jsonify({"error": "Ticker symbol is required"}), 400

        from ticker_chart_ranges import normalize_ticker_chart_range

        chart_range = normalize_ticker_chart_range(request.args.get('range', '3m'))
        _, year_from, year_to = _ticker_price_request_params()

        user_is_admin = is_admin()
        auth_token = request.cookies.get('auth_token')

        trades = _get_ticker_etf_trades_cached(
            ticker,
            user_is_admin,
            auth_token,
            chart_range,
            year_from=year_from,
            year_to=year_to,
        )
        return jsonify({"data": trades})
    except Exception as e:
        logger.error(f"Error fetching ETF trades for {ticker}: {e}", exc_info=True)
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc(),
            "type": type(e).__name__
        }), 500

@app.route('/api/v2/ticker/external-links')
@require_auth
def api_ticker_external_links():
    """Get external links for a ticker"""
    try:
        ticker = request.args.get('ticker', '').upper().strip()
        if not ticker:
            return jsonify({"error": "Ticker symbol is required"}), 400

        exchange = request.args.get('exchange', None)

        from ticker_utils import get_ticker_external_links
        links = get_ticker_external_links(ticker, exchange=exchange)

        return jsonify(links)
    except Exception as e:
        logger.error(f"Error fetching external links for {ticker}: {e}")
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc(),
            "type": type(e).__name__
        }), 500


# ============================================================================
# Congress Trades Routes (Flask v2)
# ============================================================================

@cache_resource
def get_postgres_client_congress():
    """Get PostgreSQL client instance for congress trades analysis data"""
    try:
        from postgres_client import PostgresClient
        return PostgresClient()
    except Exception as e:
        logger.warning(f"PostgreSQL not available (AI analysis disabled): {e}")
        return None

@cache_data(ttl=3600)
def get_unique_tickers_congress(_supabase_client, refresh_key: int, _cache_version: Optional[str] = None) -> List[str]:
    """Get all unique tickers from congress_trades table (cached 1 hour).

    Uses RPC SELECT DISTINCT with parallel chunk fallback.
    """
    if _cache_version is None:
        try:
            from cache_version import get_cache_version
            _cache_version = get_cache_version()
        except ImportError:
            _cache_version = ""

    from flask_data_utils import fetch_unique_column_values_parallel
    return fetch_unique_column_values_parallel(
        _supabase_client, 'congress_trades_enriched', 'ticker'
    )

@cache_data(ttl=3600)
def get_unique_politicians_congress(_supabase_client, refresh_key: int, _cache_version: Optional[str] = None) -> List[str]:
    """Get all unique politicians from congress_trades table (cached 1 hour).

    Uses RPC SELECT DISTINCT with parallel chunk fallback.
    """
    if _cache_version is None:
        try:
            from cache_version import get_cache_version
            _cache_version = get_cache_version()
        except ImportError:
            _cache_version = ""

    from flask_data_utils import fetch_unique_column_values_parallel
    return fetch_unique_column_values_parallel(
        _supabase_client, 'congress_trades_enriched', 'politician'
    )

@cache_data(ttl=60)
def get_analysis_data_congress(_postgres_client, refresh_key: int) -> Dict[int, Dict[str, Any]]:
    """Get AI analysis data from PostgreSQL (cached 60s)"""
    if _postgres_client is None:
        return {}

    try:
        result = _postgres_client.execute_query(
            "SELECT trade_id, conflict_score, reasoning, model_used, analyzed_at FROM congress_trades_analysis WHERE conflict_score IS NOT NULL ORDER BY analyzed_at DESC"
        )

        analysis_map = {}
        for row in result:
            trade_id = row['trade_id']
            if trade_id not in analysis_map:
                analysis_map[trade_id] = row

        return analysis_map
    except Exception as e:
        logger.error(f"Error fetching analysis data: {e}")
        return {}

@cache_data(ttl=21600)
def get_congress_trades_cached(
    _supabase_client,
    refresh_key: int,
    ticker_filter: Optional[str] = None,
    politician_filter: Optional[str] = None,
    chamber_filter: Optional[str] = None,
    type_filter: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    analyzed_only: bool = False,
    unanalyzed_only: bool = False,
    min_score: Optional[float] = None,
    max_score: Optional[float] = None,
    _postgres_client = None,
    sort_by: Optional[str] = None,
    sort_dir: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> Dict[str, Any]:
    """Get congress trades with filters and pagination (cached 6 hours).
    
    Returns a dict with:
        - trades: List of trade records for the requested page
        - total: Total count of matching records
        - has_more: Whether there are more records after this page
    """
    try:
        if _supabase_client is None:
            return {"trades": [], "total": 0, "has_more": False}

        # Build base filter function for reuse
        def apply_filters(q):
            if ticker_filter:
                q = q.eq("ticker", ticker_filter)
            if politician_filter:
                q = q.eq("politician", politician_filter)
            if chamber_filter:
                q = q.eq("chamber", chamber_filter)
            if type_filter:
                q = q.eq("type", type_filter)
            if start_date:
                q = q.gte("transaction_date", start_date)
            if end_date:
                q = q.lte("transaction_date", end_date)
            return q

        sort_map = {
            "Ticker": "ticker",
            "Politician": "politician",
            "Chamber": "chamber",
            "Party": "party",
            "State": "state",
            "Date": "transaction_date",
            "Type": "type",
            "Amount": "amount",
            "Return": "pct_change",
            "Owner": "owner"
        }
        sort_column = sort_map.get(sort_by or "", "transaction_date")
        sort_direction = (sort_dir or "desc").lower()
        if sort_direction not in ("asc", "desc"):
            sort_direction = "desc"

        # NULLs should always sort last so that real data appears first
        sort_nullsfirst = False

        # Get analysis data for filtering (needed for analyzed_only and score filters)
        analysis_map = get_analysis_data_congress(_postgres_client, refresh_key) if _postgres_client else {}

        # Check if we need post-filtering (analysis-based filters require fetching all and filtering)
        needs_post_filter = analyzed_only or unanalyzed_only or min_score is not None or max_score is not None

        if needs_post_filter:
            # For analysis-based filters, we must fetch all matching trades first, then filter and paginate
            query = _supabase_client.supabase.table("congress_trades_enriched").select(
                "id, ticker, politician, chamber, party, state, transaction_date, disclosure_date, type, amount, owner, pct_change"
            )
            query = apply_filters(query)
            query = query.order("transaction_date", desc=True).order("id", desc=True)

            # Fetch all rows (with batching due to Supabase 1000 row limit)
            all_trades = []
            batch_size = 1000
            batch_offset = 0

            while True:
                result = query.range(batch_offset, batch_offset + batch_size - 1).execute()
                if not result.data:
                    break
                all_trades.extend(result.data)
                if len(result.data) < batch_size:
                    break
                batch_offset += batch_size
                if batch_offset > 100000:
                    logger.warning("Reached 100,000 row safety limit in get_congress_trades_cached pagination")
                    break

            # Post-process: filter by analysis status and score
            filtered_trades = []
            for trade in all_trades:
                trade_id = trade.get('id')

                if analyzed_only and trade_id not in analysis_map:
                    continue
                if unanalyzed_only and trade_id in analysis_map:
                    continue

                if min_score is not None or max_score is not None:
                    analysis = analysis_map.get(trade_id)
                    if not analysis or analysis.get('conflict_score') is None:
                        continue
                    score_val = float(analysis['conflict_score'])
                    if min_score is not None and score_val < min_score:
                        continue
                    if max_score is not None and score_val >= max_score:
                        continue

                filtered_trades.append(trade)

            def _parse_amount_max(amount_value: Optional[str]) -> float:
                if not amount_value or not isinstance(amount_value, str):
                    return 0.0
                lower = amount_value.lower()
                if "over" in lower or ">" in lower:
                    match = re.search(r"\$?([\d,]+)", lower)
                    if match:
                        try:
                            return float(match.group(1).replace(",", ""))
                        except ValueError:
                            return 0.0
                matches = re.findall(r"\$?([\d,]+)", lower)
                if matches:
                    try:
                        return float(matches[-1].replace(",", ""))
                    except ValueError:
                        return 0.0
                return 0.0

            def _sort_key(trade: Dict[str, Any]):
                value = trade.get(sort_column)
                if sort_column in ("transaction_date", "disclosure_date"):
                    return value or ""
                if sort_column == "amount":
                    return _parse_amount_max(value)
                if sort_column == "pct_change":
                    try:
                        return float(value) if value is not None else None
                    except (ValueError, TypeError):
                        return None
                if isinstance(value, str):
                    return value.lower()
                return value or ""

            # Separate NULLs so they always sort last regardless of direction
            null_trades = [t for t in filtered_trades if _sort_key(t) is None]
            non_null_trades = [t for t in filtered_trades if _sort_key(t) is not None]
            non_null_trades.sort(
                key=_sort_key,
                reverse=(sort_direction == "desc")
            )
            filtered_trades = non_null_trades + null_trades

            total = len(filtered_trades)
            page_trades = filtered_trades[offset:offset + limit]
            has_more = (offset + limit) < total

            logger.info(f"[CongressTrades] Post-filtered: {total} total, returning {len(page_trades)} (offset={offset})")
            return {"trades": page_trades, "total": total, "has_more": has_more}

        # Standard path: use Supabase pagination directly
        # Get count first
        count_query = _supabase_client.supabase.table("congress_trades_enriched").select("id", count="exact")
        count_query = apply_filters(count_query)
        count_result = count_query.execute()
        total = count_result.count if count_result.count is not None else 0

        # Get paginated data
        query = _supabase_client.supabase.table("congress_trades_enriched").select(
            "id, ticker, politician, chamber, party, state, transaction_date, disclosure_date, type, amount, owner, pct_change"
        )
        query = apply_filters(query)
        query = query.order(sort_column, desc=(sort_direction == "desc"), nullsfirst=sort_nullsfirst).order(
            "id", desc=(sort_direction == "desc")
        )
        query = query.range(offset, offset + limit - 1)

        result = query.execute()
        trades = result.data or []
        has_more = (offset + limit) < total

        logger.info(f"[CongressTrades] Fetched {len(trades)} rows (offset={offset}, limit={limit}, total={total})")
        return {"trades": trades, "total": total, "has_more": has_more}

    except Exception as e:
        logger.error(f"Error fetching congress trades: {e}", exc_info=True)
        return {"trades": [], "total": 0, "has_more": False}

@cache_data(ttl=86400)  # Cache for 24 hours - company names don't change often
def get_company_names_map_cached(_supabase_client, tickers_tuple: tuple, _cache_version: Optional[str] = None) -> Dict[str, str]:
    """Batch fetch company names from securities table (cached 24 hours)

    Bolt Optimization: Uses ThreadPoolExecutor to fetch batches in parallel.
    """
    if _cache_version is None:
        try:
            from cache_version import get_cache_version
            _cache_version = get_cache_version()
        except ImportError:
            _cache_version = ""

    # Convert tuple back to list
    tickers = list(tickers_tuple) if tickers_tuple else []

    company_names_map = {}

    if not _supabase_client or not tickers:
        return company_names_map

    def fetch_batch(batch):
        try:
            result = _supabase_client.supabase.table("securities")\
                .select("ticker, company_name")\
                .in_("ticker", batch)\
                .execute()
            return result.data or []
        except Exception as e:
            logger.warning(f"Error fetching company names batch: {e}")
            return []

    try:
        # Split into batches of 50 (Supabase limit)
        batches = [tickers[i:i+50] for i in range(0, len(tickers), 50)]

        # Fetch in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_batch = {executor.submit(fetch_batch, batch): batch for batch in batches}
            for future in concurrent.futures.as_completed(future_to_batch):
                data = future.result()
                for item in data:
                    ticker = item.get('ticker', '').upper()
                    company_name = item.get('company_name', '')
                    if company_name and company_name.strip() and company_name != 'Unknown':
                        company_names_map[ticker] = company_name.strip()

    except Exception as e:
        logger.warning(f"Error fetching company names: {e}")

    return company_names_map

def _process_unknown_tickers_background(tickers: List[str], supabase_client):
    """Background task to fetch metadata for unknown tickers"""
    if not tickers:
        return

    try:
        from utils.ticker_utils import get_ticker_currency

        logger.info(f"Processing {len(tickers)} unknown tickers in background...")

        # Process unknown tickers in batches to avoid overwhelming the API
        for ticker in tickers:
            try:
                # Determine currency from ticker
                currency = get_ticker_currency(ticker)

                # Ensure ticker exists in securities table with company name
                # This will fetch from yfinance if needed
                success = supabase_client.ensure_ticker_in_securities(ticker, currency)
                if success:
                    logger.debug(f"Added company name for ticker {ticker} to securities table (background)")
                else:
                    logger.warning(f"Failed to add company name for ticker {ticker} (background)")
            except Exception as ticker_error:
                logger.warning(f"Error processing ticker {ticker} for company name lookup: {ticker_error}")
                continue
    except ImportError:
        logger.warning("Could not import get_ticker_currency - skipping automatic company name lookup")
    except Exception as e:
        logger.error(f"Error in background ticker processing: {e}")

def format_date_congress(d) -> str:
    """Format date for display"""
    if d is None:
        return "N/A"

    if isinstance(d, str):
        try:
            d = datetime.fromisoformat(d.split('T')[0]).date()
        except (ValueError, AttributeError, TypeError):
            return d

    if isinstance(d, date):
        return d.strftime("%Y-%m-%d")

    return str(d)

@app.route('/congress_trades')
@require_auth
def congress_trades_page():
    """Congress Trades page (Flask v2)"""
    try:
        from flask_auth_utils import get_user_email_flask, get_auth_token
        from flask_data_utils import get_supabase_client_flask
        from cache_version import get_cache_version
        from auth import is_admin

        user_email = get_user_email_flask()

        # Get refresh key from query params
        refresh_key = int(request.args.get('refresh_key', 0))

        # Get Supabase client
        if is_admin():
            from supabase_client import SupabaseClient
            supabase_client = SupabaseClient(use_service_role=True)
        else:
            supabase_client = get_supabase_client_flask()

        if supabase_client is None:
            nav_context = get_navigation_context(current_page='congress_trades')
            return render_template('congress_trades.html',
                                 user_email=user_email,
                                 error="Congress Trades Database Unavailable",
                                 error_message="The congress trades database is not available. Check the logs or contact an administrator.",
                                 **nav_context)

        # Get Postgres client
        postgres_client = get_postgres_client_congress()

        # Get filter values from query params
        chamber_filter = request.args.get('chamber', 'All')
        type_filter = request.args.get('type', 'All')
        analysis_status = request.args.get('analysis_status', 'all')  # 'all', 'analyzed', 'unanalyzed'
        analyzed_only = (analysis_status == 'analyzed')  # For backward compatibility
        unanalyzed_only = (analysis_status == 'unanalyzed')
        score_filter = request.args.get('score_filter', 'All Scores')
        ticker_filter = request.args.get('ticker', 'All')
        politician_filter = request.args.get('politician', 'All')
        use_date_filter = request.args.get('use_date_filter') == 'true'
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        # Convert filters
        chamber_filter = None if chamber_filter == 'All' else chamber_filter
        type_filter = None if type_filter == 'All' else type_filter
        ticker_filter = None if ticker_filter == 'All' else ticker_filter
        politician_filter = None if politician_filter == 'All' else politician_filter

        min_score = None
        max_score = None
        if score_filter == "High Risk (>0.7)":
            min_score = 0.7
            max_score = None
        elif score_filter == "Medium Risk (0.3-0.7)":
            min_score = 0.3
            max_score = 0.7
        elif score_filter == "Low Risk (<0.3)":
            min_score = 0.0
            max_score = 0.3

        # Get unique values for filters
        cache_version = get_cache_version()
        unique_tickers = get_unique_tickers_congress(supabase_client, refresh_key, cache_version)
        unique_politicians = get_unique_politicians_congress(supabase_client, refresh_key, cache_version)

        # Lazy load: Pass empty data initially
        trades_data = []
        total_trades = 0
        analyzed_count = 0
        unique_tickers_count = 0
        high_risk_count = 0
        house_count = 0
        senate_count = 0
        purchase_count = 0
        sale_count = 0
        most_active_display = "Loading..."

        # Get navigation context
        nav_context = get_navigation_context(current_page='congress_trades')

        return render_template('congress_trades.html',
                             user_email=user_email,
                             refresh_key=refresh_key,
                             unique_tickers=unique_tickers,
                             unique_politicians=unique_politicians,
                             trades_data=trades_data,
                             total_trades=total_trades,
                             analyzed_count=analyzed_count,
                             unique_tickers_count=unique_tickers_count,
                             high_risk_count=high_risk_count,
                             house_count=house_count,
                             senate_count=senate_count,
                             purchase_count=purchase_count,
                             sale_count=sale_count,
                             most_active_display=most_active_display,
                             # Current filter values
                             current_chamber=request.args.get('chamber', 'All'),
                             current_type=request.args.get('type', 'All'),
                             current_analysis_status=analysis_status,
                             current_analyzed_only=analyzed_only,  # Keep for backward compatibility
                             current_score_filter=score_filter,
                             current_ticker=request.args.get('ticker', 'All'),
                             current_politician=request.args.get('politician', 'All'),
                             current_use_date_filter=use_date_filter,
                             current_start_date=start_date or '',
                             current_end_date=end_date or '',
                             **nav_context)
    except Exception as e:
        logger.error(f"Error in congress trades page: {e}", exc_info=True)
        import traceback
        tb = traceback.format_exc()
        nav_context = get_navigation_context(current_page='congress_trades')
        return render_template('congress_trades.html',
                             user_email='User',
                             error=str(e),
                             error_message="An error occurred loading congress trades. Please check the logs.",
                             **nav_context), 500

@app.route('/api/congress_trades/data')
@require_auth
def api_congress_trades_data():
    """API endpoint for congress trades data (JSON) with server-side pagination.
    
    Query parameters:
        - limit: Number of records per page (default 100, max 500)
        - offset: Starting offset for pagination (default 0)
        - ticker, politician, chamber, type: Filter values
        - start_date, end_date: Date range filters
        - analysis_status: 'all', 'analyzed', or 'unanalyzed'
        - min_score, max_score: Score range filters
        - refresh_key: Cache refresh key
    
    Returns:
        - trades: List of formatted trade records for the requested page
        - total: Total count of matching records
        - next_offset: Offset for the next page (if has_more is true)
        - has_more: Whether there are more records after this page
    """
    try:
        from flask_auth_utils import get_auth_token
        from flask_data_utils import get_supabase_client_flask
        from cache_version import get_cache_version
        from auth import is_admin
        from web_dashboard.utils.logo_utils import get_ticker_logo_url

        refresh_key = int(request.args.get('refresh_key', 0))

        # Pagination parameters
        limit = min(int(request.args.get('limit', 100)), 500)  # Default 100, max 500
        offset = int(request.args.get('offset', 0))

        # Get Supabase client
        if is_admin():
            from supabase_client import SupabaseClient
            supabase_client = SupabaseClient(use_service_role=True)
        else:
            supabase_client = get_supabase_client_flask()

        if supabase_client is None:
            return jsonify({"error": "Supabase client unavailable"}), 500

        postgres_client = get_postgres_client_congress()

        # Get filter values
        ticker_filter = request.args.get('ticker')
        politician_filter = request.args.get('politician')
        chamber_filter = request.args.get('chamber')
        type_filter = request.args.get('type')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        sort_by = request.args.get('sort_by')
        sort_dir = request.args.get('sort_dir')
        analysis_status = request.args.get('analysis_status', 'all')  # 'all', 'analyzed', 'unanalyzed'
        analyzed_only = (analysis_status == 'analyzed')
        unanalyzed_only = (analysis_status == 'unanalyzed')
        min_score = request.args.get('min_score')
        max_score = request.args.get('max_score')
        min_score = float(min_score) if min_score else None
        max_score = float(max_score) if max_score else None

        # Get paginated trades
        result = get_congress_trades_cached(
            supabase_client,
            refresh_key,
            ticker_filter=ticker_filter if ticker_filter and ticker_filter != 'All' else None,
            politician_filter=politician_filter if politician_filter and politician_filter != 'All' else None,
            chamber_filter=chamber_filter if chamber_filter and chamber_filter != 'All' else None,
            type_filter=type_filter if type_filter and type_filter != 'All' else None,
            start_date=start_date,
            end_date=end_date,
            analyzed_only=analyzed_only,
            unanalyzed_only=unanalyzed_only,
            min_score=min_score,
            max_score=max_score,
            _postgres_client=postgres_client,
            sort_by=sort_by,
            sort_dir=sort_dir,
            limit=limit,
            offset=offset
        )

        trades = result["trades"]
        total = result["total"]
        has_more = result["has_more"]

        # Get analysis data
        analysis_map = get_analysis_data_congress(postgres_client, refresh_key) if postgres_client else {}

        # Get company names (cached) - optimize by only fetching for unique tickers in result
        unique_ticker_list = list(set([t.get('ticker') for t in trades if t.get('ticker')]))
        cache_version = get_cache_version()
        # Fetch company names in parallel batches using cached function
        company_names_map = get_company_names_map_cached(supabase_client, tuple(unique_ticker_list), cache_version)

        # Format trades data
        formatted_trades = []
        for trade in trades:
            ticker = trade.get('ticker', 'N/A')
            ticker_upper = ticker.upper() if ticker != 'N/A' else 'N/A'
            company_name = company_names_map.get(ticker_upper, 'N/A')

            trade_id = trade.get('id')
            analysis = analysis_map.get(trade_id, {})
            conflict_score = analysis.get('conflict_score')
            reasoning = analysis.get('reasoning', '')

            if conflict_score is not None:
                score_val = float(conflict_score)
                if score_val >= 0.7:
                    score_display = f"🔴 {score_val:.2f}"
                elif score_val >= 0.3:
                    score_display = f"🟡 {score_val:.2f}"
                else:
                    score_display = f"🟢 {score_val:.2f}"
            else:
                score_display = "⚪ N/A"

            reasoning_short = reasoning[:80] + '...' if reasoning and len(reasoning) > 80 else (reasoning or '')

            # Get logo URL for ticker
            logo_url = get_ticker_logo_url(ticker) if ticker != 'N/A' else None

            # Return % from congress_trade_returns (via enriched view)
            # For sales, invert the sign: stock going up after selling = negative
            # (opportunity cost), stock going down after selling = positive (good call)
            pct_change = trade.get('pct_change')
            if pct_change is not None:
                try:
                    pct_change = round(float(pct_change), 1)
                    if trade.get('type') == 'Sale':
                        pct_change = -pct_change
                except (ValueError, TypeError):
                    pct_change = None

            formatted_trades.append({
                'Ticker': ticker,
                'Company': company_name,
                'Politician': trade.get('politician', 'N/A'),
                'Chamber': trade.get('chamber', 'N/A'),
                'Party': trade.get('party', 'N/A'),
                'State': trade.get('state', 'N/A'),
                'Date': format_date_congress(trade.get('transaction_date')),
                'Type': trade.get('type', 'N/A'),
                'Amount': trade.get('amount', 'N/A'),
                'Return': pct_change,
                'Score': score_display,
                'AI Reasoning': reasoning_short,
                'Owner': trade.get('owner', 'N/A'),
                '_tooltip': reasoning if reasoning else reasoning_short,
                '_full_reasoning': reasoning if reasoning else '',
                '_trade_id': trade_id,  # Include trade ID for analysis
                '_logo_url': logo_url  # Include logo URL for display
            })

        response = {
            "trades": formatted_trades,
            "total": total,
            "has_more": has_more
        }
        if has_more:
            response["next_offset"] = offset + limit

        return jsonify(response)
    except ValueError as e:
        logger.error(f"Invalid parameter in congress trades API: {e}", exc_info=True)
        return jsonify({"error": f"Invalid parameter: {str(e)}"}), 400
    except Exception as e:
        logger.error(f"Error in congress trades API: {e}", exc_info=True)
        return jsonify({"error": "An error occurred while fetching congress trades data. Please check the logs."}), 500


@cache_data(ttl=300)
def _get_congress_trades_stats_cached(
    _supabase_client,
    _postgres_client,
    ticker_filter: Optional[str],
    politician_filter: Optional[str],
    chamber_filter: Optional[str],
    type_filter: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
    use_date_filter: bool,
    analysis_status: str,
    score_filter: str,
    _cache_version: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get aggregated statistics for congress trades.

    OPTIMIZATION (v2):
    Implements a Universal Parallel Fetch strategy.
    1. Uses parallel HEAD requests for metadata counts (House, Senate, etc.) when possible.
    2. Fetches full dataset IDs/Tickers in parallel batches (replacing serial fetching).
    3. Calculates analysis stats by joining IDs with Postgres cache in memory.
    4. Queries "Most Active" separately for the specific date window (last 31d).

    This provides O(1) performance for metadata counts in most views and vastly faster
    data retrieval (10x+) for the filtered set analysis.
    """
    if _supabase_client is None:
        return {"error": "Supabase client unavailable"}

    try:
        # 1. Determine Strategy
        # If Postgres-based filters are active (Risk Score/Status), we cannot use Supabase counts
        # for breakdown stats (e.g. House count) because Supabase includes all risks.
        # Otherwise, we can offload counts to Supabase parallel queries.
        use_fast_counts = (analysis_status == 'all' and score_filter == 'All Scores')

        # 2. Build Base Filters
        def _apply_filters_to_query(q):
            if ticker_filter: q = q.eq("ticker", ticker_filter)
            if politician_filter: q = q.eq("politician", politician_filter)
            if chamber_filter: q = q.eq("chamber", chamber_filter)
            if type_filter: q = q.eq("type", type_filter)
            if use_date_filter and start_date: q = q.gte("transaction_date", start_date)
            if use_date_filter and end_date: q = q.lte("transaction_date", end_date)
            return q

        # 3. Get Total Count (needed for pagination)
        base_query = _supabase_client.supabase.table("congress_trades_enriched").select("id", count="exact", head=True)
        base_query = _apply_filters_to_query(base_query)
        count_result = base_query.execute()
        total_filtered_rows = count_result.count if count_result.count is not None else 0

        if total_filtered_rows == 0:
            return {
                "total_trades": 0, "analyzed_count": 0, "house_count": 0, "senate_count": 0,
                "purchase_count": 0, "sale_count": 0, "unique_tickers_count": 0,
                "high_risk_count": 0, "most_active_display": "N/A"
            }

        # 4. Execute Parallel Tasks
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = {}

            # A. Parallel Counts (if applicable)
            if use_fast_counts:
                def _get_sb_count(col=None, val=None, vals=None):
                    q = _supabase_client.supabase.table("congress_trades_enriched").select("id", count="exact", head=True)
                    q = _apply_filters_to_query(q)
                    if col:
                        if vals: q = q.in_(col, vals)
                        elif val: q = q.eq(col, val)
                    res = q.execute()
                    return res.count if res.count is not None else 0

                futures['house'] = executor.submit(_get_sb_count, 'chamber', 'House')
                futures['senate'] = executor.submit(_get_sb_count, 'chamber', 'Senate')
                futures['purchase'] = executor.submit(_get_sb_count, 'type', 'Purchase')
                futures['sale'] = executor.submit(_get_sb_count, 'type', None, ['Sale', 'Sale (Full)', 'Sale (Partial)'])

            # B. Parallel Data Fetch (IDs + Tickers + optional columns)
            # If we can't use fast counts, we need chamber/type to count in Python
            cols = "id, ticker" if use_fast_counts else "id, ticker, chamber, type"

            def _fetch_chunk(offset, chunk_size):
                q = _supabase_client.supabase.table("congress_trades_enriched").select(cols)
                q = _apply_filters_to_query(q)
                # Order by ID to ensure stable pagination
                q = q.order("id")
                return q.range(offset, offset + chunk_size - 1).execute().data

            chunk_size = 5000
            num_chunks = (total_filtered_rows // chunk_size) + 1
            fetch_futures = [executor.submit(_fetch_chunk, i * chunk_size, chunk_size) for i in range(num_chunks)]

            # C. Most Active (Last 31 Days)
            def _get_most_active():
                cutoff = (datetime.now() - timedelta(days=31)).strftime('%Y-%m-%d')
                q = _supabase_client.supabase.table("congress_trades_enriched").select("politician, owner")
                q = _apply_filters_to_query(q)
                q = q.gte("transaction_date", cutoff).limit(1000)
                return q.execute().data

            futures['most_active'] = executor.submit(_get_most_active)

            # --- Gather Results (each with individual error handling) ---

            # 1. Collect Fetched Rows
            fetched_rows = []
            for f in concurrent.futures.as_completed(fetch_futures):
                try:
                    data = f.result()
                    if data:
                        fetched_rows.extend(data)
                except Exception as e:
                    logger.warning(f"[CongressStats] Chunk fetch failed: {e}")

            # 2. Collect Counts
            house_count = 0
            senate_count = 0
            purchase_count = 0
            sale_count = 0
            for key in ['house', 'senate', 'purchase', 'sale']:
                if key in futures:
                    try:
                        val = futures[key].result()
                        if key == 'house': house_count = val
                        elif key == 'senate': senate_count = val
                        elif key == 'purchase': purchase_count = val
                        elif key == 'sale': sale_count = val
                    except Exception as e:
                        logger.warning(f"[CongressStats] {key} count failed, defaulting to 0: {e}")

            # 3. Collect Most Active
            recent_trades = []
            try:
                if 'most_active' in futures:
                    recent_trades = futures['most_active'].result() or []
            except Exception as e:
                logger.warning(f"[CongressStats] Most active fetch failed: {e}")

        # D. Fetch Analysis Data scoped to collected trade IDs (after rows are available)
        pg_analysis_map = {}
        if _postgres_client and fetched_rows:
            try:
                trade_ids = [r['id'] for r in fetched_rows if r.get('id')]
                if trade_ids:
                    for i in range(0, len(trade_ids), 10000):
                        batch = trade_ids[i:i + 10000]
                        pg_res = _postgres_client.execute_query(
                            "SELECT trade_id, conflict_score FROM congress_trades_analysis "
                            "WHERE trade_id = ANY(%s) AND conflict_score IS NOT NULL",
                            (batch,)
                        )
                        for r in pg_res:
                            pg_analysis_map[r['trade_id']] = r['conflict_score']
            except Exception as e:
                logger.warning(f"[CongressStats] Postgres analysis fetch failed: {e}")

        # 5. Process Fetched Data (Intersection & Python Counts)
        final_trades = []
        unique_tickers = set()

        # Helper for score filtering
        def _matches_score_filter(score):
            if score_filter == "High Risk (>0.7)": return score >= 0.7
            if score_filter == "Medium Risk (0.3-0.7)": return 0.3 <= score < 0.7
            if score_filter == "Low Risk (<0.3)": return score < 0.3
            return True

        # Process rows
        for row in fetched_rows:
            tid = row.get('id')
            score = pg_analysis_map.get(tid)
            has_analysis = score is not None

            # Apply Postgres Filters (if any)
            if analysis_status == 'analyzed' and not has_analysis: continue
            if analysis_status == 'unanalyzed' and has_analysis: continue
            if score_filter != 'All Scores':
                if not has_analysis or not _matches_score_filter(score): continue

            final_trades.append(row)
            if row.get('ticker'):
                unique_tickers.add(row['ticker'])

        # Recalculate stats based on final filtered set
        total_trades = len(final_trades)
        analyzed_count = sum(1 for r in final_trades if r.get('id') in pg_analysis_map)
        high_risk_count = sum(1 for r in final_trades if r.get('id') in pg_analysis_map and pg_analysis_map[r['id']] >= 0.7)

        # If not using fast counts, compute breakdown in Python from final set
        if not use_fast_counts:
            house_count = sum(1 for r in final_trades if r.get('chamber') == 'House')
            senate_count = sum(1 for r in final_trades if r.get('chamber') == 'Senate')
            purchase_count = sum(1 for r in final_trades if r.get('type') == 'Purchase')
            sale_count = sum(1 for r in final_trades if r.get('type') in ('Sale', 'Sale (Full)', 'Sale (Partial)'))

        # 6. Process Most Active (Last 31 Days)
        most_active_display = "N/A"
        if recent_trades:
            politician_counts = {}
            for t in recent_trades:
                if t.get('owner', '').lower() in ('spouse', 'child', 'dependent'):
                    continue
                pol = t.get('politician', 'Unknown')
                politician_counts[pol] = politician_counts.get(pol, 0) + 1

            if politician_counts:
                top = max(politician_counts.items(), key=lambda x: x[1])
                most_active_display = f"{top[0]} ({top[1]})"

        logger.info(f"[CongressStats] Optimized fetch complete. Total: {total_trades}")

        return {
            "total_trades": total_trades,
            "analyzed_count": analyzed_count,
            "house_count": house_count,
            "senate_count": senate_count,
            "purchase_count": purchase_count,
            "sale_count": sale_count,
            "unique_tickers_count": len(unique_tickers),
            "high_risk_count": high_risk_count,
            "most_active_display": most_active_display
        }

    except Exception as e:
        logger.error(f"[CongressStats] Error in optimized stats: {e}", exc_info=True)
        return {
            "total_trades": 0, "analyzed_count": 0, "house_count": 0, "senate_count": 0,
            "purchase_count": 0, "sale_count": 0, "unique_tickers_count": 0,
            "high_risk_count": 0, "most_active_display": "Error"
        }


@app.route('/api/congress_trades/stats')
@require_auth
def api_congress_trades_stats():
    """API endpoint for congress trades aggregated statistics (JSON)"""
    try:
        from flask_data_utils import get_supabase_client_flask
        from cache_version import get_cache_version
        from auth import is_admin

        # Get Supabase client
        if is_admin():
            from supabase_client import SupabaseClient
            supabase_client = SupabaseClient(use_service_role=True)
        else:
            supabase_client = get_supabase_client_flask()

        if supabase_client is None:
            return jsonify({"error": "Supabase client unavailable"}), 500

        postgres_client = get_postgres_client_congress()

        # Get filter values
        ticker_filter = request.args.get('ticker')
        politician_filter = request.args.get('politician')
        chamber_filter = request.args.get('chamber')
        type_filter = request.args.get('type')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        use_date_filter = request.args.get('use_date_filter') == 'true'
        analysis_status = request.args.get('analysis_status', 'all')
        score_filter = request.args.get('score_filter', 'All Scores')

        # Normalize "All" values to None
        ticker_filter = None if ticker_filter in (None, '', 'All') else ticker_filter
        politician_filter = None if politician_filter in (None, '', 'All') else politician_filter
        chamber_filter = None if chamber_filter in (None, '', 'All') else chamber_filter
        type_filter = None if type_filter in (None, '', 'All') else type_filter

        cache_version = get_cache_version()

        stats = _get_congress_trades_stats_cached(
            supabase_client,
            postgres_client,
            ticker_filter,
            politician_filter,
            chamber_filter,
            type_filter,
            start_date,
            end_date,
            use_date_filter,
            analysis_status,
            score_filter,
            _cache_version=cache_version
        )

        if "error" in stats:
            return jsonify(stats), 500

        return jsonify(stats)

    except Exception as e:
        logger.error(f"Error in congress trades stats API: {e}", exc_info=True)
        return jsonify({"error": "An error occurred while fetching congress trades statistics."}), 500


@app.route('/congress_trades/positions')
@require_auth
def congress_positions_page():
    """Congress Closed Positions sub-page"""
    try:
        from flask_auth_utils import get_user_email_flask
        from cache_version import get_cache_version

        user_email = get_user_email_flask()
        nav_context = get_navigation_context(current_page='congress_trades')
        cache_version = get_cache_version()

        return render_template('congress_positions.html',
                             user_email=user_email,
                             cache_version=cache_version,
                             **nav_context)
    except Exception as e:
        logger.error(f"Error loading congress positions page: {e}", exc_info=True)
        nav_context = get_navigation_context(current_page='congress_trades')
        return render_template('congress_positions.html',
                             error="An error occurred loading the positions page.",
                             **nav_context), 500


@app.route('/api/congress_trades/positions/data')
@require_auth
def api_congress_positions_data():
    """API endpoint for closed position data (one row per politician+ticker)."""
    try:
        from flask_data_utils import get_supabase_client_flask
        from auth import is_admin
        from supabase_client import SupabaseClient

        if is_admin():
            client = SupabaseClient(use_service_role=True)
        else:
            client = get_supabase_client_flask()

        if client is None:
            return jsonify({"error": "Database unavailable"}), 503

        # Query params
        period = request.args.get('period', 'last_12m')
        politician = request.args.get('politician', '')
        sort_by = request.args.get('sort_by', 'est_pnl')
        sort_dir = request.args.get('sort_dir', 'desc')
        limit = min(int(request.args.get('limit', 500)), 2000)
        offset = int(request.args.get('offset', 0))

        # Build query - join with politicians to get name
        query = client.supabase.table("congress_positions") \
            .select("*, politicians(name, party, chamber)")

        # Period filter on first_buy_date
        if period == '2025':
            query = query.gte("first_buy_date", "2025-01-01")
        elif period == 'last_12m':
            from datetime import datetime, timedelta
            cutoff = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
            query = query.gte("first_buy_date", cutoff)
        # 'all' = no date filter

        # Status filter (only closed for now)
        query = query.eq("status", "closed")

        # Politician name filter
        if politician:
            # We can't filter on joined table easily, so we'll do it in post-processing
            pass

        # Sorting
        allowed_sorts = {
            'est_pnl': 'est_pnl',
            'pct_return': 'pct_return',
            'est_invested': 'est_invested',
            'days_held': 'days_held',
            'first_buy_date': 'first_buy_date',
            'ticker': 'ticker',
            'spy_pct_change': 'spy_pct_change',
        }
        sort_column = allowed_sorts.get(sort_by, 'est_pnl')
        is_desc = sort_dir.lower() == 'desc'
        query = query.order(sort_column, desc=is_desc, nullsfirst=False)

        query = query.range(offset, offset + limit - 1)
        result = query.execute()
        rows = result.data or []

        # Format response
        positions = []
        for row in rows:
            pol = row.get("politicians") or {}
            pol_name = pol.get("name", "Unknown")

            # Post-filter by politician name if specified
            if politician and politician.lower() not in pol_name.lower():
                continue

            positions.append({
                "id": row.get("id"),
                "politician": pol_name,
                "party": pol.get("party", ""),
                "chamber": pol.get("chamber", ""),
                "ticker": row.get("ticker", ""),
                "buy_count": row.get("buy_count", 0),
                "sell_count": row.get("sell_count", 0),
                "first_buy_date": str(row.get("first_buy_date", ""))[:10],
                "last_sell_date": str(row.get("last_sell_date", ""))[:10],
                "avg_buy_price": float(row["avg_buy_price"]) if row.get("avg_buy_price") else None,
                "avg_sell_price": float(row["avg_sell_price"]) if row.get("avg_sell_price") else None,
                "pct_return": float(row["pct_return"]) if row.get("pct_return") is not None else None,
                "est_invested": float(row["est_invested"]) if row.get("est_invested") else None,
                "est_pnl": float(row["est_pnl"]) if row.get("est_pnl") is not None else None,
                "days_held": row.get("days_held"),
                "spy_pct_change": float(row["spy_pct_change"]) if row.get("spy_pct_change") is not None else None,
            })

        return jsonify({"positions": positions, "total": len(positions)})

    except Exception as e:
        logger.error(f"Error in congress positions data API: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/congress_trades/positions/leaderboard')
@require_auth
def api_congress_positions_leaderboard():
    """API endpoint for politician-level leaderboard (aggregated from closed positions)."""
    try:
        from flask_data_utils import get_supabase_client_flask
        from auth import is_admin
        from supabase_client import SupabaseClient

        if is_admin():
            client = SupabaseClient(use_service_role=True)
        else:
            client = get_supabase_client_flask()

        if client is None:
            return jsonify({"error": "Database unavailable"}), 503

        # Query params
        period = request.args.get('period', 'last_12m')
        min_positions = int(request.args.get('min_positions', 3))
        sort_by = request.args.get('sort_by', 'total_est_pnl')
        limit = min(int(request.args.get('limit', 50)), 200)

        # Compute cutoff date from period
        cutoff_date = None
        if period == '2025':
            cutoff_date = '2025-01-01'
        elif period == 'last_12m':
            from datetime import datetime, timedelta
            cutoff_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        # Call SQL aggregate function (GROUP BY runs server-side)
        rpc_params = {'p_min_positions': min_positions}
        if cutoff_date:
            rpc_params['p_cutoff_date'] = cutoff_date

        result = client.supabase.rpc('get_politician_leaderboard', rpc_params).execute()
        leaderboard = result.data or []

        # Convert Decimal-like strings to floats for JSON serialization
        for row in leaderboard:
            for key in ('win_pct', 'avg_return_pct', 'total_est_invested', 'total_est_pnl'):
                if row.get(key) is not None:
                    row[key] = float(row[key])

        # Sort and limit (lightweight — typically <200 rows post-aggregation)
        sort_keys = {
            'total_est_pnl': lambda x: x.get('total_est_pnl') or 0,
            'win_pct': lambda x: x.get('win_pct') or 0,
            'avg_return': lambda x: x.get('avg_return_pct') or 0,
            'positions': lambda x: x.get('positions') or 0,
        }
        sort_fn = sort_keys.get(sort_by, sort_keys['total_est_pnl'])
        leaderboard.sort(key=sort_fn, reverse=True)
        leaderboard = leaderboard[:limit]

        return jsonify({"leaderboard": leaderboard, "total": len(leaderboard)})

    except Exception as e:
        logger.error(f"Error in congress positions leaderboard API: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/congress_trades/analyze', methods=['POST'])
@require_auth
def api_analyze_congress_trades():
    """API endpoint to analyze selected congress trades"""
    try:
        from flask_auth_utils import can_modify_data_flask
        from auth import is_admin

        if not can_modify_data_flask():
            return jsonify({"error": "Read-only users cannot analyze trades"}), 403

        data = request.get_json()
        if not data or 'trade_ids' not in data:
            return jsonify({"error": "Missing trade_ids in request"}), 400

        trade_ids = data.get('trade_ids', [])
        if not isinstance(trade_ids, list) or len(trade_ids) == 0:
            return jsonify({"error": "trade_ids must be a non-empty list"}), 400

        # Limit batch size to prevent overwhelming the system
        if len(trade_ids) > 50:
            return jsonify({"error": "Maximum 50 trades can be analyzed at once"}), 400

        # Get clients
        if is_admin():
            from supabase_client import SupabaseClient
            supabase_client = SupabaseClient(use_service_role=True)
        else:
            from flask_data_utils import get_supabase_client_flask
            supabase_client = get_supabase_client_flask()

        if supabase_client is None:
            return jsonify({"error": "Supabase client unavailable"}), 500

        postgres_client = get_postgres_client_congress()
        if postgres_client is None:
            return jsonify({"error": "PostgreSQL client unavailable"}), 500

        # Import analysis functions
        import sys
        from pathlib import Path
        project_root = Path(__file__).parent.parent
        sys.path.insert(0, str(project_root))
        sys.path.insert(0, str(project_root / 'web_dashboard'))

        from scripts.analyze_congress_trades_batch import (
            get_trade_context,
            analyze_trade,
            is_low_risk_asset
        )
        from ollama_client import OllamaClient
        from settings import get_summarizing_model
        from user_preferences import get_user_ai_model

        # Check Ollama
        ollama = OllamaClient()
        if not ollama or not ollama.check_health():
            return jsonify({"error": "Ollama is not accessible. Please ensure Ollama is running."}), 503

        # Get model from request, fallback to user preference, then system default
        model_name = data.get('model') or get_user_ai_model() or get_summarizing_model()

        # Fetch trades from Supabase
        result = supabase_client.supabase.table("congress_trades_enriched")\
            .select("*")\
            .in_("id", trade_ids)\
            .execute()

        if not result.data:
            return jsonify({"error": "No trades found with the provided IDs"}), 404

        trades = result.data
        processed = 0
        errors = 0
        skipped = 0

        # Process each trade
        for trade in trades:
            try:
                # Get trade context
                context = get_trade_context(supabase_client, trade)

                # Check if low-risk (skip AI analysis)
                is_low_risk, filter_reason = is_low_risk_asset(context)

                if is_low_risk:
                    # Auto-assign low conflict score
                    analysis = {
                        'conflict_score': 0.0,
                        'confidence_score': 1.0,
                        'reasoning': f"Auto-filtered: {filter_reason}"
                    }
                    skipped += 1
                else:
                    # Analyze with AI
                    analysis = analyze_trade(ollama, context, model=model_name)

                if analysis and 'conflict_score' in analysis:
                    score = float(analysis['conflict_score'])
                    confidence = float(analysis.get('confidence_score', 0.75))
                    reasoning = analysis.get('reasoning', 'No reasoning provided')

                    # Save to PostgreSQL
                    postgres_client.execute_update(
                        """
                        INSERT INTO congress_trades_analysis
                            (trade_id, conflict_score, confidence_score, reasoning, model_used, analysis_version)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (trade_id, model_used, analysis_version)
                        DO UPDATE SET
                            conflict_score = EXCLUDED.conflict_score,
                            confidence_score = EXCLUDED.confidence_score,
                            reasoning = EXCLUDED.reasoning,
                            analyzed_at = NOW()
                        """,
                        (trade['id'], score, confidence, reasoning, model_name, 1)
                    )

                    processed += 1
                else:
                    errors += 1

            except Exception as e:
                logger.error(f"Error processing trade {trade.get('id', 'unknown')}: {e}", exc_info=True)
                errors += 1

        message = f"Processed {processed} trade(s)"
        if skipped > 0:
            message += f", skipped {skipped} low-risk trade(s)"
        if errors > 0:
            message += f", {errors} error(s)"

        return jsonify({
            "success": True,
            "processed": processed,
            "skipped": skipped,
            "errors": errors,
            "message": message
        })

    except Exception as e:
        logger.error(f"Error in analyze congress trades API: {e}", exc_info=True)
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

@app.route('/api/congress_trades/preview_context', methods=['POST'])
@require_auth
def api_congress_trades_preview_context():
    """Preview the AI context for selected trades"""
    try:
        from flask_auth_utils import can_modify_data_flask
        from auth import is_admin

        if not can_modify_data_flask():
            return jsonify({"error": "Read-only users cannot preview context"}), 403

        data = request.get_json()
        if not data or 'trade_ids' not in data:
            return jsonify({"error": "Missing trade_ids in request"}), 400

        trade_ids = data.get('trade_ids', [])
        if not isinstance(trade_ids, list) or len(trade_ids) == 0:
            return jsonify({"error": "trade_ids must be a non-empty list"}), 400

        # Limit batch size
        if len(trade_ids) > 50:
            return jsonify({"error": "Maximum 50 trades can be previewed at once"}), 400

        # Get clients
        if is_admin():
            from supabase_client import SupabaseClient
            supabase_client = SupabaseClient(use_service_role=True)
        else:
            from flask_data_utils import get_supabase_client_flask
            supabase_client = get_supabase_client_flask()

        if supabase_client is None:
            return jsonify({"error": "Supabase client unavailable"}), 500

        # Import analysis functions
        import sys
        from pathlib import Path
        project_root = Path(__file__).parent.parent
        sys.path.insert(0, str(project_root))
        sys.path.insert(0, str(project_root / 'web_dashboard'))

        from scripts.analyze_congress_trades_batch import get_trade_context

        # Fetch trades from Supabase
        result = supabase_client.supabase.table("congress_trades_enriched")\
            .select("*")\
            .in_("id", trade_ids)\
            .execute()

        if not result.data:
            return jsonify({"error": "No trades found with the provided IDs"}), 404

        trades = result.data
        context_parts = []

        # Format context for each trade using PROMPT_TEMPLATE structure
        for trade in trades:
            context = get_trade_context(supabase_client, trade)

            # Format similar to PROMPT_TEMPLATE
            description_line = ""
            if context.get('description'):
                description_line = f"- Description: {context.get('description')}\n"

            context_str = f"""Analyze this trade for potential Insider Trading/Conflict of Interest.
Data:
- Politician: {context.get('politician', 'Unknown')} ({context.get('party', 'Unknown')} - {context.get('state', 'Unknown')})
- Chamber: {context.get('chamber', 'Unknown')}
- Asset Owner: {context.get('owner', 'Self')}
- Committee Assignments: {context.get('committees', 'Unknown')}
- Ticker: {context.get('ticker', 'Unknown')}
- Company: {context.get('company_name', 'Unknown')}
- Sector: {context.get('sector', 'Unknown')}
{description_line}- Date: {context.get('date', 'Unknown')}
- Type: {context.get('type', 'Unknown')}
- Amount: {context.get('amount', 'Unknown')}

Task:
Calculate a 'conflict_score' from 0.0 to 1.0 based on these rules:
1. HIGH SCORE (0.8-1.0): Direct overlap (e.g., Armed Services member buying Defense stock, spouse trades, timing near votes).
2. MEDIUM SCORE (0.4-0.7): Sector overlap or related industries.
3. LOW SCORE (0.0-0.3): Broad index funds or clearly unrelated industries.

Consider:
- Committee jurisdiction over company's sector
- Asset owner (Self vs Spouse/Dependent) - spouse trades can still be concerning
- Political party relevance to industry
- State interests (e.g., CA rep + tech stocks, TX rep + energy)

Return JSON with TWO fields:
{{
  "conflict_score": 0.95,
  "confidence_score": 0.88,
  "reasoning": "Rep. Smith (R-TX) sits on House Armed Services and bought $50k RTX. High overlap between committee jurisdiction and defense contractor."
}}

The confidence_score (0.0-1.0) indicates how certain you are about the conflict_score. Use high confidence (>0.8) for clear-cut cases, medium (0.5-0.8) for typical cases, and low (<0.5) for ambiguous situations.
"""
            context_parts.append(context_str)

        # Combine all contexts
        full_context = "\n\n---\n\n".join(context_parts)

        return jsonify({
            "success": True,
            "context": full_context,
            "char_count": len(full_context)
        })

    except Exception as e:
        logger.error(f"Error in congress trades preview context API: {e}", exc_info=True)
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

# ============================================================================
# Insider Trades Routes (Flask v2)
# ============================================================================

@cache_data(ttl=3600)
def get_unique_tickers_insider(
    _supabase_client, refresh_key: int, _cache_version: Optional[str] = None
) -> List[str]:
    """Get all unique tickers from insider_trades table (cached 1 hour).

    Uses RPC SELECT DISTINCT with parallel chunk fallback.
    """
    if _cache_version is None:
        try:
            from cache_version import get_cache_version
            _cache_version = get_cache_version()
        except ImportError:
            _cache_version = ""

    from flask_data_utils import fetch_unique_column_values_parallel
    return fetch_unique_column_values_parallel(
        _supabase_client, 'insider_trades', 'ticker'
    )


INSIDER_NAME_UPPER_TOKENS = {
    "LLC",
    "L.L.C",
    "L.L.C.",
    "LLP",
    "L.L.P",
    "L.L.P.",
    "LP",
    "L.P",
    "L.P.",
    "INC",
    "INC.",
    "CO",
    "CO.",
    "CORP",
    "CORP.",
    "LTD",
    "LTD.",
    "PLC",
    "PLC.",
    "AG",
    "S.A",
    "S.A.",
    "SA",
    "N.V",
    "N.V.",
    "NV",
    "B.V",
    "B.V.",
    "BV",
    "GMBH",
    "S.R.L",
    "S.R.L.",
    "SRL",
    "S.P.A",
    "S.P.A.",
    "SPA",
    "PTY",
    "PTY.",
    "PTE",
    "PTE.",
}

INSIDER_NAME_ROMAN_NUMERALS = {"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"}


def _title_case_insider_word(word: str) -> str:
    def _title_part(part: str) -> str:
        if not part:
            return part
        return part[0].upper() + part[1:].lower()

    return "-".join("'".join(_title_part(part) for part in segment.split("'")) for segment in word.split("-"))


def normalize_insider_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return name

    normalized_tokens = []
    for token in name.strip().split():
        prefix_match = re.match(r"^[^A-Za-z0-9]*", token)
        suffix_match = re.match(r"[^A-Za-z0-9]*$", token)
        prefix = prefix_match.group(0) if prefix_match else ""
        suffix = suffix_match.group(0) if suffix_match else ""
        core_start = len(prefix)
        core_end = len(token) - len(suffix)
        core = token[core_start:core_end]

        if not core:
            normalized_tokens.append(token)
            continue

        core_upper = core.upper()
        if (core_upper in INSIDER_NAME_UPPER_TOKENS
                or core_upper in INSIDER_NAME_ROMAN_NUMERALS
                or re.fullmatch(r"(?:[A-Za-z]\.){1,4}", core)):
            normalized_core = core_upper
        else:
            normalized_core = _title_case_insider_word(core)

        normalized_tokens.append(f"{prefix}{normalized_core}{suffix}")

    return " ".join(normalized_tokens)


@cache_data(ttl=3600)
def get_unique_insider_names(
    _supabase_client, refresh_key: int, _cache_version: Optional[str] = None
) -> List[str]:
    """Get all unique insider names from insider_trades table (cached 1 hour).

    Uses RPC SELECT DISTINCT with parallel chunk fallback.
    Applies normalize_insider_name() post-processing for display.
    """
    if _cache_version is None:
        try:
            from cache_version import get_cache_version
            _cache_version = get_cache_version()
        except ImportError:
            _cache_version = ""

    from flask_data_utils import fetch_unique_column_values_parallel
    raw_names = fetch_unique_column_values_parallel(
        _supabase_client, 'insider_trades', 'insider_name'
    )
    # Normalize and deduplicate (normalization can merge different casings)
    normalized = set()
    for name in raw_names:
        n = normalize_insider_name(name)
        if n:
            normalized.add(n)
    return sorted(normalized)


@cache_data(ttl=300)
def get_latest_insider_trade_timestamp(
    _supabase_client, refresh_key: int, _cache_version: Optional[str] = None
) -> Optional[str]:
    """Get the most recent insider trade created_at timestamp (cached 5 min)."""
    if _cache_version is None:
        try:
            from cache_version import get_cache_version
            _cache_version = get_cache_version()
        except ImportError:
            _cache_version = ""

    try:
        if _supabase_client is None:
            return None

        result = _supabase_client.supabase.table("insider_trades")\
            .select("created_at")\
            .order("created_at", desc=True)\
            .limit(1)\
            .execute()

        if result.data:
            return result.data[0].get("created_at")
    except Exception as e:
        logger.warning(f"Error fetching latest insider trade timestamp: {e}")

    return None


@cache_data(ttl=300)
def get_last_job_success_timestamp(
    job_id: str, refresh_key: int, _cache_version: Optional[str] = None
) -> Optional[datetime]:
    """Get the most recent successful execution timestamp for a scheduler job."""
    if _cache_version is None:
        try:
            from cache_version import get_cache_version
            _cache_version = get_cache_version()
        except ImportError:
            _cache_version = ""

    try:
        from scheduler.scheduler_core import get_job_logs

        logs = get_job_logs(job_id, limit=10)
        for log in logs:
            if log.get("success") and log.get("timestamp"):
                return log["timestamp"]
    except Exception as e:
        logger.warning(f"Error fetching job status for {job_id}: {e}")

    return None


@cache_data(ttl=21600)
def get_insider_trades_cached(
    _supabase_client,
    refresh_key: int,
    ticker_filters: Optional[List[str]] = None,
    type_filter: Optional[str] = None,
    insider_filter: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    min_value: Optional[float] = None,
    sort_by: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    _cache_version: Optional[str] = None
) -> Dict[str, Any]:
    """Get insider trades with filters and pagination (cached 6 hours).
    
    Returns a dict with:
        - trades: List of trade records for the requested page
        - total: Total count of matching records
        - has_more: Whether there are more records after this page
    """
    if _cache_version is None:
        try:
            from cache_version import get_cache_version
            _cache_version = get_cache_version()
        except ImportError:
            _cache_version = ""

    try:
        if _supabase_client is None:
            return {"trades": [], "total": 0, "has_more": False}

        # Build base filter function for reuse
        def apply_filters(q):
            if ticker_filters:
                q = q.in_("ticker", ticker_filters)
            if type_filter:
                q = q.eq("type", type_filter)
            if insider_filter:
                q = q.ilike("insider_name", f"%{insider_filter}%")
            if start_date:
                q = q.gte("transaction_date", start_date)
            if end_date:
                q = q.lte("transaction_date", end_date)
            if min_value is not None:
                q = q.gte("value", min_value)
            return q

        sort_column = "transaction_date"
        if sort_by == "Value":
            sort_column = "value"
        elif sort_by == "Shares":
            sort_column = "shares"

        # Get count first
        count_query = _supabase_client.supabase.table("insider_trades").select("ticker", count="exact")
        count_query = apply_filters(count_query)
        count_result = count_query.execute()
        total = count_result.count if count_result.count is not None else 0

        # Get paginated data
        query = _supabase_client.supabase.table("insider_trades").select(
            "ticker, insider_name, insider_title, transaction_date, disclosure_date, "
            "type, shares, price_per_share, value, shares_held_after, percent_change"
        )
        query = apply_filters(query)
        query = query.order(sort_column, desc=True)
        query = query.range(offset, offset + limit - 1)

        result = query.execute()
        trades = result.data or []
        has_more = (offset + limit) < total

        logger.info(f"[InsiderTrades] Fetched {len(trades)} rows (offset={offset}, limit={limit}, total={total})")
        return {"trades": trades, "total": total, "has_more": has_more}
    except Exception as e:
        logger.error(f"Error fetching insider trades: {e}", exc_info=True)
        return {"trades": [], "total": 0, "has_more": False}


@app.route('/insider_trades')
@require_auth
def insider_trades_page():
    """Insider Trades page (Flask v2)"""
    try:
        from flask_auth_utils import get_user_email_flask
        from flask_data_utils import get_supabase_client_flask
        from user_preferences import format_timestamp_in_user_timezone
        from cache_version import get_cache_version
        from auth import is_admin

        user_email = get_user_email_flask()

        refresh_key = int(request.args.get("refresh_key", 0))

        if is_admin():
            from supabase_client import SupabaseClient
            supabase_client = SupabaseClient(use_service_role=True)
        else:
            supabase_client = get_supabase_client_flask()

        if supabase_client is None:
            nav_context = get_navigation_context(current_page='insider_trades')
            return render_template('insider_trades.html',
                                 user_email=user_email,
                                 error="Insider Trades Database Unavailable",
                                 error_message="The insider trades database is not available. Check the logs or contact an administrator.",
                                 **nav_context)

        cache_version = get_cache_version()
        unique_insiders = get_unique_insider_names(supabase_client, refresh_key, cache_version)

        # Date filter defaults to last 7 days
        today = datetime.utcnow().date()
        default_start = (today - timedelta(days=7)).strftime("%Y-%m-%d")
        default_end = today.strftime("%Y-%m-%d")

        use_date_filter_param = request.args.get("use_date_filter")
        has_query_params = len(request.args) > 0
        if use_date_filter_param is None:
            use_date_filter = not has_query_params
        else:
            use_date_filter = use_date_filter_param == "true"

        start_date = request.args.get("start_date") or default_start
        end_date = request.args.get("end_date") or default_end

        latest_created_at = get_latest_insider_trade_timestamp(
            supabase_client, refresh_key, cache_version
        )
        if latest_created_at:
            try:
                normalized = latest_created_at.replace("Z", "+00:00")
                parsed = datetime.fromisoformat(normalized)
                latest_created_at = format_timestamp_in_user_timezone(
                    parsed.strftime("%Y-%m-%d %H:%M"),
                    format="%Y-%m-%d %I:%M %p %Z"
                )
            except Exception:
                pass

        last_job_run = get_last_job_success_timestamp(
            "insider_trades_fetch", refresh_key, cache_version
        )
        if last_job_run:
            try:
                last_job_run = format_timestamp_in_user_timezone(
                    last_job_run.strftime("%Y-%m-%d %H:%M"),
                    format="%Y-%m-%d %I:%M %p %Z"
                )
            except Exception:
                last_job_run = last_job_run.isoformat()

        nav_context = get_navigation_context(current_page='insider_trades')
        update_timestamp = last_job_run or latest_created_at or "N/A"

        return render_template('insider_trades.html',
                             user_email=user_email,
                             refresh_key=refresh_key,
                             unique_insiders=unique_insiders,
                             newest_timestamp=latest_created_at or "N/A",
                             last_job_run=last_job_run or "N/A",
                             update_timestamp=update_timestamp,
                             current_fund=request.args.get("fund", ""),
                             current_fund_only=request.args.get("fund_only") == "true",
                             current_type=request.args.get("type", "All"),
                             current_insider_name=request.args.get("insider_name", ""),
                             current_min_value=request.args.get("min_value", ""),
                             current_sort_by=request.args.get("sort_by", "Date"),
                             current_use_date_filter=use_date_filter,
                             current_start_date=start_date,
                             current_end_date=end_date,
                             config={
                                 "lazyLoad": True,
                                 "defaultStartDate": start_date,
                                 "defaultEndDate": end_date,
                                 "defaultUseDateFilter": use_date_filter
                             },
                             **nav_context)
    except Exception as e:
        logger.error(f"Error in insider trades page: {e}", exc_info=True)
        nav_context = get_navigation_context(current_page='insider_trades')
        return render_template('insider_trades.html',
                             user_email='User',
                             error=str(e),
                             error_message="An error occurred loading insider trades. Please check the logs.",
                             **nav_context), 500


def _process_unknown_tickers_background(tickers, supabase_client):
    """Background task to fetch metadata for unknown tickers"""
    try:
        from utils.ticker_utils import get_ticker_currency

        # Process unknown tickers
        for ticker in tickers:
            try:
                # Determine currency from ticker
                currency = get_ticker_currency(ticker)

                # Ensure ticker exists in securities table with company name
                # This will fetch from yfinance if needed
                success = supabase_client.ensure_ticker_in_securities(ticker, currency)
                if success:
                    logger.debug(f"Added company name for ticker {ticker} to securities table (background)")
                else:
                    logger.warning(f"Failed to add company name for ticker {ticker} (background)")
            except Exception as ticker_error:
                logger.warning(f"Error processing ticker {ticker} for company name lookup: {ticker_error}")
                continue
    except ImportError:
        logger.warning("Could not import get_ticker_currency in background task")
    except Exception as e:
        logger.error(f"Error in background ticker processing: {e}")


@app.route('/api/insider_trades/data')
@require_auth
def api_insider_trades_data():
    """API endpoint for insider trades data (JSON) with server-side pagination.
    
    Query parameters:
        - limit: Number of records per page (default 100, max 500)
        - offset: Starting offset for pagination (default 0)
        - ticker, type, insider_name: Filter values
        - start_date, end_date: Date range filters
        - min_value: Minimum trade value filter
        - sort_by: Sort column (Date, Value, Shares)
        - refresh_key: Cache refresh key
    
    Returns:
        - trades: List of formatted trade records for the requested page
        - total: Total count of matching records
        - next_offset: Offset for the next page (if has_more is true)
        - has_more: Whether there are more records after this page
    """
    try:
        from flask_data_utils import get_supabase_client_flask
        from cache_version import get_cache_version
        from auth import is_admin
        from web_dashboard.utils.logo_utils import get_ticker_logo_url

        refresh_key = int(request.args.get("refresh_key", 0))

        # Pagination parameters
        limit = min(max(int(request.args.get("limit", 100)), 1), 500)  # Default 100, max 500
        offset = max(int(request.args.get("offset", 0)), 0)

        if is_admin():
            from supabase_client import SupabaseClient
            supabase_client = SupabaseClient(use_service_role=True)
        else:
            supabase_client = get_supabase_client_flask()

        if supabase_client is None:
            return jsonify({"error": "Supabase client unavailable"}), 500

        ticker_filters = [t for t in request.args.getlist("ticker") if t and t != "All"]
        type_filter = request.args.get("type")
        type_filter = None if type_filter in (None, "All") else type_filter
        insider_filter = request.args.get("insider_name")
        min_value_raw = request.args.get("min_value")
        sort_by = request.args.get("sort_by", "Date")
        use_date_filter = request.args.get("use_date_filter") == "true"
        start_date = request.args.get("start_date") if use_date_filter else None
        end_date = request.args.get("end_date") if use_date_filter else None
        fund_only = request.args.get("fund_only") == "true"
        selected_fund = request.args.get("fund")

        if fund_only and selected_fund and selected_fund.lower() != "all":
            from flask_data_utils import get_current_positions_flask

            positions_df = get_current_positions_flask(fund=selected_fund)
            if positions_df.empty or "ticker" not in positions_df.columns:
                return jsonify({"trades": [], "total": 0, "has_more": False})

            fund_tickers = {
                str(ticker).strip().upper()
                for ticker in positions_df["ticker"].dropna().unique()
                if str(ticker).strip()
            }
            if not fund_tickers:
                return jsonify({"trades": [], "total": 0, "has_more": False})

            if ticker_filters:
                ticker_filters = [
                    ticker for ticker in ticker_filters
                    if str(ticker).strip().upper() in fund_tickers
                ]
            else:
                ticker_filters = sorted(fund_tickers)

            if not ticker_filters:
                return jsonify({"trades": [], "total": 0, "has_more": False})

        min_value = None
        if min_value_raw:
            try:
                min_value = float(min_value_raw)
            except ValueError:
                min_value = None

        cache_version = get_cache_version()
        result = get_insider_trades_cached(
            supabase_client,
            refresh_key,
            ticker_filters=ticker_filters or None,
            type_filter=type_filter,
            insider_filter=insider_filter or None,
            start_date=start_date,
            end_date=end_date,
            min_value=min_value,
            sort_by=sort_by,
            limit=limit,
            offset=offset,
            _cache_version=cache_version
        )

        # Backward compatibility: older call sites/tests may still return a plain list.
        if isinstance(result, dict):
            all_trades = result.get("trades", [])
            total = int(result.get("total", len(all_trades)))
            has_more = bool(result.get("has_more", False))
        else:
            all_trades = result or []
            total = len(all_trades)
            has_more = False

        def _to_float(value: Any) -> Optional[float]:
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        def _to_int(value: Any) -> Optional[int]:
            if value is None:
                return None
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return None

        # Collect all unique tickers for company name lookup
        unique_tickers = set()
        for trade in all_trades:
            ticker = trade.get("ticker", "").strip()
            if ticker and ticker != "N/A":
                unique_tickers.add(ticker.upper())

        # Bolt Optimization: Use cached parallel fetch instead of manual in_ query
        cache_version = get_cache_version()
        company_name_map = get_company_names_map_cached(
            supabase_client, tuple(sorted(list(unique_tickers))), cache_version
        )

        # Identify unknown tickers (tickers requested but not in the map)
        unknown_tickers = []
        for ticker in unique_tickers:
            if ticker not in company_name_map:
                unknown_tickers.append(ticker)

        # Bolt Optimization: Process unknown tickers in background thread (non-blocking)
        if unknown_tickers:
            logger.info(f"Scheduling background update for {len(unknown_tickers)} unknown tickers")
            try:
                threading.Thread(
                    target=_process_unknown_tickers_background,
                    args=(unknown_tickers, supabase_client),
                    daemon=True
                ).start()
            except Exception as e:
                logger.warning(f"Error starting background ticker processing: {e}")

        formatted_trades = []
        for trade in all_trades:
            ticker = trade.get("ticker", "N/A")
            logo_url = get_ticker_logo_url(ticker) if ticker and ticker != "N/A" else None
            insider_name = normalize_insider_name(trade.get("insider_name"))

            # Get company name from securities table lookup
            company_name = None
            ticker_upper = ticker.upper().strip() if ticker and ticker != "N/A" else None
            if ticker_upper and ticker_upper in company_name_map:
                company_name = company_name_map[ticker_upper]

            formatted_trades.append({
                "ticker": ticker,
                "company_name": company_name,
                "insider_name": insider_name,
                "insider_title": trade.get("insider_title"),
                "transaction_date": trade.get("transaction_date"),
                "disclosure_date": trade.get("disclosure_date"),
                "type": trade.get("type"),
                "shares": _to_int(trade.get("shares")),
                "price_per_share": _to_float(trade.get("price_per_share")),
                "value": _to_float(trade.get("value")),
                "shares_held_after": _to_int(trade.get("shares_held_after")),
                "percent_change": _to_float(trade.get("percent_change")),
                # Bolt Optimization: Removed heavy unused fields (notes, created_at)
                "_logo_url": logo_url
            })

        response = {
            "trades": formatted_trades,
            "total": total,
            "has_more": has_more
        }
        if has_more:
            response["next_offset"] = offset + limit

        return jsonify(response)
    except ValueError as e:
        logger.error(f"Invalid parameter in insider trades API: {e}", exc_info=True)
        return jsonify({"error": f"Invalid parameter: {str(e)}"}), 400
    except Exception as e:
        logger.error(f"Error in insider trades API: {e}", exc_info=True)
        return jsonify({"error": "An error occurred while fetching insider trades data. Please check the logs."}), 500

# ============================================================================
# Newsletter API Routes
# ============================================================================

# ---------------------------------------------------------------------------
# Inbound newsletter webhook
#
# This project originally received inbound mail from Mailgun's Routes feature,
# which POSTs pre-parsed form-data (sender, recipient, subject, body-plain,
# body-html, Message-Id, ...) plus an HMAC-SHA256 signature. We migrated to a
# Cloudflare Email Worker that forwards a small JSON envelope containing the
# raw RFC 5322 message, and the route below parses that envelope.
#
# If you are forking this project and want to use Mailgun instead, swap the
# parsing block below for something along these lines:
#
#     form_data = request.form
#     signature = form_data.get('signature')
#     timestamp = form_data.get('timestamp')
#     token     = form_data.get('token')
#     if not service.verify_webhook_signature(token, timestamp, signature):
#         return jsonify({'error': 'Invalid signature'}), 403
#
#     sender     = form_data.get('sender') or form_data.get('From')
#     recipient  = form_data.get('recipient')
#     subject    = form_data.get('subject')
#     body_plain = form_data.get('body-plain')
#     body_html  = form_data.get('body-html')
#     message_id = form_data.get('Message-Id')
#
#     # "Name <email>" -> sender_name + sender
#     from_field = form_data.get('from') or form_data.get('From')
#     sender_name, parsed_addr = email.utils.parseaddr(from_field or '')
#     if parsed_addr and not sender:
#         sender = parsed_addr
#
# Everything from `service.process_newsletter(...)` onward is provider-agnostic
# — only the parsing step above needs to change per provider.
# ---------------------------------------------------------------------------
_NEWSLETTER_WEBHOOK_TEST_TOKEN_HEADER = "X-Newsletter-Webhook-Test-Token"


def _newsletter_webhook_dry_run_requested(payload: dict[str, Any]) -> bool:
    """Return true when a Cloudflare webhook probe asks to avoid writes/AI work."""
    raw = payload.get("dry_run", False)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _newsletter_webhook_test_token_valid() -> bool:
    """Validate the shared secret required for newsletter webhook dry-runs."""
    expected = (os.getenv("NEWSLETTER_WEBHOOK_TEST_TOKEN") or "").strip()
    supplied = (
        request.headers.get(_NEWSLETTER_WEBHOOK_TEST_TOKEN_HEADER)
        or request.headers.get("X-Test-Token")
        or ""
    ).strip()
    if not expected:
        logger.warning("Newsletter webhook dry_run rejected: NEWSLETTER_WEBHOOK_TEST_TOKEN not set")
        return False
    if not supplied:
        logger.warning("Newsletter webhook dry_run rejected: missing test token header")
        return False
    if not secrets.compare_digest(supplied, expected):
        logger.warning("Newsletter webhook dry_run rejected: invalid test token")
        return False
    return True


def _decode_email_header(value: Optional[str]) -> str:
    """Decode RFC 2047 email headers such as Gmail's encoded forwarded subjects."""
    if not value:
        return ""
    try:
        from email.header import decode_header, make_header

        return str(make_header(decode_header(value))).strip()
    except Exception:
        return str(value).strip()


@app.route('/api/webhooks/newsletter', methods=['POST'])
def webhook_newsletter():
    """Cloudflare Email Worker webhook for receiving newsletters.

    Expected JSON payload:
    - from: Sender email address
    - to: Recipient email address
    - subject: Email subject
    - raw_eml: Full RFC 5322 raw email string

    Note: this endpoint used to receive Mailgun's pre-parsed form-data plus
    an HMAC signature; see the comment block above the route for a Mailgun
    drop-in replacement of the parsing block.
    """
    try:
        logger.info(f"Newsletter webhook received: content_type={request.content_type}, content_length={request.content_length}")

        payload = request.get_json(silent=True) or {}
        logger.info(f"Newsletter webhook JSON keys: {list(payload.keys())}")
        dry_run = _newsletter_webhook_dry_run_requested(payload)
        if dry_run and not _newsletter_webhook_test_token_valid():
            return jsonify({'error': 'Invalid test token'}), 403

        sender = _decode_email_header(payload.get('from'))
        recipient = _decode_email_header(payload.get('to'))
        subject = _decode_email_header(payload.get('subject'))
        raw_eml = payload.get('raw_eml') or ''

        if not all([sender, recipient, subject, raw_eml]):
            logger.warning(
                f"Missing required fields in newsletter webhook: "
                f"from={bool(sender)}, to={bool(recipient)}, "
                f"subject={bool(subject)}, raw_eml={bool(raw_eml)}"
            )
            return jsonify({'error': 'Missing required fields'}), 400

        import email as email_lib
        from email.utils import parseaddr

        try:
            msg = email_lib.message_from_string(raw_eml)
        except Exception as parse_err:
            logger.error(f"Failed to parse raw_eml: {parse_err}", exc_info=True)
            return jsonify({'error': 'Failed to parse raw email'}), 400

        def _extract_body_plain(parsed_msg):
            """Walk MIME parts to pull out the plain-text body; skip HTML and attachments."""
            for part in parsed_msg.walk():
                if part.is_multipart():
                    continue
                if part.get_content_type() != 'text/plain':
                    continue
                if 'attachment' in (part.get('Content-Disposition') or '').lower():
                    continue
                payload_bytes = part.get_payload(decode=True)
                if payload_bytes is None:
                    continue
                charset = part.get_content_charset() or 'utf-8'
                try:
                    return payload_bytes.decode(charset, errors='replace')
                except (LookupError, UnicodeDecodeError):
                    return payload_bytes.decode('utf-8', errors='replace')
            return None

        def _extract_rfc822_attachments(parsed_msg):
            """Return attached original emails from Gmail's "forward as attachments" format."""
            attached = []
            for part in parsed_msg.walk():
                if part.get_content_type() != 'message/rfc822':
                    continue
                payload = part.get_payload()
                if isinstance(payload, list):
                    attached.extend(item for item in payload if item is not None)
                    continue
                if isinstance(payload, bytes):
                    attached.append(email_lib.message_from_bytes(payload))
                    continue
                if isinstance(payload, str) and payload.strip():
                    attached.append(email_lib.message_from_string(payload))
            return attached

        def _start_newsletter_ai_thread(newsletter_id: str) -> None:
            # Kick off AI processing in a background thread so Cloudflare gets a fast response.
            # The scheduled newsletter_ai_processing job acts as a safety net for any that fail here.
            import threading

            thread = threading.Thread(
                target=_process_newsletter_ai,
                args=(newsletter_id,),
                daemon=True,
                name=f"newsletter-ai-{newsletter_id[:8]}",
            )
            thread.start()
            logger.info(f"🧵 Background AI processing started for newsletter {newsletter_id}")

        def _process_newsletter_ai(nl_id: str) -> None:
            """Background thread: generate AI summary, tickers, and embedding."""
            import threading
            import time as time_mod

            from newsletter_repository import NewsletterRepository as NLRepo
            from newsletter_service import NewsletterService as NLService
            from newsletter_service import run_newsletter_ai_pipeline
            from ollama_client import generate_summary

            t_all = time_mod.perf_counter()
            NLService.log_step(
                nl_id,
                "bg_thread",
                "start",
                thread=threading.current_thread().name,
                pipeline_source="webhook_bg",
            )
            try:
                bg_repo = NLRepo()
                bg_service = NLService()

                nl = bg_repo.get_newsletter_by_id(nl_id)
                if not nl:
                    NLService.log_step(nl_id, "fetch_row", "fail", err="not_found")
                    logger.warning(f"BG: Newsletter {nl_id} not found for AI processing")
                    return

                ra = nl.get("received_at")
                NLService.log_step(
                    nl_id,
                    "fetch_row",
                    "ok",
                    received_at=str(ra) if ra else "",
                )

                content = nl.get("body_plain") or ""
                src = "plain"
                if not content and nl.get("body_html"):
                    content = bg_service.extract_text_from_html(nl["body_html"])
                    src = "html"
                t_ce = time_mod.perf_counter()
                NLService.log_step(nl_id, "content_extract", "start", source=src)
                pre_len = len(content or "")
                content = bg_service.clean_forwarded_body(content)
                NLService.log_step(
                    nl_id,
                    "content_extract",
                    "ok" if (content or "").strip() else "skip",
                    duration_ms=int((time_mod.perf_counter() - t_ce) * 1000),
                    chars_pre_clean=pre_len,
                    chars_after_clean=len(content or ""),
                    source=src,
                )
                if not (content or "").strip():
                    NLService.log_step(nl_id, "body_clean", "skip", reason="empty_after_clean")
                    logger.warning(f"BG: Newsletter {nl_id} has no content — skipping AI")
                    return

                NLService.log_step(nl_id, "body_clean", "ok", chars=len(content))

                known = bg_service.get_known_tickers_for_validation()
                run_newsletter_ai_pipeline(
                    nl_id,
                    content=content,
                    subject=nl.get("subject") or "",
                    service=bg_service,
                    repo=bg_repo,
                    generate_summary=generate_summary,
                    pipeline_source="webhook_bg",
                    include_subject_in_update=False,
                    extract_known_tickers=known,
                )

                logger.info(f"✅ BG: Newsletter {nl_id} AI processing complete")
            except Exception as bg_err:
                NLService.log_step(
                    nl_id,
                    "pipeline",
                    "fail",
                    err=f"{type(bg_err).__name__}: {bg_err}",
                )
                logger.error(f"❌ BG: Newsletter {nl_id} AI processing failed: {bg_err}", exc_info=True)
            finally:
                NLService.log_step(
                    nl_id,
                    "bg_thread",
                    "ok",
                    duration_ms=int((time_mod.perf_counter() - t_all) * 1000),
                    pipeline_source="webhook_bg",
                )

        def _ingest_message(parsed_msg, fallback_sender: str, fallback_subject: str) -> tuple[dict, int]:
            # Prefer the inner From header's display name + address; fall back to the JSON `from`.
            item_sender = fallback_sender
            sender_name = None
            parsed_name, parsed_addr = parseaddr(
                _decode_email_header(parsed_msg.get('From') or fallback_sender)
            )
            if parsed_name:
                sender_name = parsed_name.strip() or None
            if parsed_addr:
                item_sender = parsed_addr.strip()

            message_id = (
                parsed_msg.get('Message-ID') or parsed_msg.get('Message-Id') or ''
            ).strip() or None
            item_subject = _decode_email_header(parsed_msg.get('Subject') or fallback_subject)
            body_plain = _extract_body_plain(parsed_msg)
            timestamp = None
            body_html = None

            from newsletter_service import NewsletterService

            service = NewsletterService()

            # Process newsletter (without embedding first to avoid timeout)
            logger.info(f"Processing newsletter from {item_sender}: {item_subject}")
            processed_data = service.process_newsletter(
                sender=item_sender,
                recipient=recipient,
                subject=item_subject,
                body_plain=body_plain,
                body_html=body_html,
                sender_name=sender_name,
                message_id=message_id,
                timestamp=timestamp,
                skip_embedding=True
            )

            if dry_run:
                logger.info(f"Newsletter webhook dry_run parsed from {item_sender}: {item_subject}")
                return {
                    'status': 'dry_run',
                    'parsed': {
                        'sender': item_sender,
                        'sender_name': sender_name,
                        'recipient': recipient,
                        'subject': processed_data.get('subject'),
                        'message_id': message_id,
                        'body_plain_chars': len(processed_data.get('body_plain') or ''),
                        'has_body_plain': bool(processed_data.get('body_plain')),
                    },
                    'tickers': processed_data.get('tickers') or [],
                    'article_url': processed_data.get('article_url'),
                }, 200

            from newsletter_repository import NewsletterRepository

            repo = NewsletterRepository()
            dup_id = repo.find_recent_duplicate_by_body(processed_data.get('body_plain'))
            if dup_id:
                logger.info(
                    f"⏭️ Newsletter duplicate detected — dropping forward of "
                    f"{dup_id} (subject={item_subject[:80]!r})"
                )
                return {
                    'status': 'duplicate',
                    'duplicate_of': dup_id,
                    'subject': processed_data.get('subject'),
                }, 200

            newsletter_id = repo.save_newsletter(**processed_data)
            if not newsletter_id:
                logger.error("Failed to save newsletter to database")
                return {'status': 'error', 'error': 'Failed to save newsletter'}, 500

            logger.info(f"✅ Newsletter saved: {newsletter_id}")
            _start_newsletter_ai_thread(newsletter_id)

            return {
                'status': 'success',
                'id': newsletter_id,
                'tickers': processed_data.get('tickers', []),
                'subject': processed_data.get('subject'),
            }, 200

        attached_messages = _extract_rfc822_attachments(msg)
        if attached_messages:
            logger.info(
                f"Newsletter webhook detected {len(attached_messages)} attached RFC822 messages"
            )
            items = []
            status_code = 200
            for idx, attached_msg in enumerate(attached_messages, start=1):
                try:
                    item, item_status = _ingest_message(attached_msg, sender, subject)
                except Exception as item_err:
                    logger.error(
                        f"Failed to process attached newsletter #{idx}: {item_err}",
                        exc_info=True,
                    )
                    item = {'status': 'error', 'error': str(item_err)}
                    item_status = 500
                item['index'] = idx
                items.append(item)
                if item_status >= 500:
                    status_code = 207

            return jsonify({
                'status': 'batch',
                'count': len(items),
                'saved': sum(1 for item in items if item.get('status') == 'success'),
                'duplicates': sum(1 for item in items if item.get('status') == 'duplicate'),
                'errors': sum(1 for item in items if item.get('status') == 'error'),
                'items': items,
            }), status_code

        result, status_code = _ingest_message(msg, sender, subject)
        if status_code >= 500:
            return jsonify({'error': result.get('error', 'Failed to save newsletter')}), status_code
        if result.get('status') == 'success':
            result.pop('subject', None)
        return jsonify(result), status_code
            
    except Exception as e:
        logger.error(f"Error processing newsletter webhook: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/newsletters', methods=['GET'])
@require_auth
def get_newsletters():
    """Get recent newsletters with pagination
    
    Query params:
    - limit: Number of results (default 20, max 100)
    - offset: Number to skip (default 0)
    - ticker: Filter by ticker symbol (optional)
    """
    try:
        # Parse query params
        limit = min(int(request.args.get('limit', 20)), 100)
        offset = int(request.args.get('offset', 0))
        ticker = request.args.get('ticker')
        
        # Get newsletters from repository
        from newsletter_repository import NewsletterRepository
        repo = NewsletterRepository()
        
        newsletters = repo.get_recent_newsletters(
            limit=limit,
            offset=offset,
            ticker=ticker.upper() if ticker else None
        )
        
        # Get total count
        total_count = repo.get_newsletter_count(ticker=ticker.upper() if ticker else None)
        
        # Format response
        return jsonify({
            'newsletters': newsletters,
            'total': total_count,
            'limit': limit,
            'offset': offset
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching newsletters: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/newsletters/<newsletter_id>', methods=['GET'])
@require_auth
def get_newsletter(newsletter_id):
    """Get a single newsletter by ID"""
    try:
        from newsletter_repository import NewsletterRepository
        repo = NewsletterRepository()
        
        newsletter = repo.get_newsletter_by_id(newsletter_id)
        
        if not newsletter:
            return jsonify({'error': 'Newsletter not found'}), 404
        
        return jsonify(newsletter), 200
        
    except Exception as e:
        logger.error(f"Error fetching newsletter {newsletter_id}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/newsletters/<newsletter_id>', methods=['DELETE'])
@require_admin
def delete_newsletter(newsletter_id):
    """Delete a newsletter by ID (admin only)"""
    try:
        from newsletter_repository import NewsletterRepository
        repo = NewsletterRepository()

        deleted = repo.delete_newsletter(newsletter_id)
        if deleted:
            logger.info(f"Newsletter {newsletter_id} deleted by admin")
            return jsonify({'success': True}), 200
        return jsonify({'success': False, 'error': 'Newsletter not found'}), 404
    except Exception as e:
        logger.error(f"Error deleting newsletter {newsletter_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/newsletters/search', methods=['POST'])
@require_auth
def search_newsletters():
    """Search newsletters using semantic similarity
    
    POST body:
    - query: Search query text
    - limit: Number of results (default 10, max 50)
    """
    try:
        data = request.get_json()
        
        if not data or 'query' not in data:
            return jsonify({'error': 'Missing query parameter'}), 400
        
        query = data['query']
        limit = min(int(data.get('limit', 10)), 50)
        
        # Search newsletters
        from newsletter_repository import NewsletterRepository
        repo = NewsletterRepository()
        
        results = repo.search_newsletters(query_text=query, limit=limit)
        
        return jsonify({
            'results': results,
            'query': query,
            'limit': limit
        }), 200
        
    except Exception as e:
        logger.error(f"Error searching newsletters: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/newsletters', methods=['GET'])
@require_auth
def newsletters_page():
    """Render newsletters page"""
    try:
        nav_context = get_navigation_context(current_page='newsletters')
        newsletter_email = os.getenv('NEWSLETTER_EMAIL', 'newsletters@yourdomain.com')
        return render_template('newsletters.html', newsletter_email=newsletter_email, **nav_context)
    except Exception as e:
        logger.error(f"Error rendering newsletters page: {e}", exc_info=True)
        return render_template('error.html', error=str(e)), 500


# ============================================================================
# Main Application Entry Point
# ============================================================================

if __name__ == '__main__':

    # Run the app
    # Use port 5001 to avoid conflict with NFT calculator app on port 5000
    port = int(os.getenv('FLASK_PORT', '5001'))
    # Use FLASK_DEBUG env var (default False) for safety in production
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(debug=debug_mode, host='0.0.0.0', port=port)
