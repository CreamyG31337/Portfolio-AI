#!/usr/bin/env python3
"""
AI Settings
===========

Admin page for configuring AI services, Ollama settings, and AI-related system settings.
"""

import streamlit as st
import sys
import os
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from auth_utils import is_authenticated, has_admin_access, can_modify_data, get_user_email, redirect_to_login
from streamlit_utils import get_supabase_client
from navigation import render_navigation
from supabase_client import SupabaseClient

# Import shared utilities
from admin_utils import perf_timer

# Import log_handler to register PERF logging level
try:
    import log_handler  # noqa: F401 - Import to register PERF level
except ImportError:
    pass

# Performance logging setup
import logging
logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(page_title="AI Settings", page_icon="🤖", layout="wide")

# Check authentication - redirect to main page if not logged in
if not is_authenticated():
    redirect_to_login("pages/admin_ai_settings.py")

# Refresh token if needed (auto-refresh before expiry)
from auth_utils import refresh_token_if_needed
if not refresh_token_if_needed():
    from auth_utils import logout_user
    logout_user(return_to="pages/admin_ai_settings.py")
    st.stop()

# Check admin access (allows both admin and readonly_admin)
if not has_admin_access():
    st.error("❌ Access Denied: Admin privileges required")
    st.info("Only administrators can access this page.")
    st.stop()

# Navigation
render_navigation(show_ai_assistant=True, show_settings=True)

# Header
st.markdown("# 🤖 AI Settings")
st.caption(f"Logged in as: {get_user_email()}")

client = get_supabase_client()
if not client:
    st.error("Failed to connect to database")
