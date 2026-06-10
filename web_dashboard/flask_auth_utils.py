#!/usr/bin/env python3
"""
Flask Authentication Utilities
==============================

Helper functions for Flask routes to extract user information from auth_token cookie.
Shares the same cookie format as Streamlit auth system.
"""

import base64
import json
import logging
import os
import threading
import time
import uuid
from typing import Optional, Dict, Any
from flask import request

logger = logging.getLogger(__name__)

# Flask signed session keys for admin "view as user" (JWT remains the admin's).
SESSION_IMPERSONATE_USER_ID = "impersonate_user_id"
SESSION_IMPERSONATE_USER_EMAIL = "impersonate_user_email"

# Lock dictionary to prevent concurrent refresh attempts with the same refresh_token
# Key: refresh_token value, Value: threading.Lock
_refresh_locks: Dict[str, threading.Lock] = {}
_refresh_locks_lock = threading.Lock()  # Lock for the locks dict itself

# Supabase refresh tokens are single-use: exchanging RT1 revokes it and issues RT2.
# Reusing RT1 more than REFRESH_TOKEN_REUSE_INTERVAL (default 10s) after the exchange
# revokes the ENTIRE session family and logs the user out everywhere. Requests that
# were sent with the old cookie (parallel fetches, queued requests, lost Set-Cookie
# responses) must therefore be handed the already-issued tokens instead of replaying
# the exchange. This cache maps old refresh_token -> (issued_at, access, refresh,
# expires_in) for a grace period so refresh is idempotent within this process.
_REFRESH_CACHE_TTL = 60.0  # seconds
_recent_refreshes: Dict[str, tuple[float, str, Optional[str], Optional[int]]] = {}


def get_auth_token() -> Optional[str]:
    """Get auth_token or session_token from cookies, or from refreshed token if available"""
    # Check for newly refreshed token first (set by @require_auth decorator)
    if hasattr(request, '_new_auth_token') and request._new_auth_token:
        return request._new_auth_token
    # Fall back to cookies
    return request.cookies.get('auth_token') or request.cookies.get('session_token')


def is_supabase_jwt(token: Optional[str]) -> bool:
    """Return True if the token looks like a Supabase access JWT."""
    if not token:
        return False
    try:
        token_parts = token.split('.')
        if len(token_parts) < 2:
            return False
        payload = token_parts[1]
        payload += '=' * (4 - len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload)
        claims = json.loads(decoded)
        # Supabase access tokens include iss and aud="authenticated"
        iss = claims.get('iss')
        aud = claims.get('aud')
        if aud != "authenticated":
            return False
        if iss:
            supabase_url = os.getenv("SUPABASE_URL", "")
            if supabase_url and iss.startswith(supabase_url):
                return True
        # If we couldn't validate iss, still treat as Supabase if aud matches
        return True
    except Exception:
        return False


def get_supabase_access_token() -> Optional[str]:
    """Get a Supabase access token (auth_token only), never a session_token."""
    # Prefer refreshed token if available
    candidate = getattr(request, '_new_auth_token', None) or request.cookies.get('auth_token')
    return candidate if is_supabase_jwt(candidate) else None


def get_refresh_token() -> Optional[str]:
    """Get refresh_token from cookies"""
    import logging
    logger = logging.getLogger(__name__)
    
    token = request.cookies.get('refresh_token')
    logger.debug(f"[FLASK_AUTH] get_refresh_token() called, found refresh_token: {bool(token)}, length: {len(token) if token else 0}")
    if token:
        logger.debug(f"[FLASK_AUTH] refresh_token value (first 20 chars): {token[:20]}...")
    else:
        logger.warning(f"[FLASK_AUTH] refresh_token cookie NOT FOUND. Available cookies: {list(request.cookies.keys())}")
    return token


