#!/usr/bin/env python3
"""
Authentication utilities for Streamlit dashboard
Handles user login, session management, and token storage
"""

import os
import streamlit as st
from typing import Optional, Dict
import requests
import base64
import json
import time
from dotenv import load_dotenv
from supabase import create_client, Client
# CookieManager imported in functions where needed to avoid import errors at module level

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")


def login_user(email: str, password: str) -> Optional[Dict]:
    """Authenticate user with Supabase and return session data"""
    if not SUPABASE_URL or not SUPABASE_PUBLISHABLE_KEY:
        return None
    
    try:
        response = requests.post(
            f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
            headers={
                "apikey": SUPABASE_PUBLISHABLE_KEY,
                "Content-Type": "application/json"
            },
            json={
                "email": email,
                "password": password
            }
        )
        
        if response.status_code == 200:
            auth_data = response.json()
            return {
                "access_token": auth_data.get("access_token"),
                "refresh_token": auth_data.get("refresh_token"),  # Store refresh token
                "user": auth_data.get("user"),
                "expires_at": auth_data.get("expires_at"),
                "expires_in": auth_data.get("expires_in")  # Also store expires_in for easier calculation
            }
        else:
            error_data = response.json() if response.text else {}
            return {"error": error_data.get("msg", "Login failed")}
    except Exception as e:
        return {"error": str(e)}


def register_user(email: str, password: str) -> Optional[Dict]:
    """Register new user with Supabase"""
    if not SUPABASE_URL or not SUPABASE_PUBLISHABLE_KEY:
        return None
    
    try:
        response = requests.post(
            f"{SUPABASE_URL}/auth/v1/signup",
            headers={
                "apikey": SUPABASE_PUBLISHABLE_KEY,
                "Content-Type": "application/json"
            },
            json={
                "email": email,
                "password": password
            }
        )
        
        if response.status_code == 200:
            auth_data = response.json()
            # Supabase may return user without access_token if email confirmation is required
            return {
                "access_token": auth_data.get("access_token"),
                "refresh_token": auth_data.get("refresh_token"),  # Store refresh token
                "user": auth_data.get("user"),
                "expires_at": auth_data.get("expires_at"),
                "expires_in": auth_data.get("expires_in"),
                "requires_confirmation": auth_data.get("access_token") is None
            }
        else:
            error_data = {}
            try:
                error_data = response.json() if response.text else {}
            except:
                error_data = {"message": response.text or "Unknown error"}
            
            error_msg = error_data.get("msg") or error_data.get("message") or error_data.get("error_description") or "Registration failed"
            error_code = error_data.get("error") or error_data.get("error_code", "")
            
            if "database" in error_msg.lower() or "Database error" in error_msg:
                return {
                    "error": f"Database error: {error_msg}. This might be due to a database trigger failing. Check Supabase logs for details.",
                    "error_code": error_code,
                    "details": error_data
                }
            
            return {
                "error": error_msg,
                "error_code": error_code,
                "details": error_data
            }
    except Exception as e:
        return {"error": str(e)}


def get_user_token() -> Optional[str]:
    """Get current user's access token from session state
    
    IMPORTANT: This function is for Streamlit contexts ONLY!
    If you're in a Flask context, use flask_auth_utils.get_auth_token() instead.
    
    Raises:
        RuntimeError: If called from Flask context or when Streamlit is not available
    """
    import logging
    logger = logging.getLogger(__name__)
    
    if st is None:
        raise RuntimeError(
            "get_user_token() called but Streamlit is not available. "
            "Use flask_auth_utils.get_auth_token() in Flask context instead."
        )
    
    # Check if we're actually in a Streamlit context with session_state
    try:
        if not hasattr(st, 'session_state'):
            raise RuntimeError(
                "get_user_token() called but st.session_state is not available. "
                "You may be calling this from a Flask thread. "
                "Use flask_auth_utils.get_auth_token() in Flask context instead."
            )
        
        if "user_token" in st.session_state:
            return st.session_state.user_token
        
        logger.debug("get_user_token(): No user_token in session_state")
        return None
        
    except RuntimeError:
        # Re-raise our own RuntimeErrors
        raise
    except Exception as e:
        # st.session_state access failed - we're in wrong context
        raise RuntimeError(
            f"get_user_token() failed to access st.session_state - likely called from Flask thread! "
            f"Use flask_auth_utils.get_auth_token() in Flask context instead. "
            f"Original error: {e}"
        )


