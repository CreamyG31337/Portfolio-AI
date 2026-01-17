#!/usr/bin/env python3
"""
Authentication system for portfolio dashboard
Handles user login, registration, and fund access control
"""

import os
import jwt
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify, session, redirect, url_for
import requests
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)

class AuthManager:
    """Handles user authentication and authorization"""
    
    def __init__(self):
        self.supabase_url = os.getenv("SUPABASE_URL")
        self.supabase_anon_key = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
        self.jwt_secret = os.getenv("JWT_SECRET", "your-secret-key-change-this")
        
        # Debug logging
        if not self.supabase_anon_key:
            logger.warning("AuthManager: No Supabase anon key found in environment (checked SUPABASE_PUBLISHABLE_KEY and SUPABASE_ANON_KEY)")
        
    def get_user_funds(self, user_id: str) -> List[str]:
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
    
    def verify_session(self, token: str) -> Optional[dict]:
        """Verify and decode a JWT session token"""
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
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
        # First, try to refresh token if needed
        from flask_auth_utils import refresh_token_if_needed_flask, get_auth_token, is_authenticated_flask
        success, new_token, new_refresh, expires_in = refresh_token_if_needed_flask()
        
        if not success:
            # Token refresh failed or token is invalid
            if request.path.startswith('/api/'):
                return jsonify({"error": "Authentication required"}), 401
            else:
                from flask import redirect
                # Redirect to /auth instead of / to avoid redirect loop
                return redirect('/auth')
        
        # Store new tokens in request context if they were refreshed
        if new_token:
            request._new_auth_token = new_token
            if new_refresh:
                request._new_refresh_token = new_refresh
            if expires_in:
                request._token_expires_in = expires_in
        
        # Check for auth_token (use new token if available, otherwise from cookies)
        token = new_token or (request.cookies.get('auth_token') or 
                              request.cookies.get('session_token') or 
                              request.headers.get('Authorization', '').replace('Bearer ', ''))
        
        if not token:
            # For HTML pages, redirect to login; for API, return JSON error
            if request.path.startswith('/api/'):
                return jsonify({"error": "Authentication required"}), 401
            else:
                from flask import redirect
                # Redirect to /auth instead of / to avoid redirect loop
                return redirect('/auth')
        
        # Try to verify with auth_manager (for session_token format)
        user_data = auth_manager.verify_session(token)
        
        # If that fails, try parsing as JWT (for auth_token format from Streamlit)
        if not user_data:
            try:
                # Check if token is valid by parsing it
                import base64
                import json as json_lib
                token_parts = token.split('.')
                if len(token_parts) >= 2:
                    payload = token_parts[1]
                    payload += '=' * (4 - len(payload) % 4)
                    decoded = base64.urlsafe_b64decode(payload)
                    user_data = json_lib.loads(decoded)
                    # Check expiration
                    import time
                    exp = user_data.get('exp', 0)
                    if exp > 0 and exp < time.time():
                        # Token expired, don't use it
                        user_data = None
                    else:
                        # Convert to format expected by request context
                        user_data = {
                            "user_id": user_data.get("sub"),
                            "email": user_data.get("email")
                        }
            except Exception:
                pass
        
        if not user_data:
            # For HTML pages, redirect to login; for API, return JSON error
            if request.path.startswith('/api/'):
                return jsonify({"error": "Invalid or expired session"}), 401
            else:
                from flask import redirect
                # Redirect to /auth instead of / to avoid redirect loop
                return redirect('/auth')
        
        # Add user data to request context
        request.user_id = user_data.get("user_id") or user_data.get("sub")
        request.user_email = user_data.get("email")
        
        # Execute the route function
        response = f(*args, **kwargs)
        
        # If token was refreshed, update cookies in the response
        if new_token:
            import os
            is_production = os.getenv("FLASK_ENV") == "production"
            response.set_cookie(
                'auth_token',
                new_token,
                max_age=expires_in if expires_in else 3600,
                httponly=True,
                secure=is_production,
                samesite='None' if is_production else 'Lax'
            )
            if new_refresh:
                response.set_cookie(
                    'refresh_token',
                    new_refresh,
                    max_age=86400 * 30,  # 30 days
                    httponly=True,
                    secure=is_production,
                    samesite='None' if is_production else 'Lax'
                )
        
        return response
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