def _is_uuid(value: Optional[str]) -> bool:
    if not value or not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def ensure_impersonation_session_valid() -> None:
    """Clear impersonation from Flask session if caller is not a full admin or state is invalid.

    Call once per authenticated request (e.g. end of require_auth). Idempotent per request.
    """
    if getattr(request, "_impersonation_session_checked", False):
        return
    request._impersonation_session_checked = True
    try:
        from flask import session, has_request_context

        if not has_request_context():
            return
        raw_id = session.get(SESSION_IMPERSONATE_USER_ID)
        if not raw_id:
            return
        if not _is_uuid(str(raw_id)):
            session.pop(SESSION_IMPERSONATE_USER_ID, None)
            session.pop(SESSION_IMPERSONATE_USER_EMAIL, None)
            logger.info("Cleared impersonation: invalid user id in session")
            return
        auth_id = get_user_id_flask()
        if not auth_id:
            session.pop(SESSION_IMPERSONATE_USER_ID, None)
            session.pop(SESSION_IMPERSONATE_USER_EMAIL, None)
            return
        if str(raw_id) == str(auth_id):
            session.pop(SESSION_IMPERSONATE_USER_ID, None)
            session.pop(SESSION_IMPERSONATE_USER_EMAIL, None)
            logger.info("Cleared impersonation: cannot impersonate self")
            return
        if not can_modify_data_flask():
            session.pop(SESSION_IMPERSONATE_USER_ID, None)
            session.pop(SESSION_IMPERSONATE_USER_EMAIL, None)
            logger.info("Cleared impersonation: user is not a full admin (can_modify_data false)")
    except Exception as e:
        logger.debug("ensure_impersonation_session_valid: %s", e, exc_info=True)


def get_effective_user_id_flask() -> Optional[str]:
    """User id for fund list and preference reads: impersonated target if active, else JWT user."""
    ensure_impersonation_session_valid()
    try:
        from flask import session, has_request_context

        if has_request_context():
            imp = session.get(SESSION_IMPERSONATE_USER_ID)
            if imp and _is_uuid(str(imp)):
                return str(imp)
    except Exception:
        pass
    return get_user_id_flask()


def get_effective_user_email_flask() -> Optional[str]:
    """Email for current request context: impersonated target if active, else JWT email."""
    ensure_impersonation_session_valid()
    try:
        from flask import has_request_context, session

        if has_request_context():
            imp_email = session.get(SESSION_IMPERSONATE_USER_EMAIL)
            if imp_email:
                return str(imp_email).strip()
    except Exception:
        pass
    return get_user_email_flask()


def get_flask_cache_scope_id() -> str:
    """Composite cache key segment: authenticated JWT user + effective user (impersonation-safe)."""
    auth = get_user_id_flask() or "anonymous"
    eff = get_effective_user_id_flask() or auth
    return f"{auth}|{eff}"


def is_impersonating_flask() -> bool:
    """True if a full admin is viewing as another user (Flask session)."""
    ensure_impersonation_session_valid()
    auth = get_user_id_flask()
    eff = get_effective_user_id_flask()
    return bool(auth and eff and auth != eff)


def get_impersonation_banner_context() -> Dict[str, Any]:
    """Template/API payload for impersonation banner."""
    ensure_impersonation_session_valid()
    if not is_impersonating_flask():
        return {"impersonating": False}
    try:
        from flask import session, has_request_context

        if not has_request_context():
            return {"impersonating": False}
        return {
            "impersonating": True,
            "impersonate_user_id": str(session.get(SESSION_IMPERSONATE_USER_ID) or ""),
            "impersonate_user_email": session.get(SESSION_IMPERSONATE_USER_EMAIL) or "",
        }
    except Exception:
        return {"impersonating": False}


def get_user_id_flask() -> Optional[str]:
    """Extract user ID from auth_token/session_token cookie (Flask context)"""
    token = get_auth_token()
    if not token:
        return None
    
    try:
        # Parse JWT token
        # Handle simple encoding (no header) or full JWT
        token_parts = token.split('.')
        
        if len(token_parts) < 2:
            # Try to decode as raw payload if it's not a full JWT
            # session_token might be full JWT, auth_token definitely is
            return None
        
        # Decode payload
        payload = token_parts[1]
        # Add padding if needed
        payload += '=' * (4 - len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload)
        user_data = json.loads(decoded)
        
        # Extract user ID (Supabase uses 'sub', our session uses 'user_id')
        user_id = user_data.get('sub') or user_data.get('user_id')
        return user_id
    except Exception as e:
        logger.warning(f"Error extracting user ID from token: {e}")
        return None