def get_user_id() -> Optional[str]:
    """Get current user's ID from session state
    
    IMPORTANT: This function is for Streamlit contexts ONLY!
    If you're in a Flask context, use flask_auth_utils.get_user_id_flask() instead.
    
    Raises:
        RuntimeError: If called from Flask context
    """
    try:
        if "user_id" in st.session_state:
            return st.session_state.user_id
        return None
    except Exception as e:
        raise RuntimeError(
            f"get_user_id() failed to access st.session_state - likely called from Flask thread! "
            f"Use flask_auth_utils.get_user_id_flask() in Flask context instead. "
            f"Original error: {e}"
        )


def get_user_email() -> Optional[str]:
    """Get current user's email from session state
    
    IMPORTANT: This function is for Streamlit contexts ONLY!
    If you're in a Flask context, use flask_auth_utils.get_user_email_flask() instead.
    
    Raises:
        RuntimeError: If called from Flask context
    """
    try:
        if "user_email" in st.session_state:
            return st.session_state.user_email
        return None
    except Exception as e:
        raise RuntimeError(
            f"get_user_email() failed to access st.session_state - likely called from Flask thread! "
            f"Use flask_auth_utils.get_user_email_flask() in Flask context instead. "
            f"Original error: {e}"
        )


def is_authenticated() -> bool:
    """Check if user is authenticated.
    
    This function automatically attempts to restore the session from cookies
    if the user is not already authenticated, ensuring deep-linked pages work correctly.
    """
    # First check if already authenticated
    if "user_token" in st.session_state and st.session_state.user_token is not None:
        return True
    
    # Try to restore session from cookie (for deep-linked subpages)
    try:
        cookies = st.context.cookies
        auth_token = cookies.get("auth_token")
        
        if auth_token:
            # Validate token
            token_parts = auth_token.split('.')
            if len(token_parts) >= 2:
                payload = token_parts[1]
                payload += '=' * (4 - len(payload) % 4)
                decoded = base64.urlsafe_b64decode(payload)
                user_data = json.loads(decoded)
                exp = user_data.get("exp", 0)
                
                current_time = int(time.time())
                
                if exp > current_time:
                    # Token valid, restore session
                    print(f"DEBUG: Restoring session from cookie. User: {user_data.get('email')}")
                    set_user_session(auth_token, skip_cookie_redirect=True, expires_at=exp,
                                    refresh_token=cookies.get("refresh_token"))
                    return True
                else:
                    print(f"DEBUG: Cookie token expired. Exp: {exp}, Now: {current_time}")
        else:
            print("DEBUG: No auth_token cookie found on reload")
    except Exception as e:
        print(f"DEBUG: Error restoring session: {e}")
        pass
    
    print("DEBUG: is_authenticated returning False")
    return False


def logout_user(reason: str = "manual", return_to: Optional[str] = None):
    """Clear user session
    
    Args:
        reason: Reason for logout. Options:
            - "manual": User clicked logout button (default)
            - "session_expired": Token expired
            - "refresh_failed": Token refresh failed
            - "invalid_token": Token validation failed
        return_to: Optional page to redirect back to after login
    """
    if "user_token" in st.session_state:
        del st.session_state.user_token
    if "user_id" in st.session_state:
        del st.session_state.user_id
    if "user_email" in st.session_state:
        del st.session_state.user_email
    if "refresh_token" in st.session_state:
        del st.session_state.refresh_token
    if "token_expires_at" in st.session_state:
        del st.session_state.token_expires_at
    # Clear cookie flag so next login will set a fresh cookie
    if "session_restored_from_cookie" in st.session_state:
        del st.session_state.session_restored_from_cookie
    
    # Redirect through set_cookie.html to clear the cookie
    # (Streamlit can't clear cookies directly due to iframe sandboxing)
    import urllib.parse
    encoded_reason = urllib.parse.quote(reason, safe='')
    
    redirect_url = f'/set_cookie.html?action=clear&reason={encoded_reason}'
    if return_to:
        encoded_return = urllib.parse.quote(return_to, safe='')
        redirect_url += f'&return_to={encoded_return}'
        
    st.markdown(
        f'<meta http-equiv="refresh" content="0; url={redirect_url}">',
        unsafe_allow_html=True
    )
    st.write("Logging out...")
    st.stop()


def redirect_to_login(return_to: Optional[str] = None):
    """Redirect to main page login while preserving current page context
    
    Args:
        return_to: Path to the current page (e.g., 'pages/social_sentiment.py')
    """
    if return_to:
        st.session_state.return_to = return_to
    
    st.switch_page("streamlit_app.py")
    st.stop()


