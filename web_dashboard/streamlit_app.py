#!/usr/bin/env python3
"""
Streamlit Portfolio Performance Dashboard
Displays historical performance graphs and current portfolio data
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timezone
import sys
from pathlib import Path
import base64
import json
import time
import os
import logging
from user_preferences import get_user_preference

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


# Initialize scheduler once per Streamlit worker process (lazy initialization)
_logger = logging.getLogger(__name__)
_postgres_checked = False
_scheduler_init_timeout = 30  # seconds



def _start_scheduler_with_result(result_holder: dict):
    """Helper function to run scheduler start in a thread and store result."""
    import threading
    import os
    
    thread_name = threading.current_thread().name
    thread_id = threading.current_thread().ident
    process_id = os.getpid() if hasattr(os, 'getpid') else 'N/A'
    
    try:
        _logger.debug(f"[PID:{process_id} TID:{thread_id}] [{thread_name}] Starting scheduler...")
        from scheduler import start_scheduler
        started = start_scheduler()
        result_holder["started"] = started
        result_holder["success"] = True
        _logger.debug(f"[PID:{process_id} TID:{thread_id}] [{thread_name}] Scheduler start completed (started={started})")
    except Exception as e:
        import traceback
        result_holder["success"] = False
        result_holder["error"] = str(e)
        result_holder["traceback"] = traceback.format_exc()
        _logger.error(f"[PID:{process_id} TID:{thread_id}] [{thread_name}] Scheduler start failed: {e}", exc_info=True)
    finally:
        _logger.debug(f"[PID:{process_id} TID:{thread_id}] [{thread_name}] Thread exiting")


# Use @st.cache_resource to ensure scheduler starts exactly once per process
# This is Streamlit's recommended pattern for singletons
@st.cache_resource
def _get_scheduler_singleton():
    """Initialize scheduler once per Streamlit process with timeout protection."""
    import threading
    
    _logger.info("="*60)
    _logger.info("SCHEDULER INITIALIZATION STARTING")
    _logger.info(f"  Process ID: {os.getpid()}")
    _logger.info(f"  Thread ID: {threading.current_thread().ident}")
    _logger.info(f"  Timeout: {_scheduler_init_timeout}s")
    _logger.info("="*60)
    
    # Use a thread with timeout to prevent indefinite hangs
    result_holder = {"success": False, "started": False, "error": None, "traceback": None}
    
    init_thread = threading.Thread(
        target=_start_scheduler_with_result,
        args=(result_holder,),
        name="SchedulerInitThread",
        daemon=True  # Don't block process exit
    )
    
    try:
        _logger.info("  → Starting scheduler init thread...")
        init_thread.start()
        init_thread.join(timeout=_scheduler_init_timeout)
        
        if init_thread.is_alive():
            # Timeout occurred - thread is still running
            _logger.error(f"❌ SCHEDULER INIT TIMEOUT after {_scheduler_init_timeout}s!")
            _logger.error("   The scheduler initialization is stuck (likely DB query or lock).")
            _logger.error("   Dashboard will continue without scheduler features.")
            return {"status": "timeout", "error": f"Initialization timed out after {_scheduler_init_timeout}s"}
        
        # Thread completed - check result
        if result_holder["success"]:
            if result_holder["started"]:
                _logger.info("✅ Scheduler started successfully")
            else:
                _logger.info("ℹ️ Scheduler already running (reused)")
            return {"status": "running", "error": None}
        else:
            _logger.error(f"❌ Scheduler failed to start: {result_holder['error']}")
            if result_holder["traceback"]:
                _logger.error(f"Traceback:\n{result_holder['traceback']}")
            return {"status": "failed", "error": result_holder["error"]}
            
    except Exception as e:
        import traceback
        _logger.error(f"❌ Unexpected error during scheduler init: {e}")
        _logger.error(f"Traceback:\n{traceback.format_exc()}")
        return {"status": "failed", "error": str(e)}


def _init_scheduler():
    """Initialize scheduler - wrapper for compatibility with graceful degradation."""
    # This will use the cached result if available, or run once if not
    try:
        result = _get_scheduler_singleton()
        status = result.get("status", "unknown")
        
        if status == "running":
            return True
        elif status == "timeout":
            _logger.warning("⚠️ Scheduler timed out - dashboard running without scheduler")
            return False
        else:
            _logger.warning(f"⚠️ Scheduler status: {status} - some features may be unavailable")
            return False
    except Exception as e:
        _logger.error(f"❌ Exception in _init_scheduler: {e}")
        return False





def _check_postgres_connection():
    """Check Postgres connection on startup and log status."""
    global _postgres_checked
    if _postgres_checked:
        return
    
    _postgres_checked = True
    
    try:
        import logging
        logger = logging.getLogger(__name__)
        
        # Check if RESEARCH_DATABASE_URL is set
        database_url = os.getenv("RESEARCH_DATABASE_URL")
        if not database_url:
            logger.warning("Postgres: RESEARCH_DATABASE_URL not set - research articles storage disabled")
            return
        
        # Try to connect
        from web_dashboard.postgres_client import PostgresClient
        client = PostgresClient()
        
        if client.test_connection():
            # Get basic stats
            try:
                result = client.execute_query("SELECT COUNT(*) as count FROM research_articles")
                count = result[0]['count'] if result else 0
                logger.info(f"Postgres: Connected successfully - {count} research articles in database")
            except Exception:
                logger.info("Postgres: Connected successfully (table may not exist yet)")
        else:
            logger.warning("Postgres: Connection test failed - research articles storage may not work")
    except ImportError:
        # psycopg2 not installed - that's okay, Postgres is optional
        logger = logging.getLogger(__name__)
        logger.debug("Postgres: psycopg2 not installed - research articles storage disabled")
    except Exception as e:
        # Fail gracefully - Postgres is optional
        logger = logging.getLogger(__name__)
        logger.warning(f"Postgres: Connection check failed (non-critical): {e}")



from streamlit_utils import (
    render_sidebar_fund_selector,
    get_available_funds,
    get_current_positions,
    get_trade_log,
    get_cash_balances,
    calculate_portfolio_value_over_time,
    get_supabase_client,
    get_investor_count,
    get_investor_allocations,
    get_user_investment_metrics,
    get_fund_thesis_data,
    get_realized_pnl,
    get_user_display_currency,
    convert_to_display_currency,
    fetch_latest_rates_bulk,
    display_dataframe_with_copy,
    get_biggest_movers
)
from aggrid_utils import display_aggrid_with_ticker_navigation, TICKER_CELL_RENDERER_JS, TICKER_CLICK_HANDLER_JS_TEMPLATE
from chart_utils import (
    create_portfolio_value_chart,
    create_performance_by_fund_chart,
    create_pnl_chart,
    create_trades_timeline_chart,
    create_currency_exposure_chart,
    create_sector_allocation_chart,
    create_investor_allocation_chart
)
from auth_utils import (
    login_user,
    register_user,
    is_authenticated,
    logout_user,
    set_user_session,
    get_user_email,
    get_user_id,
    get_user_token,
    is_admin
)

# Page configuration
st.set_page_config(
    page_title="Portfolio Performance Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': None,
        'Report a bug': None,
        'About': None
    }
)




# Custom CSS (dark mode compatible)
st.markdown("""
    <style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        margin-bottom: 1rem;
    }
    .metric-card {
        background-color: var(--secondary-background-color);
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    .timestamp-display {
        font-size: 0.9rem;
        margin-top: -0.8rem;
        margin-bottom: 0.5rem;
    }
    
    /* Modern Navigation Styling */
    /* Navigation section titles */
    .nav-section-title {
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: rgb(49, 51, 63);
        opacity: 0.7;
        margin: 1.5rem 0 0.75rem 0;
        padding: 0 0.5rem;
    }
    
    /* Dark mode support for section titles */
    @media (prefers-color-scheme: dark) {
        .nav-section-title {
            color: rgb(250, 250, 250);
        }
    }
    
    /* Navigation cards - style the page link containers */
    section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] > div[style*="flex-direction: column"] > div {
        transition: all 0.25s ease;
    }
    
    /* Style page links as cards */
    section[data-testid="stSidebar"] a[data-testid="stPageLink"] {
        display: block;
        padding: 0.75rem 1rem;
        margin: 0.5rem 0;
        background-color: var(--secondary-background-color, #f0f2f6);
        border-radius: 0.5rem;
        border: 1px solid rgba(128, 128, 128, 0.1);
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        transition: all 0.25s ease;
        text-decoration: none;
        color: inherit;
    }
    
    /* Dark mode adjustments for page links */
    @media (prefers-color-scheme: dark) {
        section[data-testid="stSidebar"] a[data-testid="stPageLink"] {
            background-color: var(--secondary-background-color, #262730);
            border-color: rgba(255, 255, 255, 0.1);
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
        }
    }
    
    section[data-testid="stSidebar"] a[data-testid="stPageLink"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        background-color: var(--background-color, #ffffff);
        border-color: rgba(128, 128, 128, 0.2);
    }
    
    @media (prefers-color-scheme: dark) {
        section[data-testid="stSidebar"] a[data-testid="stPageLink"]:hover {
            background-color: var(--background-color, #0e1117);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
        }
    }
    
    /* Active page link styling */
    section[data-testid="stSidebar"] a[data-testid="stPageLink"][aria-current="page"] {
        background: linear-gradient(135deg, rgba(255, 75, 75, 0.2) 0%, var(--secondary-background-color, #f0f2f6) 100%);
        border-color: rgba(255, 75, 75, 0.5);
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
        font-weight: 600;
    }
    
    @media (prefers-color-scheme: dark) {
        section[data-testid="stSidebar"] a[data-testid="stPageLink"][aria-current="page"] {
            background: linear-gradient(135deg, rgba(255, 75, 75, 0.3) 0%, var(--secondary-background-color, #262730) 100%);
            border-color: rgba(255, 75, 75, 0.6);
        }
    }
    
    /* Navigation badges */
    .nav-badge {
        display: inline-block;
        padding: 0.35rem 0.75rem;
        border-radius: 1rem;
        font-size: 0.75rem;
        font-weight: 600;
        margin: 0.5rem 0;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        transition: all 0.2s ease;
    }
    
    .nav-badge-admin {
        background: linear-gradient(135deg, #10b981 0%, #059669 100%);
        color: white;
    }
    
    .nav-badge-role {
        background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
        color: white;
    }
    
    .nav-badge:hover {
        transform: scale(1.05);
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
    }
    
    /* Modern divider */
    .nav-divider {
        height: 1px;
        background: linear-gradient(90deg, transparent 0%, rgba(128, 128, 128, 0.3) 50%, transparent 100%);
        margin: 1.5rem 0;
        border: none;
    }
    
    /* Style expander in sidebar */
    section[data-testid="stSidebar"] div[data-testid="stExpander"] {
        background-color: var(--secondary-background-color, #f0f2f6);
        border-radius: 0.5rem;
        border: 1px solid rgba(128, 128, 128, 0.1);
        margin: 0.5rem 0;
        padding: 0.5rem;
    }
    
    @media (prefers-color-scheme: dark) {
        section[data-testid="stSidebar"] div[data-testid="stExpander"] {
            background-color: var(--secondary-background-color, #262730);
            border-color: rgba(255, 255, 255, 0.1);
        }
    }
    
    section[data-testid="stSidebar"] div[data-testid="stExpander"]:hover {
        border-color: rgba(128, 128, 128, 0.2);
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }
    
    @media (prefers-color-scheme: dark) {
        section[data-testid="stSidebar"] div[data-testid="stExpander"]:hover {
            border-color: rgba(255, 255, 255, 0.2);
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
        }
    }
    
    /* Improve sidebar title styling */
    section[data-testid="stSidebar"] h1 {
        font-size: 1.5rem;
        font-weight: 700;
        margin-bottom: 1.5rem;
        background: linear-gradient(135deg, #ff4b4b 0%, #1f77b4 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
    }
    
    @media (prefers-color-scheme: dark) {
        section[data-testid="stSidebar"] h1 {
            background: linear-gradient(135deg, #ff6b6b 0%, #4dabf7 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
    }
    
    /* Style info/success boxes in sidebar */
    section[data-testid="stSidebar"] div[data-baseweb="notification"] {
        border-radius: 0.5rem;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        margin: 0.5rem 0;
        transition: all 0.2s ease;
    }
    
    section[data-testid="stSidebar"] div[data-baseweb="notification"]:hover {
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
    }
    </style>
""", unsafe_allow_html=True)


def show_login_page():
    """Display login/register page"""
    st.markdown('<div class="main-header">📈 Portfolio Performance Dashboard</div>', unsafe_allow_html=True)
    
    tab1, tab2, tab3 = st.tabs(["Login", "Register", "Forgot Password"])
    
    with tab1:
        st.markdown("### Login")
        
        # Magic link option
        use_magic_link = st.checkbox("Send magic link instead", key="use_magic_link")
        
        with st.form("login_form"):
            email = st.text_input("Email", type="default", key="login_email")
            
            if not use_magic_link:
                password = st.text_input("Password", type="password", key="login_password")
            else:
                password = None
                st.info("A magic link will be sent to your email. Click the link to log in.")
            
            submit = st.form_submit_button("Login" if not use_magic_link else "Send Magic Link")
            
            if submit:
                if email:
                    if use_magic_link:
                        # Send magic link
                        from auth_utils import send_magic_link
                        result = send_magic_link(email)
                        if result and result.get("success"):
                            st.success(result.get("message", "Magic link sent! Check your email."))
                        else:
                            error_msg = result.get("error", "Failed to send magic link") if result else "Failed to send magic link"
                            st.error(f"Error: {error_msg}")
                    else:
                        # Regular password login
                        if password:
                            result = login_user(email, password)
                            if result and "access_token" in result:
                                set_user_session(
                                    result["access_token"], 
                                    result["user"],
                                    refresh_token=result.get("refresh_token"),
                                    expires_at=result.get("expires_at")
                                )
                                st.success("Login successful!")
                                st.rerun()
                            else:
                                error_msg = result.get("error", "Login failed") if result else "Login failed"
                                st.error(f"Login failed: {error_msg}")
                        else:
                            st.error("Please enter your password")
                else:
                    st.error("Please enter your email")
    
    with tab2:
        st.markdown("### Register")
        with st.form("register_form"):
            email = st.text_input("Email", type="default", key="reg_email")
            password = st.text_input("Password", type="password", key="reg_password")
            confirm_password = st.text_input("Confirm Password", type="password", key="reg_confirm")
            submit = st.form_submit_button("Register")
            
            if submit:
                if email and password and confirm_password:
                    if password != confirm_password:
                        st.error("Passwords do not match")
                    else:
                        result = register_user(email, password)
                        if result and not result.get("error"):
                            # Registration succeeded
                            if result.get("access_token"):
                                # User is logged in immediately (email confirmation not required)
                                set_user_session(
                                    result["access_token"], 
                                    result.get("user"),
                                    refresh_token=result.get("refresh_token"),
                                    expires_at=result.get("expires_at")
                                )
                                st.success("✅ Registration successful! You are now logged in.")
                                st.rerun()
                            else:
                                # Email confirmation required
                                st.info("📧 **Registration successful!** Please check your email to confirm your account. Click the confirmation link in the email to complete registration.")
                        else:
                            error_msg = result.get("error", "Registration failed") if result else "Registration failed"
                            st.error(f"❌ Registration failed: {error_msg}")
                else:
                    st.error("Please fill in all fields")
    
    with tab3:
        st.markdown("### Reset Password")
        st.info("Enter your email address and we'll send you a password reset link.")
        
        with st.form("reset_password_form"):
            email = st.text_input("Email", type="default", key="reset_email")
            submit = st.form_submit_button("Send Reset Link")
            
            if submit:
                if email:
                    from auth_utils import request_password_reset
                    result = request_password_reset(email)
                    if result and result.get("success"):
                        st.success(result.get("message", "Password reset email sent! Check your inbox."))
                    else:
                        error_msg = result.get("error", "Failed to send reset email") if result else "Failed to send reset email"
                        st.error(f"Error: {error_msg}")
                else:
                    st.error("Please enter your email address")


def create_timestamp_display_component(timestamp_iso: str, is_market_open: bool, is_today: bool):
    """
    Create a JavaScript component to display timestamp in user's browser timezone.
    
    Args:
        timestamp_iso: ISO format timestamp string (UTC)
        is_market_open: Whether market is currently open
        is_today: Whether timestamp is from today
    """
    import streamlit.components.v1 as components
    
    js_code = f"""
    <div id="timestamp-container" style="font-size: 0.9rem; margin-top: -0.8rem; margin-bottom: 0.5rem; padding-top: 2px; line-height: 1.4; overflow: visible;"></div>
    <script>
    (function() {{
        function formatTimestamp() {{
            // Parse the timestamp
            const timestamp = new Date('{timestamp_iso}');
            const isMarketOpen = {str(is_market_open).lower()};
            const isToday = {str(is_today).lower()};
            
            // Get user's timezone
            const userTZ = Intl.DateTimeFormat().resolvedOptions().timeZone;
            
            // Calculate market close hour in user's timezone
            // Market closes at 4:00 PM EST (16:00 EST)
            // Create a date at 4pm EST on the timestamp date, then convert to user's timezone
            const timestampDate = new Date(timestamp);
            const year = timestampDate.getUTCFullYear();
            const month = timestampDate.getUTCMonth();
            const day = timestampDate.getUTCDate();
            
            // Determine if DST is in effect for EST/EDT
            // DST: 2nd Sunday of March to 1st Sunday of November
            function isDST(date) {{
                const m = date.getUTCMonth();
                if (m >= 3 && m <= 9) return true; // Apr-Oct = EDT
                if (m < 2 || m > 10) return false; // Jan-Feb, Nov-Dec = EST
                // March: check if after 2nd Sunday
                if (m === 2) {{
                    const d = date.getUTCDate();
                    const dow = date.getUTCDay();
                    // Find 2nd Sunday: first find 1st Sunday, then add 7 days
                    const firstSunday = 1 + (7 - dow) % 7;
                    const secondSunday = firstSunday + 7;
                    return d >= secondSunday;
                }}
                // November: check if before 1st Sunday
                if (m === 10) {{
                    const d = date.getUTCDate();
                    const dow = date.getUTCDay();
                    const firstSunday = 1 + (7 - dow) % 7;
                    return d < firstSunday;
                }}
                return false;
            }}
            
            // Market closes at 4pm EST = 20:00 UTC (EDT) or 21:00 UTC (EST)
            const marketCloseHourUTC = isDST(timestampDate) ? 20 : 21;
            
            // Create market close time in UTC
            const marketCloseUTC = new Date(Date.UTC(year, month, day, marketCloseHourUTC, 0, 0));
            
            // Determine if we should show minutes
            const showMinutes = isMarketOpen && isToday;
            
            // If market is closed or not today, use market close time instead of actual timestamp
            let displayTime = timestamp;
            if (!isMarketOpen || !isToday) {{
                // Use the market close time (already calculated in UTC)
                displayTime = marketCloseUTC;
            }}
            
            // Format the timestamp in user's timezone
            const options = {{
                weekday: 'long',
                month: 'short',
                day: 'numeric',
                hour: 'numeric',
                hour12: true,
                timeZone: userTZ
            }};
            
            if (showMinutes) {{
                options.minute = '2-digit';
            }}
            
            const formatted = new Intl.DateTimeFormat('en-US', options).format(displayTime);
            
            // Display the timestamp
            const container = document.getElementById('timestamp-container');
            if (container) {{
                container.textContent = 'Market data last updated: ' + formatted;
                // Detect if we're in dark mode by checking the iframe's background
                const isDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
                // Or check if body/container has dark background
                const bodyBg = window.getComputedStyle(document.body).backgroundColor;
                const isDarkBg = bodyBg && (bodyBg.includes('rgb(14, 17, 23)') || bodyBg.includes('rgb(38, 39, 48)') || bodyBg === 'rgb(0, 0, 0)');
                
                if (isDark || isDarkBg) {{
                    container.style.color = 'rgba(255, 255, 255, 0.8)';
                }} else {{
                    container.style.color = 'rgba(0, 0, 0, 0.8)';
                }}
            }}
        }}
        
        // Try to format immediately
        formatTimestamp();
        
        // Also try when DOM is ready (in case script runs before DOM)
        if (document.readyState === 'loading') {{
            document.addEventListener('DOMContentLoaded', formatTimestamp);
        }}
    }})();
    </script>
    """
    
    components.html(js_code, height=35)


def show_password_reset_page(access_token: str):
    """Display dedicated password reset page"""
    # Add link back to main page
    st.markdown('[← Back to Main Page](/)', unsafe_allow_html=True)
    st.markdown('<div class="main-header">🔐 Reset Your Password</div>', unsafe_allow_html=True)
    
    # Check if password reset already completed
    if st.session_state.get("password_reset_completed"):
        st.success("✅ **Password reset completed successfully!**")
        st.info("You can now log in with your new password.")
        st.markdown(f'[Click here to go to the main page](/) or wait 5 seconds to be redirected automatically.')
        st.markdown("""
        <script>
        setTimeout(function() {
            window.location.href = window.location.origin;
        }, 5000);
        </script>
        """, unsafe_allow_html=True)
        return
    
    # Check token expiration before showing form
    try:
        token_parts = access_token.split('.')
        if len(token_parts) >= 2:
            payload = token_parts[1]
            payload += '=' * (4 - len(payload) % 4)
            decoded = base64.urlsafe_b64decode(payload)
            user_data = json.loads(decoded)
            exp = user_data.get("exp", 0)
            current_time = int(time.time())
            
            if exp < current_time:
                st.error("❌ **Reset link expired** - This password reset link has expired. Please request a new one.")
                st.markdown(f'[Click here to go back to the main page](/) or wait 5 seconds to be redirected automatically.')
                st.markdown("""
                <script>
                setTimeout(function() {
                    window.location.href = window.location.origin;
                }, 5000);
                </script>
                """, unsafe_allow_html=True)
                return
        else:
            st.error("❌ **Invalid reset token** - The reset link is invalid.")
            st.markdown(f'[Click here to go back to the main page](/) or wait 5 seconds to be redirected automatically.')
            st.markdown("""
            <script>
            setTimeout(function() {
                window.location.href = window.location.origin;
            }, 5000);
            </script>
            """, unsafe_allow_html=True)
            return
    except Exception as e:
        st.error(f"❌ **Error processing reset token** - {e}")
        st.markdown(f'[Click here to go back to the main page](/) or wait 5 seconds to be redirected automatically.')
        st.markdown("""
        <script>
        setTimeout(function() {
            window.location.href = window.location.origin;
        }, 5000);
        </script>
        """, unsafe_allow_html=True)
        return
    
    # Set session with reset token first (required for password update)
    if "reset_token" not in st.session_state or st.session_state.reset_token != access_token:
        try:
            # Decode JWT to get user info
            token_parts = access_token.split('.')
            if len(token_parts) >= 2:
                payload = token_parts[1]
                payload += '=' * (4 - len(payload) % 4)
                decoded = base64.urlsafe_b64decode(payload)
                user_data = json.loads(decoded)
                
                user = {
                    "id": user_data.get("sub"),
                    "email": user_data.get("email")
                }
                
                # Set session with reset token
                set_user_session(access_token, user)
                st.session_state.reset_token = access_token
        except Exception as e:
            st.error(f"Error processing reset token: {e}")
            return
    
    # Show password reset form
    st.markdown("### Enter Your New Password")
    st.info("Please enter your new password below. Make sure it's strong and memorable.")
    
    with st.form("new_password_form"):
        new_password = st.text_input("New Password", type="password", key="new_password")
        confirm_password = st.text_input("Confirm Password", type="password", key="confirm_new_password")
        submit = st.form_submit_button("Update Password", use_container_width=True)
        
        if submit:
            if new_password and confirm_password:
                if new_password != confirm_password:
                    st.error("Passwords do not match")
                else:
                    # Update password using Supabase client with proper session validation
                    import os
                    from supabase import create_client
                    import requests
                    
                    supabase_url = os.getenv("SUPABASE_URL")
                    supabase_key = os.getenv("SUPABASE_PUBLISHABLE_KEY")
                    
                    if not supabase_url or not supabase_key:
                        st.error("❌ **Error**: Supabase configuration missing. Please contact support.")
                        st.stop()
                        return
                    
                    # Extract email from token for verification and display
                    user_email = None
                    try:
                        token_parts = access_token.split('.')
                        if len(token_parts) >= 2:
                            payload = token_parts[1]
                            payload += '=' * (4 - len(payload) % 4)
                            decoded = base64.urlsafe_b64decode(payload)
                            user_data = json.loads(decoded)
                            user_email = user_data.get("email")
                    except Exception as decode_error:
                        st.error(f"❌ **Error**: Failed to decode recovery token: {decode_error}")
                        if is_admin():
                            with st.expander("🔍 Debug Information"):
                                st.write(f"Token length: {len(access_token)}")
                                st.write(f"Token parts: {len(token_parts) if 'token_parts' in locals() else 'N/A'}")
                                st.exception(decode_error)
                        return
                    
                    if not user_email:
                        st.error("❌ **Error**: Could not extract email from recovery token. Please request a new reset link.")
                        return
                    
                    # Show status and try Supabase client first
                    status_container = st.container()
                    with status_container:
                        st.info(f"🔄 **Status**: Preparing to update password for {user_email}...")
                    
                    try:
                        # Try using Supabase client first
                        supabase = create_client(supabase_url, supabase_key)
                        
                        # Attempt to set session with recovery token
                        # Note: Recovery tokens may not have refresh_token, so this might fail
                        with status_container:
                            st.info("🔄 **Status**: Attempting to authenticate with Supabase client...")
                        
                        try:
                            # Try to set session - this may fail for recovery tokens without refresh_token
                            # But we'll try it first as it's the preferred method
                            session_response = supabase.auth.set_session(
                                access_token=access_token,
                                refresh_token=""  # Recovery tokens typically don't have this
                            )
                            
                            # Check if session was established
                            if session_response and hasattr(session_response, 'user') and session_response.user:
                                with status_container:
                                    st.success("✅ **Status**: Authenticated with Supabase client successfully!")
                                
                                # Use Supabase client to update password
                                with status_container:
                                    st.info("🔄 **Status**: Updating password using Supabase client...")
                                
                                user_response = supabase.auth.update_user({"password": new_password})
                                
                                if user_response and hasattr(user_response, 'user') and user_response.user:
                                    # Success using Supabase client
                                    with status_container:
                                        st.success("✅ **Status**: Password updated successfully using Supabase client!")
                                    
                                    st.session_state.password_reset_completed = True
                                    st.success("✅ **Password updated successfully!**")
                                    st.info("🔄 **Redirecting to main page...** You can now log in with your new password.")
                                    st.markdown(f'[Click here to go to the main page](/) or wait 5 seconds to be redirected automatically.')
                                    
                                    logout_user()
                                    if "reset_token" in st.session_state:
                                        del st.session_state.reset_token
                                    
                                    st.markdown("""
                                    <script>
                                    setTimeout(function() {
                                        window.location.href = window.location.origin;
                                    }, 5000);
                                    </script>
                                    """, unsafe_allow_html=True)
                                    
                                    st.rerun()
                                else:
                                    with status_container:
                                        st.warning("⚠️ **Status**: Supabase client update_user() returned invalid response, falling back to REST API...")
                                    raise Exception("Supabase client update_user() returned invalid response")
                            else:
                                with status_container:
                                    st.warning("⚠️ **Status**: Could not establish session with Supabase client (recovery tokens may not support this), falling back to REST API...")
                                raise Exception("Could not establish session with Supabase client")
                                
                        except Exception as client_error:
                            # Supabase client method failed, fall back to REST API
                            with status_container:
                                st.info(f"🔄 **Status**: Supabase client method unavailable ({str(client_error)[:50]}...), using REST API instead...")
                            
                            # Use REST API with access_token directly
                            # This validates the token server-side via JWT verification
                            with status_container:
                                st.info("🔄 **Status**: Sending password update request to Supabase REST API...")
                            
                            response = requests.put(
                                f"{supabase_url}/auth/v1/user",
                                headers={
                                    "apikey": supabase_key,
                                    "Authorization": f"Bearer {access_token}",
                                    "Content-Type": "application/json"
                                },
                                json={"password": new_password},
                                timeout=10
                            )
                            
                            with status_container:
                                st.info(f"📡 **Status**: Received response from Supabase API (HTTP {response.status_code})")
                            
                            if response.status_code == 200:
                                response_data = response.json() if response.text else {}
                                
                                # Show response data for debugging
                                with st.expander("🔍 API Response Details"):
                                    st.json(response_data)
                                
                                # Check truthiness consistently for all fields
                                if response_data.get("id") or response_data.get("user") or response_data.get("email"):
                                    # Success - password was updated via REST API
                                    with status_container:
                                        st.success("✅ **Status**: Password updated successfully via REST API!")
                                    
                                    st.session_state.password_reset_completed = True
                                    st.success("✅ **Password updated successfully!**")
                                    st.info("🔄 **Redirecting to main page...** You can now log in with your new password.")
                                    st.markdown(f'[Click here to go to the main page](/) or wait 5 seconds to be redirected automatically.')
                                    
                                    logout_user()
                                    if "reset_token" in st.session_state:
                                        del st.session_state.reset_token
                                    
                                    st.markdown("""
                                    <script>
                                    setTimeout(function() {
                                        window.location.href = window.location.origin;
                                    }, 5000);
                                    </script>
                                    """, unsafe_allow_html=True)
                                    
                                    st.rerun()
                                else:
                                    with status_container:
                                        st.error("❌ **Status**: API returned 200 but response data is invalid")
                                    st.error("❌ **Error**: Password update response was invalid. Please try again or request a new reset link.")
                                    
                                    if is_admin():
                                        with st.expander("🔍 Debug Information"):
                                            st.write("**Response Status**: 200 OK")
                                            st.write("**Response Data**:")
                                            st.json(response_data)
                                            st.write("**Expected Fields**: id, user, or email")
                                    
                                    return
                            else:
                                # API returned an error
                                with status_container:
                                    st.error(f"❌ **Status**: Supabase API returned error (HTTP {response.status_code})")
                                
                                try:
                                    error_data = response.json() if response.text else {}
                                    error_msg = error_data.get("msg") or error_data.get("message") or error_data.get("error_description") or f"HTTP {response.status_code}"
                                    
                                    # Provide helpful error messages
                                    if response.status_code == 401:
                                        st.error("❌ **Error**: Reset link expired or invalid. Please request a new password reset link.")
                                    elif response.status_code == 400:
                                        st.error(f"❌ **Error**: {error_msg}")
                                    else:
                                        st.error(f"❌ **Error**: Failed to update password. {error_msg}")
                                    
                                    # Show full error for debugging (admin only)
                                    if is_admin():
                                        with st.expander("🔍 Error Details"):
                                            st.write(f"**HTTP Status**: {response.status_code}")
                                            st.write("**Error Response**:")
                                            st.json(error_data)
                                            st.write("**Request Headers**:")
                                            st.json({
                                                "apikey": f"{supabase_key[:10]}...",
                                                "Authorization": "Bearer [token]",
                                                "Content-Type": "application/json"
                                            })
                                            st.write("**User Email**:", user_email)
                                        
                                except Exception as parse_error:
                                    st.error(f"❌ **Error**: Failed to update password (HTTP {response.status_code}). Could not parse error response.")
                                    if is_admin():
                                        with st.expander("🔍 Debug Information"):
                                            st.write(f"**HTTP Status**: {response.status_code}")
                                            st.write(f"**Response Text**: {response.text[:500]}")
                                            st.exception(parse_error)
                                
                                return
                                
                    except requests.exceptions.Timeout:
                        st.error("❌ **Error**: Request timed out. Please check your connection and try again.")
                        if is_admin():
                            with st.expander("🔍 Debug Information"):
                                st.write("**Error Type**: Network Timeout")
                                st.write("**Timeout**: 10 seconds")
                    except requests.exceptions.RequestException as e:
                        st.error(f"❌ **Error**: Network error - {str(e)}. Please try again.")
                        if is_admin():
                            with st.expander("🔍 Debug Information"):
                                st.write("**Error Type**: Network Request Exception")
                                st.exception(e)
                    except Exception as e:
                        error_msg = str(e)
                        st.error(f"❌ **Error**: Unexpected error updating password: {error_msg}. Please try again or request a new reset link.")
                        if is_admin():
                            with st.expander("🔍 Error Details"):
                                st.write("**Error Type**: Unexpected Exception")
                            st.exception(e)
                            st.write("**User Email**:", user_email)
                            st.write("**Supabase URL**:", supabase_url)
            else:
                st.error("Please fill in both password fields")


def format_currency_label(currency_code: str) -> str:
    """Format currency code for display in labels.
    
    Args:
        currency_code: Currency code (e.g., 'CAD', 'USD')
        
    Returns:
        Formatted label like "(CAD)" or "(USD)"
    """
    return f"({currency_code})"


def main():
    """Main dashboard function"""
    
    # Generate or retrieve session ID for log tracking
    if 'session_id' not in st.session_state:
        import uuid
        st.session_state.session_id = str(uuid.uuid4())[:8]  # Short 8-char ID
    
    session_id = st.session_state.session_id
    
    # Initialize file-based logging
    try:
        from log_handler import setup_logging, log_message
        setup_logging()
        import time
        start_time = time.time()
        log_message(f"[{session_id}] PERF: Streamlit script run started", level='DEBUG')
    except Exception as e:
        print(f"Warning: Could not initialize logging: {e}")
    
    # Handle magic link token from query params (set by JavaScript hash processor above)
    import base64
    import json
    import time
    
    # ===== TOKEN REFRESH =====
    # Check if token needs to be refreshed (before authentication checks)
    # This ensures users stay logged in when active
    if is_authenticated():
        from auth_utils import refresh_token_if_needed
        try:
            refreshed = refresh_token_if_needed()
            if not refreshed:
                # Refresh failed - token is invalid or expired
                # Log user out with appropriate reason
                logout_user("session_expired")
        except Exception as e:
            # If refresh check fails, continue anyway (token might still be valid)
            pass
    
    # ===== COOKIE UPDATE STRATEGY =====
    # We don't update the cookie automatically during active use to avoid disruptive redirects.
    # Instead:
    # 1. During active use: Session state is maintained, so cookie staleness doesn't matter
    # 2. On page reload: Cookie is checked and restored (see below)
    # 3. When restoring from cookie: We update it with the current valid token (no redirect needed)
    # 
    # This means the cookie might be slightly stale during active use, but that's fine since
    # we rely on session state. The cookie is only needed for restoration after page reload.
    
    # Clear the update flag - we'll handle cookie updates when restoring from cookie instead
    if "_cookie_needs_update" in st.session_state:
        # Token was refreshed, but we'll update cookie on next page load/restore
        # This avoids disruptive redirects during active use
        del st.session_state._cookie_needs_update
    
    # Helper to get current page path for return_to redirects
    def get_current_page_path():
        """Get the current page path to redirect back to after cookie operations."""
        # 1. Check query parameters first (passed from subpages)
        try:
            if "return_to" in st.query_params:
                return st.query_params["return_to"]
        except Exception:
            pass
            
        # 2. Check session state (set before switching pages)
        if "return_to" in st.session_state:
            val = st.session_state.return_to
            # Clear it so it doesn't persist forever
            del st.session_state.return_to
            return val

        # 3. Fallback to Referer header
        try:
            # Try to get path from st.context.headers (Streamlit 1.37+)
            headers = getattr(st.context, 'headers', {})
            referer = headers.get('Referer', '')
            if referer:
                from urllib.parse import urlparse
                parsed = urlparse(referer)
                if parsed.path:
                    # Strip lead slash if redirecting to pages/...
                    path = parsed.path
                    if path.startswith('/pages/'):
                        return path.substring(1) if hasattr(path, 'substring') else path[1:]
                    return path
        except Exception:
            pass
            
        # Default to root if we can't determine the path
        return '/'
    
    # ===== SESSION PERSISTENCE VIA COOKIES =====
    # Cookies are set in auth_callback.html and set_cookie.html (regular HTML pages, not iframe)
    # Cookies are read here using st.context.cookies (server-side, Streamlit 1.37+)
    # Both access_token and refresh_token are now stored in cookies for full session recovery
    
    # Try to restore session from cookie if not already authenticated
    if not is_authenticated():
        try:
            # st.context.cookies is available in Streamlit 1.37+
            # It's a read-only dict of cookies sent in the initial HTTP request
            cookies = st.context.cookies
            auth_token = cookies.get("auth_token")
            cookie_refresh_token = cookies.get("refresh_token")
            
            if auth_token:
                # Validate token
                token_parts = auth_token.split('.')
                if len(token_parts) >= 2:
                    payload = token_parts[1]
                    payload += '=' * (4 - len(payload) % 4)
                    decoded = base64.urlsafe_b64decode(payload)
                    user_data = json.loads(decoded)
                    exp = user_data.get("exp", 0)
                    user_id_from_token = user_data.get("sub")
                    user_email_from_token = user_data.get("email")
                    
                    current_time = int(time.time())
                    time_until_expiry = exp - current_time
                    
                    if exp > current_time:
                        # Token valid, restore session (skip redirect since we're restoring from cookie)
                        # Also restore refresh_token from cookie so we can refresh later
                        set_user_session(auth_token, skip_cookie_redirect=True, expires_at=exp,
                                        refresh_token=cookie_refresh_token)
                        
                        # Update cookie proactively on page load to keep it fresh
                        # Refresh if cookie has <= 30 minutes left (keeps it fresh)
                        # This ensures cookie stays valid and prevents logout on next page load
                        # Redirects only happen on page load, not during active use
                        if time_until_expiry <= 1800:  # 30 minutes
                            # Cookie token is getting stale, refresh it proactively
                            from auth_utils import refresh_token_if_needed
                            try:
                                if refresh_token_if_needed():
                                    # Token was refreshed, update cookie with new token
                                    # This happens on page load, so redirect is acceptable
                                    new_token = st.session_state.get("user_token")
                                    new_refresh = st.session_state.get("refresh_token")
                                    if new_token and new_token != auth_token:
                                        # New token is different, update cookies
                                        import urllib.parse
                                        encoded_token = urllib.parse.quote(new_token, safe='')
                                        return_to = urllib.parse.quote(get_current_page_path(), safe='')
                                        redirect_url = f'/set_cookie.html?token={encoded_token}&return_to={return_to}'
                                        if new_refresh:
                                            encoded_refresh = urllib.parse.quote(new_refresh, safe='')
                                            redirect_url += f'&refresh_token={encoded_refresh}'
                                        st.markdown(
                                            f'<meta http-equiv="refresh" content="0; url={redirect_url}">',
                                            unsafe_allow_html=True
                                        )
                                        st.write("Refreshing session...")
                                        st.stop()
                            except Exception:
                                # If refresh fails, continue with restored session
                                pass
                        
                        # Verify user_id was set correctly
                        restored_user_id = get_user_id()
                        if restored_user_id != user_id_from_token:
                            # Session restoration mismatch - silently continue
                            pass
                        # No rerun needed - we're already in the right state
                    elif cookie_refresh_token:
                        # Access token expired, but we have refresh_token - try to refresh!
                        # This is the key improvement: recover session after Docker restart
                        try:
                            import requests
                            SUPABASE_URL = os.getenv("SUPABASE_URL")
                            SUPABASE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
                            
                            if SUPABASE_URL and SUPABASE_KEY:
                                response = requests.post(
                                    f"{SUPABASE_URL}/auth/v1/token?grant_type=refresh_token",
                                    headers={
                                        "apikey": SUPABASE_KEY,
                                        "Content-Type": "application/json"
                                    },
                                    json={"refresh_token": cookie_refresh_token},
                                    timeout=10
                                )
                                
                                if response.status_code == 200:
                                    auth_data = response.json()
                                    new_access_token = auth_data.get("access_token")
                                    new_refresh_token = auth_data.get("refresh_token")
                                    new_expires_at = auth_data.get("expires_at")
                                    
                                    if new_access_token:
                                        # Success! Restore session and update cookies with fresh tokens
                                        set_user_session(new_access_token, skip_cookie_redirect=True,
                                                        refresh_token=new_refresh_token,
                                                        expires_at=new_expires_at)
                                        
                                        # Update cookies with new tokens via redirect
                                        import urllib.parse
                                        encoded_token = urllib.parse.quote(new_access_token, safe='')
                                        return_to = urllib.parse.quote(get_current_page_path(), safe='')
                                        redirect_url = f'/set_cookie.html?token={encoded_token}&return_to={return_to}'
                                        if new_refresh_token:
                                            encoded_refresh = urllib.parse.quote(new_refresh_token, safe='')
                                            redirect_url += f'&refresh_token={encoded_refresh}'
                                        st.markdown(
                                            f'<meta http-equiv="refresh" content="0; url={redirect_url}">',
                                            unsafe_allow_html=True
                                        )
                                        st.write("Session recovered, updating cookies...")
                                        st.stop()
                        except Exception:
                            # Refresh failed, user will need to log in again
                            pass
                    # If token expired and no refresh_token, user will need to log in again
        except (AttributeError, Exception):
            # Cookie restoration failed - silently continue
            pass
    
    # Check for authentication errors in query params
    query_params = st.query_params
    if "auth_error" in query_params:
        error_code = query_params.get("error_code", "")
        error_desc = query_params.get("error_desc", "")
        
        # Show user-friendly error message
        if error_code == "otp_expired":
            st.error("❌ **Magic link expired** - The login link has expired. Please request a new magic link.")
        elif error_code:
            st.error(f"❌ **Authentication Error** - {error_desc or error_code}")
        else:
            st.error(f"❌ **Authentication Error** - {error_desc or 'An error occurred during authentication'}")
        
        # Clear error params
        st.query_params.clear()
    
    # Check for password reset token first - show dedicated page
    query_params = st.query_params
    if "magic_token" in query_params:
        access_token = query_params["magic_token"]
        auth_type = query_params.get("auth_type", "magiclink")
        
        # Handle password reset - show dedicated page
        if auth_type == "recovery":
            show_password_reset_page(access_token)
            return
    
    # Check for magic link login (not password reset)
    query_params = st.query_params
    if "magic_token" in query_params and not is_authenticated():
        access_token = query_params["magic_token"]
        auth_type = query_params.get("auth_type", "magiclink")
        
        # Handle magic link login (password reset handled above)
        try:
            # Decode JWT payload (middle part)
            token_parts = access_token.split('.')
            if len(token_parts) >= 2:
                # Decode base64url (JWT uses base64url)
                payload = token_parts[1]
                # Add padding if needed
                payload += '=' * (4 - len(payload) % 4)
                decoded = base64.urlsafe_b64decode(payload)
                user_data = json.loads(decoded)
                
                # Create user dict from token
                user = {
                    "id": user_data.get("sub"),
                    "email": user_data.get("email")
                }
                
                # Set session
                set_user_session(access_token, user)
                
                # Clear query params
                st.query_params.clear()
                
                st.success("Magic link login successful!")
                st.rerun()
        except Exception as e:
            st.error(f"Error processing magic link: {e}")
            st.query_params.clear()
    
    # NOW: Check authentication (after restoration attempts)
    
    if not is_authenticated():
        show_login_page()
        return
    
    # Scheduler is now initialized at module level (not lazy)
    # Check scheduler status for UI display
    try:
        from scheduler.scheduler_core import is_scheduler_running
        if not is_scheduler_running():
            import logging
            logging.getLogger(__name__).warning("Scheduler not running - some features may be unavailable")
    except Exception:
        pass  # Scheduler check failed, continue anyway
    
    # Check Postgres connection (non-blocking, logs status)
    try:
        _check_postgres_connection()
    except Exception:
        pass  # Postgres is optional
    
    # Header with user info and logout
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown('<div class="main-header">📈 Portfolio Performance Dashboard</div>', unsafe_allow_html=True)
    with col2:
        user_email = get_user_email()
        if user_email:
            st.write(f"Logged in as: **{user_email}**")
        if st.button("Logout"):
            logout_user()
            st.rerun()
    
    # Check V2 Preference and Redirect
    try:
        from user_preferences import get_user_preference
        v2_enabled = get_user_preference('v2_enabled', default=False)
        if v2_enabled:
             st.info("Redirecting to New Dashboard (V2)...")
             st.markdown('<meta http-equiv="refresh" content="0;url=/v2/dashboard">', unsafe_allow_html=True)
             st.stop()
    except Exception as e:
        _logger.warning(f"V2 redirect check failed: {e}")

    # Initialize scheduler (after V2 redirect check)
    # This prevents blocking the redirect if scheduler takes time to start
    try:
        _logger.info("Initializing scheduler (post-redirect check)...")
        _init_scheduler()
    except Exception as e:
        _logger.error(f"Failed to initialize scheduler: {e}", exc_info=True)


    # Sidebar - Navigation and Filters
    from navigation import render_navigation
    render_navigation(show_ai_assistant=True, show_settings=True)
    
    st.sidebar.markdown("---")
    
    # Debug section (visible to all authenticated users, requires ?debug=admin query param)
    query_params = st.query_params
    if query_params.get("debug") == "admin":
        st.sidebar.markdown("---")
        with st.sidebar.expander("🔍 Debug Info", expanded=True):
            user_id = get_user_id()
            user_email = get_user_email()
            admin_status = is_admin()
            
            st.write("**Session State:**")
            st.write(f"- User ID: `{user_id}`" if user_id else "- User ID: *Not set*")
            st.write(f"- User Email: `{user_email}`" if user_email else "- User Email: *Not set*")
            st.write(f"- Admin Status: `{admin_status}`")
            st.write(f"- Authenticated: `{is_authenticated()}`")
            
            # Try to get more details about admin check
            if user_id:
                try:
                    client = get_supabase_client()
                    if client:
                        st.write("**Supabase Client:** ✅ Initialized")
                        # Try the RPC call to see what happens
                        try:
                            result = client.supabase.rpc('is_admin', {'user_uuid': user_id}).execute()
                            st.write(f"**RPC Result Type:** `{type(result.data).__name__}`")
                            st.write(f"**RPC Result Value:** `{result.data}`")
                        except Exception as rpc_error:
                            st.write(f"**RPC Error:** `{str(rpc_error)}`")
                        
                        # Check user profile directly
                        try:
                            profile_result = client.supabase.table("user_profiles").select("role, email").eq("user_id", user_id).execute()
                            if profile_result.data:
                                profile = profile_result.data[0]
                                st.write(f"**User Profile Role:** `{profile.get('role', 'N/A')}`")
                                st.write(f"**User Profile Email:** `{profile.get('email', 'N/A')}`")
                                
                                if profile.get('role') != 'admin':
                                    st.warning("⚠️ Your role in the database is not 'admin'")
                                    st.info("💡 To become an admin, run: `python web_dashboard/setup_admin.py`")
                            else:
                                st.warning("⚠️ No user profile found in database")
                        except Exception as profile_error:
                            st.write(f"**Profile Check Error:** `{str(profile_error)}`")
                    else:
                        st.write("**Supabase Client:** ❌ Failed to initialize")
                except Exception as e:
                    st.write(f"**Error:** `{str(e)}`")
            else:
                st.write("**Note:** Cannot check admin status - user_id not set")
        st.sidebar.markdown("---")
    
    st.sidebar.title("Filters")
    
    # Use standardized sidebar fund selector
    selected_fund = render_sidebar_fund_selector()
    if selected_fund is None:
        st.stop()
    
    # Simple time range selector (for performance when data grows)
    time_range = st.sidebar.radio(
        "Time Range",
        options=["All Time", "Last 3 Months"],
        index=0,  # Default to All Time
        help="Filter performance charts by time period. Use 'Last 3 Months' for faster loading with large datasets."
    )
    
    # Convert time range to days parameter
    days_filter = None if time_range == "All Time" else 90  # ~3 months
    
    # Use selected fund directly (no "All Funds" conversion needed)
    fund_filter = selected_fund
    
    # Display fund name
    st.sidebar.info(f"Viewing: **{fund_filter}**")
    
    # Get timestamp first (quick query) to display immediately
    latest_timestamp = None
    is_market_open = False
    is_today = False
    
    try:
        # Quick query to get latest timestamp
        from log_handler import log_message
        positions_df_quick = get_current_positions(fund_filter)
        if not positions_df_quick.empty and 'date' in positions_df_quick.columns:
            try:
                max_date = positions_df_quick['date'].max()
                if isinstance(max_date, str):
                    from dateutil import parser
                    latest_timestamp = parser.parse(max_date)
                elif hasattr(max_date, 'to_pydatetime'):
                    latest_timestamp = max_date.to_pydatetime()
                elif isinstance(max_date, pd.Timestamp):
                    latest_timestamp = max_date.to_pydatetime()
                else:
                    latest_timestamp = max_date
                
                if latest_timestamp.tzinfo is None:
                    latest_timestamp = latest_timestamp.replace(tzinfo=timezone.utc)
                
                # Check market status
                try:
                    from market_data.market_hours import MarketHours
                    market_hours = MarketHours()
                    is_market_open = market_hours.is_market_open()
                except Exception:
                    pass
                
                # Check if today
                today_utc = datetime.now(timezone.utc).date()
                if latest_timestamp.tzinfo is not None:
                    timestamp_utc = latest_timestamp.astimezone(timezone.utc)
                else:
                    timestamp_utc = latest_timestamp.replace(tzinfo=timezone.utc)
                timestamp_date = timestamp_utc.date()
                is_today = timestamp_date == today_utc
            except Exception:
                pass
    except Exception:
        pass
    
    # Display timestamp right after header
    if latest_timestamp:
        try:
            timestamp_iso = latest_timestamp.isoformat()
            create_timestamp_display_component(timestamp_iso, is_market_open, is_today)
        except Exception:
            pass
    
    # Main content
    try:
        # Load data
        from log_handler import log_message
        import time
        
        log_message(f"[{session_id}] PERF: Starting dashboard data load for fund: {fund_filter}", level='PERF')
        data_load_start = time.time()
        
        # Get user's display currency preference (needed for all calculations)
        display_currency = get_user_display_currency()
        
        with st.spinner("Loading portfolio data..."):
            t0 = time.time()
            positions_df = get_current_positions(fund_filter)
            log_message(f"[{session_id}] PERF: get_current_positions took {time.time() - t0:.2f}s", level='PERF')
            
            t0 = time.time()
            trades_df = get_trade_log(limit=1000, fund=fund_filter)
            log_message(f"[{session_id}] PERF: get_trade_log took {time.time() - t0:.2f}s", level='PERF')
            
            t0 = time.time()
            cash_balances = get_cash_balances(fund_filter)
            log_message(f"[{session_id}] PERF: get_cash_balances took {time.time() - t0:.2f}s", level='PERF')
            
            t0 = time.time()
            portfolio_value_df = calculate_portfolio_value_over_time(fund_filter, days=days_filter, display_currency=display_currency)
            log_message(f"[{session_id}] PERF: calculate_portfolio_value_over_time took {time.time() - t0:.2f}s", level='PERF')
        
        log_message(f"[{session_id}] PERF: Total data load took {time.time() - data_load_start:.2f}s", level='PERF')
        
        # Investment Thesis section
        if fund_filter:
            thesis_data = get_fund_thesis_data(fund_filter)
            if thesis_data:
                # Top separator removed as this is now the first section
                with st.expander("📋 Investment Thesis", expanded=True):
                    st.markdown(f"### {thesis_data.get('title', 'Investment Thesis')}")
                    st.markdown(thesis_data.get('overview', ''))
                    # Note: Pillars will be shown near sectors chart below
        
        # Metrics row
        st.markdown("### Performance Metrics")
        
        metrics_start = time.time()
        log_message(f"[{session_id}] PERF: Starting metrics calculations", level='PERF')
        
        with st.spinner("Calculating metrics..."):
            # Check investor count to determine layout (hide if only 1 investor)
            t0 = time.time()
            num_investors = get_investor_count(fund_filter)
            log_message(f"[{session_id}] PERF: get_investor_count took {time.time() - t0:.2f}s", level='PERF')
            show_investors = num_investors > 1
            
            # Calculate total portfolio value from current positions (with currency conversion to display currency)
            portfolio_value_no_cash = 0.0  # Portfolio value without cash (for investment metrics)
            total_value = 0.0
            total_pnl = 0.0
        
        t0 = time.time()
        
        # BULK FETCH OPTIMIZATION: Get all required exchange rates in one go
        # Collect currencies from positions and cash
        all_currencies = set()
        if not positions_df.empty:
            all_currencies.update(positions_df['currency'].fillna('CAD').astype(str).str.upper().unique().tolist())
        all_currencies.update([str(c).upper() for c in cash_balances.keys()])
        
        # Fetch dictionary of rates: {'USD': 1.35, 'CAD': 1.0}
        rate_map = fetch_latest_rates_bulk(list(all_currencies), display_currency)
        
        # Helper to get rate safely (default 1.0)
        def get_rate_safe(curr):
            return rate_map.get(str(curr).upper(), 1.0)
            
        # 1. Calculate Portfolio Value (Vectorized)
        if not positions_df.empty and 'market_value' in positions_df.columns:
            # Create temporary rate column for vector operation
            # Use map for fast lookup
            rates = positions_df['currency'].fillna('CAD').astype(str).str.upper().map(get_rate_safe)
            portfolio_value_no_cash = (positions_df['market_value'].fillna(0) * rates).sum()
        log_message(f"[{session_id}] PERF: market_value calculation (vectorized) took {time.time() - t0:.2f}s", level='PERF')

        # 2. Calculate Total P&L (Vectorized)
        t0 = time.time()
        if not positions_df.empty and 'unrealized_pnl' in positions_df.columns:
            rates = positions_df['currency'].fillna('CAD').astype(str).str.upper().map(get_rate_safe)
            total_pnl = (positions_df['unrealized_pnl'].fillna(0) * rates).sum()
        log_message(f"[{session_id}] PERF: unrealized_pnl calculation (vectorized) took {time.time() - t0:.2f}s", level='PERF')
        
        # 3. Calculate Cash (Fast Loop with Lookup)
        t0 = time.time()
        total_cash_display = 0.0
        for currency, amount in cash_balances.items():
            if amount > 0:
                total_cash_display += amount * get_rate_safe(currency)
        total_value = portfolio_value_no_cash + total_cash_display
        log_message(f"[{session_id}] PERF: cash calculation (lookup) took {time.time() - t0:.2f}s", level='PERF')
        
        # Get user's investment metrics (if they have contributions)
        t0 = time.time()
        user_investment = get_user_investment_metrics(fund_filter, portfolio_value_no_cash, include_cash=True, session_id=session_id, display_currency=display_currency)
        log_message(f"[{session_id}] PERF: get_user_investment_metrics took {time.time() - t0:.2f}s", level='PERF')
        
        # 4. Calculate Last Trading Day P&L (Vectorized)
        t0 = time.time()
        last_day_pnl = 0.0
        last_day_pnl_pct = 0.0
        if not positions_df.empty and 'daily_pnl' in positions_df.columns:
            rates = positions_df['currency'].fillna('CAD').astype(str).str.upper().map(get_rate_safe)
            last_day_pnl = (positions_df['daily_pnl'].fillna(0) * rates).sum()
            
            # Calculate percentage based on yesterday's value (total_value - today's change)
            yesterday_value = total_value - last_day_pnl
            if yesterday_value > 0:
                last_day_pnl_pct = (last_day_pnl / yesterday_value) * 100
        log_message(f"[{session_id}] PERF: daily_pnl calculation (vectorized) took {time.time() - t0:.2f}s", level='PERF')

        # Calculate "Unrealized P&L" (sum of open positions pnl)
        # We already calculated total_pnl above which is exactly this
        unrealized_pnl = total_pnl
        unrealized_pnl_pct = (unrealized_pnl / (portfolio_value_no_cash - unrealized_pnl) * 100) if (portfolio_value_no_cash - unrealized_pnl) > 0 else 0.0

        # Num holdings for display
        num_holdings = len(positions_df) if not positions_df.empty else 0
        
        # Calculate total fund return (matching graph - stock performance only, not including cash drag)
        # This shows the same metric as the graph for consistency
        # Fund return = unrealized P&L / cost basis (same as graph calculation)
        if portfolio_value_no_cash > 0:
            cost_basis = portfolio_value_no_cash - unrealized_pnl
            fund_return_pct = (unrealized_pnl / cost_basis * 100) if cost_basis > 0 else 0.0
            fund_return_dollars = unrealized_pnl
        else:
            fund_return_pct = 0.0
            fund_return_dollars = 0.0


        # --- DYNAMIC LAYOUT LOGIC ---
        
        # Check if we should use Multi-Investor layout or Single Investor layout
        is_multi_investor = show_investors # Calculated earlier as num_investors > 1

        if is_multi_investor:
            # === MULTI-INVESTOR LAYOUT ===
            # Separates "Your Performance" from "Fund Performance"
            
            st.markdown("#### 👤")
            col1, col2, col3, col4 = st.columns(4)
            
            if user_investment:
                # Calculate User's Day Change based on ownership
                user_ownership_ratio = user_investment['ownership_pct'] / 100.0
                user_day_pnl = last_day_pnl * user_ownership_ratio
                
                with col1:
                    st.metric(
                        f"Your Value {format_currency_label(display_currency)}",
                        f"${user_investment['current_value']:,.2f}",
                        help="Current market value of your specific share in the fund."
                    )
                with col2:
                    st.metric(
                        "Your Day Change",
                        f"${user_day_pnl:,.2f}",
                        f"{last_day_pnl_pct:+.2f}%", 
                        help="Estimated change in your investment value since last market close."
                    )
                with col3:
                    st.metric(
                        "Your Return",
                        f"${user_investment['gain_loss']:,.2f}",
                        f"{user_investment['gain_loss_pct']:+.2f}%",
                        help="Total return on your investment (Current Value - Net Contribution)."
                    )
                with col4:
                    st.metric(
                        "Ownership",
                        f"{user_investment['ownership_pct']:.2f}%",
                        help="Your percentage ownership of the total fund assets."
                    )
            else:
                st.info("No contribution data found for your account in this fund.")

            st.markdown("#### 🏦")
            f_col1, f_col2, f_col3, f_col4 = st.columns(4)
            
            with f_col1:
                st.metric(
                    f"Fund Total Value {format_currency_label(display_currency)}", 
                    f"${total_value:,.2f}",
                    help="Total value of all assets in the fund (Cash + Positions) for ALL investors."
                )
            with f_col2:
                st.metric(
                    "Fund Return",
                    f"${fund_return_dollars:,.2f}", 
                    f"{fund_return_pct:+.2f}%",
                    help="Total return on all investments in the fund since inception."
                )
            with f_col3:
                st.metric("Investors", f"{num_investors}", help="Total number of distinct investors in this fund.")
            with f_col4:
                st.metric("Holdings", f"{num_holdings}", help="Number of open stock positions.")

        else:
            # === SINGLE INVESTOR LAYOUT ===
            # Consolidated view since User == Fund
            
            # We want 4 main metrics: Value, Total Return (All time), Day P&L, Unrealized P&L
            m_col1, m_col2, m_col3, m_col4 = st.columns(4)
            
            # Add section heading for single investor layout
            st.markdown("#### 💼")
            
            with m_col1:
                st.metric(
                    f"Portfolio Value {format_currency_label(display_currency)}", 
                    f"${total_value:,.2f}",
                    help="Total current value of your portfolio (Cash + Positions)."
                )
            
            with m_col2:
                # Total Return - Prioritize user_investment calc as it accounts for realized gains
                if user_investment:
                    st.metric(
                        "Total Return",
                        f"{user_investment['gain_loss_pct']:+.2f}%",
                        f"${user_investment['gain_loss']:,.2f}",
                        help="All-time return on investment (Current Value - Net Contribution)."
                    )
                else:
                    # Fallback to unrealized if no contribution data
                    st.metric(
                        f"Unrealized Return {format_currency_label(display_currency)}",
                        f"${unrealized_pnl:,.2f}",
                        f"{unrealized_pnl_pct:+.2f}%",
                        help="Return based on currently held positions only (excludes realized gains/losses)."
                    )

            with m_col3:
                st.metric(
                    f"Day Change {format_currency_label(display_currency)}", 
                    f"${last_day_pnl:,.2f}", 
                    f"{last_day_pnl_pct:+.2f}%",
                    help="Change in portfolio value since the last market close."
                )
                
            with m_col4:
                 st.metric(
                    f"Open P&L {format_currency_label(display_currency)}", 
                    f"${unrealized_pnl:,.2f}",
                    help="Unrealized Profit/Loss from currently held positions."
                )

        # Biggest Daily Movers Table
        if not positions_df.empty:
            try:
                movers = get_biggest_movers(positions_df, display_currency, limit=10)
                
                if not movers['gainers'].empty or not movers['losers'].empty:
                    st.markdown("### 📊 Biggest Daily Movers")
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        if not movers['gainers'].empty:
                            st.markdown("#### 🟢 Top Gainers")
                            gainers_df = movers['gainers'].copy()
                            
                            # Format columns for display
                            display_cols = {}
                            if 'ticker' in gainers_df.columns:
                                display_cols['ticker'] = 'Ticker'
                            if 'company_name' in gainers_df.columns:
                                display_cols['company_name'] = 'Company'
                            # Track if return_pct is used as daily column to avoid duplication
                            return_pct_used_as_daily = False
                            
                            if 'daily_pnl_pct' in gainers_df.columns:
                                gainers_df['daily_pnl_pct'] = gainers_df['daily_pnl_pct'].apply(lambda x: f"{x:+.2f}%")
                                display_cols['daily_pnl_pct'] = '1-Day %'
                            elif 'return_pct' in gainers_df.columns:
                                gainers_df['return_pct'] = gainers_df['return_pct'].apply(lambda x: f"{x:+.2f}%")
                                display_cols['return_pct'] = 'Return %'
                                return_pct_used_as_daily = True
                            
                            if 'pnl_display' in gainers_df.columns:
                                gainers_df['pnl_display'] = gainers_df['pnl_display'].apply(lambda x: f"${x:+,.2f}")
                                display_cols['pnl_display'] = '1-Day P&L'
                            if 'five_day_pnl_pct' in gainers_df.columns:
                                gainers_df['five_day_pnl_pct'] = gainers_df['five_day_pnl_pct'].apply(lambda x: f"{x:+.2f}%" if pd.notna(x) else "N/A")
                                display_cols['five_day_pnl_pct'] = '5-Day %'
                            if 'five_day_pnl_display' in gainers_df.columns:
                                gainers_df['five_day_pnl_display'] = gainers_df['five_day_pnl_display'].apply(lambda x: f"${x:+,.2f}" if pd.notna(x) else "N/A")
                                display_cols['five_day_pnl_display'] = '5-Day P&L'
                            # Only show return_pct as total return if it wasn't already used as daily
                            if 'return_pct' in gainers_df.columns and not return_pct_used_as_daily:
                                gainers_df['return_pct'] = gainers_df['return_pct'].apply(lambda x: f"{x:+.2f}%" if pd.notna(x) else "N/A")
                                display_cols['return_pct'] = 'Total Return %'
                            if 'total_pnl_display' in gainers_df.columns:
                                gainers_df['total_pnl_display'] = gainers_df['total_pnl_display'].apply(lambda x: f"${x:+,.2f}" if pd.notna(x) else "N/A")
                                display_cols['total_pnl_display'] = 'Total P&L'
                            if 'current_price' in gainers_df.columns:
                                gainers_df['current_price'] = gainers_df['current_price'].apply(lambda x: f"${x:.2f}")
                                display_cols['current_price'] = 'Price'
                            if 'market_value' in gainers_df.columns:
                                gainers_df['market_value'] = gainers_df['market_value'].apply(lambda x: f"${x:,.2f}")
                                display_cols['market_value'] = 'Value'
                            
                            # Rename columns
                            gainers_df = gainers_df.rename(columns=display_cols)
                            # Select only renamed columns that exist
                            available_cols = [col for col in display_cols.values() if col in gainers_df.columns]
                            if available_cols:
                                gainers_df = gainers_df[available_cols]
                            
                            # Calculate dynamic height based on number of rows
                            # Header: ~45px, each row: ~38px, padding: ~10px
                            # Cap at 500px max (for 10 rows limit)
                            num_rows = len(gainers_df)
                            dynamic_height = min(500, max(100, 45 + (num_rows * 38) + 10))
                            
                            # Use AgGrid with clickable ticker links
                            selected_ticker = display_aggrid_with_ticker_navigation(
                                gainers_df,
                                ticker_column="Ticker",
                                height=dynamic_height,
                                fit_columns=True
                            )
                            
                            # Handle ticker selection
                            if selected_ticker:
                                st.session_state['selected_ticker'] = selected_ticker
                                st.switch_page("pages/ticker_details.py")
                        else:
                            st.info("No gainers to display")
                    
                    with col2:
                        if not movers['losers'].empty:
                            st.markdown("#### 🔴 Top Losers")
                            losers_df = movers['losers'].copy()
                            
                            # Format columns for display
                            display_cols = {}
                            if 'ticker' in losers_df.columns:
                                display_cols['ticker'] = 'Ticker'
                            if 'company_name' in losers_df.columns:
                                display_cols['company_name'] = 'Company'
                            # Track if return_pct is used as daily column to avoid duplication
                            return_pct_used_as_daily = False
                            
                            if 'daily_pnl_pct' in losers_df.columns:
                                losers_df['daily_pnl_pct'] = losers_df['daily_pnl_pct'].apply(lambda x: f"{x:+.2f}%")
                                display_cols['daily_pnl_pct'] = '1-Day %'
                            elif 'return_pct' in losers_df.columns:
                                losers_df['return_pct'] = losers_df['return_pct'].apply(lambda x: f"{x:+.2f}%")
                                display_cols['return_pct'] = 'Return %'
                                return_pct_used_as_daily = True
                            
                            if 'pnl_display' in losers_df.columns:
                                losers_df['pnl_display'] = losers_df['pnl_display'].apply(lambda x: f"${x:+,.2f}")
                                display_cols['pnl_display'] = '1-Day P&L'
                            if 'five_day_pnl_pct' in losers_df.columns:
                                losers_df['five_day_pnl_pct'] = losers_df['five_day_pnl_pct'].apply(lambda x: f"{x:+.2f}%" if pd.notna(x) else "N/A")
                                display_cols['five_day_pnl_pct'] = '5-Day %'
                            if 'five_day_pnl_display' in losers_df.columns:
                                losers_df['five_day_pnl_display'] = losers_df['five_day_pnl_display'].apply(lambda x: f"${x:+,.2f}" if pd.notna(x) else "N/A")
                                display_cols['five_day_pnl_display'] = '5-Day P&L'
                            # Only show return_pct as total return if it wasn't already used as daily
                            if 'return_pct' in losers_df.columns and not return_pct_used_as_daily:
                                losers_df['return_pct'] = losers_df['return_pct'].apply(lambda x: f"{x:+.2f}%" if pd.notna(x) else "N/A")
                                display_cols['return_pct'] = 'Total Return %'
                            if 'total_pnl_display' in losers_df.columns:
                                losers_df['total_pnl_display'] = losers_df['total_pnl_display'].apply(lambda x: f"${x:+,.2f}" if pd.notna(x) else "N/A")
                                display_cols['total_pnl_display'] = 'Total P&L'
                            if 'current_price' in losers_df.columns:
                                losers_df['current_price'] = losers_df['current_price'].apply(lambda x: f"${x:.2f}")
                                display_cols['current_price'] = 'Price'
                            if 'market_value' in losers_df.columns:
                                losers_df['market_value'] = losers_df['market_value'].apply(lambda x: f"${x:,.2f}")
                                display_cols['market_value'] = 'Value'
                            
                            # Rename columns
                            losers_df = losers_df.rename(columns=display_cols)
                            # Select only renamed columns that exist
                            available_cols = [col for col in display_cols.values() if col in losers_df.columns]
                            if available_cols:
                                losers_df = losers_df[available_cols]
                            
                            # Calculate dynamic height based on number of rows
                            # Header: ~45px, each row: ~38px, padding: ~10px
                            # Cap at 500px max (for 10 rows limit)
                            num_rows = len(losers_df)
                            dynamic_height = min(500, max(100, 45 + (num_rows * 38) + 10))
                            
                            # Use AgGrid with clickable ticker links
                            selected_ticker = display_aggrid_with_ticker_navigation(
                                losers_df,
                                ticker_column="Ticker",
                                height=dynamic_height,
                                fit_columns=True
                            )
                            
                            # Handle ticker selection
                            if selected_ticker:
                                st.session_state['selected_ticker'] = selected_ticker
                                st.switch_page("pages/ticker_details.py")
                        else:
                            st.info("No losers to display")
                    
                    st.markdown("---")
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Error displaying biggest daily movers: {e}", exc_info=True)

        # Charts section
        st.markdown("---")
        st.markdown("### Performance Charts")
        
        log_message(f"[{session_id}] PERF: Metrics calculations complete, took {time.time() - metrics_start:.2f}s total", level='PERF')
        log_message(f"[{session_id}] PERF: Starting chart section", level='PERF')
        charts_start = time.time()
        
        # Portfolio value over time
        if not portfolio_value_df.empty:
            st.markdown("#### Portfolio Performance (Baseline 100)")
            
            # Chart controls (benchmark selector removed - all benchmarks now available in legend)
            use_solid = st.checkbox("📱 Solid Lines Only (for mobile)", value=False, help="Use solid lines instead of dashed for better mobile readability")
            
            # All benchmarks are now passed to the chart (S&P 500 visible, others in legend)
            all_benchmarks = ['sp500', 'qqq', 'russell2000', 'vti']
            
            # Use normalized performance index (baseline 100) like the console app
            log_message(f"[{session_id}] PERF: Creating portfolio value chart", level='PERF')
            t0 = time.time()
            fig = create_portfolio_value_chart(
                portfolio_value_df, 
                fund_filter,
                show_normalized=True,  # Show percentage change from baseline
                show_benchmarks=all_benchmarks,  # All benchmarks (S&P 500 visible, others in legend)
                show_weekend_shading=True,
                use_solid_lines=use_solid,
                display_currency=display_currency
            )
            log_message(f"[{session_id}] PERF: create_portfolio_value_chart took {time.time() - t0:.2f}s", level='PERF')
            
            t0 = time.time()
            st.plotly_chart(fig, use_container_width=True, key="portfolio_performance_chart")
            log_message(f"[{session_id}] PERF: st.plotly_chart (render) took {time.time() - t0:.2f}s", level='PERF')
            
            # Individual holdings performance chart (lazy loading)
            st.markdown("---")
            show_holdings = st.checkbox("📊 Show Individual Stock Performance", value=False)
            
            if show_holdings:
                col1, col2 = st.columns([3, 1])
                
                with col1:
                    date_range = st.radio(
                        "Date Range:",
                        options=["Last 7 Days", "Last 30 Days", "All Time"],
                        horizontal=True,
                        index=0  # Default to 7 days
                    )
                
                # Map selection to days parameter
                days_map = {
                    "Last 7 Days": 7,
                    "Last 30 Days": 30,
                    "All Time": 0  # 0 = all time
                }
                days = days_map[date_range]
                
                with st.spinner(f"Loading {date_range.lower()} of stock data..."):
                    from streamlit_utils import get_individual_holdings_performance
                    holdings_df = get_individual_holdings_performance(fund_filter, days=days)
                
                if not holdings_df.empty:
                    # Stock filter dropdown
                    # Dynamically build sector/industry options from data (gracefully handle nulls)
                    sectors = sorted([s for s in holdings_df.get('sector', pd.Series()).dropna().unique() if s])
                    industries = sorted([i for i in holdings_df.get('industry', pd.Series()).dropna().unique() if i])
                    
                    filter_options = [
                        "All stocks",
                        "Winners (↑ total %)",
                        "Losers (↓ total %)",
                        "Daily winners (↑ 1-day %)",
                        "Daily losers (↓ 1-day %)",
                        "Top 5 performers",
                        "Bottom 5 performers",
                        "Canadian (CAD)",
                        "American (USD)",
                        "Stocks only",
                        "ETFs only"
                    ]
                    
                    # Add sector options if data exists
                    if sectors:
                        filter_options.append("--- By Sector ---")
                        filter_options.extend([f"Sector: {s}" for s in sectors])
                    
                    # Add industry options if data exists
                    if industries:
                        filter_options.append("--- By Industry ---")
                        filter_options.extend([f"Industry: {i}" for i in industries])
                    
                    stock_filter = st.selectbox(
                        "📈 Stock filter",
                        options=filter_options,
                        index=0,
                        help="Filter the stocks shown in the chart below"
                    )
                    
                    # Apply filter - need to filter by unique tickers, not all rows
                    # First, get unique tickers with their metadata for filtering
                    if not holdings_df.empty:
                        # Get latest row per ticker for filtering metadata
                        latest_per_ticker = holdings_df.sort_values('date').groupby('ticker').last().reset_index()
                        
                        # Apply filter to get list of tickers to show
                        tickers_to_show = latest_per_ticker['ticker'].tolist()
                        
                        if stock_filter == "Winners (↑ total %)":
                            if 'return_pct' in latest_per_ticker.columns:
                                tickers_to_show = latest_per_ticker[latest_per_ticker['return_pct'].fillna(0) > 0]['ticker'].tolist()
                        elif stock_filter == "Losers (↓ total %)":
                            if 'return_pct' in latest_per_ticker.columns:
                                tickers_to_show = latest_per_ticker[latest_per_ticker['return_pct'].fillna(0) < 0]['ticker'].tolist()
                        elif stock_filter == "Daily winners (↑ 1-day %)":
                            if 'daily_pnl_pct' in latest_per_ticker.columns:
                                tickers_to_show = latest_per_ticker[latest_per_ticker['daily_pnl_pct'].fillna(0) > 0]['ticker'].tolist()
                        elif stock_filter == "Daily losers (↓ 1-day %)":
                            if 'daily_pnl_pct' in latest_per_ticker.columns:
                                tickers_to_show = latest_per_ticker[latest_per_ticker['daily_pnl_pct'].fillna(0) < 0]['ticker'].tolist()
                        elif stock_filter == "Top 5 performers":
                            if 'return_pct' in latest_per_ticker.columns:
                                top_5 = latest_per_ticker.nlargest(5, 'return_pct')
                                tickers_to_show = top_5['ticker'].tolist()
                        elif stock_filter == "Bottom 5 performers":
                            if 'return_pct' in latest_per_ticker.columns:
                                bottom_5 = latest_per_ticker.nsmallest(5, 'return_pct')
                                tickers_to_show = bottom_5['ticker'].tolist()
                        elif stock_filter == "Canadian (CAD)":
                            if 'currency' in latest_per_ticker.columns:
                                tickers_to_show = latest_per_ticker[latest_per_ticker['currency'] == 'CAD']['ticker'].tolist()
                        elif stock_filter == "American (USD)":
                            if 'currency' in latest_per_ticker.columns:
                                tickers_to_show = latest_per_ticker[latest_per_ticker['currency'] == 'USD']['ticker'].tolist()
                        elif stock_filter == "Stocks only":
                            if 'ticker' in latest_per_ticker.columns:
                                tickers_to_show = latest_per_ticker[~latest_per_ticker['ticker'].str.contains('ETF', case=False, na=False)]['ticker'].tolist()
                        elif stock_filter == "ETFs only":
                            if 'ticker' in latest_per_ticker.columns:
                                tickers_to_show = latest_per_ticker[latest_per_ticker['ticker'].str.contains('ETF', case=False, na=False)]['ticker'].tolist()
                        elif stock_filter.startswith("Sector: "):
                            sector_name = stock_filter.replace("Sector: ", "")
                            if 'sector' in latest_per_ticker.columns:
                                tickers_to_show = latest_per_ticker[latest_per_ticker['sector'] == sector_name]['ticker'].tolist()
                        elif stock_filter.startswith("Industry: "):
                            industry_name = stock_filter.replace("Industry: ", "")
                            if 'industry' in latest_per_ticker.columns:
                                tickers_to_show = latest_per_ticker[latest_per_ticker['industry'] == industry_name]['ticker'].tolist()
                        # Skip separator lines - show all
                        elif stock_filter.startswith("---"):
                            pass  # No filter applied, show all
                        
                        # Filter the full time-series DataFrame to only include selected tickers
                        filtered_df = holdings_df[holdings_df['ticker'].isin(tickers_to_show)].copy()
                    else:
                        filtered_df = holdings_df.copy()
                    
                    from chart_utils import create_individual_holdings_chart
                    holdings_fig = create_individual_holdings_chart(
                        filtered_df,
                        fund_name=fund_filter,
                        show_benchmarks=all_benchmarks,  # Use same benchmarks as main chart
                        show_weekend_shading=True,
                        use_solid_lines=use_solid
                    )  
                    st.plotly_chart(holdings_fig, use_container_width=True, key="individual_holdings_chart")
                    
                    # Show summary stats
                    num_stocks = holdings_df['ticker'].nunique()
                    st.caption(f"Showing {num_stocks} individual stocks over {date_range.lower()}")
                else:
                    st.info(f"No holdings data available for {date_range.lower()}")
        
        else:
            st.info("No historical portfolio value data available")
        
        
        # Current positions
        st.markdown("---")
        st.markdown("### Current Positions")
        
        # Fetch dividend data once for use in both P&L chart and Dividend History section
        dividend_data = []
        if fund_filter:
            try:
                # Import utility locally to avoid circular imports
                try:
                    from utils.db_utils import fetch_dividend_log
                except ImportError:
                    from web_dashboard.utils.db_utils import fetch_dividend_log
                
                # Fetch dividend data (filtered by selected fund, last 365 days)
                dividend_data = fetch_dividend_log(days_lookback=365, fund=fund_filter)
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Could not fetch dividend data: {e}")
        
        if not positions_df.empty:
            # P&L chart
            if 'pnl' in positions_df.columns or 'unrealized_pnl' in positions_df.columns:
                st.markdown("#### P&L by Position")
                st.info("💡 **Winning positions with gains** show overlay bars (green unrealized + gold dividends). **Winning positions with losses offset by dividends** show red bar below axis (loss) + gold bar above axis (dividends) at the same position. **Losing positions** show single red bars below axis.", icon="ℹ️")
                fig = create_pnl_chart(positions_df, fund_filter, display_currency=display_currency, dividend_data=dividend_data)
                st.plotly_chart(fig, use_container_width=True, key="pnl_by_position_chart")
            
            
            # Currency exposure chart
            if 'currency' in positions_df.columns and 'market_value' in positions_df.columns:
                st.markdown("#### Currency Exposure")
                
                # Load user preference for inverse rate
                try:
                    from user_preferences import get_user_preference, set_user_preference
                    default_inverse = get_user_preference('inverse_exchange_rate', False)
                except ImportError:
                    default_inverse = False
                
                # Toggle for inverting exchange rate
                inverse_rate = st.checkbox("Show CAD/USD instead of USD/CAD", value=default_inverse, key="inverse_exchange_rate")
                
                # Save preference if changed
                if inverse_rate != default_inverse:
                    try:
                        from user_preferences import set_user_preference
                        set_user_preference('inverse_exchange_rate', inverse_rate)
                    except ImportError:
                        pass
                
                # Show current USD/CAD exchange rate and historical chart
                try:
                    from datetime import timedelta
                    client = get_supabase_client()
                    
                    if client:
                        # Get latest rate
                        latest_rate = client.get_latest_exchange_rate('USD', 'CAD')
                        
                        # Get 90-day historical rates
                        end_date = datetime.now(timezone.utc)
                        start_date = end_date - timedelta(days=90)
                        historical_rates = client.get_exchange_rates(start_date, end_date, 'USD', 'CAD')
                        
                        # Display in two columns: rate metric + exposure pie chart
                        col1, col2 = st.columns([1, 2])
                        
                        with col1:
                            if latest_rate:
                                if inverse_rate:
                                    # Show CAD/USD (inverse)
                                    inverted = 1.0 / float(latest_rate)
                                    st.metric("CAD/USD Rate", f"{inverted:.4f}", help="Current exchange rate: 1 CAD = X USD")
                                else:
                                    # Show USD/CAD (normal)
                                    st.metric("USD/CAD Rate", f"{float(latest_rate):.4f}", help="Current exchange rate: 1 USD = X CAD")
                            
                            # Show historical chart
                            if historical_rates:
                                import plotly.graph_objects as go
                                
                                # Prepare data for chart
                                dates = [pd.to_datetime(r['timestamp']) for r in historical_rates]
                                if inverse_rate:
                                    # Invert the rates
                                    rates = [1.0 / float(r['rate']) for r in historical_rates]
                                    chart_title = 'CAD/USD Rate (90 Days)'
                                    y_label = 'CAD/USD'
                                else:
                                    rates = [float(r['rate']) for r in historical_rates]
                                    chart_title = 'USD/CAD Rate (90 Days)'
                                    y_label = 'USD/CAD'
                                
                                fig_rate = go.Figure()
                                fig_rate.add_trace(go.Scatter(
                                    x=dates,
                                    y=rates,
                                    mode='lines',
                                    name=y_label,
                                    line=dict(color='#3b82f6', width=2),
                                    hovertemplate='%{x|%b %d}<br>%{y:.4f}<extra></extra>'
                                ))
                                
                                fig_rate.update_layout(
                                    title=chart_title,
                                    xaxis_title='Date',
                                    yaxis_title='Rate',
                                    template='plotly_white',
                                    height=300,
                                    margin=dict(l=10, r=10, t=40, b=10),
                                    showlegend=False
                                )
                                
                                st.plotly_chart(fig_rate, use_container_width=True, key="usd_cad_rate_chart")
                        
                        with col2:
                            # Show currency exposure pie chart
                            fig = create_currency_exposure_chart(positions_df, fund_filter)
                            st.plotly_chart(fig, use_container_width=True, key="currency_exposure_chart")
                    else:
                        # Fallback if client not available
                        fig = create_currency_exposure_chart(positions_df, fund_filter)
                        st.plotly_chart(fig, use_container_width=True, key="currency_exposure_chart")
                        
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(f"Could not load exchange rate info: {e}")
                    # Fallback to just showing currency exposure chart
                    fig = create_currency_exposure_chart(positions_df, fund_filter)
                    st.plotly_chart(fig, use_container_width=True, key="currency_exposure_chart")
            
            # Investment Thesis Pillars (near sectors chart)
            if fund_filter:
                thesis_data = get_fund_thesis_data(fund_filter)
                if thesis_data and thesis_data.get('pillars'):
                    st.markdown("#### Investment Thesis Pillars")
                    pillars = thesis_data['pillars']
                    
                    # Display pillars in columns (2-3 columns depending on number of pillars)
                    num_pillars = len(pillars)
                    if num_pillars <= 2:
                        cols = st.columns(num_pillars)
                    elif num_pillars == 3:
                        cols = st.columns(3)
                    else:
                        cols = st.columns(3)  # Max 3 columns, will wrap
                    
                    for i, pillar in enumerate(pillars):
                        col_idx = i % len(cols)
                        with cols[col_idx]:
                            with st.container():
                                st.markdown(f"**{pillar.get('name', 'Pillar')}** ({pillar.get('allocation', 'N/A')})")
                                st.markdown(pillar.get('thesis', ''))
                                st.markdown("---")
            
            # Sector allocation chart
            if 'ticker' in positions_df.columns and 'market_value' in positions_df.columns:
                st.markdown("#### Sector Allocation")
                fig = create_sector_allocation_chart(positions_df, fund_filter)
                st.plotly_chart(fig, use_container_width=True, key="sector_allocation_chart")
            
            # Investor allocation chart (with privacy controls)
            # Only show if there are multiple investors
            if num_investors > 1:
                st.markdown("#### Investor Allocation")
                user_email = get_user_email()
                admin_status = is_admin()
                investors_df = get_investor_allocations(fund_filter, user_email, admin_status)
                
                if not investors_df.empty:
                    # Create two columns: chart on left, table on right
                    col1, col2 = st.columns([1.2, 0.8])
                    
                    with col1:
                        fig = create_investor_allocation_chart(investors_df, fund_filter)
                        st.plotly_chart(fig, use_container_width=True, key="investor_allocation_chart")
                    
                    with col2:
                        st.markdown("**Investment Amounts**")
                        # Validate required columns exist
                        required_cols = ['contributor_display', 'net_contribution', 'ownership_pct']
                        if not all(col in investors_df.columns for col in required_cols):
                            st.error("Missing required columns in investor data")
                        else:
                            # Format the table with dollar amounts and percentages
                            # Note: get_investor_allocations already sorts by net_contribution, but we ensure it here
                            display_df = investors_df[required_cols].copy()
                            display_df = display_df.sort_values('net_contribution', ascending=False)
                            
                            # Handle NaN/None values in formatting
                            def format_currency(val):
                                """Format currency with NaN handling"""
                                if pd.isna(val) or val is None:
                                    return "$0.00"
                                try:
                                    return f"${float(val):,.2f}"
                                except (ValueError, TypeError):
                                    return "$0.00"
                            
                            def format_percentage(val):
                                """Format percentage with NaN handling"""
                                if pd.isna(val) or val is None:
                                    return "0.00%"
                                try:
                                    return f"{float(val):.2f}%"
                                except (ValueError, TypeError):
                                    return "0.00%"
                            
                            display_df['Investment'] = display_df['net_contribution'].apply(format_currency)
                            display_df['Percentage'] = display_df['ownership_pct'].apply(format_percentage)
                            table_df = display_df[['contributor_display', 'Investment', 'Percentage']].copy()
                            table_df.columns = ['Investor', 'Investment', 'Ownership %']
                            
                            # Style the table with right-aligned dollar and percentage columns
                            styled_table = table_df.style.set_properties(
                                subset=['Investment', 'Ownership %'],
                                **{'text-align': 'right'}
                            )
                            
                            # Display as a styled table
                            st.dataframe(
                                styled_table,
                                use_container_width=True,
                                hide_index=True,
                                height=min(400, 50 + len(table_df) * 35)  # Dynamic height based on rows
                            )
                            
                            # Show total at bottom (handle NaN case)
                            total = investors_df['net_contribution'].sum()
                            if pd.isna(total):
                                total = 0.0
                            st.markdown(f"**Total:** ${total:,.2f}")
                else:
                    st.info("No investor data available for this fund")
            
            # Positions table
            st.markdown("#### Positions Table")
            
            # Fetch additional data for enhanced view
            # 1. First trade dates for "Opened" column
            try:
                from streamlit_utils import get_first_trade_dates
                first_trade_dates = get_first_trade_dates(fund_filter)
            except ImportError:
                first_trade_dates = {}
                
            if not positions_df.empty:
                # Prepare enhanced dataframe for AgGrid
                ag_df = positions_df.copy()
                
                # Add Company Name from securities (already in positions_df if joined, effectively)
                # The view 'latest_positions' has 'company', let's accept it.
                if 'company' not in ag_df.columns:
                    ag_df['company'] = ag_df.get('company_name', '')
                
                # Add Date Opened
                ag_df['opened'] = ag_df['ticker'].map(first_trade_dates)
                
                # Add Avg Price and Current Price
                # cost_basis is total cost. shares is total shares.
                ag_df['avg_price'] = ag_df.apply(lambda x: x['cost_basis'] / x['shares'] if x['shares'] > 0 else 0, axis=1)
                
                # Ensure we have current price
                if 'current_price' not in ag_df.columns:
                    ag_df['current_price'] = ag_df['price'] # Fallback
                
                # Calculate Portfolio Weight
                total_portfolio_value = ag_df['market_value'].sum()
                ag_df['weight'] = ag_df['market_value'] / total_portfolio_value if total_portfolio_value > 0 else 0
                
                # Format Combined Columns (Value + P&L)
                # User wants: "merge the dollars and % into single columns"
                # We will create display columns for AgGrid
                
                def format_combined_pnl(val, pct, currency_symbol="$"):
                    if pd.isna(val) or pd.isna(pct):
                        return "—"
                    color = "green" if val >= 0 else "red"
                    arrow = "▲" if val >= 0 else "▼"
                    # HTML styling will be handled by AgGrid cell renderer or we just pass text
                    # For now with simple config, let's pass formatted text string
                    # But user wants color. We need AgGrid renderer relative to value.
                    return f"{currency_symbol}{abs(val):,.2f} {arrow} {abs(pct):.1f}%"

                # We will leave the raw values for AgGrid to render with custom cell renderer for colors
                # But to merge columns, we create a valid field.
                
                # Let's create specific fields for AgGrid
                
                # 1. Ticker (with navigation)
                # 2. Company
                # 3. Opened
                # 4. Shares
                # 5. Avg Price
                # 6. Current Price
                # 7. Value
                # 8. Total P&L (Value + %)
                # 9. 1-Day P&L (Value + %)
                # 10. 5-Day P&L (Value + %)
                # 11. Weight
                
                # Helper for currency symbol
                curr_symbol = "$" if display_currency in ['USD', 'CAD'] else "" # Simple logic
                
                # Prepare display data
                display_df = pd.DataFrame()
                display_df['Ticker'] = ag_df['ticker']
                display_df['Company'] = ag_df['company'].fillna('—')
                # Ensure date format is strictly mm-dd-yy (e.g. 08-25-25)
                display_df['Opened'] = pd.to_datetime(ag_df['opened'], errors='coerce').dt.strftime('%m-%d-%y').fillna('—')
                display_df['Shares'] = ag_df['shares']
                display_df['Avg Price'] = ag_df['avg_price']
                display_df['Current Price'] = ag_df['current_price']
                display_df['Value'] = ag_df['market_value']
                
                # P&L Data (Hidden, for styling)
                display_df['_total_pnl'] = ag_df['unrealized_pnl']
                display_df['_total_pnl_pct'] = ag_df['return_pct']
                display_df['_daily_pnl'] = ag_df.get('daily_pnl', 0)
                display_df['_daily_pnl_pct'] = ag_df.get('daily_pnl_pct', 0)
                display_df['_5day_pnl'] = ag_df.get('five_day_pnl', 0)
                display_df['_5day_pnl_pct'] = ag_df.get('five_day_pnl_pct', 0)
                
                display_df['Weight'] = ag_df['weight']
                
                # Define combined columns (Strings)
                display_df['Total P&L'] = display_df.apply(
                    lambda x: f"${x['_total_pnl']:,.2f} {x['_total_pnl_pct']:+.1f}%", axis=1
                )
                display_df['1-Day P&L'] = display_df.apply(
                    lambda x: f"${x['_daily_pnl']:,.2f} {x['_daily_pnl_pct']:+.1f}%", axis=1
                )
                display_df['5-Day P&L'] = display_df.apply(
                    lambda x: f"${x['_5day_pnl']:,.2f} {x['_5day_pnl_pct']:+.1f}%", axis=1
                )

                # Import AgGrid components
                from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode
                
                gb = GridOptionsBuilder.from_dataframe(display_df)
                
                # Configure Columns
                gb.configure_column("Ticker", pinned="left", width=100, cellRenderer=JsCode(TICKER_CELL_RENDERER_JS))
                gb.configure_column("Company", width=200, tooltipField="Company")
                gb.configure_column("Opened", width=100)
                gb.configure_column("Shares", type=["numericColumn", "numberColumnFilter"], precision=4, width=100)
                gb.configure_column("Avg Price", type=["numericColumn", "numberColumnFilter"], valueFormatter="x.toLocaleString('en-US', {style: 'currency', currency: 'USD'})", width=100)
                gb.configure_column("Current Price", type=["numericColumn", "numberColumnFilter"], valueFormatter="x.toLocaleString('en-US', {style: 'currency', currency: 'USD'})", width=100)
                gb.configure_column("Value", type=["numericColumn", "numberColumnFilter"], valueFormatter="x.toLocaleString('en-US', {style: 'currency', currency: 'USD'})", width=120)
                
                # Configure Weight
                gb.configure_column("Weight", type=["numericColumn"], valueFormatter="(x * 100).toFixed(1) + '%'", width=80)
                
                # Configure Combined P&L Columns with Custom Coloring
                pnl_cell_style = JsCode("""
                function(params) {
                    if (!params.value) return null;
                    // Check if string contains '-' suggesting negative money or %
                    // Actually clearer to use the hidden raw values if accessible, but params.data accesses the row data
                    let val = 0;
                    if (params.colDef.field === 'Total P&L') val = params.data._total_pnl;
                    else if (params.colDef.field === '1-Day P&L') val = params.data._daily_pnl;
                    else if (params.colDef.field === '5-Day P&L') val = params.data._5day_pnl;
                    
                    if (val > 0) return {color: '#10b981', fontWeight: 'bold', textAlign: 'right'}; // Green
                    if (val < 0) return {color: '#ef4444', fontWeight: 'bold', textAlign: 'right'}; // Red
                    return {textAlign: 'right'};
                }
                """)
                
                gb.configure_column("Total P&L", cellStyle=pnl_cell_style, width=150)
                gb.configure_column("1-Day P&L", cellStyle=pnl_cell_style, width=150)
                gb.configure_column("5-Day P&L", cellStyle=pnl_cell_style, width=150)
                
                # Hide technical columns
                for col in ['_total_pnl', '_total_pnl_pct', '_daily_pnl', '_daily_pnl_pct', '_5day_pnl', '_5day_pnl_pct']:
                    gb.configure_column(col, hide=True)
                
                # General Options - disable auto page size so user can select from 25/50/100
                gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=50)
                gb.configure_grid_options(domLayout='normal')
                # Use new rowSelection object format (AG Grid v32.2+)
                # Deprecated: gb.configure_selection(selection_mode="single", use_checkbox=False)
                gb.configure_grid_options(
                    rowSelection={
                        "mode": "singleRow",
                        "checkboxes": False,
                        "enableClickSelection": True,
                    }
                )
                
                # Add Ticker Click Handler
                grid_options = gb.build()
                grid_options['onCellClicked'] = {
                    'function': TICKER_CLICK_HANDLER_JS_TEMPLATE.format(col_id='Ticker')
                }
                # Configure page size selector options
                grid_options['paginationPageSizeSelector'] = [25, 50, 100]
                
                # Render Grid
                grid_response = AgGrid(
                    display_df,
                    gridOptions=grid_options,
                    height=600,
                    update_mode=GridUpdateMode.SELECTION_CHANGED,
                    allow_unsafe_jscode=True,
                    theme='streamlit'
                )
                
                # Handle Navigation
                selected_rows = grid_response.get('selected_rows')
                if selected_rows is not None and len(selected_rows) > 0:
                    if isinstance(selected_rows, pd.DataFrame):
                        if 'Ticker' in selected_rows.columns:
                            selected_ticker = str(selected_rows.iloc[0]['Ticker'])
                    elif isinstance(selected_rows, list):
                        selected_row = selected_rows[0]
                        if isinstance(selected_row, dict) and 'Ticker' in selected_row:
                            selected_ticker = str(selected_row['Ticker'])
                    
                    if selected_ticker:
                         st.session_state['selected_ticker'] = selected_ticker
                         st.switch_page("pages/ticker_details.py")
            
            else:
                 st.info("No current positions found")
            
            # Holdings Info table - Company, Sector, Industry
            # Data is already available from latest_positions view (joins with securities table)
            st.markdown("#### Holdings Info")
            if not positions_df.empty:
                # Debug: Log available columns (only in development)
                import logging
                logger = logging.getLogger(__name__)
                if os.environ.get('STREAMLIT_ENV') != 'production':
                    logger.debug(f"Available columns in positions_df: {list(positions_df.columns)}")
                
                # Extract company, sector, industry from positions_df (already loaded from database)
                holdings_info_cols = ['ticker']
                col_rename = {'ticker': 'Ticker'}
                
                if 'company' in positions_df.columns:
                    holdings_info_cols.append('company')
                    col_rename['company'] = 'Company'
                if 'sector' in positions_df.columns:
                    holdings_info_cols.append('sector')
                    col_rename['sector'] = 'Sector'
                if 'industry' in positions_df.columns:
                    holdings_info_cols.append('industry')
                    col_rename['industry'] = 'Industry'
                
                # Filter to only existing columns
                holdings_info_cols = [col for col in holdings_info_cols if col in positions_df.columns]
                
                if holdings_info_cols:
                    holdings_info_df = positions_df[holdings_info_cols].copy()
                    holdings_info_df = holdings_info_df.rename(columns=col_rename)
                    # Remove duplicates (in case same ticker appears multiple times)
                    holdings_info_df = holdings_info_df.drop_duplicates(subset=['Ticker'])
                    # Fill NaN values with 'N/A' for display
                    holdings_info_df = holdings_info_df.fillna('N/A')
                    display_dataframe_with_copy(holdings_info_df, label="Holdings Info", key_suffix="holdings_info", use_container_width=True, height=300)
                else:
                    st.warning("⚠️ Company, sector, and industry data not available. The database view may need to be updated. See database/fixes/DF_017_restore_securities_to_latest_positions.sql")
        else:
            st.info("No current positions found")
        
        # Recent trades
        st.markdown("---")
        st.markdown("### Recent Trades")
        
        if not trades_df.empty:
            # Limit to last 50 trades for display
            recent_trades = trades_df.head(50).copy()
            
            # company_name comes from get_trade_log() which joins with securities table
            # Rename to 'company' for display column consistency
            # Fall back to positions lookup for any remaining None values
            if 'company_name' in recent_trades.columns:
                recent_trades['company'] = recent_trades['company_name']
            else:
                recent_trades['company'] = None
            
            # Fill missing company names from positions data (if available)
            if not positions_df.empty and 'company' in positions_df.columns and 'ticker' in recent_trades.columns:
                # Create a lookup dictionary from positions_df: ticker -> company
                ticker_to_company = positions_df.set_index('ticker')['company'].to_dict()
                
                # Fill None values in recent_trades['company'] using the lookup
                mask = recent_trades['company'].isna() | (recent_trades['company'] == '')
                recent_trades.loc[mask, 'company'] = recent_trades.loc[mask, 'ticker'].map(ticker_to_company)
            
            # Infer action type (BUY/SELL/DRIP) from reason field
            if 'reason' in recent_trades.columns:
                def infer_action(reason):
                    if pd.isna(reason) or reason is None:
                        return 'BUY'  # Default if no reason
                    reason_lower = str(reason).lower()
                    if 'sell' in reason_lower or 'limit sell' in reason_lower or 'market sell' in reason_lower:
                        return 'SELL'
                    if 'drip' in reason_lower or 'dividend' in reason_lower:
                        return 'DRIP'
                    return 'BUY'  # Default to BUY if no sell/drip keywords found
                recent_trades['Action'] = recent_trades['reason'].apply(infer_action)
            else:
                # No reason column - default all rows to BUY
                recent_trades['Action'] = 'BUY'
            
            # Ensure Action column exists (safety check)
            if 'Action' not in recent_trades.columns:
                recent_trades['Action'] = 'BUY'
            
            # Build display columns
            display_cols = ['date', 'ticker']
            col_rename = {'date': 'Date', 'ticker': 'Ticker'}
            
            if 'company' in recent_trades.columns:
                display_cols.append('company')
                col_rename['company'] = 'Company'
            
            display_cols.extend(['Action', 'shares', 'price'])
            col_rename.update({'Action': 'Action', 'shares': 'Shares', 'price': 'Price'})
            
            # Create a better P&L/Amount column
            # For SELLs: show realized P&L (if available)
            # For BUYs/DRIPs: show purchase amount (shares * price)
            if 'pnl' in recent_trades.columns and 'shares' in recent_trades.columns and 'price' in recent_trades.columns:
                def calculate_display_amount(row):
                    action = row.get('Action', 'BUY')
                    pnl = row.get('pnl', 0)
                    shares = row.get('shares', 0)
                    price = row.get('price', 0)
                    
                    if action == 'SELL':
                        return pnl  # Show realized P&L for sells
                    else:
                        return shares * price  # Show purchase amount for buys/drips
                
                recent_trades['display_amount'] = recent_trades.apply(calculate_display_amount, axis=1)
                display_cols.append('display_amount')
                col_rename['display_amount'] = 'Amount / P&L'
            elif 'pnl' in recent_trades.columns:
                display_cols.append('pnl')
                col_rename['pnl'] = 'Realized P&L'
            
            # Filter to existing columns
            display_cols = [col for col in display_cols if col in recent_trades.columns]
            
            if display_cols:
                display_df = recent_trades[display_cols].copy()
                display_df = display_df.rename(columns=col_rename)
                
                # Format date column to show only date (no time)
                if 'Date' in display_df.columns:
                    display_df['Date'] = pd.to_datetime(display_df['Date'], errors='coerce').dt.strftime('%m-%d-%y')
                
                # Format columns
                format_dict = {}
                if 'Shares' in display_df.columns:
                    format_dict['Shares'] = '{:.4f}'
                if 'Price' in display_df.columns:
                    format_dict['Price'] = '${:.2f}'
                if 'Realized P&L' in display_df.columns:
                    format_dict['Realized P&L'] = '${:,.2f}'
                if 'Amount / P&L' in display_df.columns:
                    format_dict['Amount / P&L'] = '${:,.2f}'
                
                # Apply styling
                styled_df = display_df.style.format(format_dict)
                
                # Right-align dollar amount columns
                dollar_columns = []
                if 'Price' in display_df.columns:
                    dollar_columns.append('Price')
                if 'Amount / P&L' in display_df.columns:
                    dollar_columns.append('Amount / P&L')
                if 'Realized P&L' in display_df.columns:
                    dollar_columns.append('Realized P&L')
                
                if dollar_columns:
                    styled_df = styled_df.set_properties(subset=dollar_columns, **{'text-align': 'right'})
                
                # Right-align Shares column if present
                if 'Shares' in display_df.columns:
                    styled_df = styled_df.set_properties(subset=['Shares'], **{'text-align': 'right'})
                
                # Color-code based on Action type
                if 'Action' in display_df.columns:
                    def color_action(val):
                        if val == 'SELL':
                            return 'color: #ef4444; font-weight: bold'  # Red
                        elif val == 'DRIP':
                            return 'color: #10b981; font-weight: bold'  # Green
                        elif val == 'BUY':
                            return 'color: #f59e0b; font-weight: bold'  # Yellow/Orange
                        return ''
                    styled_df = styled_df.map(color_action, subset=['Action'])
                
                # Color-code P&L/Amount column based on Action type
                if 'Amount / P&L' in display_df.columns and 'Action' in display_df.columns:
                    def color_amount_row(row):
                        # Return a list of styles for ALL columns in the row
                        styles = [''] * len(row)
                        
                        # Find the index of the Amount / P&L column
                        if 'Amount / P&L' not in row.index:
                            return styles
                        
                        amount_idx = row.index.get_loc('Amount / P&L')
                        
                        # Get action
                        action = str(row.get('Action', 'BUY')).upper()
                        
                        # Get the raw value from display_df (before formatting)
                        row_idx = row.name
                        try:
                            val = display_df.loc[row_idx, 'Amount / P&L']
                            if isinstance(val, str):
                                val_num = float(val.replace('$', '').replace(',', '').strip())
                            else:
                                val_num = float(val) if pd.notna(val) else 0
                        except:
                            val_num = 0
                        
                        # Apply color based on action type
                        if action == 'SELL':
                            if val_num > 0:
                                styles[amount_idx] = 'color: #10b981; font-weight: bold'  # Green for profit
                            elif val_num < 0:
                                styles[amount_idx] = 'color: #ef4444; font-weight: bold'  # Red for loss
                        elif action == 'DRIP':
                            styles[amount_idx] = 'color: #10b981; font-weight: bold'  # Green always
                        elif action == 'BUY':
                            styles[amount_idx] = 'color: #f59e0b; font-weight: bold'  # Orange
                        
                        return styles
                    
                    styled_df = styled_df.apply(color_amount_row, axis=1)
                elif 'Realized P&L' in display_df.columns:
                    def color_trade_pnl(val):
                        try:
                            if isinstance(val, str):
                                val = float(val.replace('$', '').replace(',', ''))
                            if val > 0:
                                return 'color: #10b981'
                            elif val < 0:
                                return 'color: #ef4444'
                        except:
                            pass
                        return ''
                    styled_df = styled_df.map(color_trade_pnl, subset=['Realized P&L'])
                
                display_dataframe_with_copy(styled_df, label="Recent Trades", key_suffix="recent_trades_styled", use_container_width=True, height=400)
            else:
                display_dataframe_with_copy(recent_trades, label="Recent Trades", key_suffix="recent_trades_raw", use_container_width=True, height=400)
        else:
            st.info("No recent trades found")
        
        # Close P&L section (realized gains/losses from closed positions)
        st.markdown("---")
        st.markdown("### 🏦 Closed Positions P&L")
        
        # Calculate realized P&L
        realized_pnl_data = get_realized_pnl(fund=fund_filter, display_currency=display_currency)
        total_realized = realized_pnl_data.get('total_realized_pnl', 0.0)
        num_closed = realized_pnl_data.get('num_closed_trades', 0)
        winning_trades = realized_pnl_data.get('winning_trades', 0)
        losing_trades = realized_pnl_data.get('losing_trades', 0)
        trades_by_ticker = realized_pnl_data.get('trades_by_ticker', {})
        
        
        if num_closed > 0:
            # Display primary metrics (matching console app structure)
            pnl_col1, pnl_col2, pnl_col3, pnl_col4 = st.columns(4)
            
            with pnl_col1:
                st.metric(
                    f"Total Realized P&L {format_currency_label(display_currency)}",
                    f"${total_realized:,.2f}",
                    help="Total realized profit/loss from all closed positions (matches console app)."
                )
            
            with pnl_col2:
                # Calculate average return percentage
                avg_return_pct = (total_realized / realized_pnl_data.get('total_cost_basis', 1.0) * 100) if realized_pnl_data.get('total_cost_basis', 0) > 0 else 0.0
                st.metric(
                    "Avg Return %",
                    f"{avg_return_pct:+.2f}%",
                    help="Average return percentage across all closed positions."
                )
            
            with pnl_col3:
                total_proceeds = realized_pnl_data.get('total_proceeds', 0.0)
                st.metric(
                    f"Total Proceeds {format_currency_label(display_currency)}",
                    f"${total_proceeds:,.2f}",
                    help=f"Total proceeds from all sales in {display_currency}."
                )
            
            with pnl_col4:
                # Calculate best trade percentage
                best_trade_pct = realized_pnl_data.get('best_trade_pct', 0.0)
                st.metric(
                    "Best Trade %",
                    f"{best_trade_pct:+.2f}%",
                    help="Highest return percentage from a single closed position."
                )
            
            # Secondary metrics row
            pnl_col5, pnl_col6, pnl_col7, pnl_col8 = st.columns(4)
            
            with pnl_col5:
                st.metric(
                    "Closed Trades",
                    f"{num_closed}",
                    help="Total number of closed positions (sell transactions)."
                )
            
            with pnl_col6:
                st.metric(
                    "Winning Trades",
                    f"{winning_trades}",
                    help="Number of closed positions with positive realized P&L."
                )
            
            with pnl_col7:
                st.metric(
                    "Losing Trades",
                    f"{losing_trades}",
                    help="Number of closed positions with negative realized P&L."
                )
            
            with pnl_col8:
                win_rate = (winning_trades / num_closed * 100) if num_closed > 0 else 0.0
                st.metric(
                    "Win Rate",
                    f"{win_rate:.1f}%",
                    help="Percentage of closed trades with positive P&L."
                )
            
            # Show breakdown by ticker if there are multiple tickers
            if len(trades_by_ticker) > 1:
                st.markdown("#### Realized P&L by Ticker")
                
                # Get trade log to extract buy/sell prices and dates
                all_trades_df = get_trade_log(limit=10000, fund=fund_filter)
                
                # Create DataFrame for display (handle new structure)
                currency_label = format_currency_label(display_currency)
                ticker_data = []
                
                for ticker, data in trades_by_ticker.items():
                    if isinstance(data, dict):
                        # Get buy and sell trades for this ticker
                        ticker_trades = all_trades_df[all_trades_df['ticker'] == ticker].copy() if not all_trades_df.empty else pd.DataFrame()
                        
                        # Identify buy vs sell trades
                        buy_trades = pd.DataFrame()
                        sell_trades = pd.DataFrame()
                        
                        if not ticker_trades.empty and 'reason' in ticker_trades.columns:
                            reason_lower = ticker_trades['reason'].astype(str).str.lower()
                            sell_mask = reason_lower.str.contains('sell', na=False)
                            sell_trades = ticker_trades[sell_mask].copy()
                            buy_trades = ticker_trades[~sell_mask].copy()
                        
                        # Calculate average buy price
                        avg_buy_price = 0.0
                        first_buy_date = None
                        if not buy_trades.empty and 'price' in buy_trades.columns:
                            # Calculate weighted average buy price
                            buy_trades['total_cost'] = buy_trades['shares'] * buy_trades['price']
                            total_buy_cost = buy_trades['total_cost'].sum()
                            total_buy_shares = buy_trades['shares'].sum()
                            if total_buy_shares > 0:
                                avg_buy_price = total_buy_cost / total_buy_shares
                            
                            # Get first buy date
                            if 'date' in buy_trades.columns:
                                buy_dates = pd.to_datetime(buy_trades['date'], errors='coerce')
                                buy_dates = buy_dates.dropna()
                                if not buy_dates.empty:
                                    first_buy_date = buy_dates.min()
                        
                        # Calculate average sell price
                        avg_sell_price = 0.0
                        last_sell_date = None
                        if not sell_trades.empty and 'price' in sell_trades.columns:
                            # Calculate weighted average sell price
                            sell_trades['total_proceeds'] = sell_trades['shares'] * sell_trades['price']
                            total_sell_proceeds = sell_trades['total_proceeds'].sum()
                            total_sell_shares = sell_trades['shares'].sum()
                            if total_sell_shares > 0:
                                avg_sell_price = total_sell_proceeds / total_sell_shares
                            
                            # Get last sell date
                            if 'date' in sell_trades.columns:
                                sell_dates = pd.to_datetime(sell_trades['date'], errors='coerce')
                                sell_dates = sell_dates.dropna()
                                if not sell_dates.empty:
                                    last_sell_date = sell_dates.max()
                        
                        # Convert prices to display currency if needed
                        # Note: For simplicity, using current rates. For accuracy, should use historical rates.
                        if avg_buy_price > 0 and not buy_trades.empty:
                            buy_currency = str(buy_trades.iloc[0].get('currency', 'CAD')).upper() if pd.notna(buy_trades.iloc[0].get('currency')) else 'CAD'
                            buy_date = first_buy_date if first_buy_date else None
                            avg_buy_price = convert_to_display_currency(avg_buy_price, buy_currency, buy_date, display_currency)
                        
                        if avg_sell_price > 0 and not sell_trades.empty:
                            sell_currency = str(sell_trades.iloc[0].get('currency', 'CAD')).upper() if pd.notna(sell_trades.iloc[0].get('currency')) else 'CAD'
                            sell_date = last_sell_date if last_sell_date else None
                            avg_sell_price = convert_to_display_currency(avg_sell_price, sell_currency, sell_date, display_currency)
                        
                        # Format dates as date only (no time)
                        buy_date_str = first_buy_date.strftime('%Y-%m-%d') if first_buy_date and pd.notna(first_buy_date) else 'N/A'
                        sell_date_str = last_sell_date.strftime('%Y-%m-%d') if last_sell_date and pd.notna(last_sell_date) else 'N/A'
                        
                        ticker_data.append({
                            'Ticker': ticker,
                            f'Realized P&L {currency_label}': data.get('realized_pnl', 0.0),
                            'Shares Sold': data.get('shares_sold', 0.0),
                            f'Proceeds {currency_label}': data.get('proceeds', 0.0),
                            f'Avg Buy Price {currency_label}': avg_buy_price,
                            f'Avg Sell Price {currency_label}': avg_sell_price,
                            'First Buy Date': buy_date_str,
                            'Last Sell Date': sell_date_str
                        })
                    else:
                        # Legacy structure (just a number)
                        ticker_data.append({
                            'Ticker': ticker,
                            f'Realized P&L {currency_label}': float(data),
                            'Shares Sold': 0.0,
                            f'Proceeds {currency_label}': 0.0,
                            f'Avg Buy Price {currency_label}': 0.0,
                            f'Avg Sell Price {currency_label}': 0.0,
                            'First Buy Date': 'N/A',
                            'Last Sell Date': 'N/A'
                        })
                
                ticker_pnl_df = pd.DataFrame(ticker_data)
                pnl_col_name = f'Realized P&L {currency_label}'
                proceeds_col_name = f'Proceeds {currency_label}'
                buy_price_col_name = f'Avg Buy Price {currency_label}'
                sell_price_col_name = f'Avg Sell Price {currency_label}'
                ticker_pnl_df = ticker_pnl_df.sort_values(pnl_col_name, ascending=False)
                
                # Format dollar amounts as strings for AgGrid display
                # AgGrid doesn't use pandas styling, so we need to format values directly
                ticker_pnl_df[pnl_col_name] = ticker_pnl_df[pnl_col_name].apply(lambda x: f"${x:,.2f}")
                ticker_pnl_df['Shares Sold'] = ticker_pnl_df['Shares Sold'].apply(lambda x: f"{x:,.2f}")
                ticker_pnl_df[proceeds_col_name] = ticker_pnl_df[proceeds_col_name].apply(lambda x: f"${x:,.2f}")
                ticker_pnl_df[buy_price_col_name] = ticker_pnl_df[buy_price_col_name].apply(lambda x: f"${x:,.2f}" if x > 0 else "N/A")
                ticker_pnl_df[sell_price_col_name] = ticker_pnl_df[sell_price_col_name].apply(lambda x: f"${x:,.2f}" if x > 0 else "N/A")
                
                # Display dataframe with AgGrid for ticker navigation
                selected_ticker = display_aggrid_with_ticker_navigation(
                    ticker_pnl_df,
                    ticker_column="Ticker",
                    height=300,
                    fit_columns=True
                )
                
                # Handle ticker selection
                if selected_ticker:
                    # Use session state to pass ticker to details page
                    st.session_state['selected_ticker'] = selected_ticker
                    st.switch_page("pages/ticker_details.py")
        else:
            st.info("No closed positions found. Realized P&L will appear here once you close positions.")
        
        # Dividend History Section
        st.markdown("---")
        st.markdown("### 🏦 Dividend History")

        try:
            # dividend_data already fetched earlier to avoid duplicate DB calls
            
            if dividend_data:
                # Convert to DataFrame
                div_df = pd.DataFrame(dividend_data)
                
                # Calculate Summary Metrics
                total_dividends = div_df['net_amount'].sum()
                total_reinvested = div_df['reinvested_shares'].sum()
                num_payouts = len(div_df)
                total_us_tax = (div_df['gross_amount'] - div_df['net_amount']).sum()
                
                # Find largest dividend
                largest_idx = div_df['net_amount'].idxmax()
                largest_dividend = div_df.loc[largest_idx, 'net_amount']
                largest_ticker = div_df.loc[largest_idx, 'ticker'] if 'ticker' in div_df.columns else 'N/A'
                
                # Display Metrics
                d_col1, d_col2, d_col3, d_col4, d_col5 = st.columns(5)
                with d_col1:
                    st.metric("Total Dividends (LTM)", f"${total_dividends:,.2f}", help="Total net dividends received in the last 12 months.")
                with d_col2:
                    st.metric("US Tax Paid (LTM)", f"${total_us_tax:,.2f}", help="Total US withholding tax paid on dividends in the last 12 months.")
                with d_col3:
                    st.metric("Largest Dividend", f"${largest_dividend:,.2f}", delta=largest_ticker, help="Largest single dividend payment and its ticker.")
                with d_col4:
                    st.metric("Reinvested Shares", f"{total_reinvested:.4f}", help="Total shares acquired via DRIP.")
                with d_col5:
                    st.metric("Payout Events", f"{num_payouts}", help="Number of dividend payments received.")

                # Format DataFrame for Display
                display_cols = ['pay_date', 'ticker', 'gross_amount', 'net_amount', 'reinvested_shares', 'drip_price']
                div_display_df = div_df[display_cols].copy()
                div_display_df.columns = ['Pay Date', 'Ticker', 'Gross ($)', 'Net ($)', 'Reinvested Shares', 'DRIP Price ($)']
                
                # Format dollar columns to 2 decimals
                if 'Gross ($)' in div_display_df.columns:
                    div_display_df['Gross ($)'] = div_display_df['Gross ($)'].apply(lambda x: f"${float(x):,.2f}" if pd.notna(x) else "$0.00")
                if 'Net ($)' in div_display_df.columns:
                    div_display_df['Net ($)'] = div_display_df['Net ($)'].apply(lambda x: f"${float(x):,.2f}" if pd.notna(x) else "$0.00")
                if 'DRIP Price ($)' in div_display_df.columns:
                    div_display_df['DRIP Price ($)'] = div_display_df['DRIP Price ($)'].apply(lambda x: f"${float(x):,.2f}" if pd.notna(x) else "$0.00")
                
                # AgGrid Display with ticker navigation
                selected_ticker = display_aggrid_with_ticker_navigation(
                    div_display_df,
                    ticker_column="Ticker",
                    height=300,
                    fit_columns=True
                )
                
                # Handle ticker selection
                if selected_ticker:
                    st.session_state['selected_ticker'] = selected_ticker
                    st.switch_page("pages/ticker_details.py")
            else:
                st.info("No dividend history found for the last 365 days.")
                
        except Exception as e:
            st.error(f"Error loading dividend history: {e}")
        
        # Footer with build info
        st.markdown("---")
        # Get build timestamp from environment variable (set by CI) or use current time
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
        
        st.markdown(
            f"""
            <div style='text-align: center; color: #666; font-size: 0.8em;'>
                LLM Micro-Cap Trading Bot Dashboard • Build: {build_timestamp}
            </div>
            """, 
            unsafe_allow_html=True
        )
    except Exception as e:
        st.error(f"Error loading data: {e}")
        st.exception(e)



    # Log total execution time
    try:
        duration = time.time() - start_time
        log_message(f"PERF: Streamlit script run finished in {duration:.3f}s", level='PERF')
    except Exception:
        pass

if __name__ == "__main__":
    main()