def get_user_email_flask() -> Optional[str]:
    """Extract user email from auth_token cookie (Flask context)"""
    token = get_auth_token()
    if not token:
        return None
    
    try:
        # Parse JWT token
        token_parts = token.split('.')
        if len(token_parts) < 2:
            return None
        
        # Decode payload
        payload = token_parts[1]
        payload += '=' * (4 - len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload)
        user_data = json.loads(decoded)
        
        # Extract email
        email = user_data.get('email')
        return email
    except Exception as e:
        logger.warning(f"Error extracting email from token: {e}")
        return None


def _get_refresh_lock(rt: str) -> threading.Lock:
    """Get or create a lock for a specific refresh_token to prevent concurrent refreshes"""
    with _refresh_locks_lock:
        if rt not in _refresh_locks:
            _refresh_locks[rt] = threading.Lock()
        return _refresh_locks[rt]


def _do_refresh(rt: str) -> tuple[bool, Optional[str], Optional[str], Optional[int]]:
    """Internal function to perform the refresh API call.
    
    Returns:
        Tuple of (success, new_access_token, new_refresh_token, expires_in)
        
    Supabase error codes we detect:
        - refresh_token_already_used: Token revoked (outside reuse interval)
        - refresh_token_not_found: Session/token deleted
        - session_expired: Inactivity timeout or timebox exceeded
        - session_not_found: Session deleted (user signed out elsewhere)
        - invalid_credentials: Token format invalid
        - conflict: Too many concurrent refresh requests
    """
    try:
        import requests

        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
        
        if not supabase_url or not supabase_key:
            logger.warning("[FLASK_AUTH] Missing Supabase URL/key for refresh")
            return (False, None, None, None)
        
        response = requests.post(
            f"{supabase_url}/auth/v1/token?grant_type=refresh_token",
            headers={
                "apikey": supabase_key,
                "Content-Type": "application/json"
            },
            json={"refresh_token": rt},
            timeout=10
        )
        
        if response.status_code == 200:
            auth_data = response.json()
            new_access_token = auth_data.get("access_token")
            new_refresh_token = auth_data.get("refresh_token")
            expires_in = auth_data.get("expires_in", 3600)
            
            if new_access_token:
                logger.debug(f"[FLASK_AUTH] Token refresh successful, expires_in={expires_in}s")
                return (True, new_access_token, new_refresh_token, expires_in)
        
        # Parse error response for better diagnostics
        error_code = None
        error_msg = None
        try:
            error_data = response.json()
            error_code = error_data.get("error_code") or error_data.get("code")
            error_msg = error_data.get("error_description") or error_data.get("msg") or error_data.get("message")
        except Exception:
            pass
        
        error_text = response.text.lower()
        rt_preview = rt[:8] + "..." if len(rt) > 8 else rt
        
        # Categorize the error for better debugging
        if error_code == "refresh_token_already_used":
            # Refresh token was revoked - outside the 10s reuse window
            # This means the token was used successfully elsewhere but we didn't get the new tokens
            logger.error(
                f"[FLASK_AUTH] REFRESH TOKEN REVOKED (refresh_token_already_used): "
                f"Token {rt_preview} was already used and rotated. "
                f"This usually means: (1) concurrent requests caused a race condition outside the 10s reuse window, "
                f"or (2) the token was refreshed on another device/session. "
                f"User must re-login. HTTP {response.status_code}"
            )
        elif error_code == "refresh_token_not_found":
            # Session containing this refresh token no longer exists
            logger.error(
                f"[FLASK_AUTH] SESSION NOT FOUND (refresh_token_not_found): "
                f"Token {rt_preview} session no longer exists. "
                f"Possible causes: (1) user signed out elsewhere, (2) session was deleted, "
                f"(3) refresh token is from a different environment/project. "
                f"User must re-login. HTTP {response.status_code}"
            )
        elif error_code == "session_expired":
            # Inactivity timeout or session timebox exceeded
            logger.error(
                f"[FLASK_AUTH] SESSION EXPIRED (session_expired): "
                f"Token {rt_preview} session has expired due to inactivity or reaching max lifetime. "
                f"Check Supabase Auth settings for session timeouts. "
                f"User must re-login. HTTP {response.status_code}"
            )
        elif error_code == "session_not_found":
            # Session deleted (similar to refresh_token_not_found)
            logger.error(
                f"[FLASK_AUTH] SESSION NOT FOUND (session_not_found): "
                f"Token {rt_preview} session was deleted (user signed out or session purged). "
                f"User must re-login. HTTP {response.status_code}"
            )
        elif error_code == "conflict":
            # Too many concurrent refresh attempts
            logger.warning(
                f"[FLASK_AUTH] CONFLICT (conflict): "
                f"Too many concurrent refresh requests for token {rt_preview}. "
                f"This is a race condition - another request is refreshing. "
                f"Consider exponential backoff. HTTP {response.status_code}"
            )
        elif error_code == "invalid_credentials":
            # Token format or grant type invalid
            logger.error(
                f"[FLASK_AUTH] INVALID CREDENTIALS (invalid_credentials): "
                f"Token {rt_preview} format or grant type not recognized. "
                f"This may indicate a corrupted token or wrong token type. "
                f"User must re-login. HTTP {response.status_code}"
            )
        elif "already been used" in error_text or "already used" in error_text:
            # Fallback detection for older Supabase versions
            logger.error(
                f"[FLASK_AUTH] REFRESH TOKEN ALREADY USED (legacy detection): "
                f"Token {rt_preview} was already consumed. HTTP {response.status_code}: {response.text[:200]}"
            )
        elif response.status_code == 400:
            # Generic 400 - could be various issues
            logger.error(
                f"[FLASK_AUTH] BAD REQUEST (400): "
                f"Token {rt_preview} refresh failed with 400. "
                f"error_code={error_code}, error_msg={error_msg}, "
                f"response={response.text[:300]}"
            )
        elif response.status_code == 401:
            # Unauthorized - token or apikey issue
            logger.error(
                f"[FLASK_AUTH] UNAUTHORIZED (401): "
                f"Token {rt_preview} refresh failed with 401. "
                f"error_code={error_code}, error_msg={error_msg}, "
                f"This may indicate invalid apikey or token. response={response.text[:200]}"
            )
        elif response.status_code == 429:
            # Rate limited
            logger.warning(
                f"[FLASK_AUTH] RATE LIMITED (429): "
                f"Too many refresh requests. Implement exponential backoff. "
                f"response={response.text[:200]}"
            )
        else:
            # Unknown error
            logger.warning(
                f"[FLASK_AUTH] REFRESH FAILED: "
                f"Token {rt_preview}, HTTP {response.status_code}, "
                f"error_code={error_code}, error_msg={error_msg}, "
                f"response={response.text[:300]}"
            )
        
        return (False, None, None, None)
    except Exception as e:
        logger.warning(f"[FLASK_AUTH] Refresh exception: {e}", exc_info=True)
        return (False, None, None, None)