else:
    try:
        # Check if system_settings table exists
        try:
            settings_result = client.supabase.table("system_settings").select("*").execute()
            settings_data = {s['key']: s['value'] for s in settings_result.data} if settings_result.data else {}
        except Exception:
            settings_data = {}
            st.warning("⚠️ system_settings table not found. Some settings may not be available.")
        
        # Ollama Configuration
        st.subheader("🦙 Ollama Configuration")
        st.caption("Configure Ollama AI service settings")
        
        with st.expander("Ollama Settings", expanded=True):
            ollama_base_url = st.text_input(
                "Ollama Base URL",
                value=os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434"),
                key="ollama_base_url",
                help="URL for Ollama API (default: http://host.docker.internal:11434)"
            )
            
            ollama_model = st.text_input(
                "Default Ollama Model",
                value=os.getenv("OLLAMA_MODEL", "mistral-nemo:12b"),
                key="ollama_model",
                help="Default model to use for Ollama (default: mistral-nemo:12b)"
            )
            
            ollama_enabled = st.checkbox(
                "Enable Ollama",
                value=os.getenv("OLLAMA_ENABLED", "true").lower() == "true",
                key="ollama_enabled",
                help="Enable/disable Ollama AI service"
            )
            
            # Test Ollama connection
            if st.button("🔍 Test Ollama Connection", type="secondary"):
                try:
                    from ollama_client import check_ollama_health, get_ollama_client
                    
                    if check_ollama_health():
                        st.success("✅ Ollama is running and accessible")
                        
                        # Try to get model info
                        ollama_client = get_ollama_client()
                        if ollama_client:
                            try:
                                models = ollama_client.list_available_models()
                                if models:
                                    st.info(f"📦 Available models: {', '.join(models)}")
                                else:
                                    st.warning("⚠️ No models found in Ollama")
                            except Exception as e:
                                st.warning(f"Could not list models: {e}")
                    else:
                        st.error("❌ Cannot connect to Ollama. Please check if Ollama is running.")
                except ImportError:
                    st.error("❌ Ollama client not available")
                except Exception as e:
                    st.error(f"Error testing Ollama: {e}")
        
        st.divider()
        
        # Research Domain Health
        st.subheader("🔬 Research Domain Health")
        st.caption("Monitor and manage research domain blacklist and health")
        
        try:
            # Check if research_domain_health table exists
            health_result = client.supabase.table("research_domain_health").select("*").order("consecutive_failures", desc=True).limit(20).execute()
            
            if health_result.data:
                import pandas as pd
                health_df = pd.DataFrame(health_result.data)
                
                # Format for display
                if 'last_attempt_at' in health_df.columns:
                    health_df['last_attempt_at'] = pd.to_datetime(health_df['last_attempt_at']).dt.strftime('%Y-%m-%d %H:%M')
                if 'last_success_at' in health_df.columns:
                    health_df['last_success_at'] = pd.to_datetime(health_df['last_success_at']).dt.strftime('%Y-%m-%d %H:%M')
                if 'auto_blacklisted_at' in health_df.columns:
                    health_df['auto_blacklisted_at'] = pd.to_datetime(health_df['auto_blacklisted_at']).dt.strftime('%Y-%m-%d %H:%M')
                
                st.dataframe(health_df, use_container_width=True)
                
                # Blacklist management
                st.markdown("#### Manage Blacklist")
                
                col_blacklist1, col_blacklist2 = st.columns(2)
                with col_blacklist1:
                    blacklist_domain = st.text_input("Domain to Blacklist", key="blacklist_domain", placeholder="example.com")
                    if st.button("🚫 Add to Blacklist", disabled=not can_modify_data()):
                        if not can_modify_data():
                            st.error("❌ Read-only admin cannot modify blacklist")
                        elif not blacklist_domain:
                            st.error("Please enter a domain")
                        else:
                            try:
                                # Use service role client for modifications (required by RLS policy)
                                admin_client = SupabaseClient(use_service_role=True)
                                # Update or insert blacklist entry
                                now = datetime.now().isoformat()
                                admin_client.supabase.table("research_domain_health").upsert({
                                    "domain": blacklist_domain,
                                    "auto_blacklisted": True,
                                    "consecutive_failures": 999,  # High count to ensure it's blacklisted
                                    "auto_blacklisted_at": now,
                                    "last_attempt_at": now,
                                    "updated_at": now
                                }).execute()
                                
                                st.success(f"✅ {blacklist_domain} added to blacklist")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error adding to blacklist: {e}")
                
                with col_blacklist2:
                    remove_domain = st.selectbox(
                        "Domain to Remove from Blacklist",
                        options=[""] + [d['domain'] for d in health_result.data if d.get('auto_blacklisted')],
                        key="remove_blacklist_domain"
                    )
                    if st.button("✅ Remove from Blacklist", disabled=(not remove_domain or not can_modify_data())):
                        if not can_modify_data():
                            st.error("❌ Read-only admin cannot modify blacklist")
                        elif not remove_domain:
                            st.error("Please select a domain")
                        else:
                            try:
                                # Use service role client for modifications (required by RLS policy)
                                admin_client = SupabaseClient(use_service_role=True)
                                now = datetime.now().isoformat()
                                admin_client.supabase.table("research_domain_health").update({
                                    "auto_blacklisted": False,
                                    "consecutive_failures": 0,
                                    "updated_at": now
                                }).eq("domain", remove_domain).execute()
                                
                                st.success(f"✅ {remove_domain} removed from blacklist")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error removing from blacklist: {e}")
            else:
                st.info("No domain health data found")
        except Exception as e:
            st.warning(f"Could not load research domain health: {e}")
            st.info("The research_domain_health table may not exist. This is normal if research features are not enabled.")
        
        st.divider()
        
        # System Settings
        st.subheader("⚙️ System Settings")
        st.caption("Manage AI-related system settings")
        
        with st.expander("System Settings", expanded=False):
            # Auto-blacklist threshold
            auto_blacklist_threshold = st.number_input(
                "Auto-Blacklist Threshold",
                min_value=1,
                max_value=10,
                value=int(settings_data.get('auto_blacklist_threshold', 4)),
                key="auto_blacklist_threshold",
                help="Number of failures before a domain is automatically blacklisted"
            )
            
            if st.button("💾 Save System Settings", type="primary", disabled=not can_modify_data()):
                if not can_modify_data():
                    st.error("❌ Read-only admin cannot modify system settings")
                else:
                    try:
                        # Upsert system settings
                        client.supabase.table("system_settings").upsert({
                            "key": "auto_blacklist_threshold",
                            "value": str(auto_blacklist_threshold),
                            "updated_at": datetime.now().isoformat()
                        }).execute()
                        
                        st.success("✅ System settings saved")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error saving settings: {e}")
        
        st.divider()
        
        # AI Service Status
        st.subheader("📊 AI Service Status")
        st.caption("Check status of AI services")
        
        col_status1, col_status2, col_status3 = st.columns(3)
        
        with col_status1:
            st.markdown("#### Ollama Status")
            try:
                from ollama_client import check_ollama_health
                
                if check_ollama_health():
                    st.success("✅ Ollama is running")
                else:
                    st.error("❌ Ollama is not accessible")
            except ImportError:
                st.warning("⚠️ Ollama client not available")
            except Exception as e:
                st.error(f"Error checking Ollama: {e}")
        
        with col_status2:
            st.markdown("#### Research Database")
            try:
                from admin_utils import get_postgres_status_cached
                
                connected, stats = get_postgres_status_cached()
                if connected:
                    st.success("✅ Research database connected")
                    if stats:
                        st.info(f"Total articles: {stats.get('total', 0)}")
                        st.info(f"Recent (7d): {stats.get('recent_7d', 0)}")
                else:
                    st.error("❌ Research database not connected")
            except Exception as e:
                st.warning(f"Could not check research database: {e}")
        
        with col_status3:
            st.markdown("#### WebAI Cookie Status")
            try:
                from webai_wrapper import check_cookie_config, _load_cookies
                
                # Check cookie configuration
                config_status = check_cookie_config()
                
                # Determine overall status
                has_cookies = False
                cookie_source = None
                
                if config_status.get("env_var_exists"):
                    has_cookies = config_status.get("has_secure_1psid", False)
                    cookie_source = "Environment Variable"
                elif config_status.get("cookie_files", {}).get("webai_cookies.json", {}).get("root_exists"):
                    has_cookies = True
                    cookie_source = "Cookie File (root)"
                elif config_status.get("cookie_files", {}).get("webai_cookies.json", {}).get("web_exists"):
                    has_cookies = True
                    cookie_source = "Cookie File (web_dashboard)"
                elif config_status.get("cookie_files", {}).get("ai_service_cookies.json", {}).get("root_exists"):
                    has_cookies = True
                    cookie_source = "Cookie File (ai_service_cookies.json)"
                
                # Check shared volume (Docker container)
                shared_cookie_path = Path("/shared/cookies/webai_cookies.json")
                if shared_cookie_path.exists():
                    has_cookies = True
                    cookie_source = "Shared Volume (/shared/cookies)"
                
                if has_cookies:
                    st.success("✅ Cookies configured")
                    if cookie_source:
                        st.caption(f"Source: {cookie_source}")
                    
                    # Try to load cookies to verify they're valid
                    try:
                        secure_1psid, secure_1psidts = _load_cookies()
                        if secure_1psid:
                            st.info(f"✅ __Secure-1PSID: Found")
                            if secure_1psidts:
                                st.info(f"✅ __Secure-1PSIDTS: Found")
                            else:
                                st.warning("⚠️ __Secure-1PSIDTS: Missing (optional)")
                        else:
                            st.error("❌ Cookies found but invalid format")
                    except Exception as e:
                        st.warning(f"⚠️ Could not load cookies: {str(e)[:50]}")
                else:
                    st.error("❌ No cookies found")
                    st.caption("Configure cookies to use WebAI models")
                    
            except ImportError:
                st.warning("⚠️ WebAI wrapper not available")
            except Exception as e:
                st.error(f"Error checking cookies: {e}")
        
        # WebAI Cookie Details and Testing
        st.markdown("---")
        with st.expander("🔍 WebAI Cookie Details & Testing", expanded=False):
            try:
                from webai_wrapper import check_cookie_config, _load_cookies, test_webai_connection
                import json
                
                # Show detailed configuration
                st.markdown("#### Cookie Configuration Details")
                config_status = check_cookie_config()
                
                col_detail1, col_detail2 = st.columns(2)
                
                with col_detail1:
                    st.markdown("**Environment Variables:**")
                    if config_status.get("env_var_exists"):
                        st.success("✅ WEBAI_COOKIES_JSON is set")
                        st.caption(f"Length: {config_status.get('env_var_length', 0)} chars")
                        if config_status.get("json_parse_success"):
                            st.success("✅ JSON parsing: Valid")
                            if config_status.get("has_secure_1psid"):
                                st.success("✅ Has __Secure-1PSID")
                            else:
                                st.error("❌ Missing __Secure-1PSID")
                            if config_status.get("has_secure_1psidts"):
                                st.success("✅ Has __Secure-1PSIDTS")
                            else:
                                st.warning("⚠️ Missing __Secure-1PSIDTS (optional)")
                        else:
                            st.error("❌ JSON parsing: Failed")
                            if config_status.get("json_parse_error"):
                                st.caption(f"Error: {str(config_status.get('json_parse_error'))[:100]}")
                    else:
                        st.info("ℹ️ WEBAI_COOKIES_JSON not set")
                    
                    # Check individual env vars
                    if config_status.get("individual_vars", {}).get("WEBAI_SECURE_1PSID"):
                        st.success("✅ WEBAI_SECURE_1PSID is set")
                    if config_status.get("individual_vars", {}).get("WEBAI_SECURE_1PSIDTS"):
                        st.success("✅ WEBAI_SECURE_1PSIDTS is set")
                
                with col_detail2:
                    st.markdown("**Cookie Files:**")
                    cookie_files = config_status.get("cookie_files", {})
                    for name, locations in cookie_files.items():
                        if locations.get("root_exists") or locations.get("web_exists"):
                            st.success(f"✅ {name} found")
                            if locations.get("root_exists"):
                                st.caption(f"  • Root: {Path('.').resolve() / name}")
                            if locations.get("web_exists"):
                                st.caption(f"  • Web: {Path('web_dashboard') / name}")
                        else:
                            st.info(f"ℹ️ {name} not found")
                    
                    # Check shared volume (Docker)
                    shared_cookie_path = Path("/shared/cookies/webai_cookies.json")
                    if shared_cookie_path.exists():
                        st.success("✅ Shared volume cookie file exists")
                        st.caption(f"  • {shared_cookie_path}")
                        try:
                            with open(shared_cookie_path, 'r') as f:
                                shared_cookies = json.load(f)
                            if "__Secure-1PSID" in shared_cookies:
                                st.success("  ✅ Valid JSON with __Secure-1PSID")
                            else:
                                st.warning("  ⚠️ JSON missing __Secure-1PSID")
                        except Exception as e:
                            st.error(f"  ❌ Error reading file: {str(e)[:50]}")
                    else:
                        st.info("ℹ️ Shared volume cookie file not found")
                        st.caption("  • /shared/cookies/webai_cookies.json")
                
                # Cookie Test Section
                st.markdown("---")
                st.markdown("#### Test Cookie Connection")
                st.caption("⚠️ This will make a minimal API call to validate cookies. Use sparingly to avoid rate limiting.")
                
                if st.button("🧪 Test Cookie Connection", type="primary", key="test_webai_cookie"):
                    with st.spinner("Testing cookie connection..."):
                        try:
                            # Find cookie file to test
                            cookie_file = None
                            shared_cookie_path = Path("/shared/cookies/webai_cookies.json")
                            if shared_cookie_path.exists():
                                cookie_file = str(shared_cookie_path)
                            else:
                                # Try other locations
                                project_root = Path(__file__).parent.parent.parent
                                for name in ["webai_cookies.json", "ai_service_cookies.json"]:
                                    test_path = project_root / name
                                    if test_path.exists():
                                        cookie_file = str(test_path)
                                        break
                            
                            # Run test
                            test_result = test_webai_connection(cookies_file=cookie_file)
                            
                            if test_result.get("success"):
                                st.success("✅ Cookie test successful!")
                                st.info(f"Response received: {test_result.get('details', {}).get('response_length', 0)} chars")
                                if test_result.get("details", {}).get("has_1psid"):
                                    st.success("✅ __Secure-1PSID: Valid")
                                if test_result.get("details", {}).get("has_1psidts"):
                                    st.success("✅ __Secure-1PSIDTS: Valid")
                            else:
                                st.error(f"❌ Cookie test failed: {test_result.get('message', 'Unknown error')}")
                                if test_result.get("details", {}).get("error_type") == "missing_cookies":
                                    st.info("💡 No cookies found. Configure cookies first.")
                                else:
                                    error_details = test_result.get("details", {})
                                    if error_details.get("error"):
                                        with st.expander("Error Details"):
                                            st.code(error_details.get("error"))
                        except Exception as e:
                            st.error(f"❌ Test error: {e}")
                            import traceback
                            with st.expander("Error Details"):
                                st.code(traceback.format_exc())
                
            except ImportError as e:
                st.warning(f"⚠️ WebAI wrapper not available: {e}")
            except Exception as e:
                st.error(f"Error loading cookie details: {e}")
                import traceback
                with st.expander("Error Details"):
                    st.code(traceback.format_exc())
                
    except Exception as e:
        st.error(f"Error loading AI settings: {e}")
        import traceback
        with st.expander("Error Details"):
            st.code(traceback.format_exc())