def set_user_session(access_token: str, user: Optional[Dict] = None, skip_cookie_redirect: bool = False, 
                     refresh_token: Optional[str] = None, expires_at: Optional[int] = None,
                     return_to: Optional[str] = None):
    """Store user session data. If user is None, decode from JWT token.
    
    Args:
        access_token: The JWT access token
        user: Optional user dict with id and email
        skip_cookie_redirect: If True, don't redirect to set cookie (used when restoring from cookie)
        refresh_token: Optional refresh token for automatic token renewal
        expires_at: Optional expiration timestamp (Unix epoch seconds)
        return_to: Optional page to redirect back to after setting cookies
    """
    st.session_state.user_token = access_token
    
    # Store refresh token and expiration if provided
    if refresh_token:
        st.session_state.refresh_token = refresh_token
    if expires_at:
        st.session_state.token_expires_at = expires_at
    elif access_token:
        # Try to extract expiration from JWT token if not provided
        try:
            token_parts = access_token.split('.')
            if len(token_parts) >= 2:
                payload = token_parts[1]
                payload += '=' * (4 - len(payload) % 4)
                decoded = base64.urlsafe_b64decode(payload)
                user_data = json.loads(decoded)
                exp = user_data.get("exp")
                if exp:
                    st.session_state.token_expires_at = exp
        except Exception:
            pass  # If we can't decode, that's okay - we'll refresh based on time
    
    if user:
        st.session_state.user_id = user.get("id")
        st.session_state.user_email = user.get("email")
    else:
        # Decode user info from JWT token if user object not provided
        try:
            token_parts = access_token.split('.')
            if len(token_parts) >= 2:
                payload = token_parts[1]
                # Add padding if needed (JWT uses base64url)
                payload += '=' * (4 - len(payload) % 4)
                decoded = base64.urlsafe_b64decode(payload)
                user_data = json.loads(decoded)
                st.session_state.user_id = user_data.get("sub")
                st.session_state.user_email = user_data.get("email")
            else:
                st.session_state.user_id = None
                st.session_state.user_email = None
        except Exception:
            # If decoding fails, just store token
            st.session_state.user_id = None
            st.session_state.user_email = None
    
    # For email/password login, redirect through set_cookie.html to persist the cookie
    # (Streamlit can't set cookies directly due to iframe sandboxing)
    # Skip if restoring from cookie (to avoid infinite loop)
    if not skip_cookie_redirect and "session_restored_from_cookie" not in st.session_state:
        import urllib.parse
        encoded_token = urllib.parse.quote(access_token, safe='')
        
        # Store token temporarily in session state (will be cleared after redirect)
        st.session_state._pending_cookie_token = access_token
        
        # Build redirect URL with both access_token and refresh_token
        redirect_url = f'/set_cookie.html?token={encoded_token}'
        if refresh_token:
            encoded_refresh = urllib.parse.quote(refresh_token, safe='')
            redirect_url += f'&refresh_token={encoded_refresh}'
        
        if return_to:
            encoded_return = urllib.parse.quote(return_to, safe='')
            redirect_url += f'&return_to={encoded_return}'
        
        # Use JavaScript via st.markdown with meta refresh (not stripped like script tags)
        # This will redirect the ENTIRE page, not just an iframe
        st.markdown(
            f'<meta http-equiv="refresh" content="0; url={redirect_url}">',
            unsafe_allow_html=True
        )
        st.write("Saving session... Redirecting...")
        st.stop()  # Stop execution - we'll continue after redirect back
    
    # Mark that session is set (either from cookie restore or after redirect)
    st.session_state.session_restored_from_cookie = True


def request_password_reset(email: str) -> Optional[Dict]:
    """Request password reset email from Supabase"""
    if not SUPABASE_URL or not SUPABASE_PUBLISHABLE_KEY:
        return None
    
    # Redirect to auth callback page which processes hash and redirects to Streamlit
    # Build redirect URL from APP_DOMAIN env variable (e.g., "example.com" or "app.example.com")
    app_domain = os.getenv("APP_DOMAIN")
    if not app_domain:
        return {"error": "APP_DOMAIN environment variable is required. Please set it in your .env file or environment."}
    
    redirect_url = os.getenv("MAGIC_LINK_REDIRECT_URL", f"https://{app_domain}/auth_callback.html")
    
    try:
        # Use Supabase client library which handles redirect_to correctly
        # Note: reset_password_for_email() returns None on success, raises exception on failure
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY)
        supabase.auth.reset_password_for_email(
            email,
            {
                "redirect_to": redirect_url
            }
        )
        # If we get here, no exception was raised = success
        return {"success": True, "message": "Password reset email sent"}
    except Exception as e:
        return {"error": str(e)}