def _get_cached_refresh(rt: str) -> Optional[tuple[bool, str, Optional[str], Optional[int]]]:
    """Return cached refresh result for an already-exchanged refresh token, if fresh."""
    entry = _recent_refreshes.get(rt)
    if entry and (time.time() - entry[0]) < _REFRESH_CACHE_TTL:
        logger.debug("[FLASK_AUTH] Refresh cache hit - reusing tokens from earlier exchange")
        return (True, entry[1], entry[2], entry[3])
    return None


def _stash_tokens_on_request(access_token: str, refresh_token: Optional[str],
                             expires_in: Optional[int]) -> None:
    """Record refreshed tokens on the request so the app-level after_request hook
    persists them as cookies no matter which code path performed the refresh."""
    try:
        from flask import has_request_context
        if not has_request_context():
            return
        request._new_auth_token = access_token
        if refresh_token:
            request._new_refresh_token = refresh_token
        if expires_in:
            request._token_expires_in = expires_in
    except Exception as e:
        logger.debug(f"[FLASK_AUTH] Could not stash refreshed tokens on request: {e}")


def _refresh_with_cache(rt: str, blocking: bool = True) -> tuple[bool, Optional[str], Optional[str], Optional[int]]:
    """Exchange a refresh token for new tokens, idempotently.

    If this refresh token was already exchanged within the grace period, returns the
    tokens issued by that exchange instead of replaying it (replaying outside
    Supabase's reuse interval revokes the whole session). The per-token lock
    serializes concurrent callers so only one of them performs the network call.

    With blocking=False, returns (True, None, None, None) if another thread holds the
    lock — callers use this for proactive refresh where the current token is still valid.
    """
    cached = _get_cached_refresh(rt)
    if cached:
        _stash_tokens_on_request(cached[1], cached[2], cached[3])
        return cached

    lock = _get_refresh_lock(rt)
    if not lock.acquire(blocking=blocking):
        logger.debug("[FLASK_AUTH] Refresh skipped - another request is refreshing")
        return (True, None, None, None)
    try:
        # Re-check under the lock: another request may have refreshed while we waited
        cached = _get_cached_refresh(rt)
        if cached:
            _stash_tokens_on_request(cached[1], cached[2], cached[3])
            return cached

        result = _do_refresh(rt)
        if result[0] and result[1]:
            now = time.time()
            with _refresh_locks_lock:
                _recent_refreshes[rt] = (now, result[1], result[2], result[3])
                # Prune expired cache entries and their locks to keep memory bounded
                stale = [k for k, v in _recent_refreshes.items()
                         if (now - v[0]) > _REFRESH_CACHE_TTL]
                for k in stale:
                    _recent_refreshes.pop(k, None)
                    if k != rt:
                        _refresh_locks.pop(k, None)
            _stash_tokens_on_request(result[1], result[2], result[3])
        return result
    finally:
        lock.release()


