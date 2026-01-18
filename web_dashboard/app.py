#!/usr/bin/env python3
"""
Portfolio Performance Web Dashboard
A Flask web app to display trading bot portfolio performance using Supabase
"""

# Check critical dependencies first
try:
    from flask import Flask, render_template, jsonify, request, redirect, url_for, session, Response
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
import os
import re
from datetime import datetime, timedelta, date
from pathlib import Path
import yfinance as yf
import plotly.graph_objs as go
import plotly.utils
from typing import Dict, List, Optional, Tuple, Any
import logging
import requests
import threading
from flask_cors import CORS
from flask_cache_utils import cache_data, cache_resource

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
app.secret_key = os.getenv("FLASK_SECRET_KEY", "your-secret-key-change-this")

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
    from flask_wtf.csrf import CSRFProtect
    csrf = CSRFProtect(app)
    CSRF_ENABLED = True
    logger.info("CSRF protection enabled via Flask-WTF")
except ImportError:
    CSRF_ENABLED = False
    logger.warning("Flask-WTF not available - CSRF protection disabled. Install with: pip install flask-wtf")

# Configure CORS to allow credentials from Vercel deployment
CORS(app, 
     supports_credentials=True,
     origins=["https://webdashboard-hazel.vercel.app", "http://localhost:5000"],
     allow_headers=["Content-Type", "Authorization"],
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
os.environ["JWT_SECRET"] = os.getenv("JWT_SECRET", "your-jwt-secret-change-this")

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
                    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; padding: 2rem; line-height: 1.5; }}
                    h1 {{ color: #dc2626; border-bottom: 2px solid #fee2e2; padding-bottom: 0.5rem; }}
                    pre {{ background: #f3f4f6; padding: 1.5rem; border-radius: 0.5rem; overflow-x: auto; font-size: 0.9em; border: 1px solid #e5e7eb; }}
                    .error-msg {{ font-size: 1.25rem; font-weight: 600; margin-bottom: 1rem; color: #1f2937; }}
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
            <body style="font-family: sans-serif; padding: 2rem; text-align: center;">
                <h1>500 Internal Server Error</h1>
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
                    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; padding: 2rem; line-height: 1.5; }}
                    h1 {{ color: #dc2626; border-bottom: 2px solid #fee2e2; padding-bottom: 0.5rem; }}
                    pre {{ background: #f3f4f6; padding: 1.5rem; border-radius: 0.5rem; overflow-x: auto; font-size: 0.9em; border: 1px solid #e5e7eb; }}
                    .error-msg {{ font-size: 1.25rem; font-weight: 600; margin-bottom: 1rem; color: #1f2937; }}
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
            <body style="font-family: sans-serif; padding: 2rem; text-align: center;">
                <h1>Application Error</h1>
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
        from flask import request
        user_token = request.cookies.get('auth_token') or request.cookies.get('session_token')
        
        return SupabaseClient(user_token=user_token)
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

def get_navigation_context(current_page: str = None) -> Dict[str, Any]:
    """Get navigation context for Flask templates"""
    try:
        from shared_navigation import get_navigation_links, is_page_migrated
        from user_preferences import get_user_preference
        from flask_auth_utils import get_user_email_flask
        
        # Get navigation links
        links = get_navigation_links()
        is_v2_enabled = get_user_preference('v2_enabled', default=False)
        
        # If we're on a v2 page (current_page is migrated), assume v2 is enabled for navigation
        # This ensures menu is populated when viewing v2 pages
        if current_page and is_page_migrated(current_page):
            is_v2_enabled = True
        
        # Build navigation context
        # Only check: is v2 enabled AND is page migrated? If yes, show link.
        # Don't hide links for any other reason - let pages handle errors and authorization
        nav_links = []
        for link in links:
            # Only check: if page is migrated, show it only if v2 is enabled
            # Otherwise, show it (it's a Streamlit page)
            show = True
            if is_page_migrated(link['page']):
                # Only show migrated pages if v2 is enabled
                show = is_v2_enabled
            
            # Determine URL (use Flask route if migrated and v2 enabled)
            url = link['url']
            if is_page_migrated(link['page']) and is_v2_enabled:
                url = link['url']  # Already points to Flask route
            
            nav_links.append({
                'name': link['name'],
                'url': url,
                'icon': link['icon'],
                'show': show,
                'active': current_page == link['page']
            })
        
        # Get available funds for the sidebar selector (Flask-compatible)
        try:
            from flask_data_utils import get_available_funds_flask
            available_funds = get_available_funds_flask()
        except Exception as e:
            logger.warning(f"Could not load available funds: {e}")
            available_funds = []
        
        # Check if user is admin
        # Note: We show admin menu items if user is authenticated, regardless of admin check result
        # This prevents buggy admin checks from hiding menu items - let the pages handle authorization
        is_admin_value = False
        
        try:
            # Check if user is authenticated (has user_id or email)
            user_is_authenticated = False
            
            if hasattr(request, 'user_id') and request.user_id:
                user_is_authenticated = True
            else:
                # Try to get user_id from session/cookies
                try:
                    from flask_auth_utils import get_user_id_flask
                    user_id = get_user_id_flask()
                    if user_id:
                        user_is_authenticated = True
                except Exception:
                    pass
            
            # If still not authenticated, check via email
            if not user_is_authenticated:
                try:
                    from flask_auth_utils import get_user_email_flask
                    if get_user_email_flask():
                        user_is_authenticated = True
                except Exception:
                    pass
            
            # If user is authenticated, show admin menu (optimistic approach)
            # Pages will handle actual authorization with @require_admin decorator
            if user_is_authenticated:
                is_admin_value = True
        except Exception:
            # If anything fails, default to showing menu if we can detect user is logged in
            try:
                from flask_auth_utils import get_user_email_flask
                if get_user_email_flask():
                    is_admin_value = True
            except Exception:
                pass
        
        # Get currently selected fund - check URL parameter first, then user preference
        selected_fund = None
        try:
            # Check URL parameter first (for persistence across refreshes)
            from flask import request
            url_fund = request.args.get('fund')
            if url_fund:
                selected_fund = url_fund
            else:
                # Fall back to user preference
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
            
        return {
            'navigation_links': nav_links,
            'is_admin': is_admin_value,
            'available_funds': available_funds,
            'selected_fund': selected_fund,
            'allow_all_funds': allow_all_funds,
            'scheduler_status': scheduler_status
        }
    except Exception as e:
        logger.warning(f"Error building navigation context: {e}")
        return {
            'navigation_links': [],
            'is_admin': False,
            'available_funds': []
        }







# Register Blueprints
try:
    from routes.research_routes import research_bp
    app.register_blueprint(research_bp)
    logger.debug("Registered Research Blueprint")
except Exception as e:
    logger.error(f"Failed to register Research Blueprint: {e}", exc_info=True)

try:
    from routes.etf_routes import etf_bp
    app.register_blueprint(etf_bp)
    logger.debug("Registered ETF Blueprint")
except Exception as e:
    logger.error(f"Failed to register ETF Blueprint: {e}", exc_info=True)

try:
    from routes.social_sentiment_routes import social_sentiment_bp
    app.register_blueprint(social_sentiment_bp)
    logger.debug("Registered Social Sentiment Blueprint")
except Exception as e:
    logger.error(f"Failed to register Social Sentiment Blueprint: {e}", exc_info=True)

try:
    from routes.fund_routes import fund_bp
    app.register_blueprint(fund_bp)
    logger.debug("Registered Fund Blueprint")
except Exception as e:
    logger.error(f"Failed to register Fund Blueprint: {e}", exc_info=True)

try:
    from routes.admin_routes import admin_bp
    app.register_blueprint(admin_bp)
    logger.debug("Registered Admin Blueprint")
except Exception as e:
    logger.error(f"Failed to register Admin Blueprint: {e}", exc_info=True)

try:
    from routes.color_test_routes import color_test_bp
    app.register_blueprint(color_test_bp)
    logger.debug("Registered Color Test Blueprint")
except Exception as e:
    logger.error(f"Failed to register Color Test Blueprint: {e}", exc_info=True)

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
                        # start_scheduler() returned False (already running or failed)
                        log_both('warning', f"⚠️ start_scheduler() returned False on attempt {attempt + 1}")
                        
                        # Check if it's because another process has it running
                        if is_scheduler_running():
                            log_both('info', "✅ Another process has scheduler running (detected via heartbeat)")
                            break
                        
                        # Otherwise, it failed - retry if we have attempts left
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
            
            # CRITICAL: Thread stays alive to execute scheduler jobs
            # Sleep forever to keep thread alive and log heartbeat
            sleep_count = 0
            while True:
                sleep_count += 1
                logger.debug(f"[PID:{process_id} TID:{thread_id}] [{thread_name}] Keeping scheduler thread alive (cycle {sleep_count})")
                time.sleep(60)
                
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
# Only start if not explicitly disabled (e.g. in Flask container where Streamlit runs the scheduler)
# AND check if we haven't already started the thread (improves safety during reloads/imports)
if os.environ.get('DISABLE_SCHEDULER', '').lower() != 'true':
    # IMPORTANT: In Flask debug mode with reloader, there are TWO processes:
    # - Parent process (PID 1): Monitors for file changes, restarts child
    # - Child/reloader process: Actually runs the Flask app (WERKZEUG_RUN_MAIN=true)
    # We should ONLY start the scheduler in ONE of them to avoid conflicts.
    #
    # When debug mode is enabled (FLASK_DEBUG=true), only start in the child process.
    # When debug mode is disabled, start normally.
    flask_debug = os.environ.get('FLASK_DEBUG', '').lower() == 'true'
    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    
    should_start = True
    reason = ""
    
    if flask_debug and not is_reloader_process:
        # This is the parent/monitor process in debug mode - don't start scheduler here
        should_start = False
        reason = "Flask debug mode: deferring scheduler to reloader child process"
        logger.info(f"ℹ️ {reason}")
    
    if should_start:
        # Check if thread is already running to avoid duplicates
        _existing_threads = [t.name for t in threading.enumerate()]
        if "SchedulerInitThread" not in _existing_threads:
            _start_scheduler_background()
        else:
            logger.debug("ℹ️ SchedulerInitThread already running, skipping duplicate start")
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
    """Load and process portfolio data from Supabase (web app only - no CSV fallback)"""
    if not REPOSITORY_AVAILABLE:
        logger.error("Repository system not available - cannot load portfolio data")
        return {
            "portfolio": pd.DataFrame(),
            "trades": pd.DataFrame(),
            "cash_balances": {"CAD": 0.0, "USD": 0.0},
            "available_funds": [],
            "current_fund": None,
            "error": "Repository system not available. Please check data.repositories module."
        }
    
    try:
        # Use repository system to load from Supabase
        repository = RepositoryFactory.create_repository(
            'supabase',
            url=os.getenv("SUPABASE_URL"),
            key=os.getenv("SUPABASE_ANON_KEY"),
            fund=fund_name
        )

        # Get available funds
        available_funds = repository.get_available_funds()
        if fund_name and fund_name not in available_funds:
            logger.warning(f"Fund '{fund_name}' not found in Supabase")
            return {
                "portfolio": pd.DataFrame(),
                "trades": pd.DataFrame(),
                "cash_balances": {"CAD": 0.0, "USD": 0.0},
                "available_funds": available_funds,
                "current_fund": None,
                "error": f"Fund '{fund_name}' not found"
            }

        # Get data from Supabase using repository (filtered by fund if specified)
        positions = repository.get_current_positions(fund=fund_name)
        trades = repository.get_trade_log(limit=1000, fund=fund_name)
        cash_balances = repository.get_cash_balances()

        # Convert to DataFrames for compatibility with existing code
        portfolio_df = pd.DataFrame(positions) if positions else pd.DataFrame()
        trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()

        return {
            "portfolio": portfolio_df,
            "trades": trades_df,
            "cash_balances": cash_balances,
            "available_funds": available_funds,
            "current_fund": fund_name
        }
    except Exception as e:
        logger.error(f"Error loading portfolio data from Supabase: {e}", exc_info=True)
        return {
            "portfolio": pd.DataFrame(),
            "trades": pd.DataFrame(),
            "cash_balances": {"CAD": 0.0, "USD": 0.0},
            "available_funds": [],
            "current_fund": None,
            "error": f"Failed to load data from Supabase: {str(e)}"
        }

def calculate_performance_metrics(portfolio_df: pd.DataFrame, trade_df: pd.DataFrame, fund_name=None) -> Dict:
    """Calculate key performance metrics for a specific fund or all funds"""
    try:
        client = get_supabase_client()
        if client and fund_name:
            # Get metrics for specific fund
            positions = client.get_current_positions(fund=fund_name)
            trades = client.get_trade_log(limit=1000, fund=fund_name)

            total_value = sum(pos["total_market_value"] for pos in positions)
            total_cost_basis = sum(pos["total_cost_basis"] for pos in positions)
            unrealized_pnl = sum(pos["total_pnl"] for pos in positions)
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
        
        # Fallback to local calculation if Supabase not available
        if portfolio_df.empty:
            return {
                "total_value": 0,
                "total_cost_basis": 0,
                "unrealized_pnl": 0,
                "performance_pct": 0,
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0
            }
        
        # Calculate current portfolio metrics
        if 'total_market_value' in portfolio_df.columns:
            total_value = portfolio_df['total_market_value'].sum()
            total_cost_basis = portfolio_df['total_cost_basis'].sum()
            unrealized_pnl = portfolio_df['total_pnl'].sum()
        else:
            # Fallback for old CSV format
            current_positions = portfolio_df[portfolio_df.get('Total Value', 0) > 0]
            total_value = current_positions.get('Total Value', pd.Series([0])).sum()
            total_cost_basis = current_positions.get('Cost Basis', pd.Series([0])).sum()
            unrealized_pnl = current_positions.get('PnL', pd.Series([0])).sum()
        
        performance_pct = (unrealized_pnl / total_cost_basis * 100) if total_cost_basis > 0 else 0
        
        # Calculate trade statistics
        if not trade_df.empty:
            total_trades = len(trade_df)
            if 'pnl' in trade_df.columns:
                winning_trades = len(trade_df[trade_df['pnl'] > 0])
                losing_trades = len(trade_df[trade_df['pnl'] < 0])
            else:
                winning_trades = len(trade_df[trade_df.get('PnL', 0) > 0])
                losing_trades = len(trade_df[trade_df.get('PnL', 0) < 0])
        else:
            total_trades = winning_trades = losing_trades = 0
        
        return {
            "total_value": round(total_value, 2),
            "total_cost_basis": round(total_cost_basis, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "performance_pct": round(performance_pct, 2),
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades
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
                    
                    for _, pos in current_positions.iterrows():
                        ticker = pos['Ticker']
                        value = Decimal(str(pos['Total Value']))
                        cost_basis = Decimal(str(pos['Cost Basis']))
                        
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

# Register Dashboard Blueprint
try:
    from routes.dashboard_routes import dashboard_bp
    app.register_blueprint(dashboard_bp)
    logger.debug("Registered Dashboard Blueprint")
except Exception as e:
    logger.error(f"Failed to register Dashboard Blueprint: {e}", exc_info=True)

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
        
        auth_token = request.cookies.get('auth_token')
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
            logger.info("[AUTH] Root route: User not authenticated, redirecting to auth")
            return redirect(url_for('auth_page'))
    except Exception as e:
        logger.error(f"Error in root route: {e}", exc_info=True)
        # On error, just redirect to auth - don't delete cookies
        # Cookies might be valid, error might be unrelated to auth
        return redirect('/auth')

@app.route('/auth')
def auth_page():
    """Authentication page"""
    return render_template('auth.html')

@app.route('/auth/debug')
def auth_debug():
    """Unauthenticated debug endpoint to check token state"""
    import base64
    import json as json_lib
    import time
    
    auth_token = request.cookies.get('auth_token')
    session_token = request.cookies.get('session_token')
    refresh_token = request.cookies.get('refresh_token')
    
    def decode_token(token):
        if not token:
            return None
        try:
            parts = token.split('.')
            if len(parts) < 2:
                return {"error": "Invalid JWT format"}
            payload = parts[1]
            payload += '=' * (4 - len(payload) % 4)
            decoded = base64.urlsafe_b64decode(payload)
            data = json_lib.loads(decoded)
            # Add human-readable expiry info
            exp = data.get('exp', 0)
            if exp:
                now = int(time.time())
                data['_exp_human'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(exp))
                data['_expired'] = exp < now
                data['_seconds_until_expiry'] = exp - now
            return data
        except Exception as e:
            return {"error": str(e)}
    
    return jsonify({
        "auth_token": {
            "present": bool(auth_token),
            "length": len(auth_token) if auth_token else 0,
            "decoded": decode_token(auth_token)
        },
        "session_token": {
            "present": bool(session_token),
            "length": len(session_token) if session_token else 0,
            "decoded": decode_token(session_token)
        },
        "refresh_token": {
            "present": bool(refresh_token),
            "length": len(refresh_token) if refresh_token else 0
        },
        "server_time": int(time.time()),
        "server_time_human": time.strftime('%Y-%m-%d %H:%M:%S')
    })

@app.route('/api/auth/login', methods=['POST'])
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
            }
        )
        
        logger.info(f"Login attempt for {email}: Status {response.status_code}")
        if response.status_code != 200:
            logger.error(f"Login failed: {response.text}")
        
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
            elif error_code == "invalid_credentials":
                return jsonify({"error": "Invalid email or password."}), 401
            else:
                return jsonify({"error": error_msg}), 401
            
    except Exception as e:
        logger.error(f"Login error: {e}", exc_info=True)
        import traceback
        return jsonify({"error": "Login failed", "message": str(e), "traceback": traceback.format_exc()}), 500

@app.route('/api/debug/cookies')
def debug_cookies():
    """Debug endpoint to inspect cookies received by the server"""
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
        response = requests.post(
            f"{os.getenv('SUPABASE_URL')}/auth/v1/otp",
            headers={
                "apikey": os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY"),
                "Content-Type": "application/json"
            },
            json={
                "email": email,
                "create_user": False,
                "data": {
                    "redirect_to": redirect_url
                }
            }
        )
        
        if response.status_code == 200:
            return jsonify({"message": "Magic link sent to your email"})
        else:
            return jsonify({"error": "Failed to send magic link"}), response.status_code
            
    except Exception as e:
        logger.error(f"Magic link error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/auth/reset-password-request', methods=['POST'])
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
            
        # Request recovery email from Supabase
        response = requests.post(
            f"{os.getenv('SUPABASE_URL')}/auth/v1/recover",
            headers={
                "apikey": os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY"),
                "Content-Type": "application/json"
            },
            json={
                "email": email,
                "redirect_to": redirect_url
            }
        )
        
        # Supabase returns 200 even if user doesn't exist (security)
        if response.status_code == 200:
            return jsonify({"message": "If an account matches that email, a password reset link has been sent."})
        else:
            return jsonify({"error": "Failed to send reset email"}), response.status_code
            
    except Exception as e:
        logger.error(f"Password reset request error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/auth/change-password', methods=['POST'])
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
            }
        )
        
        if response.status_code == 200:
            return jsonify({"message": "Password updated successfully"})
        else:
            return jsonify({"error": "Failed to update password"}), response.status_code
            
    except Exception as e:
        logger.error(f"Password change error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/auth/register', methods=['POST'])
def register():
    """Handle user registration"""
    try:
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
            }
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
    response = jsonify({"message": "Logged out successfully"})
    is_production = request.host != 'localhost:5000' and not request.host.startswith('127.0.0.1')
    
    # Clear session_token (Flask login)
    response.set_cookie(
        'session_token', 
        '', 
        expires=0,
        secure=is_production,
        samesite='Lax'
    )
    
    # Clear auth_token (Streamlit login) to prevent auto-login loop
    response.set_cookie(
        'auth_token', 
        '', 
        expires=0,
        secure=is_production,
        samesite='Lax'
    )
    
    # Clear refresh_token
    response.set_cookie(
        'refresh_token', 
        '', 
        expires=0,
        secure=is_production,
        samesite='Lax'
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
            }
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
            params={"select": "fund"}
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
            }
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
            params={"email": f"eq.{user_email}", "select": "user_id"}
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
            params={"user_id": f"eq.{user_id}", "fund_name": f"eq.{fund_name}"}
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
                }
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
            for _, row in data['portfolio'].iterrows():
                # Calculate market value and total P&L
                market_value = float(row['shares']) * float(row['price'])
                total_pnl = market_value - float(row['cost_basis'])
                
                current_positions.append({
                    'ticker': row['ticker'],
                    'shares': round(float(row['shares']), 4),
                    'price': round(float(row['price']), 2),
                    'cost_basis': round(float(row['cost_basis']), 2),
                    'market_value': round(market_value, 2),
                    'pnl': round(total_pnl, 2),
                    'pnl_pct': round((total_pnl / float(row['cost_basis']) * 100), 2) if float(row['cost_basis']) > 0 else 0.0,
                    # Add SQL-calculated P&L metrics
                    'daily_pnl_dollar': round(float(row.get('daily_pnl_dollar', 0)), 2),
                    'daily_pnl_pct': round(float(row.get('daily_pnl_pct', 0)), 2),
                    'weekly_pnl_dollar': round(float(row.get('weekly_pnl_dollar', 0)), 2),
                    'weekly_pnl_pct': round(float(row.get('weekly_pnl_pct', 0)), 2),
                    'monthly_pnl_dollar': round(float(row.get('monthly_pnl_dollar', 0)), 2),
                    'monthly_pnl_pct': round(float(row.get('monthly_pnl_pct', 0)), 2)
                })
        else:
            # CSV format fallback
            current_positions_df = data['portfolio'][data['portfolio'].get('Total Value', 0) > 0]
            for _, row in current_positions_df.iterrows():
                current_positions.append({
                    'ticker': row['Ticker'],
                    'shares': round(row['Shares'], 4),
                    'price': round(row['Price'], 2),
                    'cost_basis': round(row['Cost Basis'], 2),
                    'market_value': round(row['Total Value'], 2),
                    'pnl': round(row['PnL'], 2),
                    'pnl_pct': round((row['PnL'] / row['Cost Basis'] * 100), 2) if row['Cost Basis'] > 0 else 0
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
@require_auth
def logs_debug():
    """Debug endpoint to check admin status without requiring admin"""
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
            token = request.cookies.get('auth_token') or request.cookies.get('session_token')
            if token and len(token.split('.')) == 3:
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
            token = request.cookies.get('auth_token') or request.cookies.get('session_token')
            if token and request_user_id and len(token.split('.')) == 3:
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
                             user_theme=current_theme,
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

@app.route('/api/settings/debug', methods=['GET'])
@require_auth
def settings_debug():
    """Debug endpoint to test preference saving"""
    try:
        from user_preferences import set_user_preference, get_user_preference, _get_user_id, _is_authenticated
        from flask_auth_utils import get_user_id_flask, get_auth_token
        from supabase_client import SupabaseClient
        
        user_id = get_user_id_flask()
        token = get_auth_token()
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
        from user_preferences import get_user_theme
        
        user_email = get_user_email_flask()
        ticker = request.args.get('ticker', '').upper().strip()
        user_theme = get_user_theme() or 'system'
        
        # Get navigation context
        nav_context = get_navigation_context(current_page='ticker_details')
        
        return render_template('ticker_details.html',
                             user_email=user_email,
                             ticker=ticker,
                             user_theme=user_theme,
                             **nav_context)
    except Exception as e:
        logger.error(f"Error loading ticker details page: {e}")
        return jsonify({"error": "Failed to load ticker details page"}), 500

@cache_data(ttl=60)
def _get_all_tickers_cached():
    """Get all unique tickers with caching (60s TTL)"""
    try:
        logger.info("Starting _get_all_tickers_cached")
        from ticker_utils import get_all_unique_tickers
        tickers = get_all_unique_tickers()
        count = len(tickers) if tickers else 0
        logger.info(f"_get_all_tickers_cached retrieved {count} tickers")
        return sorted(tickers) if tickers else []
    except Exception as e:
        logger.error(f"Error fetching ticker list in _get_all_tickers_cached: {e}", exc_info=True)
        return []

@app.route('/api/v2/ticker/list')
@require_auth
def api_ticker_list():
    """Get list of all available tickers for dropdown"""
    try:
        tickers = _get_all_tickers_cached()
        return jsonify({"tickers": tickers})
    except Exception as e:
        logger.error(f"Error fetching ticker list: {e}")
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc(),
            "type": type(e).__name__
        }), 500

@cache_data(ttl=300)
def _get_ticker_info_cached(ticker: str, user_is_admin: bool, auth_token: Optional[str]):
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
    return get_ticker_info(ticker, supabase_client, postgres_client)

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
        
        # Check if user is admin
        user_is_admin = is_admin()
        auth_token = request.cookies.get('auth_token')
        
        # Get ticker info (cached)
        try:
            ticker_data = _get_ticker_info_cached(ticker, user_is_admin, auth_token)
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

@cache_data(ttl=300)
def _get_ticker_price_history_cached(ticker: str, days: int, user_is_admin: bool, auth_token: Optional[str]):
    """Get ticker price history with caching (300s TTL)"""
    from supabase_client import SupabaseClient
    
    if user_is_admin:
        supabase_client = SupabaseClient(use_service_role=True)
    else:
        supabase_client = SupabaseClient(user_token=auth_token) if auth_token else None
    
    if not supabase_client:
        raise ValueError("Unable to connect to database")
    
    from ticker_utils import get_ticker_price_history
    return get_ticker_price_history(ticker, supabase_client, days=days)

@app.route('/api/v2/ticker/price-history')
@require_auth
def api_ticker_price_history():
    """Get price history for a ticker"""
    try:
        from auth import is_admin
        
        ticker = request.args.get('ticker', '').upper().strip()
        if not ticker:
            return jsonify({"error": "Ticker symbol is required"}), 400
        
        days = int(request.args.get('days', 90))
        user_is_admin = is_admin()
        auth_token = request.cookies.get('auth_token')
        
        # Get price history (cached)
        price_df = _get_ticker_price_history_cached(ticker, days, user_is_admin, auth_token)
        
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
def _get_ticker_chart_data_cached(ticker: str, use_solid: bool, user_is_admin: bool, auth_token: Optional[str], range: str = '3m'):
    """Get ticker chart data with caching (300s TTL) - theme applied separately"""
    from supabase_client import SupabaseClient
    
    if user_is_admin:
        supabase_client = SupabaseClient(use_service_role=True)
    else:
        supabase_client = SupabaseClient(user_token=auth_token) if auth_token else None
    
    if not supabase_client:
        raise ValueError("Unable to connect to database")
    
    # Convert range to days
    range_days = {
        '3m': 90,
        '6m': 180,
        '1y': 365,
        '2y': 730,
        '5y': 1825
    }.get(range, 90)
    
    from ticker_utils import get_ticker_price_history
    price_df = get_ticker_price_history(ticker, supabase_client, days=range_days)
    
    if price_df.empty:
        raise ValueError("No price data available")
    
    # Downsample to maintain ~90 data points
    from chart_utils import downsample_price_data
    price_df = downsample_price_data(price_df, range_days)
    
    # Fetch congress trades for this ticker within the chart date range
    congress_trades = []
    try:
        from cache_version import get_cache_version
        refresh_key = get_cache_version()
        
        # Calculate date range for congress trades (match chart range)
        start_date = (date.today() - timedelta(days=range_days)).isoformat()
        end_date = date.today().isoformat()
        
        # Fetch congress trades
        congress_trades = get_congress_trades_cached(
            supabase_client,
            refresh_key,
            ticker_filter=ticker,
            start_date=start_date,
            end_date=end_date,
            _postgres_client=None  # Not needed for basic trade data
        )
    except Exception as e:
        logger.warning(f"Error fetching congress trades for chart: {e}")
        # Continue without congress trades if there's an error
    
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
        congress_trades=congress_trades  # NEW parameter
    )
    
    # Serialize with numpy array conversion for proper JSON encoding
    from plotly_utils import serialize_plotly_figure
    return serialize_plotly_figure(fig)


def _get_ticker_chart_cached(ticker: str, use_solid: bool, user_is_admin: bool, auth_token: Optional[str], theme: Optional[str] = None, range: str = '3m'):
    """Get ticker chart with theme applied dynamically (not cached per theme)"""
    import json
    
    # Get cached chart data (without theme)
    chart_json_str = _get_ticker_chart_data_cached(ticker, use_solid, user_is_admin, auth_token, range)
    
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
        # Get theme from request (client detects actual page theme)
        client_theme = request.args.get('theme', '').strip().lower()
        # Get range from request (default: 3m)
        chart_range = request.args.get('range', '3m').strip().lower()
        # Validate range
        if chart_range not in ['3m', '6m', '1y', '2y', '5y']:
            chart_range = '3m'
        
        user_is_admin = is_admin()
        auth_token = request.cookies.get('auth_token')
        
        # Get chart (cached) - use client theme if valid, otherwise fall back to user preference
        chart_json = _get_ticker_chart_cached(ticker, use_solid, user_is_admin, auth_token, theme=client_theme if client_theme in ['dark', 'light'] else None, range=chart_range)
        return Response(chart_json, mimetype='application/json')
    except Exception as e:
        logger.error(f"Error generating chart for {ticker}: {e}", exc_info=True)
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

@app.route('/api/v2/ai/search', methods=['POST'])
@require_auth
def api_ai_search():
    """Perform web search"""
    try:
        data = request.get_json()
        query = data.get('query')
        
        if not query:
            return jsonify({"error": "No query provided"}), 400
            
        from searxng_client import get_searxng_client
        client = get_searxng_client()
        
        if not client:
            return jsonify({"error": "Search is unavailable"}), 503
            
        results = client.search(query)
        return jsonify({"results": results})
        
    except Exception as e:
        logger.error(f"Error performing search: {e}")
        return jsonify({"error": str(e)}), 500

@cache_data(ttl=300)
def _get_context_data_packet(user_id: str, fund: str):
    """Get context data packet with caching (300s TTL)"""
    from flask_data_utils import (
        get_current_positions_flask, get_trade_log_flask, get_cash_balances_flask,
        calculate_portfolio_value_over_time_flask, get_fund_thesis_data_flask,
        calculate_performance_metrics_flask
    )
    
    logger.info(f"Refreshing context data for {user_id}/{fund}")
    
    # Fetch all components
    positions_df = get_current_positions_flask(fund)
    trades_df = get_trade_log_flask(limit=100, fund=fund)
    
    try:
        metrics = calculate_performance_metrics_flask(fund)
        portfolio_df = calculate_portfolio_value_over_time_flask(fund, days=365)
    except Exception as e:
        logger.warning(f"Error loading metrics: {e}")
        metrics = None
        portfolio_df = None
        
    try:
        cash = get_cash_balances_flask(fund)
    except Exception as e:
        logger.warning(f"Error loading cash: {e}")
        cash = None
        
    try:
        thesis_data = get_fund_thesis_data_flask(fund)
    except Exception as e:
        logger.warning(f"Error loading thesis: {e}")
        thesis_data = None
        
    return {
        'positions_df': positions_df,
        'trades_df': trades_df,
        'metrics': metrics,
        'portfolio_df': portfolio_df,
        'cash': cash,
        'thesis_data': thesis_data
    }

@app.route('/api/v2/ai/preview_context', methods=['POST'])
@require_auth
def api_ai_preview_context():
    """Preview the AI context (debug mode) - Shows the raw data tables sent to LLM
    Uses backend caching to avoid re-fetching data when toggling options.
    """
    try:
        from flask_auth_utils import get_user_id_flask
        from ai_context_builder import (
            format_holdings, format_thesis, format_trades, 
            format_performance_metrics, format_cash_balances,
            format_price_volume_table, format_fundamentals_table
        )
        
        data = request.get_json()
        fund = data.get('fund')
        
        if not fund:
            return jsonify({"error": "No fund specified"}), 400

        user_id = get_user_id_flask()
        
        # Get cached data packet
        data_packet = _get_context_data_packet(user_id, fund)
            
        # --- Context Assembly ---
        # Unpack data
        positions_df = data_packet['positions_df']
        trades_df = data_packet['trades_df']
        metrics = data_packet['metrics']
        portfolio_df = data_packet['portfolio_df']
        cash = data_packet['cash']
        thesis_data = data_packet['thesis_data']
        
        context_parts = []
        
        # 1. ALWAYS INCLUDED: Holdings
        include_pv = data.get('include_price_volume', True)
        include_fund = data.get('include_fundamentals', True)
        
        if not positions_df.empty:
            holdings_text = format_holdings(
                positions_df,
                fund,
                trades_df=trades_df,
                include_price_volume=include_pv,
                include_fundamentals=include_fund
            )
            context_parts.append(holdings_text)
        
        # 2. ALWAYS INCLUDED: Performance Metrics
        if metrics:
            context_parts.append(format_performance_metrics(metrics, portfolio_df))
        
        # 3. ALWAYS INCLUDED: Cash Balances
        if cash:
            context_parts.append(format_cash_balances(cash))
        
        # 4. OPTIONAL: Thesis
        if data.get('include_thesis', False) and thesis_data:
            context_parts.append(format_thesis(thesis_data))
        
        # 5. OPTIONAL: Recent Trades
        if data.get('include_trades', False) and not trades_df.empty:
            context_parts.append(format_trades(trades_df, limit=100))
        
        # Combine all parts
        context_string = "\n\n---\n\n".join(context_parts) if context_parts else "No context data available"
        
        return jsonify({
            "success": True, 
            "context": context_string,
            "char_count": len(context_string)
        })
        
    except Exception as e:
        logger.error(f"Error generating context preview: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ============================================================================
# AI Assistant Routes (Flask v2)
# ============================================================================

@cache_data(ttl=30)
def _get_cached_ollama_health():
    """Check Ollama health with 30s cache"""
    from ollama_client import check_ollama_health
    return check_ollama_health()

@cache_data(ttl=30)
def _get_cached_searxng_health():
    """Check SearXNG health with 30s cache"""
    from searxng_client import check_searxng_health
    return check_searxng_health()

@cache_data(ttl=30)
def _get_cached_ollama_models():
    """Get available Ollama models with 30s cache"""
    from ollama_client import list_available_models
    return list_available_models()

@app.route('/ai_assistant')
@require_auth
def ai_assistant_page():
    """AI Assistant chat interface page (Flask v2)"""
    try:
        from flask_auth_utils import get_user_email_flask
        from user_preferences import get_user_theme, get_user_ai_model
        from flask_data_utils import get_available_funds_flask
        
        user_email = get_user_email_flask()
        user_theme = get_user_theme() or 'system'
        default_model = get_user_ai_model()
        
        # Get available funds (cached in flask_data_utils)
        available_funds = get_available_funds_flask()
        
        # Get available models (cached)
        ollama_models = _get_cached_ollama_models()
        ollama_available = _get_cached_ollama_health()
        searxng_available = _get_cached_searxng_health()
        
        # Check for WebAI models
        try:
            from ai_service_keys import get_model_display_name
            webai_models = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-3.0-pro"]
            has_webai = True
        except (ImportError, FileNotFoundError):
            webai_models = []
            has_webai = False
        
        # Get navigation context
        nav_context = get_navigation_context(current_page='ai_assistant')
        
        return render_template('ai_assistant.html',
                             user_email=user_email,
                             user_theme=user_theme,
                             default_model=default_model,
                             ollama_models=ollama_models,
                             ollama_available=ollama_available,
                             searxng_available=searxng_available,
                             webai_models=webai_models,
                             has_webai=has_webai,
                             **nav_context)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Error loading AI assistant page: {e}\n{tb}")
        # Show full stack trace on page for debugging
        return f'''<!DOCTYPE html>
<html>
<head><title>Error - AI Assistant</title></head>
<body style="background:#1a1a2e;color:#eee;font-family:monospace;padding:20px;">
<h1 style="color:#ff6b6b;">❌ Failed to load AI Assistant Page</h1>
<h2 style="color:#feca57;">Exception: {type(e).__name__}</h2>
<pre style="background:#16213e;padding:20px;border-radius:8px;overflow-x:auto;white-space:pre-wrap;word-wrap:break-word;">{e}</pre>
<h3 style="color:#54a0ff;">Stack Trace:</h3>
<pre style="background:#16213e;padding:20px;border-radius:8px;overflow-x:auto;white-space:pre-wrap;word-wrap:break-word;">{tb}</pre>
<p><a href="/" style="color:#5f27cd;">← Back to Dashboard</a></p>
</body>
</html>''', 500

@cache_data(ttl=30)
def _get_formatted_ai_models():
    """Get formatted AI models list with 30s cache"""
    from ollama_client import list_available_models
    try:
        from ai_service_keys import get_model_display_name
    except ImportError:
        def get_model_display_name(m): return m

    all_models = list_available_models()
    formatted_models = []
    for model in all_models:
        if model.startswith("glm-"):
            # Only expose GLM in the selectable list when the API key is set
            try:
                from glm_config import get_zhipu_api_key
                if not get_zhipu_api_key():
                    continue
            except ImportError:
                continue
            display_name = "GLM " + model[4:].replace("-", " ") if len(model) > 4 else model
            formatted_models.append({"id": model, "name": display_name, "type": "glm"})
            continue
        is_webai = model.startswith('gemini-')
        display_name = model

        if is_webai:
            try:
                display_name = get_model_display_name(model)
                # Add sparkle to webai models if not already there
                if 'AI' in display_name or 'Gemini' in display_name:
                     display_name = f"✨ {display_name}"
            except:
                pass
        
        formatted_models.append({
            'id': model,
            'name': display_name,
            'type': 'webai' if is_webai else 'ollama'
        })
    
    return formatted_models

@app.route('/api/v2/ai/models', methods=['GET'])
@require_auth
def api_ai_models():
    """Get available AI models"""
    try:
        formatted_models = _get_formatted_ai_models()
        return jsonify({"models": formatted_models})
    except Exception as e:
        logger.error(f"Error fetching AI models: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/v2/ai/context/build', methods=['POST'])
# Context build endpoint - v2
@require_auth
def api_ai_context_build():
    """Build context string with portfolio data tables (called by JS before chat)"""
    try:
        from flask_auth_utils import get_user_id_flask
        from ai_context_builder import (
            format_holdings, format_thesis, format_trades, 
            format_performance_metrics, format_cash_balances
        )
        # Use Flask-safe data access
        from flask_data_utils import (
            get_current_positions_flask, get_trade_log_flask
        )
        from flask_data_utils import (
            get_cash_balances_flask, calculate_portfolio_value_over_time_flask,
            get_fund_thesis_data_flask, calculate_performance_metrics_flask
        )
        
        data = request.get_json()
        fund = data.get('fund')
        
        logger.info(f"[Context Build] Request received for fund: {fund}")
        
        if not fund:
            logger.warning("[Context Build] No fund specified, returning empty context")
            return jsonify({"context_string": "", "char_count": 0})

        context_parts = []
        
        # --- Always Included: Holdings with all data tables ---
        positions_df = get_current_positions_flask(fund)
        trades_df = get_trade_log_flask(limit=100, fund=fund)
        
        logger.info(f"[Context Build] Positions count: {len(positions_df) if positions_df is not None else 0}")
        logger.info(f"[Context Build] Trades count: {len(trades_df) if trades_df is not None else 0}")
        
        include_pv = data.get('include_price_volume', True)
        include_fund = data.get('include_fundamentals', True)
        
        if not positions_df.empty:
            holdings_text = format_holdings(
                positions_df,
                fund,
                trades_df=trades_df,
                include_price_volume=include_pv,
                include_fundamentals=include_fund
            )
            context_parts.append(holdings_text)
            logger.info(f"[Context Build] Holdings text length: {len(holdings_text)}")
        else:
            logger.warning(f"[Context Build] No positions found for fund: {fund}")
        
        # --- Always Included: Performance Metrics ---
        try:
            metrics = calculate_performance_metrics_flask(fund)
            portfolio_df = calculate_portfolio_value_over_time_flask(fund, days=365)
            if metrics:
                context_parts.append(format_performance_metrics(metrics, portfolio_df))
                logger.info(f"[Context Build] Performance metrics added")
        except Exception as e:
            logger.warning(f"Error loading performance metrics: {e}")
        
        # --- Always Included: Cash Balances ---
        try:
            cash = get_cash_balances_flask(fund)
            if cash:
                context_parts.append(format_cash_balances(cash))
                logger.info(f"[Context Build] Cash balances added")
        except Exception as e:
            logger.warning(f"Error loading cash balances: {e}")
        
        # --- Optional: Thesis ---
        if data.get('include_thesis', False):
            try:
                thesis_data = get_fund_thesis_data_flask(fund)
                if thesis_data:
                    context_parts.append(format_thesis(thesis_data))
            except Exception as e:
                logger.warning(f"Error loading thesis: {e}")
        
        # --- Optional: Trades ---
        if data.get('include_trades', False):
            try:
                if trades_df is not None and not trades_df.empty:
                    context_parts.append(format_trades(trades_df, limit=100))
            except Exception as e:
                logger.warning(f"Error loading trades: {e}")
        
        # Combine all parts
        context_string = "\n\n---\n\n".join(context_parts) if context_parts else ""
        
        logger.info(f"[Context Build] Final context length: {len(context_string)} chars, {len(context_parts)} parts")
        
        return jsonify({
            "context_string": context_string,
            "char_count": len(context_string)
        })
        
    except Exception as e:
        logger.error(f"Error building context: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/api/v2/ai/context', methods=['GET', 'POST'])
@require_auth
def api_ai_context():
    """Get or update context items"""
    try:
        from flask_auth_utils import get_user_id_flask
        from chat_context import ContextItemType, ContextItem
        import json as json_lib
        
        user_id = get_user_id_flask()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401
        
        # Initialize context in session if needed
        if 'ai_context_items' not in session:
            session['ai_context_items'] = []
        
        if request.method == 'GET':
            # Return current context items
            context_items = session.get('ai_context_items', [])
            # Convert to serializable format
            items = []
            for item_dict in context_items:
                items.append({
                    'item_type': item_dict['item_type'],
                    'fund': item_dict.get('fund'),
                    'metadata': item_dict.get('metadata', {})
                })
            return jsonify({"items": items})
        
        elif request.method == 'POST':
            # Add or remove context item
            data = request.get_json()
            action = data.get('action')  # 'add' or 'remove'
            item_type_str = data.get('item_type')
            fund = data.get('fund')
            metadata = data.get('metadata', {})
            
            try:
                item_type = ContextItemType(item_type_str)
            except ValueError:
                return jsonify({"error": f"Invalid item type: {item_type_str}"}), 400
            
            context_items = session.get('ai_context_items', [])
            
            # Create item dict for comparison
            item_dict = {
                'item_type': item_type_str,
                'fund': fund,
                'metadata': metadata
            }
            
            if action == 'add':
                # Check if already exists
                if item_dict not in context_items:
                    context_items.append(item_dict)
                    session['ai_context_items'] = context_items
                    return jsonify({"success": True, "message": "Item added"})
                else:
                    return jsonify({"success": False, "message": "Item already exists"})
            
            elif action == 'remove':
                if item_dict in context_items:
                    context_items.remove(item_dict)
                    session['ai_context_items'] = context_items
                    return jsonify({"success": True, "message": "Item removed"})
                else:
                    return jsonify({"success": False, "message": "Item not found"})
            
            elif action == 'clear':
                session['ai_context_items'] = []
                return jsonify({"success": True, "message": "All items cleared"})
            
            else:
                return jsonify({"error": f"Invalid action: {action}"}), 400
    
    except Exception as e:
        logger.error(f"Error managing context: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500





@app.route('/api/v2/ai/repository', methods=['POST'])
@require_auth
def api_ai_repository():
    """Search research repository (RAG)"""
    try:
        from ollama_client import get_ollama_client, check_ollama_health
        from research_repository import ResearchRepository
        
        if not check_ollama_health():
            return jsonify({"error": "Ollama unavailable (required for embeddings)"}), 503
        
        data = request.get_json()
        user_query = data.get('query', '')
        max_results = data.get('max_results', 3)
        min_similarity = data.get('min_similarity', 0.6)
        
        # Generate embedding
        client = get_ollama_client()
        if not client:
            return jsonify({"error": "Ollama client not available"}), 503
        
        query_embedding = client.generate_embedding(user_query)
        if not query_embedding:
            return jsonify({"error": "Failed to generate embedding"}), 500
        
        # Search repository
        repo = ResearchRepository()
        articles = repo.search_similar_articles(
            query_embedding=query_embedding,
            limit=max_results,
            min_similarity=min_similarity
        )
        
        return jsonify({
            "success": True,
            "articles": articles
        })
    
    except Exception as e:
        logger.error(f"Error searching repository: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/api/v2/ai/portfolio-intelligence', methods=['POST'])
@require_auth
def api_ai_portfolio_intelligence():
    """Check portfolio news from research repository"""
    try:
        from research_repository import ResearchRepository
        from flask_data_utils import get_current_positions_flask
        
        data = request.get_json()
        fund = data.get('fund')
        
        if not fund:
            return jsonify({"error": "Fund is required"}), 400
        
        # Initialize repository
        repo = ResearchRepository()
        
        # Get portfolio tickers
        portfolio_tickers = set()
        positions_df = get_current_positions_flask(fund)
        if not positions_df.empty and 'ticker' in positions_df.columns:
            portfolio_tickers = {t.strip().upper() for t in positions_df['ticker'].dropna().unique()}
        
        if not portfolio_tickers:
            return jsonify({
                "success": False,
                "message": "No positions found in current portfolio to check.",
                "matching_articles": []
            })
        
        # Fetch recent articles
        recent_articles = repo.get_recent_articles(limit=50, days=7)
        
        # Filter for holdings
        matching_articles = []
        seen_titles = set()
        
        for article in recent_articles:
            article_tickers = article.get('tickers')
            if not article_tickers:
                continue
            
            art_ticker_set = {t.upper() for t in article_tickers}
            matches = art_ticker_set.intersection(portfolio_tickers)
            
            if matches and article['title'] not in seen_titles:
                matching_articles.append({
                    'title': article.get('title'),
                    'matched_holdings': list(matches),
                    'summary': article.get('summary', 'No summary'),
                    'conclusion': article.get('conclusion', 'N/A'),
                    'source': article.get('source', 'Unknown'),
                    'published_at': article.get('published_at', '')
                })
                seen_titles.add(article['title'])
        
        return jsonify({
            "success": True,
            "matching_articles": matching_articles,
            "count": len(matching_articles)
        })
    
    except Exception as e:
        logger.error(f"Error checking portfolio news: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/api/v2/ai/chat', methods=['POST'])
@require_auth
def api_ai_chat():
    """Handle chat message and stream AI response"""
    try:
        from flask import Response, stream_with_context
        from flask_auth_utils import get_user_id_flask
        from chat_context import ContextItemType
        from ai_context_builder import (
            format_holdings, format_thesis, format_trades,
            format_performance_metrics, format_cash_balances
        )
        from flask_data_utils import (
            get_current_positions_flask, get_trade_log_flask
        )
        from flask_data_utils import (
            get_cash_balances_flask, calculate_portfolio_value_over_time_flask,
            get_fund_thesis_data_flask, calculate_performance_metrics_flask
        )
        from ai_prompts import get_system_prompt
        from search_utils import format_search_results
        from research_utils import escape_markdown
        import json as json_lib
        
        user_id = get_user_id_flask()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401
        
        data = request.get_json()
        user_query = data.get('query', '')
        model = data.get('model')
        fund = data.get('fund')
        context_items = data.get('context_items', [])
        conversation_history = data.get('conversation_history', [])
        include_search = data.get('include_search', False)
        include_repository = data.get('include_repository', False)
        search_results = data.get('search_results')  # Pre-computed search results
        repository_articles = data.get('repository_articles')  # Pre-computed repository results
        
        if not user_query:
            return jsonify({"error": "Query is required"}), 400
        
        # Use pre-built context string if provided (from caching), otherwise build it
        context_string = data.get('context_string', '')
        
        if not context_string:
            # Build context string from items
            context_parts = []
            
            for item_dict in context_items:
                item_type_str = item_dict['item_type']
                item_fund = item_dict.get('fund') or fund
                
                try:
                    item_type = ContextItemType(item_type_str)
                except ValueError:
                    continue
                
                try:
                    if item_type == ContextItemType.HOLDINGS:
                        positions_df = get_current_positions_flask(item_fund)
                        trades_df = get_trade_log_flask(limit=1000, fund=item_fund) if item_fund else None
                        include_pv = data.get('include_price_volume', True)
                        include_fund = data.get('include_fundamentals', True)
                        context_parts.append(
                            format_holdings(
                                positions_df,
                                item_fund or "Unknown",
                                trades_df=trades_df,
                                include_price_volume=include_pv,
                                include_fundamentals=include_fund
                            )
                        )
                    elif item_type == ContextItemType.THESIS:
                        thesis_data = get_fund_thesis_data_flask(item_fund or "")
                        if thesis_data:
                            context_parts.append(format_thesis(thesis_data))
                    elif item_type == ContextItemType.TRADES:
                        limit = item_dict.get('metadata', {}).get('limit', 100)
                        trades_df = get_trade_log_flask(limit=limit, fund=item_fund)
                        context_parts.append(format_trades(trades_df, limit))
                    elif item_type == ContextItemType.METRICS:
                        portfolio_df = calculate_portfolio_value_over_time_flask(item_fund, days=365) if item_fund else None
                        metrics = calculate_performance_metrics_flask(item_fund) if item_fund else {}
                        context_parts.append(format_performance_metrics(metrics, portfolio_df))
                    elif item_type == ContextItemType.CASH_BALANCES:
                        cash = get_cash_balances_flask(item_fund) if item_fund else {}
                        context_parts.append(format_cash_balances(cash))
                except Exception as e:
                    logger.warning(f"Error loading {item_type_str}: {e}")
                    continue
            
            context_string = "\n\n---\n\n".join(context_parts) if context_parts else ""
        
        # Add search results if provided (always add these dynamically)
        if search_results and search_results.get('formatted'):
            if context_string:
                context_string = f"{context_string}\n\n---\n\n{search_results['formatted']}"
            else:
                context_string = search_results['formatted']
        
        # Add repository articles if provided (always add these dynamically)
        if repository_articles:
            articles_text = "## Relevant Research from Repository:\n\n"
            for i, article in enumerate(repository_articles, 1):
                similarity = article.get('similarity', 0)
                title = article.get('title', 'Untitled')
                summary = escape_markdown(article.get('summary', article.get('content', '')[:300]))
                source = article.get('source', 'Unknown')
                published = article.get('published_at', '')
                
                articles_text += f"### Article {i} (Similarity: {similarity:.2%})\n"
                articles_text += f"**{title}**\n"
                articles_text += f"*Source: {source}"
                if published:
                    articles_text += f" | Published: {published}"
                articles_text += "*\n\n"
                if summary:
                    articles_text += f"{summary}\n\n"
                articles_text += "---\n\n"
            
            if context_string:
                context_string = f"{context_string}\n\n{articles_text}"
            else:
                context_string = articles_text
        
        # Generate prompt using context items
        # Simple prompt generation (can be enhanced later)
        if context_items:
            # Build a descriptive prompt based on context items
            item_types = [item.get('item_type') for item in context_items]
            if 'holdings' in item_types and 'thesis' in item_types:
                prompt = f"Based on the portfolio holdings and investment thesis provided above, analyze how well the current positions align with the stated investment strategy. {user_query}"
            elif 'trades' in item_types:
                prompt = f"Based on the trading activity data provided above, analyze recent trades and review trade patterns. {user_query}"
            elif 'metrics' in item_types:
                prompt = f"Based on the performance metrics data provided above, analyze portfolio performance. {user_query}"
            else:
                prompt = f"Based on the portfolio data provided above, {user_query}"
        else:
            prompt = user_query
        
        # Combine context and prompt
        full_prompt = prompt
        if context_string:
            full_prompt = f"{context_string}\n\n{prompt}"
        
        # Get system prompt
        system_prompt = get_system_prompt()
        
        # Check if using WebAI or Ollama
        if model and model.startswith("gemini-"):
            # WebAI (non-streaming)
            try:
                from webai_wrapper import PersistentConversationSession
                from ai_service_keys import get_model_display_name_short
                
                # Get or create session
                session_key = f'webai_session_{user_id}'
                if session_key not in session:
                    session[session_key] = PersistentConversationSession(
                        session_id=user_id,
                        auto_refresh=False,
                        model=model,
                        system_prompt=system_prompt
                    )
                
                webai_session = session[session_key]
                
                # For WebAI, include instructions in message
                webai_instructions = (
                    "You are an AI portfolio assistant. Analyze the provided portfolio data, "
                    "news, and research articles to provide insights. Be concise and actionable.\n\n"
                )
                webai_message = webai_instructions + full_prompt
                
                # Send message (non-streaming)
                full_response = webai_session.send_sync(webai_message)
                
                return jsonify({
                    "response": full_response,
                    "model": model,
                    "streaming": False
                })
            
            except Exception as e:
                logger.error(f"WebAI error: {e}", exc_info=True)
                return jsonify({"error": f"WebAI error: {str(e)}"}), 500

        elif model and model.startswith("glm-"):
            # GLM via Z.AI (OpenAI-compatible /chat/completions, streaming)
            try:
                from glm_config import get_zhipu_api_key, ZHIPU_BASE_URL

                key = get_zhipu_api_key()
                if not key:
                    return jsonify({"error": "GLM API key not set. Add ZHIPU_API_KEY or save via AI Settings."}), 503

                # Model config for max_tokens / temperature
                cfg_path = Path(__file__).resolve().parent / "model_config.json"
                me = {}
                if cfg_path.exists():
                    try:
                        with open(cfg_path, "r", encoding="utf-8") as f:
                            mc = json_lib.load(f)
                        me = (mc.get("models") or {}).get(model, mc.get("default_config") or {})
                    except Exception:
                        pass
                max_tokens = me.get("max_tokens") or me.get("num_predict") or 4096
                temperature = float(me.get("temperature", 0.1))

                # Build messages: system, then conversation_history, then user
                messages = [{"role": "system", "content": system_prompt}]
                for h in (conversation_history or []):
                    role = (h.get("role") or "user").lower()
                    if role == "assistant":
                        role = "assistant"
                    elif role != "system":
                        role = "user"
                    content = h.get("content") or h.get("text") or ""
                    if content:
                        messages.append({"role": role, "content": content})
                messages.append({"role": "user", "content": full_prompt})

                url = f"{ZHIPU_BASE_URL.rstrip('/')}/chat/completions"
                headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                payload = {
                    "model": model,
                    "messages": messages,
                    "stream": True,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }

                def generate_glm():
                    try:
                        r = requests.post(url, json=payload, headers=headers, stream=True, timeout=90)
                        r.raise_for_status()
                        for line in r.iter_lines(decode_unicode=True):
                            if not line or not line.strip():
                                continue
                            s = line.strip()
                            if s.startswith("data: "):
                                data = s[6:].strip()
                                if data == "[DONE]":
                                    yield f"data: {json_lib.dumps({'chunk': '', 'done': True})}\n\n"
                                    return
                                try:
                                    obj = json_lib.loads(data)
                                    for c in (obj.get("choices") or [])[:1]:
                                        delta = c.get("delta") or {}
                                        part = delta.get("content") or ""
                                        if part:
                                            yield f"data: {json_lib.dumps({'chunk': part, 'done': False})}\n\n"
                                        if c.get("finish_reason") == "stop":
                                            yield f"data: {json_lib.dumps({'chunk': '', 'done': True})}\n\n"
                                            return
                                except json_lib.JSONDecodeError:
                                    continue
                        yield f"data: {json_lib.dumps({'chunk': '', 'done': True})}\n\n"
                    except Exception as e:
                        logger.error(f"GLM streaming error: {e}", exc_info=True)
                        yield f"data: {json_lib.dumps({'error': str(e), 'done': True})}\n\n"

                return Response(
                    stream_with_context(generate_glm()),
                    mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
            except ImportError as e:
                logger.error(f"GLM import error: {e}", exc_info=True)
                return jsonify({"error": "glm_config not available"}), 500
            except Exception as e:
                logger.error(f"GLM error: {e}", exc_info=True)
                return jsonify({"error": str(e)}), 500

        else:
            # Ollama (streaming)
            from ollama_client import get_ollama_client
            
            client = get_ollama_client()
            if not client:
                return jsonify({"error": "Ollama client not available"}), 503
            
            def generate():
                """Generator for streaming response"""
                try:
                    for chunk in client.query_ollama(
                        prompt=full_prompt,
                        model=model or "granite3.2:8b",
                        stream=True,
                        temperature=None,
                        max_tokens=None,
                        system_prompt=system_prompt
                    ):
                        yield f"data: {json_lib.dumps({'chunk': chunk, 'done': False})}\n\n"
                    
                    # Send done signal
                    yield f"data: {json_lib.dumps({'chunk': '', 'done': True})}\n\n"
                
                except Exception as e:
                    logger.error(f"Streaming error: {e}", exc_info=True)
                    error_msg = json_lib.dumps({'error': str(e), 'done': True})
                    yield f"data: {error_msg}\n\n"
            
            return Response(
                stream_with_context(generate()),
                mimetype='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'X-Accel-Buffering': 'no'  # Disable nginx buffering
                }
            )
    
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


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
    """Get all unique tickers from congress_trades table (cached 1 hour)"""
    if _cache_version is None:
        try:
            from cache_version import get_cache_version
            _cache_version = get_cache_version()
        except ImportError:
            _cache_version = ""
    
    try:
        if _supabase_client is None:
            return []
        
        all_tickers = set()
        batch_size = 1000
        offset = 0
        
        while True:
            result = _supabase_client.supabase.table("congress_trades_enriched")\
                .select("ticker")\
                .range(offset, offset + batch_size - 1)\
                .execute()
            
            if not result.data:
                break
            
            for trade in result.data:
                ticker = trade.get('ticker')
                if ticker:
                    all_tickers.add(ticker)
            
            if len(result.data) < batch_size:
                break
            
            offset += batch_size
            
            if offset > 100000:
                logger.warning("Reached 100,000 row safety limit in get_unique_tickers_congress pagination")
                break
        
        return sorted(list(all_tickers))
    except Exception as e:
        logger.error(f"Error fetching unique tickers: {e}", exc_info=True)
        return []

@cache_data(ttl=3600)
def get_unique_politicians_congress(_supabase_client, refresh_key: int, _cache_version: Optional[str] = None) -> List[str]:
    """Get all unique politicians from congress_trades table (cached 1 hour)"""
    if _cache_version is None:
        try:
            from cache_version import get_cache_version
            _cache_version = get_cache_version()
        except ImportError:
            _cache_version = ""
    
    try:
        if _supabase_client is None:
            return []
        
        all_politicians = set()
        batch_size = 1000
        offset = 0
        
        while True:
            result = _supabase_client.supabase.table("congress_trades_enriched")\
                .select("politician")\
                .range(offset, offset + batch_size - 1)\
                .execute()
            
            if not result.data:
                break
            
            for trade in result.data:
                politician = trade.get('politician')
                if politician:
                    all_politicians.add(politician)
            
            if len(result.data) < batch_size:
                break
            
            offset += batch_size
            
            if offset > 100000:
                logger.warning("Reached 100,000 row safety limit in get_unique_politicians_congress pagination")
                break
        
        return sorted(list(all_politicians))
    except Exception as e:
        logger.error(f"Error fetching unique politicians: {e}", exc_info=True)
        return []

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
    min_score: Optional[float] = None,
    max_score: Optional[float] = None,
    _postgres_client = None
) -> List[Dict[str, Any]]:
    """Get congress trades with filters (cached 6 hours). Fetches ALL matching rows."""
    try:
        if _supabase_client is None:
            return []
        
        # Optimize query to select only needed columns
        query = _supabase_client.supabase.table("congress_trades_enriched").select(
            "id, ticker, politician, chamber, party, state, transaction_date, type, amount, owner"
        )
        
        if ticker_filter:
            query = query.eq("ticker", ticker_filter)
        if politician_filter:
            query = query.eq("politician", politician_filter)
        if chamber_filter:
            query = query.eq("chamber", chamber_filter)
        if type_filter:
            query = query.eq("type", type_filter)
        if start_date:
            query = query.gte("transaction_date", start_date)
        if end_date:
            query = query.lte("transaction_date", end_date)
        
        query = query.order("transaction_date", desc=True)
        
        # Get analysis data for filtering (needed for analyzed_only and score filters)
        analysis_map = get_analysis_data_congress(_postgres_client, refresh_key) if _postgres_client else {}
        
        # Fetch ALL rows using pagination (Supabase limits to 1000 per request)
        all_trades = []
        batch_size = 1000
        offset = 0

        while True:
            result = query.range(offset, offset + batch_size - 1).execute()

            if not result.data:
                break

            all_trades.extend(result.data)

            if len(result.data) < batch_size:
                break

            offset += batch_size

            # Safety limit
            if offset > 100000:
                logger.warning("Reached 100,000 row safety limit in get_congress_trades_cached pagination")
                break

        logger.info(f"[CongressTrades] Fetched {len(all_trades)} total rows from Supabase")
        
        # Post-process: filter by analysis status and score
        if analyzed_only or min_score is not None or max_score is not None:
            filtered_trades = []
            for trade in all_trades:
                trade_id = trade.get('id')
                
                if analyzed_only and trade_id not in analysis_map:
                    continue
                
                # Check score filters
                if min_score is not None or max_score is not None:
                    analysis = analysis_map.get(trade_id)
                    if not analysis or analysis.get('conflict_score') is None:
                        continue
                    
                    score_val = float(analysis['conflict_score'])
                    
                    # Check minimum score
                    if min_score is not None and score_val < min_score:
                        continue
                    
                    # Check maximum score (for Low Risk filter)
                    if max_score is not None and score_val >= max_score:
                        continue
                
                filtered_trades.append(trade)
            
            return filtered_trades
        
        return all_trades
    except Exception as e:
        logger.error(f"Error fetching congress trades: {e}", exc_info=True)
        return []

@cache_data(ttl=86400)  # Cache for 24 hours - company names don't change often
def get_company_names_map_congress(_supabase_client, tickers_tuple: tuple, _cache_version: Optional[str] = None) -> Dict[str, str]:
    """Batch fetch company names from securities table (cached 24 hours)"""
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
    
    try:
        # Query in chunks of 50 (Supabase limit)
        for i in range(0, len(tickers), 50):
            ticker_batch = tickers[i:i+50]
            result = _supabase_client.supabase.table("securities")\
                .select("ticker, company_name")\
                .in_("ticker", ticker_batch)\
                .execute()
            
            if result.data:
                for item in result.data:
                    ticker = item.get('ticker', '').upper()
                    company_name = item.get('company_name', '')
                    if company_name and company_name.strip() and company_name != 'Unknown':
                        company_names_map[ticker] = company_name.strip()
    except Exception as e:
        logger.warning(f"Error fetching company names: {e}")
    
    return company_names_map

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
        from user_preferences import get_user_theme
        from cache_version import get_cache_version
        from auth import is_admin
        
        user_email = get_user_email_flask()
        user_theme = get_user_theme() or 'system'
        
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
                                 user_theme=user_theme,
                                 error="Congress Trades Database Unavailable",
                                 error_message="The congress trades database is not available. Check the logs or contact an administrator.",
                                 **nav_context)
        
        # Get Postgres client
        postgres_client = get_postgres_client_congress()
        
        # Get filter values from query params
        chamber_filter = request.args.get('chamber', 'All')
        type_filter = request.args.get('type', 'All')
        analyzed_only = request.args.get('analyzed_only') == 'true'
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
                             user_theme=user_theme,
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
                             current_analyzed_only=analyzed_only,
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
                             user_theme='system',
                             error=str(e),
                             error_message="An error occurred loading congress trades. Please check the logs.",
                             **nav_context), 500

@app.route('/api/congress_trades/data')
@require_auth
def api_congress_trades_data():
    """API endpoint for congress trades data (JSON) - fetches ALL data at once"""
    try:
        from flask_auth_utils import get_auth_token
        from flask_data_utils import get_supabase_client_flask
        from cache_version import get_cache_version
        from auth import is_admin
        
        refresh_key = int(request.args.get('refresh_key', 0))
        
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
        analyzed_only = request.args.get('analyzed_only') == 'true'
        min_score = request.args.get('min_score')
        max_score = request.args.get('max_score')
        min_score = float(min_score) if min_score else None
        max_score = float(max_score) if max_score else None
        
        # Get ALL trades (cached - internal pagination happens in the function)
        all_trades = get_congress_trades_cached(
            supabase_client,
            refresh_key,
            ticker_filter=ticker_filter if ticker_filter and ticker_filter != 'All' else None,
            politician_filter=politician_filter if politician_filter and politician_filter != 'All' else None,
            chamber_filter=chamber_filter if chamber_filter and chamber_filter != 'All' else None,
            type_filter=type_filter if type_filter and type_filter != 'All' else None,
            start_date=start_date,
            end_date=end_date,
            analyzed_only=analyzed_only,
            min_score=min_score,
            max_score=max_score,
            _postgres_client=postgres_client
        )
        
        # Get analysis data
        analysis_map = get_analysis_data_congress(postgres_client, refresh_key) if postgres_client else {}
        
        # Get company names (cached) - optimize by only fetching for unique tickers in result
        unique_ticker_list = list(set([t.get('ticker') for t in all_trades if t.get('ticker')]))
        cache_version = get_cache_version()
        # Fetch company names in chunks is handled by get_company_names_map_congress
        company_names_map = get_company_names_map_congress(supabase_client, tuple(unique_ticker_list), cache_version)
        
        # Format trades data
        formatted_trades = []
        for trade in all_trades:
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
                'Score': score_display,
                'AI Reasoning': reasoning_short,
                'Owner': trade.get('owner', 'N/A'),
                '_tooltip': reasoning if reasoning else reasoning_short,
                '_full_reasoning': reasoning if reasoning else ''
            })

        return jsonify({
            "trades": formatted_trades,
            "has_more": False,
            "total": len(all_trades)
        })
    except ValueError as e:
        logger.error(f"Invalid parameter in congress trades API: {e}", exc_info=True)
        return jsonify({"error": f"Invalid parameter: {str(e)}"}), 400
    except Exception as e:
        logger.error(f"Error in congress trades API: {e}", exc_info=True)
        return jsonify({"error": "An error occurred while fetching congress trades data. Please check the logs."}), 500

if __name__ == '__main__':
    # Run the app
    # Use port 5001 to avoid conflict with NFT calculator app on port 5000
    port = int(os.getenv('FLASK_PORT', '5001'))
    app.run(debug=True, host='0.0.0.0', port=port)
