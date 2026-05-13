#!/usr/bin/env python3
"""
Shared Navigation Component
===========================

Provides consistent navigation across all pages in the web dashboard.
Handles page links, admin status, and AI Assistant availability.
"""

import streamlit as st


def render_navigation(show_ai_assistant: bool = True, show_settings: bool = True) -> None:
    """
    Render the shared navigation sidebar component with modern card-based design.
    
    Args:
        show_ai_assistant: Whether to show AI Assistant link (default: True)
        show_settings: Whether to show Settings link (default: True)
    """
    # CRITICAL: Restore session from cookies FIRST before any preference checks
    # This ensures we have valid auth context when checking preferences
    try:
        from auth_utils import ensure_session_restored
        ensure_session_restored()
    except Exception:
        pass  # Continue with navigation even if restoration fails
    
    # Apply user's theme preference (dark/light mode override)
    try:
        from user_preferences import apply_user_theme, get_user_preference, set_user_preference
        apply_user_theme()
    except Exception:
        def get_user_preference(key, default=None): return default
        def set_user_preference(*args): return False
    
    # V2 preference: Just read from database (no caching, no toggle widget here)
    # The toggle is now on the settings page to avoid refresh loops
    try:
        from auth_utils import is_authenticated
        import logging
        nav_logger = logging.getLogger(__name__)
        if is_authenticated():
            is_v2_enabled = get_user_preference('v2_enabled', default=False)
            nav_logger.debug(f"[NAV DEBUG] v2_enabled loaded = {is_v2_enabled} (type: {type(is_v2_enabled).__name__})")
        else:
            is_v2_enabled = False
            nav_logger.debug("[NAV DEBUG] User not authenticated, v2_enabled = False")
    except Exception as e:
        import logging
        nav_logger = logging.getLogger(__name__)
        nav_logger.warning(f"[NAV DEBUG] Exception loading v2_enabled: {e}")
        is_v2_enabled = False
    
    try:
        from auth_utils import is_admin, get_user_email, get_user_id
        from streamlit_utils import get_supabase_client
    except ImportError:
        # If auth utils not available, render minimal navigation
        st.sidebar.title("Navigation")
        st.sidebar.markdown('<div class="nav-section-title">Pages</div>', unsafe_allow_html=True)
        st.sidebar.page_link("streamlit_app.py", label="Dashboard", icon="📈")
        return
    
    # Inject custom CSS for consistent navigation styling
    st.sidebar.markdown("""
        <style>
            .nav-section-title {
                color: rgba(128, 128, 128, 0.8);
                font-size: 0.75rem;
                font-weight: 600;
                margin: 1.25rem 0 0.5rem 0;
                text-transform: uppercase;
                letter-spacing: 0.05rem;
                padding-left: 0.5rem;
            }
            .v2-nav-link {
                display: flex;
                align-items: center;
                padding: 0.4rem 0.75rem;
                border-radius: 0.5rem;
                text-decoration: none !important;
                color: inherit !important;
                font-family: inherit;
                transition: background-color 0.2s, transform 0.1s;
                margin: 0.1rem 0;
                cursor: pointer;
                border: 1px solid transparent;
            }
            .v2-nav-link:hover {
                background-color: rgba(151, 166, 195, 0.15);
                border-color: rgba(151, 166, 195, 0.1);
                text-decoration: none !important;
                color: inherit !important;
            }
            .v2-nav-link:active {
                transform: scale(0.98);
            }
            .v2-nav-link:visited {
                text-decoration: none !important;
                color: inherit !important;
            }
            .v2-nav-link:link {
                text-decoration: none !important;
                color: inherit !important;
            }
            .v2-nav-icon {
                margin-right: 0.75rem;
                font-size: 1.15rem;
                display: flex;
                align-items: center;
                justify-content: center;
                width: 1.25rem;
                min-width: 1.25rem;
                opacity: 0.9;
            }
            .v2-nav-label {
                font-size: 0.875rem;
                font-weight: 400;
                line-height: inherit;
                letter-spacing: normal;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .nav-divider {
                margin: 1rem 0;
                border: none;
                border-top: 1px solid rgba(128, 128, 128, 0.2);
            }
            .nav-badge {
                padding: 0.15rem 0.5rem;
                border-radius: 0.5rem;
                font-size: 0.7rem;
                font-weight: 600;
                margin-bottom: 0.5rem;
                display: inline-block;
                width: fit-content;
            }
            .nav-badge-admin { 
                background-color: rgba(46, 204, 113, 0.15); 
                color: #2ecc71; 
                border: 1px solid rgba(46, 204, 113, 0.2); 
            }
            .nav-badge-role { 
                background-color: rgba(52, 152, 219, 0.15); 
                color: #3498db; 
                border: 1px solid rgba(52, 152, 219, 0.2); 
            }
        </style>
    """, unsafe_allow_html=True)

    # Navigation title with modern styling
    st.sidebar.title("Navigation")
    
    # Page links section with styled header
    st.sidebar.markdown('<div class="nav-section-title">Pages</div>', unsafe_allow_html=True)
    st.sidebar.page_link("streamlit_app.py", label="Dashboard", icon="📈")
    
    # Research Repository link (if PostgreSQL is available)
    try:
        from postgres_client import PostgresClient
        client = PostgresClient()
        if client.test_connection():
            # Check if Research page is migrated to Flask
            try:
                from shared_navigation import is_page_migrated, get_page_url
                if is_v2_enabled and is_page_migrated('research'):
                    # Use markdown link for Flask route with matching Streamlit styling
                    research_url = get_page_url('research')
                    st.sidebar.markdown(f'''
                        <a href="{research_url}" target="_self" class="v2-nav-link">
                            <span class="v2-nav-icon">📚</span>
                            <span class="v2-nav-label">Research Repository</span>
                        </a>
                    ''', unsafe_allow_html=True)
                else:
                    st.sidebar.page_link("pages/research.py", label="Research Repository", icon="📚")
            except ImportError:
                # Fallback if shared_navigation not available
                st.sidebar.page_link("pages/research.py", label="Research Repository", icon="📚")
            
            # Social Sentiment - check if migrated to Flask
            try:
                from shared_navigation import is_page_migrated, get_page_url
                if is_v2_enabled and is_page_migrated('social_sentiment'):
                    # Use markdown link for Flask route with matching Streamlit styling
                    social_sentiment_url = get_page_url('social_sentiment')
                    st.sidebar.markdown(f'''
                        <a href="{social_sentiment_url}" target="_self" class="v2-nav-link">
                            <span class="v2-nav-icon">💬</span>
                            <span class="v2-nav-label">Social Sentiment</span>
                        </a>
                    ''', unsafe_allow_html=True)
                else:
                    st.sidebar.page_link("pages/social_sentiment.py", label="Social Sentiment", icon="💬")
            except ImportError:
                # Fallback if shared_navigation not available
                st.sidebar.page_link("pages/social_sentiment.py", label="Social Sentiment", icon="💬")
            
            # ETF Holdings - check if migrated to Flask
            try:
                from shared_navigation import is_page_migrated, get_page_url
                if is_v2_enabled and is_page_migrated('etf_holdings'):
                    # Use markdown link for Flask route with matching Streamlit styling
                    etf_url = get_page_url('etf_holdings')
                    st.sidebar.markdown(f'''
                        <a href="{etf_url}" target="_self" class="v2-nav-link">
                            <span class="v2-nav-icon">💼</span>
                            <span class="v2-nav-label">ETF Holdings</span>
                        </a>
                    ''', unsafe_allow_html=True)
                else:
                    st.sidebar.page_link("pages/etf_holdings.py", label="ETF Holdings", icon="💼")
            except ImportError:
                # Fallback if shared_navigation not available
                st.sidebar.page_link("pages/etf_holdings.py", label="ETF Holdings", icon="💼")

            # Sector insights — Flask-only preview (no Streamlit page); mirror ETF Holdings v2 routing
            try:
                from shared_navigation import is_page_migrated, get_page_url
                if is_v2_enabled and is_page_migrated('sector_insights'):
                    sector_url = get_page_url('sector_insights')
                    st.sidebar.markdown(f'''
                        <a href="{sector_url}" target="_self" class="v2-nav-link">
                            <span class="v2-nav-icon">🧭</span>
                            <span class="v2-nav-label">Sector insights</span>
                        </a>
                    ''', unsafe_allow_html=True)
            except ImportError:
                pass
    except Exception:
        pass  # Silently fail if Postgres not available
    
    # Congress Trades link (if Supabase is available)
    try:
        client = get_supabase_client()
        if client and client.test_connection():
            # Check if migrated to Flask
            try:
                from shared_navigation import is_page_migrated, get_page_url
                if is_v2_enabled and is_page_migrated('congress_trades'):
                    # Use markdown link for Flask route with matching Streamlit styling
                    congress_url = get_page_url('congress_trades')
                    st.sidebar.markdown(f'''
                        <a href="{congress_url}" target="_self" class="v2-nav-link">
                            <span class="v2-nav-icon">🏛️</span>
                            <span class="v2-nav-label">Congress Trades</span>
                        </a>
                    ''', unsafe_allow_html=True)
                else:
                    st.sidebar.page_link("pages/congress_trades.py", label="Congress Trades", icon="🏛️")
            except ImportError:
                # Fallback if shared_navigation not available
                st.sidebar.page_link("pages/congress_trades.py", label="Congress Trades", icon="🏛️")
            # Ticker Lookup - check if migrated to Flask
            try:
                from shared_navigation import is_page_migrated, get_page_url
                if is_v2_enabled and is_page_migrated('ticker_details'):
                    # Use markdown link for Flask route with matching Streamlit styling
                    ticker_url = get_page_url('ticker_details')
                    st.sidebar.markdown(f'''
                        <a href="{ticker_url}" target="_self" class="v2-nav-link">
                            <span class="v2-nav-icon">🔍</span>
                            <span class="v2-nav-label">Ticker Lookup</span>
                        </a>
                    ''', unsafe_allow_html=True)
                else:
                    st.sidebar.page_link("pages/ticker_details.py", label="Ticker Lookup", icon="🔍")
            except ImportError:
                # Fallback if shared_navigation not available
                st.sidebar.page_link("pages/ticker_details.py", label="Ticker Lookup", icon="🔍")
    except Exception:
        pass  # Silently fail if Supabase not available
    
    # AI Assistant link (if available and requested)
    if show_ai_assistant:
        # Check if AI Assistant page is migrated to Flask
        try:
            from shared_navigation import is_page_migrated, get_page_url
            if is_v2_enabled and is_page_migrated('ai_assistant'):
                # Use markdown link for Flask route with matching Streamlit styling
                ai_assistant_url = get_page_url('ai_assistant')
                st.sidebar.markdown(f'''
                    <a href="{ai_assistant_url}" target="_self" class="v2-nav-link">
                        <span class="v2-nav-icon">🧠</span>
                        <span class="v2-nav-label">AI Assistant</span>
                    </a>
                ''', unsafe_allow_html=True)
            else:
                st.sidebar.page_link("pages/ai_assistant.py", label="AI Assistant", icon="🧠")
        except ImportError:
            # Fallback if shared_navigation not available
            st.sidebar.page_link("pages/ai_assistant.py", label="AI Assistant", icon="🧠")
    
    # Settings link (if requested)
    if show_settings:
        # Check if settings page is migrated to Flask
        try:
            from shared_navigation import is_page_migrated, get_page_url
            if is_v2_enabled and is_page_migrated('settings'):
                # Use markdown link for Flask route with matching Streamlit styling
                settings_url = get_page_url('settings')
                st.sidebar.markdown(f'''
                    <a href="{settings_url}" target="_self" class="v2-nav-link">
                        <span class="v2-nav-icon">👤</span>
                        <span class="v2-nav-label">User Preferences</span>
                    </a>
                ''', unsafe_allow_html=True)
            else:
                st.sidebar.page_link("pages/settings.py", label="User Preferences", icon="👤")
        except ImportError:
            # Fallback if shared_navigation not available
            st.sidebar.page_link("pages/settings.py", label="User Preferences", icon="👤")
    
    # Admin section (moved to end of menu)
    try:
        from auth_utils import has_admin_access
        admin_status = has_admin_access()
    except ImportError:
        admin_status = is_admin()
    user_email = get_user_email()
    
    if user_email:
        if admin_status:
            # Check if full admin or readonly_admin
            try:
                from auth_utils import can_modify_data
                is_full_admin = can_modify_data()
            except Exception:
                is_full_admin = False

            if is_full_admin:
                # Full admin badge
                st.sidebar.markdown(
                    '<div class="nav-badge nav-badge-admin">🔑 Full Admin</div>',
                    unsafe_allow_html=True
                )
            else:
                # Read-only admin badge
                st.sidebar.markdown(
                    '<div class="nav-badge nav-badge-role">👁️ Read-Only Admin</div>',
                    unsafe_allow_html=True
                )
            # Admin pages (only visible to admins)
            # Jobs link - check if migrated to Flask
            try:
                from shared_navigation import is_page_migrated, get_page_url
                if is_v2_enabled and is_page_migrated('admin_scheduler'):
                    # Use markdown link for Flask route with matching Streamlit styling
                    jobs_url = get_page_url('admin_scheduler')
                    st.sidebar.markdown(f'''
                        <a href="{jobs_url}" target="_self" class="v2-nav-link">
                            <span class="v2-nav-icon">🔨</span>
                            <span class="v2-nav-label">Jobs Scheduler</span>
                        </a>
                    ''', unsafe_allow_html=True)
                else:
                    st.sidebar.page_link("pages/admin_scheduler.py", label="Jobs", icon="🔨")
            except ImportError:
                # Fallback if shared_navigation not available
                st.sidebar.page_link("pages/admin_scheduler.py", label="Jobs", icon="🔨")
            # User & Access link - check if migrated to Flask
            try:
                from shared_navigation import is_page_migrated, get_page_url
                if is_v2_enabled and is_page_migrated('admin_users'):
                    # Use markdown link for Flask route with matching Streamlit styling
                    users_url = get_page_url('admin_users')
                    st.sidebar.markdown(f'''
                        <a href="{users_url}" target="_self" class="v2-nav-link">
                            <span class="v2-nav-icon">👥</span>
                            <span class="v2-nav-label">User & Access</span>
                        </a>
                    ''', unsafe_allow_html=True)
                else:
                    st.sidebar.page_link("pages/admin_users.py", label="User & Access", icon="👥")
            except ImportError:
                # Fallback if shared_navigation not available
                st.sidebar.page_link("pages/admin_users.py", label="User & Access", icon="👥")
            
            # Contributor Management link - check if migrated to Flask
            try:
                from shared_navigation import is_page_migrated, get_page_url
                if is_v2_enabled and is_page_migrated('admin_contributors'):
                    # Use markdown link for Flask route with matching Streamlit styling
                    contributors_url = get_page_url('admin_contributors')
                    st.sidebar.markdown(f'''
                        <a href="{contributors_url}" target="_self" class="v2-nav-link">
                            <span class="v2-nav-icon">👤</span>
                            <span class="v2-nav-label">Contributors</span>
                        </a>
                    ''', unsafe_allow_html=True)
                else:
                    st.sidebar.page_link("pages/admin_contributors.py", label="Contributors", icon="👤")
            except ImportError:
                # Fallback if shared_navigation not available
                st.sidebar.page_link("pages/admin_contributors.py", label="Contributors", icon="👤")
            
            # Fund Management - check if migrated to Flask
            try:
                from shared_navigation import is_page_migrated, get_page_url
                if is_v2_enabled and is_page_migrated('admin_funds'):
                    # Use markdown link for Flask route with matching Streamlit styling
                    funds_url = get_page_url('admin_funds')
                    st.sidebar.markdown(f'''
                        <a href="{funds_url}" target="_self" class="v2-nav-link">
                            <span class="v2-nav-icon">🏦</span>
                            <span class="v2-nav-label">Fund Management</span>
                        </a>
                    ''', unsafe_allow_html=True)
                else:
                    st.sidebar.page_link("pages/admin_funds.py", label="Fund Management", icon="🏦")
            except ImportError:
                # Fallback if shared_navigation not available
                st.sidebar.page_link("pages/admin_funds.py", label="Fund Management", icon="🏦")

            # Trade Entry - check if migrated to Flask
            try:
                from shared_navigation import is_page_migrated, get_page_url
                if is_v2_enabled and is_page_migrated('admin_trade_entry'):
                    # Use markdown link for Flask route with matching Streamlit styling
                    trade_entry_url = get_page_url('admin_trade_entry')
                    st.sidebar.markdown(f'''
                        <a href="{trade_entry_url}" target="_self" class="v2-nav-link">
                            <span class="v2-nav-icon">📈</span>
                            <span class="v2-nav-label">Trade Entry</span>
                        </a>
                    ''', unsafe_allow_html=True)
                else:
                    st.sidebar.page_link("pages/admin_trade_entry.py", label="Trade Entry", icon="📈")
            except ImportError:
                # Fallback if shared_navigation not available
                st.sidebar.page_link("pages/admin_trade_entry.py", label="Trade Entry", icon="📈")

            # Contributions - check if migrated to Flask
            try:
                from shared_navigation import is_page_migrated, get_page_url
                if is_v2_enabled and is_page_migrated('admin_contributions'):
                    # Use markdown link for Flask route with matching Streamlit styling
                    contributions_url = get_page_url('admin_contributions')
                    st.sidebar.markdown(f'''
                        <a href="{contributions_url}" target="_self" class="v2-nav-link">
                            <span class="v2-nav-icon">💰</span>
                            <span class="v2-nav-label">Contributions</span>
                        </a>
                    ''', unsafe_allow_html=True)
                else:
                    st.sidebar.page_link("pages/admin_contributions.py", label="Contributions", icon="💰")
            except ImportError:
                # Fallback if shared_navigation not available
                st.sidebar.page_link("pages/admin_contributions.py", label="Contributions", icon="💰")

            # AI Settings - check if migrated to Flask
            try:
                from shared_navigation import is_page_migrated, get_page_url
                if is_v2_enabled and is_page_migrated('admin_ai_settings'):
                    # Use markdown link for Flask route with matching Streamlit styling
                    ai_settings_url = get_page_url('admin_ai_settings')
                    st.sidebar.markdown(f'''
                        <a href="{ai_settings_url}" target="_self" class="v2-nav-link">
                            <span class="v2-nav-icon">🤖</span>
                            <span class="v2-nav-label">AI Settings</span>
                        </a>
                    ''', unsafe_allow_html=True)
                else:
                    st.sidebar.page_link("pages/admin_ai_settings.py", label="AI Settings", icon="🤖")
            except ImportError:
                # Fallback if shared_navigation not available
                st.sidebar.page_link("pages/admin_ai_settings.py", label="AI Settings", icon="🤖")

            # System Monitoring - check if migrated to Flask
            try:
                from shared_navigation import is_page_migrated, get_page_url
                if is_v2_enabled and is_page_migrated('admin_system'):
                    # Use markdown link for Flask route with matching Streamlit styling
                    system_url = get_page_url('admin_system')
                    st.sidebar.markdown(f'''
                        <a href="{system_url}" target="_self" class="v2-nav-link">
                            <span class="v2-nav-icon">🖥️</span>
                            <span class="v2-nav-label">System Monitoring</span>
                        </a>
                    ''', unsafe_allow_html=True)
                else:
                    st.sidebar.page_link("pages/admin_system.py", label="System Monitoring", icon="🖥️")
            except ImportError:
                # Fallback if shared_navigation not available
                st.sidebar.page_link("pages/admin_system.py", label="System Monitoring", icon="🖥️")
            
            # Logs link - check if migrated to Flask
            try:
                from shared_navigation import is_page_migrated, get_page_url
                if is_v2_enabled and is_page_migrated('admin_logs'):
                    # Use markdown link for Flask route with matching Streamlit styling
                    logs_url = get_page_url('admin_logs')
                    st.sidebar.markdown(f'''
                        <a href="{logs_url}" target="_self" class="v2-nav-link">
                            <span class="v2-nav-icon">📜</span>
                            <span class="v2-nav-label">Logs</span>
                        </a>
                    ''', unsafe_allow_html=True)
                else:
                    st.sidebar.page_link("pages/admin_logs.py", label="Logs", icon="📜")
            except ImportError:
                # Fallback if shared_navigation not available
                st.sidebar.page_link("pages/admin_logs.py", label="Logs", icon="📜")
        else:
            # Regular user (non-admin) - show role badge
            st.sidebar.markdown(
                '<div class="nav-badge nav-badge-role">👤 User</div>',
                unsafe_allow_html=True
            )
            with st.sidebar.expander("🔧 Need Admin Access?", expanded=False):
                st.write("To become an admin, run this command on the server:")
                st.code("python web_dashboard/setup_admin.py", language="bash")
                st.write(f"Then enter your email: `{user_email}`")
    
    # Modern divider
    st.sidebar.markdown('<hr class="nav-divider">', unsafe_allow_html=True)