def refresh_token_if_needed_flask() -> tuple[bool, Optional[str], Optional[str], Optional[int]]:
    """Check if token is expired or about to expire, and refresh it if needed (Flask context).
    
    This function automatically refreshes the access token when it's about to expire
    (within 5 minutes), keeping users logged in during active sessions.
    
    If auth_token is missing but refresh_token exists, attempts to refresh to get a new auth_token.
    
    IMPORTANT: Supabase refresh tokens are single-use and rotate. If multiple requests try to
    refresh simultaneously, only the first succeeds. This function uses a lock per refresh_token
    to prevent concurrent refresh attempts.
    
    Returns:
        Tuple of (success, new_access_token, new_refresh_token, expires_in)
        - success: True if token is valid or was refreshed, False if expired/invalid
        - new_access_token: New access token if refreshed, None otherwise
        - new_refresh_token: New refresh token if refreshed, None otherwise
        - expires_in: Expiration time in seconds if refreshed, None otherwise
    """
    # Check specifically for auth_token (not session_token) to determine if we need to refresh
    auth_token = request.cookies.get('auth_token')  # Check auth_token specifically
    session_token = request.cookies.get('session_token')
    refresh_token = get_refresh_token()
    
    # Use session_token as fallback for token validation, but check auth_token for refresh logic
    token = auth_token or session_token  # For validation purposes
    
    # If auth_token is present but not a Supabase JWT, treat it as missing for refresh purposes
    if auth_token and not is_supabase_jwt(auth_token):
        logger.warning("[FLASK_AUTH] auth_token is not a Supabase JWT; will attempt refresh if possible")
        auth_token = None
        token = session_token

    # If no auth_token but we have refresh_token, try to refresh immediately
    if not auth_token and refresh_token:
        # Missing auth_token - try to refresh using refresh_token
        return _refresh_with_cache(refresh_token)

    # If no token at all, can't refresh
    if not token:
        return (False, None, None, None)

    try:
        # Parse token to check expiration
        token_parts = token.split('.')
        if len(token_parts) < 2:
            return (False, None, None, None)
        
        payload = token_parts[1]
        payload += '=' * (4 - len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload)
        user_data = json.loads(decoded)
        
        # Check expiration
        exp = user_data.get('exp', 0)
        current_time = int(time.time())
        time_until_expiry = exp - current_time if exp > 0 else None
        
        # If token is expired, try to refresh it
        if exp > 0 and exp < current_time:
            # Token is expired - try to refresh
            if refresh_token:
                return _refresh_with_cache(refresh_token)
            else:
                # No refresh token available
                logger.debug("[FLASK_AUTH] Token expired and no refresh token available")
                return (False, None, None, None)

        # Token is valid - check if we should refresh it proactively
        # Only refresh if token is expiring soon (within 5 minutes)
        if time_until_expiry is not None and 0 < time_until_expiry <= 300 and refresh_token:
            # Non-blocking: if another request is already refreshing, skip — our token
            # is still valid, and the cache will serve us the new tokens next request.
            result = _refresh_with_cache(refresh_token, blocking=False)
            if result[0] and result[1]:  # Refreshed (or cache hit)
                return result

        # Token is valid and doesn't need refresh
        return (True, None, None, None)
    except Exception as e:
        logger.warning(f"[FLASK_AUTH] Error validating/refreshing token: {e}")
        return (False, None, None, None)