def send_magic_link(email: str) -> Optional[Dict]:
    """Send magic link login email from Supabase"""
    if not SUPABASE_URL or not SUPABASE_PUBLISHABLE_KEY:
        return None
    
    # Redirect to auth callback page which processes hash and redirects to Streamlit
    # Build redirect URL from APP_DOMAIN env variable (e.g., "example.com" or "app.example.com")
    app_domain = os.getenv("APP_DOMAIN")
    if not app_domain:
        return {"error": "APP_DOMAIN environment variable is required. Please set it in your .env file or environment."}
    
    redirect_url = os.getenv("MAGIC_LINK_REDIRECT_URL", f"https://{app_domain}/auth_callback.html")
    
    try:
        # Use Supabase client library which handles redirect_to correctly
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY)
        response = supabase.auth.sign_in_with_otp({
            "email": email,
            "options": {
                "email_redirect_to": redirect_url
            }
        })
        
        if response:
            return {"success": True, "message": "Magic link sent to your email"}
        else:
            return {"error": "Failed to send magic link"}
    except Exception as e:
        return {"error": str(e)}


def refresh_token_if_needed() -> bool:
    """Check if token is expired or about to expire, and refresh it if needed.
    
    This function automatically refreshes the access token when it's about to expire
    (within 5 minutes), keeping users logged in during active sessions.
    
    Note: Refresh tokens are stored in session state only (not in cookies) for security.
    This means:
    - Active users (using the app) will have tokens refreshed automatically
    - Users returning after closing the browser won't have refresh_token available,
      but can still use the app if their access_token is valid
    
    Returns:
        True if token is valid or was refreshed, False only if token is expired/invalid
    """
    if not is_authenticated():
        return False
    
    # Get current token and expiration
    access_token = get_user_token()
    expires_at = st.session_state.get("token_expires_at")
    
    if not access_token:
        # No access token at all - not authenticated
        return False
    
    # Try to determine token expiration
    current_time = int(time.time())
    token_valid = False
    time_until_expiry = None
    
    # First, check stored expiration time
    if expires_at:
        time_until_expiry = expires_at - current_time
        token_valid = time_until_expiry > 0
    else:
        # Try to decode expiration from JWT token
        try:
            token_parts = access_token.split('.')
            if len(token_parts) >= 2:
                payload = token_parts[1]
                payload += '=' * (4 - len(payload) % 4)
                decoded = base64.urlsafe_b64decode(payload)
                user_data = json.loads(decoded)
                expires_at = user_data.get("exp")
                if expires_at:
                    time_until_expiry = expires_at - current_time
                    token_valid = time_until_expiry > 0
                    # Cache the expiration for future checks
                    st.session_state.token_expires_at = expires_at
        except Exception:
            # If we can't decode the token, assume it's valid for now
            # It will fail on actual API calls if it's truly invalid
            token_valid = True
    
    # If token is expired, fail immediately
    if token_valid is False or (time_until_expiry is not None and time_until_expiry <= 0):
        return False

    # Token is valid. Streamlit (a legacy/prototype surface) intentionally does NOT
    # refresh (rotate) Supabase tokens. Supabase refresh tokens are single-use: the
    # production Flask app owns refresh + cookie persistence. If Streamlit also
    # exchanged the refresh token it would rotate it out from under Flask, orphaning
    # the browser's refresh_token cookie and logging the user out (~1h later when the
    # access token expires). So we only validate here and never call the token endpoint.
    return True


