#!/usr/bin/env python3
"""
Authentication system for portfolio dashboard
Handles user login, registration, and fund access control
"""

import base64
import json as json_lib
import os
import time
import uuid
import jwt
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify, redirect
import requests
import logging

logger = logging.getLogger(__name__)


def _auth_trace_prefix() -> str:
    """Correlation prefix for auth trace logs on the current request."""
    trace_id = getattr(request, "_auth_trace_id", None)
    return f"[AUTH_TRACE] req={trace_id} " if trace_id else "[AUTH_TRACE] "


def _auth_token_expiry_state(token: str | None) -> tuple[bool | None, int | None]:
    """Return (is_expired, exp_epoch) for a JWT-like token, or (None, None) if unknown."""
    if not token:
        return None, None
    try:
        token_parts = token.split(".")
        if len(token_parts) < 2:
            return None, None
        payload = token_parts[1]
        payload += "=" * (4 - len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload)
        token_data = json_lib.loads(decoded)
        exp = token_data.get("exp", 0)
        if exp <= 0:
            return None, None
        return exp < time.time(), int(exp)
    except Exception:
        return None, None


def _log_auth_refresh_outcome(
    success: bool,
    new_token: str | None,
    new_refresh: str | None,
    expires_in: int | None,
    branch: str,
) -> None:
    """Log the result of a refresh attempt inside require_auth."""
    logger.info(
        f"{_auth_trace_prefix()}refresh_outcome branch={branch} "
        f"success={success} new_token={'yes' if new_token else 'no'} "
        f"new_refresh={'yes' if new_refresh else 'no'} expires_in={expires_in}"
    )


def _log_auth_logout(reason: str, *, api: bool) -> None:
    """Log an explicit logout decision before redirect/401."""
    logger.info(
        f"{_auth_trace_prefix()}logout reason={reason} "
        f"path={request.path} response={'401' if api else 'redirect:/auth'}"
    )