def is_authenticated_flask() -> bool:
    """Check if user is authenticated (Flask context)
    
    This function checks if we have a valid token. It does NOT refresh the token
    (refresh should be done separately before calling this).
    """
    # Check if we have a new token from a previous refresh attempt
    token = getattr(request, '_new_auth_token', None) or get_auth_token()
    if not token:
        return False
    
    try:
        # Parse and validate token expiration
        token_parts = token.split('.')
        if len(token_parts) < 2:
            return False
        
        payload = token_parts[1]
        payload += '=' * (4 - len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload)
        user_data = json.loads(decoded)
        
        # Check expiration
        exp = user_data.get('exp', 0)
        import time
        if exp > 0 and exp < time.time():
            return False
        
        return True
    except Exception as e:
        logger.warning(f"Error validating token: {e}")
        return False


def _decode_jwt_token(token: str) -> Optional[Dict]:
    """Decode JWT token without verification (for extracting user_id/email/access_token)"""
    try:
        token_parts = token.split('.')
        if len(token_parts) >= 2:
            payload = token_parts[1]
            payload += '=' * (4 - len(payload) % 4)  # Add padding if needed
            decoded = base64.urlsafe_b64decode(payload)
            return json.loads(decoded)
    except Exception as e:
        logger.debug(f"Failed to decode JWT token: {e}")
    return None


def can_modify_data_flask() -> bool:
    """
    Check if current user can modify data (admin role only).
    readonly_admin users can view but cannot modify data.
    
    Returns:
        bool: True if user has admin role (not readonly_admin), False otherwise
    """
    user_id = get_user_id_flask()
    if not user_id:
        logger.debug("can_modify_data_flask(): No user_id found")
        return False
    
    try:
        from supabase_client import SupabaseClient
        
        # Get user's token for Supabase client
        token = get_auth_token()
        if not token:
            logger.warning(f"can_modify_data_flask(): No user token available for user_id: {user_id}")
            return False
        
        # Create Supabase client with user's token
        client = SupabaseClient()
        if not client or not client.supabase:
            logger.warning(f"can_modify_data_flask(): Failed to get Supabase client for user_id: {user_id}")
            return False
        
        # Call the can_modify_data SQL function
        result = client.supabase.rpc('can_modify_data', {'user_uuid': user_id}).execute()
        
        # Handle both scalar boolean (newer supabase-py) and list (older versions)
        if result.data is not None:
            if isinstance(result.data, bool):
                logger.debug(f"can_modify_data_flask(): RPC returned boolean {result.data} for user_id: {user_id}")
                return result.data
            elif isinstance(result.data, list) and len(result.data) > 0:
                can_modify = bool(result.data[0])
                logger.debug(f"can_modify_data_flask(): RPC returned list, first element: {can_modify} for user_id: {user_id}")
                return can_modify
            else:
                logger.warning(f"can_modify_data_flask(): Unexpected RPC result format for user_id: {user_id}, result.data: {result.data}")
        
        logger.debug(f"can_modify_data_flask(): RPC returned None for user_id: {user_id}")
        return False
    except Exception as e:
        logger.error(f"can_modify_data_flask(): Error checking modify permission for user_id {user_id}: {e}", exc_info=True)
        return False
