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
from typing import Optional, Dict
from flask import request

logger = logging.getLogger(__name__)


def get_auth_token() -> Optional[str]:
    """Get auth_token or session_token from cookies"""
    return request.cookies.get('auth_token') or request.cookies.get('session_token')


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


def refresh_token_if_needed_flask() -> tuple[bool, Optional[str], Optional[str], Optional[int]]:
    """Check if token is expired or about to expire, and refresh it if needed (Flask context).
    
    This function automatically refreshes the access token when it's about to expire
    (within 5 minutes), keeping users logged in during active sessions.
    
    Returns:
        Tuple of (success, new_access_token, new_refresh_token, expires_in)
        - success: True if token is valid or was refreshed, False if expired/invalid
        - new_access_token: New access token if refreshed, None otherwise
        - new_refresh_token: New refresh token if refreshed, None otherwise
        - expires_in: Expiration time in seconds if refreshed, None otherwise
    """
    token = get_auth_token()
    if not token:
        return (False, None, None, None)
    
    refresh_token = get_refresh_token()
    
    try:
        import time
        import os
        import requests
        
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
                try:
                    supabase_url = os.getenv("SUPABASE_URL")
                    supabase_key = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
                    
                    if supabase_url and supabase_key:
                        response = requests.post(
                            f"{supabase_url}/auth/v1/token?grant_type=refresh_token",
                            headers={
                                "apikey": supabase_key,
                                "Content-Type": "application/json"
                            },
                            json={"refresh_token": refresh_token},
                            timeout=10
                        )
                        
                        if response.status_code == 200:
                            auth_data = response.json()
                            new_access_token = auth_data.get("access_token")
                            new_refresh_token = auth_data.get("refresh_token")
                            expires_in = auth_data.get("expires_in", 3600)
                            
                            if new_access_token:
                                logger.info("[FLASK_AUTH] Token refreshed successfully")
                                return (True, new_access_token, new_refresh_token, expires_in)
                except Exception as e:
                    logger.warning(f"[FLASK_AUTH] Token refresh failed: {e}")
                    return (False, None, None, None)
            else:
                # No refresh token available
                logger.debug("[FLASK_AUTH] Token expired and no refresh token available")
                return (False, None, None, None)
        
        # Token is valid - check if we should refresh it proactively
        # Only refresh if token is expiring soon (within 5 minutes)
        if time_until_expiry is not None and 0 < time_until_expiry <= 300 and refresh_token:
            try:
                supabase_url = os.getenv("SUPABASE_URL")
                supabase_key = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
                
                if supabase_url and supabase_key:
                    response = requests.post(
                        f"{supabase_url}/auth/v1/token?grant_type=refresh_token",
                        headers={
                            "apikey": supabase_key,
                            "Content-Type": "application/json"
                        },
                        json={"refresh_token": refresh_token},
                        timeout=10
                    )
                    
                    if response.status_code == 200:
                        auth_data = response.json()
                        new_access_token = auth_data.get("access_token")
                        new_refresh_token = auth_data.get("refresh_token")
                        expires_in = auth_data.get("expires_in", 3600)
                        
                        if new_access_token:
                            logger.debug("[FLASK_AUTH] Token refreshed proactively")
                            return (True, new_access_token, new_refresh_token, expires_in)
            except Exception as e:
                logger.debug(f"[FLASK_AUTH] Proactive token refresh failed: {e}")
                # Continue with existing token if refresh fails
        
        # Token is valid and doesn't need refresh
        return (True, None, None, None)
    except Exception as e:
        logger.warning(f"[FLASK_AUTH] Error validating/refreshing token: {e}")
        return (False, None, None, None)


def is_authenticated_flask() -> bool:
    """Check if user is authenticated (Flask context)
    
    This function first attempts to refresh the token if needed, then checks authentication.
    """
    # Try to refresh token first if needed
    success, new_token, new_refresh, expires_in = refresh_token_if_needed_flask()
    if not success:
        return False
    
    # Store new tokens in request context if they were refreshed
    if new_token:
        request._new_auth_token = new_token
        if new_refresh:
            request._new_refresh_token = new_refresh
        if expires_in:
            request._token_expires_in = expires_in
    
    # Now check if we have a valid token (use new token if available)
    token = new_token or get_auth_token()
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