class AuthManager:
    """Handles user authentication and authorization"""

    def __init__(self):
        self.supabase_url = os.getenv("SUPABASE_URL")
        self.supabase_anon_key = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

        self.jwt_secret = os.getenv("JWT_SECRET")
        if not self.jwt_secret:
            import secrets
            logger.warning("AuthManager: JWT_SECRET not set. Generating a random secret. Sessions will be invalidated on restart.")
            self.jwt_secret = secrets.token_hex(32)

        self.supabase_jwt_secret = os.getenv("SUPABASE_JWT_SECRET")
        if not self.supabase_jwt_secret:
            logger.info("AuthManager: SUPABASE_JWT_SECRET not set. Token verification will fall back to API check (slower).")

        # Debug logging
        if not self.supabase_anon_key:
            logger.warning("AuthManager: No Supabase anon key found in environment (checked SUPABASE_PUBLISHABLE_KEY and SUPABASE_ANON_KEY)")

    def get_user_funds(self, user_id: str) -> list[str]:
        """Get funds assigned to a user"""
        try:
            # Get user's assigned funds from Supabase
            response = requests.post(
                f"{self.supabase_url}/rest/v1/rpc/get_user_funds",
                headers={
                    "apikey": self.supabase_anon_key,
                    "Authorization": f"Bearer {self.supabase_anon_key}",
                    "Content-Type": "application/json"
                },
                json={"user_uuid": user_id}
            )

            if response.status_code == 200:
                funds = [row["fund_name"] for row in response.json()]
                return funds
            else:
                logger.error(f"Error getting user funds: {response.text}")
                return []
        except Exception as e:
            logger.error(f"Error getting user funds: {e}")
            return []

    def check_fund_access(self, user_id: str, fund_name: str) -> bool:
        """Check if user has access to a specific fund"""
        try:
            response = requests.post(
                f"{self.supabase_url}/rest/v1/rpc/user_has_fund_access",
                headers={
                    "apikey": self.supabase_anon_key,
                    "Authorization": f"Bearer {self.supabase_anon_key}",
                    "Content-Type": "application/json"
                },
                json={"user_uuid": user_id, "fund_name": fund_name}
            )

            if response.status_code == 200:
                return response.json()
            return False
        except Exception as e:
            logger.error(f"Error checking fund access: {e}")
            return False

    def create_user_session(self, user_id: str, email: str) -> str:
        """Create a JWT session token for the user"""
        payload = {
            "user_id": user_id,
            "email": email,
            "exp": datetime.utcnow() + timedelta(hours=24)
        }
        return jwt.encode(payload, self.jwt_secret, algorithm="HS256")

    def verify_session(self, token: str) -> dict | None:
        """Verify and decode a JWT session token"""
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

    def verify_supabase_token(self, token: str) -> dict | None:
        """Verify a Supabase JWT token"""
        # Try verifying with secret if available
        if self.supabase_jwt_secret:
            try:
                # Supabase tokens usually have aud="authenticated"
                # Allow 'authenticated' audience or no audience check if needed
                payload = jwt.decode(token, self.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated")
                return payload
            except jwt.InvalidAudienceError:
                 # Try without audience check just in case
                try:
                    payload = jwt.decode(token, self.supabase_jwt_secret, algorithms=["HS256"], options={"verify_aud": False})
                    return payload
                except Exception:
                    pass
            except Exception:
                # If secret verification fails (e.g. invalid signature), return None
                return None

        # Fallback to API verification if no secret (slower but secure)
        try:
            response = requests.get(
                f"{self.supabase_url}/auth/v1/user",
                headers={
                    "apikey": self.supabase_anon_key,
                    "Authorization": f"Bearer {token}"
                },
                timeout=5
            )

            if response.status_code == 200:
                user_data = response.json()
                # Normalize to JWT payload format expected by app
                return {
                    "sub": user_data.get("id"),
                    "email": user_data.get("email"),
                    "aud": user_data.get("aud"),
                    # Add simple expiration since API check passed (token is valid now)
                    "exp": datetime.utcnow().timestamp() + 300
                }
            else:
                return None
        except Exception as e:
            logger.error(f"Error verifying Supabase token via API: {e}")
            return None

    def is_admin(self, user_id: str) -> bool:
        """Check if user is admin"""
        try:
            response = requests.post(
                f"{self.supabase_url}/rest/v1/rpc/is_admin",
                headers={
                    "apikey": self.supabase_anon_key,
                    "Authorization": f"Bearer {self.supabase_anon_key}",
                    "Content-Type": "application/json"
                },
                json={"user_uuid": user_id}
            )

            if response.status_code == 200:
                result = response.json()
                # Handle both boolean and list responses
                if isinstance(result, bool):
                    return result
                elif isinstance(result, list) and len(result) > 0:
                    return bool(result[0])
                else:
                    logger.warning(f"Unexpected is_admin response format: {result}")
                    return False
            else:
                logger.warning(f"is_admin RPC returned status {response.status_code}: {response.text}")
            return False
        except Exception as e:
            logger.error(f"Error checking admin status for user_id {user_id}: {e}")
            return False

# Global auth manager instance
auth_manager = AuthManager()

def require_auth(f):
    """Decorator to require authentication for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from flask_auth_utils import refresh_token_if_needed_flask, get_refresh_token

        request._auth_trace_id = uuid.uuid4().hex[:8]

        # Detect broken auth state first
        auth_token = request.cookies.get('auth_token')
        session_token = request.cookies.get('session_token')
        refresh_token = get_refresh_token()
        auth_expired, auth_exp = _auth_token_expiry_state(auth_token)
        logger.info(
            f"{_auth_trace_prefix()}require_auth entry path={request.path} "
            f"has_auth_token={bool(auth_token)} auth_expired={auth_expired} auth_exp={auth_exp} "
            f"has_refresh_token={bool(refresh_token)} has_session_token={bool(session_token)}"
        )

        # Don't delete cookies in require_auth - let the route handle authentication
        # Note: Supabase now returns 12-character opaque refresh tokens (this is normal)
        # Only warn if the token is suspiciously short (less than 10 chars)
        if refresh_token and len(refresh_token) < 10:
            logger.warning(f"[AUTH] require_auth: Refresh token appears corrupted (length={len(refresh_token)}), but continuing anyway")
            # Don't delete cookies - just log the warning

        # Now try to refresh token if needed (only if we have a token)
        success = True
        new_token = None
        new_refresh = None
        expires_in = None

        if auth_token or session_token:
            # We have a token - try to refresh if needed, but NEVER delete cookies here
            # If auth_token is missing but refresh_token exists, try to refresh
            if not auth_token and refresh_token:
                # Missing auth_token - try to refresh using refresh_token
                success, new_token, new_refresh, expires_in = refresh_token_if_needed_flask()
                _log_auth_refresh_outcome(
                    success, new_token, new_refresh, expires_in, "missing_auth_token"
                )
                # If refresh fails, refresh_token is expired/invalid - redirect to login
                if not success:
                    _log_auth_logout(
                        "missing_auth_token_refresh_failed",
                        api=request.path.startswith('/api/'),
                    )
                    if request.path.startswith('/api/'):
                        return jsonify({"error": "Session expired, please log in again"}), 401
                    else:
                        return redirect('/auth')
            elif auth_token:
                # Have auth_token - try to refresh proactively if needed (within 5 minutes of expiry)
                # This keeps tokens fresh during active sessions
                success, new_token, new_refresh, expires_in = refresh_token_if_needed_flask()
                _log_auth_refresh_outcome(
                    success, new_token, new_refresh, expires_in, "has_auth_token"
                )

                # Check if token is expired and refresh failed - if so, redirect to login
                if not success and not new_token:
                    # Refresh failed - check if token is expired
                    is_expired, _ = _auth_token_expiry_state(auth_token)
                    if is_expired:
                        _log_auth_logout(
                            "auth_token_expired_refresh_failed",
                            api=request.path.startswith('/api/'),
                        )
                        if request.path.startswith('/api/'):
                            return jsonify({"error": "Session expired, please log in again"}), 401
                        else:
                            return redirect('/auth')
            else:
                # Only have session_token - don't try to refresh, just use it
                # This is OK for basic auth, but Supabase features won't work
                success = True
                new_token = None
                new_refresh = None
                expires_in = None
        elif refresh_token:
            # No auth_token and no session_token, but a refresh_token exists.
            # This happens for magic-link users after the session_token (24h) expires
            # but the refresh_token (30d) is still valid. Try to recover.
            success, new_token, new_refresh, expires_in = refresh_token_if_needed_flask()
            _log_auth_refresh_outcome(
                success, new_token, new_refresh, expires_in, "refresh_token_only"
            )
            if not success:
                _log_auth_logout(
                    "refresh_token_only_failed",
                    api=request.path.startswith('/api/'),
                )
                if request.path.startswith('/api/'):
                    return jsonify({"error": "Session expired, please log in again"}), 401
                else:
                    return redirect('/auth')
        else:
            # No token at all - redirect to login
            _log_auth_logout("no_tokens", api=request.path.startswith('/api/'))
            if request.path.startswith('/api/'):
                return jsonify({"error": "Authentication required"}), 401
            else:
                return redirect('/auth')

        # Store new tokens in request context if they were refreshed
        if new_token:
            request._new_auth_token = new_token
            if new_refresh:
                request._new_refresh_token = new_refresh
            if expires_in:
                request._token_expires_in = expires_in

        # Check for auth_token (use new token if available, otherwise from cookies)
        # If we successfully refreshed, we should have a token now
        token = new_token or (request.cookies.get('auth_token') or
                              request.cookies.get('session_token') or
                              request.headers.get('Authorization', '').replace('Bearer ', ''))

        # If we don't have a token, check fallback options
        if not token:
            # Only use session_token as fallback if we never tried to refresh
            # (i.e., we only have session_token and no refresh_token was available)
            if session_token and not refresh_token:
                # Have session_token but no refresh_token - allow access but log warning
                # Supabase features won't work, but basic auth will
                logger.warning("[AUTH] require_auth: Using session_token as fallback (no refresh_token available)")
                token = session_token
            else:
                # No token at all, or refresh was attempted and failed - redirect to login
                _log_auth_logout(
                    "no_token_after_refresh_attempt",
                    api=request.path.startswith('/api/'),
                )
                if request.path.startswith('/api/'):
                    return jsonify({"error": "Authentication required"}), 401
                else:
                    return redirect('/auth')

        # If the token was just issued by a successful refresh, decode the claims
        # directly from the JWT — no additional network round-trip to Supabase needed.
        # (Without SUPABASE_JWT_SECRET, verify_supabase_token falls back to an HTTP call
        # on every request, which adds latency and fails under rate-limiting.)
        if new_token and token == new_token:
            try:
                import base64 as _b64, json as _json
                parts = new_token.split('.')
                pad = parts[1] + '=' * (4 - len(parts[1]) % 4)
                claims = _json.loads(_b64.urlsafe_b64decode(pad))
                user_data = {
                    "sub": claims.get("sub"),
                    "user_id": claims.get("sub"),
                    "email": claims.get("email"),
                    "exp": claims.get("exp"),
                }
            except Exception:
                user_data = None
        else:
            # Try to verify with auth_manager (for session_token format)
            user_data = auth_manager.verify_session(token)

            # If that fails, try verifying as Supabase token (securely)
            if not user_data:
                user_data = auth_manager.verify_supabase_token(token)

                # If verification successful but format needs adjusting
                if user_data and ("user_id" not in user_data):
                    user_data["user_id"] = user_data.get("sub")

        if not user_data:
            # For HTML pages, redirect to login; for API, return JSON error
            _log_auth_logout(
                "invalid_or_expired_session",
                api=request.path.startswith('/api/'),
            )
            if request.path.startswith('/api/'):
                return jsonify({"error": "Invalid or expired session"}), 401
            else:
                return redirect('/auth')

        # Add user data to request context
        request.user_id = user_data.get("user_id") or user_data.get("sub")
        request.user_email = user_data.get("email")
        logger.info(
            f"{_auth_trace_prefix()}require_auth ok user_id={request.user_id} "
            f"email={request.user_email} refreshed={bool(new_token)}"
        )

        from flask_auth_utils import ensure_impersonation_session_valid
        ensure_impersonation_session_valid()

        # Execute the route function.
        # Refreshed tokens are persisted as cookies by the app-level
        # persist_refreshed_tokens after_request hook (reads request._new_auth_token).
        return f(*args, **kwargs)
    return decorated_function

def require_fund_access(fund_name: str):
    """Decorator to require access to a specific fund"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not hasattr(request, 'user_id'):
                return jsonify({"error": "Authentication required"}), 401

            if not auth_manager.check_fund_access(request.user_id, fund_name):
                return jsonify({"error": "Access denied to this fund"}), 403

            return f(*args, **kwargs)
        return decorated_function
    return decorator

def get_user_funds():
    """Get funds for the current user"""
    if not hasattr(request, 'user_id'):
        return []
    return auth_manager.get_user_funds(request.user_id)

def _user_has_admin_access() -> tuple[bool, str | None]:
    """Return (is_admin, error_detail) for the current request (requires request.user_id)."""
    if not getattr(request, "user_id", None):
        return False, "no user_id on request"

    token = (
        getattr(request, "_new_auth_token", None)
        or request.cookies.get("auth_token")
        or request.cookies.get("session_token")
        or request.headers.get("Authorization", "").replace("Bearer ", "")
    )

    is_user_admin = False
    admin_check_error: str | None = None
    try:
        if token and len(token.split(".")) == 3:
            try:
                from supabase_client import SupabaseClient
                from flask_auth_utils import get_supabase_access_token

                supabase_token = get_supabase_access_token()
                client = SupabaseClient(user_token=supabase_token) if supabase_token else None
                if client:
                    result = client.supabase.rpc("is_admin", {"user_uuid": request.user_id}).execute()
                    if result and result.data is not None:
                        if isinstance(result.data, bool):
                            is_user_admin = result.data
                        elif isinstance(result.data, list) and len(result.data) > 0:
                            is_user_admin = bool(result.data[0])
            except Exception as e:
                admin_check_error = str(e)
                logger.debug("Admin check via Supabase client failed: %s", e, exc_info=True)

        if not is_user_admin:
            try:
                response = requests.post(
                    f"{auth_manager.supabase_url}/rest/v1/rpc/is_admin",
                    headers={
                        "apikey": auth_manager.supabase_anon_key,
                        "Authorization": f"Bearer {token}" if token else f"Bearer {auth_manager.supabase_anon_key}",
                        "Content-Type": "application/json",
                    },
                    json={"user_uuid": request.user_id},
                    timeout=10,
                )
                if response.status_code == 200:
                    result = response.json()
                    if isinstance(result, bool):
                        is_user_admin = result
                    elif isinstance(result, list) and len(result) > 0:
                        is_user_admin = bool(result[0])
            except Exception as e:
                admin_check_error = str(e)
                logger.debug("Admin check via HTTP failed: %s", e)

        if not is_user_admin:
            is_user_admin = auth_manager.is_admin(request.user_id)
    except Exception as e:
        admin_check_error = str(e)
        logger.error("Error checking admin status: %s", e, exc_info=True)

    return is_user_admin, admin_check_error


def require_admin(f):
    """Decorator: same session refresh as require_auth, then admin role check."""

    @wraps(f)
    @require_auth
    def decorated_function(*args, **kwargs):
        is_user_admin, admin_check_error = _user_has_admin_access()
        if not is_user_admin:
            error_msg = (
                f"Admin check failed for user_id: {getattr(request, 'user_id', None)}, "
                f"email: {getattr(request, 'user_email', None)}"
            )
            if admin_check_error:
                error_msg += f", error: {admin_check_error}"
            logger.warning(error_msg)
            if request.path.startswith("/api/"):
                return jsonify({"error": "Admin privileges required", "details": admin_check_error}), 403
            return redirect("/auth")
        return f(*args, **kwargs)

    return decorated_function

def is_admin():
    """Check if current user is admin"""
    if not hasattr(request, 'user_id'):
        return False

    # Attempt to perform a robust check similar to require_admin decorator
    try:
        token = (request.cookies.get('auth_token') or
                 request.cookies.get('session_token') or
                 request.headers.get('Authorization', '').replace('Bearer ', ''))

        if token:
            # Try using Supabase client with user's token
            # This is critical because RPC often returns false/error for Anon key
            try:
                from supabase_client import SupabaseClient
                from flask_auth_utils import get_supabase_access_token
                supabase_token = get_supabase_access_token()
                client = SupabaseClient(user_token=supabase_token) if supabase_token else None
                result = client.supabase.rpc('is_admin', {'user_uuid': request.user_id}).execute() if client else None

                if result and result.data is not None:
                    if isinstance(result.data, bool):
                        return result.data
                    elif isinstance(result.data, list) and len(result.data) > 0:
                        return bool(result.data[0])
            except Exception as e:
                logger.debug(f"is_admin helper: Supabase client check failed: {e}")

            # Fallback to HTTP request if client method fails
            # (Though if client failed, this uses Anon key which likely also fails)
            return auth_manager.is_admin(request.user_id)

    except Exception as e:
        logger.error(f"Error in is_admin helper: {e}")

    # Final fallback
    return auth_manager.is_admin(request.user_id)