def is_admin() -> bool:
    """Check if current user is admin by querying user_profiles table using SQL function"""
    import logging
    logger = logging.getLogger(__name__)
    
    user_id = get_user_id()
    if not user_id:
        logger.debug("is_admin(): No user_id in session state")
        return False
    
    try:
        from streamlit_utils import get_supabase_client
        client = get_supabase_client()
        if not client:
            logger.warning(f"is_admin(): Failed to get Supabase client for user_id: {user_id}")
            return False
        
        # Verify client has user token set
        user_token = get_user_token()
        if not user_token:
            logger.warning(f"is_admin(): No user token available for user_id: {user_id}")
        
        # Call the is_admin SQL function
        # Note: RPC functions returning scalar BOOLEAN return the value directly in result.data
        # (not wrapped in a list) in supabase>=2.3.4
        result = client.supabase.rpc('is_admin', {'user_uuid': user_id}).execute()
        
        # Handle both scalar boolean (newer supabase-py) and list (older versions)
        if result.data is not None:
            # If result.data is a boolean (scalar), return it directly
            if isinstance(result.data, bool):
                logger.debug(f"is_admin(): RPC returned boolean {result.data} for user_id: {user_id}")
                return result.data
            # If result.data is a list (older versions), get first element
            elif isinstance(result.data, list) and len(result.data) > 0:
                admin_value = bool(result.data[0])
                logger.debug(f"is_admin(): RPC returned list, first element: {admin_value} for user_id: {user_id}")
                return admin_value
            else:
                logger.warning(f"is_admin(): Unexpected RPC result format for user_id: {user_id}, result.data: {result.data}")
        
        logger.debug(f"is_admin(): RPC returned None for user_id: {user_id}")
        return False
    except Exception as e:
        logger.error(f"is_admin(): Error checking admin status for user_id {user_id}: {e}", exc_info=True)
        return False


def has_admin_access() -> bool:
    """
    Check if current user has admin access (admin or readonly_admin role).
    This allows access to admin pages for viewing/testing.
    
    Returns:
        bool: True if user has admin or readonly_admin role, False otherwise
    """
    # After SQL migration, is_admin() SQL function checks for both roles
    # So we can use the same function for page access
    return is_admin()


def can_modify_data() -> bool:
    """
    Check if current user can modify data (admin role only).
    readonly_admin users can view but cannot modify data.
    
    Returns:
        bool: True if user has admin role, False otherwise
    """
    import logging
    logger = logging.getLogger(__name__)
    
    user_id = get_user_id()
    if not user_id:
        logger.debug("can_modify_data(): No user_id in session state")
        return False
    
    try:
        from streamlit_utils import get_supabase_client
        client = get_supabase_client()
        if not client:
            logger.warning(f"can_modify_data(): Failed to get Supabase client for user_id: {user_id}")
            return False
        
        # Verify client has user token set
        user_token = get_user_token()
        if not user_token:
            logger.warning(f"can_modify_data(): No user token available for user_id: {user_id}")
        
        # Call the can_modify_data SQL function
        # Note: RPC functions returning scalar BOOLEAN return the value directly in result.data
        # (not wrapped in a list) in supabase>=2.3.4
        result = client.supabase.rpc('can_modify_data', {'user_uuid': user_id}).execute()
        
        # Handle both scalar boolean (newer supabase-py) and list (older versions)
        if result.data is not None:
            # If result.data is a boolean (scalar), return it directly
            if isinstance(result.data, bool):
                logger.debug(f"can_modify_data(): RPC returned boolean {result.data} for user_id: {user_id}")
                return result.data
            # If result.data is a list (older versions), get first element
            elif isinstance(result.data, list) and len(result.data) > 0:
                can_modify = bool(result.data[0])
                logger.debug(f"can_modify_data(): RPC returned list, first element: {can_modify} for user_id: {user_id}")
                return can_modify
            else:
                logger.warning(f"can_modify_data(): Unexpected RPC result format for user_id: {user_id}, result.data: {result.data}")
        
        logger.debug(f"can_modify_data(): RPC returned None for user_id: {user_id}")
        return False
    except Exception as e:
        logger.error(f"can_modify_data(): Error checking modify permission for user_id {user_id}: {e}", exc_info=True)
        return False


def ensure_session_restored() -> bool:
    """Ensure user session is restored from cookies if not already authenticated.
    
    This function should be called at the start of every Streamlit page to ensure
    the user session is loaded from cookies before any preference checks or navigation
    rendering occurs. This prevents race conditions where preferences are checked
    before authentication is established.
    
    Returns:
        True if user is authenticated (either already or after restoration), False otherwise
    """
    # If already authenticated, nothing to do
    if is_authenticated():
        return True
    
    # Try to restore session from cookie
    try:
        # st.context.cookies is available in Streamlit 1.37+
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
                
                current_time = int(time.time())
                
                if exp > current_time:
                    # Token valid, restore session (skip redirect since we're restoring from cookie)
                    set_user_session(auth_token, skip_cookie_redirect=True, expires_at=exp,
                                    refresh_token=cookie_refresh_token)
                    return True
    except Exception:
        # If restoration fails, that's okay - user just isn't authenticated
        pass
    
    return False