def require_admin(f):
    """Decorator to require admin privileges (also requires authentication)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # First, authenticate the user (similar to require_auth)
        token = (request.cookies.get('auth_token') or 
                 request.cookies.get('session_token') or 
                 request.headers.get('Authorization', '').replace('Bearer ', ''))
        
        if not token:
            # For HTML pages, redirect to login; for API, return JSON error
            if request.path.startswith('/api/'):
                return jsonify({"error": "Authentication required"}), 401
            else:
                from flask import redirect
                # Redirect to /auth instead of / to avoid redirect loop
                return redirect('/auth')
        
        # Try to verify with auth_manager (for session_token format)
        user_data = auth_manager.verify_session(token)
        
        # If that fails, try parsing as JWT (for auth_token format from Streamlit)
        if not user_data:
            try:
                from flask_auth_utils import is_authenticated_flask
                if is_authenticated_flask():
                    # Extract user data from token
                    import base64
                    import json as json_lib
                    token_parts = token.split('.')
                    if len(token_parts) >= 2:
                        payload = token_parts[1]
                        payload += '=' * (4 - len(payload) % 4)
                        decoded = base64.urlsafe_b64decode(payload)
                        user_data = json_lib.loads(decoded)
                        # Convert to format expected by request context
                        user_data = {
                            "user_id": user_data.get("sub"),
                            "email": user_data.get("email")
                        }
            except Exception:
                pass
        
        if not user_data:
            # For HTML pages, redirect to login; for API, return JSON error
            if request.path.startswith('/api/'):
                return jsonify({"error": "Invalid or expired session"}), 401
            else:
                from flask import redirect
                # Redirect to /auth instead of / to avoid redirect loop
                return redirect('/auth')
        
        # Add user data to request context
        request.user_id = user_data.get("user_id") or user_data.get("sub")
        request.user_email = user_data.get("email")
        
        # Now check admin status - try using Supabase client (like Streamlit does)
        is_user_admin = False
        admin_check_error = None
        try:
            # Try using Supabase client with user's token (same approach as Streamlit)
            if token and len(token.split('.')) == 3:
                try:
                    from supabase_client import SupabaseClient
                    from flask_auth_utils import get_refresh_token
                    # Create Supabase client with user token (handles auth header properly)
                    refresh_token = get_refresh_token()
                    client = SupabaseClient(user_token=token)
                    # Call RPC function (same way Streamlit does it)
                    result = client.supabase.rpc('is_admin', {'user_uuid': request.user_id}).execute()
                    
                    logger.debug(f"Admin check RPC result: {result.data}, type: {type(result.data)}")
                    
                    if result.data is not None:
                        if isinstance(result.data, bool):
                            is_user_admin = result.data
                        elif isinstance(result.data, list) and len(result.data) > 0:
                            is_user_admin = bool(result.data[0])
                        else:
                            logger.warning(f"Unexpected is_admin response format: {result.data} (type: {type(result.data)})")
                except Exception as e:
                    admin_check_error = str(e)
                    logger.debug(f"Error checking admin with Supabase client: {e}", exc_info=True)
            
            # Fallback to HTTP request method
            if not is_user_admin:
                logger.debug(f"Trying HTTP request admin check for user_id: {request.user_id}")
                try:
                    import requests
                    response = requests.post(
                        f"{auth_manager.supabase_url}/rest/v1/rpc/is_admin",
                        headers={
                            "apikey": auth_manager.supabase_anon_key,
                            "Authorization": f"Bearer {token}" if token else f"Bearer {auth_manager.supabase_anon_key}",
                            "Content-Type": "application/json"
                        },
                        json={"user_uuid": request.user_id}
                    )
                    
                    logger.debug(f"Admin check HTTP response: status={response.status_code}, body={response.text[:200]}")
                    
                    if response.status_code == 200:
                        result = response.json()
                        if isinstance(result, bool):
                            is_user_admin = result
                        elif isinstance(result, list) and len(result) > 0:
                            is_user_admin = bool(result[0])
                except Exception as e:
                    admin_check_error = str(e)
                    logger.debug(f"Error checking admin with HTTP request: {e}")
            
            # Final fallback to auth_manager method
            if not is_user_admin:
                logger.debug(f"Trying final fallback admin check for user_id: {request.user_id}")
                is_user_admin = auth_manager.is_admin(request.user_id)
                logger.debug(f"Final fallback admin check result: {is_user_admin}")
        except Exception as e:
            admin_check_error = str(e)
            logger.error(f"Error checking admin status: {e}", exc_info=True)
        
        if not is_user_admin:
            error_msg = f"Admin check failed for user_id: {request.user_id}, email: {request.user_email}"
            if admin_check_error:
                error_msg += f", error: {admin_check_error}"
            logger.warning(error_msg)
            if request.path.startswith('/api/'):
                return jsonify({"error": "Admin privileges required", "details": admin_check_error}), 403
            else:
                from flask import redirect
                # Redirect to /auth instead of / to avoid redirect loop
                return redirect('/auth')
        
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
                from flask_auth_utils import get_refresh_token
                refresh_token = get_refresh_token()
                client = SupabaseClient(user_token=token)
                result = client.supabase.rpc('is_admin', {'user_uuid': request.user_id}).execute()
                
                if result.data is not None:
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
