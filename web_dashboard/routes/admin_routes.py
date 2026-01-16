#!/usr/bin/env python3
"""
Admin Routes
============

Flask routes for admin user management, contributors, and contributor access.
Migrated from app.py to follow the blueprint pattern.
"""

from flask import Blueprint, render_template, request, jsonify
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# Add parent directory to path to allow importing from root
sys.path.append(str(Path(__file__).parent.parent))

from auth import require_admin
from supabase_client import SupabaseClient
from flask_cache_utils import cache_data
import time
from datetime import datetime
import json
from datetime import datetime, timedelta
# Scheduler imports
try:
    from scheduler import (
        get_scheduler, 
        get_all_jobs_status, 
        run_job_now, 
        pause_job, 
        resume_job,
        start_scheduler,
        is_scheduler_running
    )
    from scheduler.jobs import AVAILABLE_JOBS
except ImportError:
    # Handle case where scheduler module is not available
    AVAILABLE_JOBS = {}
    def get_all_jobs_status(): return []
    def is_scheduler_running(): return False



# Trade Entry Imports
try:
    from utils.email_trade_parser import EmailTradeParser
    from portfolio.trade_processor import TradeProcessor
    from data.repositories.repository_factory import RepositoryFactory
    from data.models.trade import Trade as TradeModel
    from data.repositories.supabase_repository import SupabaseRepository
    from web_dashboard.utils.background_rebuild import trigger_background_rebuild
except ImportError:
    pass

# AI Settings Imports
try:
    from ollama_client import check_ollama_health, get_ollama_client
    from admin_utils import get_postgres_status_cached
except ImportError:
    pass

logger = logging.getLogger(__name__)

# Helper function for FIFO P&L calculation
def calculate_fifo_pnl(fund: str, ticker: str, sell_shares: float, sell_price: float, existing_trades: list = None) -> float:
    """Calculate P&L for a sell using FIFO method.
    
    Args:
        fund: Fund name
        ticker: Ticker symbol
        sell_shares: Number of shares being sold
        sell_price: Price per share for the sell
        existing_trades: Optional list of trade dicts. If not provided, will be fetched from DB.
        
    Returns:
        Calculated P&L as float. Returns 0.0 if calculation fails.
    """
    try:
        from collections import deque
        from decimal import Decimal
        from app import get_supabase_client
        import re
        
        has_action_column = False

        if existing_trades is None:
            # Fetch existing trades - try to get action column if available
            client = get_supabase_client()
            # First try with action column
            try:
                result = client.supabase.table("trade_log") \
                    .select("shares, price, reason, action") \
                    .eq("fund", fund) \
                    .eq("ticker", ticker) \
                    .order("date") \
                    .execute()
                existing_trades = result.data or []
                has_action_column = True
            except Exception:
                # Fallback if action column doesn't exist
                result = client.supabase.table("trade_log") \
                    .select("shares, price, reason") \
                    .eq("fund", fund) \
                    .eq("ticker", ticker) \
                    .order("date") \
                    .execute()
                existing_trades = result.data or []
                has_action_column = False
        else:
            # Check if provided trades have action column
            if existing_trades and len(existing_trades) > 0 and 'action' in existing_trades[0]:
                has_action_column = True
        
        # Build FIFO queue
        lots = deque()
        for t in existing_trades:
            # Determine if this is a BUY or SELL
            trade_action = None
            
            if has_action_column and t.get('action'):
                # Use action column if available
                trade_action = str(t.get('action', '')).upper()
            else:
                # Fallback to improved string matching with regex
                reason_text = str(t.get('reason', ''))
                # Use regex to find BUY or SELL as whole words (case-insensitive)
                buy_match = re.search(r'\bBUY\b', reason_text, re.IGNORECASE)
                sell_match = re.search(r'\bSELL\b', reason_text, re.IGNORECASE)
                
                if buy_match and not sell_match:
                    trade_action = 'BUY'
                elif sell_match and not buy_match:
                    trade_action = 'SELL'
                elif buy_match and sell_match:
                    # Ambiguous - log warning and default to BUY
                    logger.warning(f"Ambiguous trade action in reason field: {reason_text}. Defaulting to BUY.")
                    trade_action = 'BUY'
                else:
                    # No clear action found - default to BUY (assume purchases)
                    # Don't log for every trade to avoid spam, but this is a potential issue
                    trade_action = 'BUY'
            
            if trade_action == 'BUY':
                lots.append((Decimal(str(t['shares'])), Decimal(str(t['price']))))
            elif trade_action == 'SELL':
                rem = Decimal(str(t['shares']))
                while rem > 0 and lots:
                    l_shares, l_price = lots[0]
                    if l_shares <= rem:
                        rem -= l_shares
                        lots.popleft()
                    else:
                        lots[0] = (l_shares - rem, l_price)
                        rem = Decimal('0')
        
        # Calculate cost for this sell
        sell_shares_decimal = Decimal(str(sell_shares))
        total_cost = Decimal('0')
        remaining_sell = sell_shares_decimal
        
        while remaining_sell > 0 and lots:
            l_shares, l_price = lots[0]
            if l_shares <= remaining_sell:
                total_cost += l_shares * l_price
                remaining_sell -= l_shares
                lots.popleft()
            else:
                total_cost += remaining_sell * l_price
                lots[0] = (l_shares - remaining_sell, l_price)
                remaining_sell = Decimal('0')
        
        proceeds = Decimal(str(sell_shares * sell_price))
        pnl = float(proceeds - total_cost)
        return pnl
    except Exception as e:
        logger.error(f"FIFO P&L Calc Error: {e}", exc_info=True)
        return 0.0

# Cached log helper
@cache_data(ttl=5)
def _get_cached_application_logs(level_filter, search, exclude_modules, since_deployment=False):
    """Get application logs with caching (5s TTL for near real-time)"""
    from log_handler import read_logs_from_file
    
    try:
        # Get all filtered logs
        all_logs = read_logs_from_file(
            n=None,
            level=level_filter,
            search=search if search else None,
            return_all=True,
            exclude_modules=exclude_modules if exclude_modules else None,
            since_deployment=since_deployment
        )
        
        # Convert datetime objects to strings for cache compatibility
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
    """Get Ollama log lines with caching"""
    from pathlib import Path
    
    log_file = Path(__file__).parent.parent / 'logs' / 'ollama.log'
    
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

admin_bp = Blueprint('admin', __name__)

# Cached helper functions
@cache_data(ttl=60)
def _get_cached_users_flask():
    """Get all users with their fund assignments (cached for 60s)"""
    try:
        # Use service_role to bypass RLS for admin operations
        client = SupabaseClient(use_service_role=True)
        
        result = client.supabase.rpc('list_users_with_funds').execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Error in _get_cached_users_flask: {e}", exc_info=True)
        return []

@cache_data(ttl=60)
def _get_cached_contributors_flask():
    """Get all contributors (cached for 60s)"""
    try:
        # Use service_role to bypass RLS for admin operations
        client = SupabaseClient(use_service_role=True)
        
        result = client.supabase.table("contributors").select("id, name, email").order("name").execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Error getting contributors: {e}", exc_info=True)
        return []

# Page route
@admin_bp.route('/admin/users')
@require_admin
def users_page():
    """Admin user & access management page (Flask v2)"""
    try:
        from flask_auth_utils import get_user_email_flask
        from user_preferences import get_user_theme
        
        user_email = get_user_email_flask()
        user_theme = get_user_theme() or 'system'
        
        # Get navigation context
        from app import get_navigation_context
        nav_context = get_navigation_context(current_page='admin_users')
        
        logger.debug(f"Rendering users page for user: {user_email}")
        
        return render_template('users.html', 
                             user_email=user_email,
                             user_theme=user_theme,
                             **nav_context)
    except Exception as e:
        logger.error(f"Error rendering users page: {e}", exc_info=True)
        # Fallback with minimal context
        try:
            from app import get_navigation_context
            nav_context = get_navigation_context(current_page='admin_users')
        except Exception:
            # If navigation context also fails, use minimal fallback
            nav_context = {}
        return render_template('users.html', 
                             user_email='Admin',
                             user_theme='system',
                             **nav_context)

# User management routes
@admin_bp.route('/api/admin/users/list')
@require_admin
def api_admin_users_list():
    """Get all users with their fund assignments (for Flask page)"""
    try:
        users = _get_cached_users_flask()
        
        # Get stats
        stats = {
            "total_users": len(users),
            "total_funds": len(set(fund for user in users for fund in (user.get('funds') or []))),
            "total_assignments": sum(len(user.get('funds') or []) for user in users)
        }
        
        return jsonify({"users": users, "stats": stats})
    except Exception as e:
        logger.error(f"Error in api_admin_users_list: {e}", exc_info=True)
        return jsonify({"error": "Failed to load users", "users": [], "stats": {"total_users": 0, "total_funds": 0, "total_assignments": 0}}), 500

@admin_bp.route('/api/admin/users/grant-admin', methods=['POST'])
@require_admin
def api_admin_grant_admin():
    """Grant admin role to a user"""
    try:
        from flask_auth_utils import can_modify_data_flask
        if not can_modify_data_flask():
            return jsonify({"error": "Read-only admin cannot modify user roles"}), 403
        
        data = request.get_json()
        user_email = data.get('user_email')
        
        if not user_email:
            return jsonify({"error": "User email required"}), 400
        
        import requests
        response = requests.post(
            f"{os.getenv('SUPABASE_URL')}/rest/v1/rpc/grant_admin_role",
            headers={
                "apikey": os.getenv("SUPABASE_ANON_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_ANON_KEY')}",
                "Content-Type": "application/json"
            },
            json={"user_email": user_email}
        )
        
        if response.status_code == 200:
            result_data = response.json()
            if isinstance(result_data, list) and len(result_data) > 0:
                result_data = result_data[0]
            
            if result_data and result_data.get('success'):
                # Clear cache
                _get_cached_users_flask.clear_all_cache()
                return jsonify(result_data), 200
            else:
                return jsonify(result_data or {"error": "Failed to grant admin role"}), 400
        else:
            error_msg = response.json().get('message', 'Failed to grant admin role') if response.text else 'Failed to grant admin role'
            return jsonify({"error": error_msg}), 400
    except Exception as e:
        logger.error(f"Error granting admin role: {e}", exc_info=True)
        return jsonify({"error": "Failed to grant admin role"}), 500

@admin_bp.route('/api/admin/users/revoke-admin', methods=['POST'])
@require_admin
def api_admin_revoke_admin():
    """Revoke admin role from a user"""
    try:
        from flask_auth_utils import can_modify_data_flask
        if not can_modify_data_flask():
            return jsonify({"error": "Read-only admin cannot modify user roles"}), 403
        
        data = request.get_json()
        user_email = data.get('user_email')
        
        if not user_email:
            return jsonify({"error": "User email required"}), 400
        
        import requests
        response = requests.post(
            f"{os.getenv('SUPABASE_URL')}/rest/v1/rpc/revoke_admin_role",
            headers={
                "apikey": os.getenv("SUPABASE_ANON_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_ANON_KEY')}",
                "Content-Type": "application/json"
            },
            json={"user_email": user_email}
        )
        
        if response.status_code == 200:
            result_data = response.json()
            if isinstance(result_data, list) and len(result_data) > 0:
                result_data = result_data[0]
            
            if result_data and result_data.get('success'):
                # Clear cache
                _get_cached_users_flask.clear_all_cache()
                return jsonify(result_data), 200
            else:
                return jsonify(result_data or {"error": "Failed to revoke admin role"}), 400
        else:
            error_msg = response.json().get('message', 'Failed to revoke admin role') if response.text else 'Failed to revoke admin role'
            return jsonify({"error": error_msg}), 400
    except Exception as e:
        logger.error(f"Error revoking admin role: {e}", exc_info=True)
        return jsonify({"error": "Failed to revoke admin role"}), 500

@admin_bp.route('/api/admin/users/delete', methods=['POST'])
@require_admin
def api_admin_delete_user():
    """Delete a user safely"""
    try:
        from flask_auth_utils import can_modify_data_flask
        if not can_modify_data_flask():
            return jsonify({"error": "Read-only admin cannot delete users"}), 403
        
        data = request.get_json()
        user_email = data.get('user_email')
        
        if not user_email:
            return jsonify({"error": "User email required"}), 400
        
        import requests
        response = requests.post(
            f"{os.getenv('SUPABASE_URL')}/rest/v1/rpc/delete_user_safe",
            headers={
                "apikey": os.getenv("SUPABASE_ANON_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_ANON_KEY')}",
                "Content-Type": "application/json"
            },
            json={"user_email": user_email}
        )
        
        if response.status_code == 200:
            result_data = response.json()
            if result_data and result_data.get('success'):
                # Clear cache
                _get_cached_users_flask.clear_all_cache()
                return jsonify(result_data), 200
            else:
                return jsonify(result_data or {"error": "Failed to delete user"}), 400
        else:
            error_msg = response.json().get('message', 'Failed to delete user') if response.text else 'Failed to delete user'
            return jsonify({"error": error_msg}), 400
    except Exception as e:
        logger.error(f"Error deleting user: {e}", exc_info=True)
        return jsonify({"error": "Failed to delete user"}), 500

@admin_bp.route('/api/admin/users/send-invite', methods=['POST'])
@require_admin
def api_admin_send_invite():
    """Send magic link invite to a user"""
    try:
        from flask_auth_utils import can_modify_data_flask, get_user_email_flask
        data = request.get_json()
        user_email = data.get('user_email')
        
        if not user_email:
            return jsonify({"error": "User email required"}), 400
        
        # Allow readonly_admin to send invite to themselves
        current_email = get_user_email_flask()
        can_send = can_modify_data_flask() or (user_email == current_email)
        
        if not can_send:
            return jsonify({"error": "Read-only admin can only send invites to themselves"}), 403
        
        # Use Supabase client to send magic link
        from supabase import create_client
        supabase_url = os.getenv("SUPABASE_URL")
        publishable_key = os.getenv("SUPABASE_PUBLISHABLE_KEY")
        
        if not supabase_url or not publishable_key:
            return jsonify({"error": "Supabase configuration missing"}), 500
        
        app_domain = os.getenv("APP_DOMAIN")
        if not app_domain:
            return jsonify({"error": "APP_DOMAIN environment variable is required"}), 500
        
        redirect_url = os.getenv("MAGIC_LINK_REDIRECT_URL", f"https://{app_domain}/auth_callback.html")
        
        supabase = create_client(supabase_url, publishable_key)
        response = supabase.auth.sign_in_with_otp({
            "email": user_email,
            "options": {
                "email_redirect_to": redirect_url
            }
        })
        
        if response:
            return jsonify({"success": True, "message": "Invite sent to your email"}), 200
        else:
            return jsonify({"error": "Failed to send invite"}), 500
    except Exception as e:
        logger.error(f"Error sending invite: {e}", exc_info=True)
        return jsonify({"error": f"Failed to send invite: {str(e)}"}), 500

@admin_bp.route('/api/admin/users/update-contributor-email', methods=['POST'])
@require_admin
def api_admin_update_contributor_email():
    """Update contributor email address"""
    try:
        from flask_auth_utils import can_modify_data_flask
        if not can_modify_data_flask():
            return jsonify({"error": "Read-only admin cannot update contributor emails"}), 403
        
        data = request.get_json()
        contributor_name = data.get('contributor_name')
        contributor_id = data.get('contributor_id')
        contributor_type = data.get('contributor_type')  # 'contributor', 'fund_contribution', 'user'
        new_email = data.get('new_email')
        
        if not new_email:
            return jsonify({"error": "New email address required"}), 400
        
        # Validate email format
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, new_email):
            return jsonify({"error": "Invalid email format"}), 400
        
        from app import get_supabase_client
        client = get_supabase_client()
        if not client:
            return jsonify({"error": "Failed to connect to database"}), 500
        
        updates_made = []
        
        # Update based on type
        if contributor_type == 'contributor' and contributor_id:
            try:
                client.supabase.table("contributors").update(
                    {"email": new_email}
                ).eq("id", contributor_id).execute()
                updates_made.append("contributors table")
            except Exception as e:
                logger.warning(f"Could not update contributors table: {e}")
        
        # Always update fund_contributions for this contributor name
        try:
            client.supabase.table("fund_contributions").update(
                {"email": new_email}
            ).eq("contributor", contributor_name).execute()
            updates_made.append("fund_contributions records")
        except Exception as e:
            logger.warning(f"Could not update fund_contributions: {e}")
        
        # If it's a registered user, also update auth
        if contributor_type == 'user' and contributor_id:
            try:
                from supabase import create_client
                supabase_url = os.getenv("SUPABASE_URL")
                service_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
                
                if supabase_url and service_key:
                    admin_client = create_client(supabase_url, service_key)
                    
                    # Check if email already exists
                    users_response = admin_client.auth.admin.list_users()
                    users_list = users_response if isinstance(users_response, list) else getattr(users_response, 'users', [])
                    
                    email_exists = False
                    for u in users_list:
                        check_email = u.email if hasattr(u, 'email') else u.get('email') if isinstance(u, dict) else None
                        if check_email and check_email.lower() == new_email.lower():
                            check_id = u.id if hasattr(u, 'id') else u.get('id') if isinstance(u, dict) else None
                            if str(check_id) != str(contributor_id):
                                email_exists = True
                                break
                    
                    if email_exists:
                        return jsonify({"error": f"Email {new_email} is already in use by another user"}), 400
                    
                    # Update email in auth.users
                    update_response = admin_client.auth.admin.update_user_by_id(
                        contributor_id,
                        {"email": new_email}
                    )
                    
                    if update_response and update_response.user:
                        updates_made.append("auth.users")
                        
                        # Also update email in user_profiles table
                        try:
                            client.supabase.table("user_profiles").update(
                                {"email": new_email}
                            ).eq("user_id", contributor_id).execute()
                            updates_made.append("user_profiles")
                        except Exception as profile_error:
                            logger.warning(f"Could not update user_profiles: {profile_error}")
                    else:
                        return jsonify({"error": "Failed to update email in auth.users"}), 500
            except Exception as auth_error:
                logger.warning(f"Could not update auth.users: {auth_error}")
        
        if updates_made:
            # Clear caches
            _get_cached_users_flask.clear_all_cache()
            _get_cached_contributors_flask.clear_all_cache()
            return jsonify({
                "success": True,
                "message": f"Email updated in: {', '.join(updates_made)}",
                "updates_made": updates_made
            }), 200
        else:
            return jsonify({"error": "No updates were made"}), 400
    except Exception as e:
        logger.error(f"Error updating contributor email: {e}", exc_info=True)
        return jsonify({"error": f"Failed to update email: {str(e)}"}), 500

# Contributor routes
@admin_bp.route('/api/admin/contributors')
@require_admin
def api_admin_contributors():
    """Get all contributors"""
    try:
        contributors = _get_cached_contributors_flask()
        return jsonify({"contributors": contributors})
    except Exception as e:
        logger.error(f"Error getting contributors: {e}", exc_info=True)
        return jsonify({"error": "Failed to load contributors", "contributors": []}), 500

@admin_bp.route('/api/admin/contributors/unregistered')
@require_admin
def api_admin_unregistered_contributors():
    """Get unregistered contributors"""
    try:
        from app import get_supabase_client
        client = get_supabase_client()
        if not client:
            return jsonify({"error": "Failed to connect to database", "contributors": []}), 500
        
        result = client.supabase.rpc('list_unregistered_contributors').execute()
        contributors = result.data if result.data else []
        return jsonify({"contributors": contributors})
    except Exception as e:
        logger.error(f"Error getting unregistered contributors: {e}", exc_info=True)
        # Check if it's a missing table error
        error_str = str(e).lower()
        if "does not exist" in error_str or "relation" in error_str or "42p01" in error_str:
            return jsonify({
                "error": "Contributors table not found. Run migration DF_009 first.",
                "contributors": []
            }), 404
        return jsonify({"error": f"Failed to load unregistered contributors: {str(e)}", "contributors": []}), 500

# Contributor access routes
@admin_bp.route('/api/admin/contributor-access')
@require_admin
def api_admin_contributor_access():
    """Get all contributor access records"""
    try:
        from app import get_supabase_client
        client = get_supabase_client()
        if not client:
            return jsonify({"error": "Failed to connect to database", "access": []}), 500
        
        # Get access records
        access_result = client.supabase.table("contributor_access").select(
            "id, contributor_id, user_id, access_level, granted_at"
        ).execute()
        
        if not access_result.data:
            return jsonify({"access": []})
        
        # Get contributor and user details
        contributors = _get_cached_contributors_flask()
        users = _get_cached_users_flask()
        
        # Optimize lookups by creating dictionaries
        contributors_map = {c['id']: c for c in contributors}
        users_map = {u.get('user_id'): u for u in users if u.get('user_id')}

        access_list = []
        for access in access_result.data:
            # Get contributor details
            contrib = contributors_map.get(access['contributor_id'], {})
            # Get user details
            user = users_map.get(access['user_id'], {})
            
            access_list.append({
                "id": access['id'],
                "contributor": contrib.get('name', 'Unknown'),
                "contributor_email": contrib.get('email', 'No email'),
                "user_email": user.get('email', 'Unknown'),
                "user_name": user.get('full_name', ''),
                "access_level": access.get('access_level', 'viewer'),
                "granted": access.get('granted_at', '')[:10] if access.get('granted_at') else ''
            })
        
        return jsonify({"access": access_list})
    except Exception as e:
        logger.error(f"Error getting contributor access: {e}", exc_info=True)
        error_str = str(e).lower()
        if "does not exist" in error_str or "relation" in error_str or "42p01" in error_str:
            return jsonify({
                "error": "Contributor access table not found. Run migration DF_009 first.",
                "access": []
            }), 404
        return jsonify({"error": f"Failed to load access records: {str(e)}", "access": []}), 500

@admin_bp.route('/api/admin/contributor-access/grant', methods=['POST'])
@require_admin
def api_admin_grant_contributor_access():
    """Grant contributor access to a user"""
    try:
        data = request.get_json()
        contributor_email = data.get('contributor_email')
        user_email = data.get('user_email')
        access_level = data.get('access_level', 'viewer')
        
        if not contributor_email or not user_email:
            return jsonify({"error": "Contributor email and user email required"}), 400
        
        if access_level not in ['viewer', 'manager', 'owner']:
            return jsonify({"error": "Invalid access level. Must be viewer, manager, or owner"}), 400
        
        from app import get_supabase_client
        client = get_supabase_client()
        if not client:
            return jsonify({"error": "Failed to connect to database"}), 500
        
        result = client.supabase.rpc(
            'grant_contributor_access',
            {
                'contributor_email': contributor_email,
                'user_email': user_email,
                'access_level': access_level
            }
        ).execute()
        
        if result.data:
            result_data = result.data[0] if isinstance(result.data, list) else result.data
            if result_data.get('success'):
                # Clear cache
                _get_cached_contributors_flask.clear_all_cache()
                return jsonify(result_data), 200
            else:
                return jsonify(result_data), 400
        else:
            return jsonify({"error": "Failed to grant access"}), 500
    except Exception as e:
        logger.error(f"Error granting contributor access: {e}", exc_info=True)
        return jsonify({"error": f"Failed to grant access: {str(e)}"}), 500

@admin_bp.route('/api/admin/contributor-access/revoke', methods=['POST'])
@require_admin
def api_admin_revoke_contributor_access():
    """Revoke contributor access from a user"""
    try:
        data = request.get_json()
        contributor_email = data.get('contributor_email')
        user_email = data.get('user_email')
        
        if not contributor_email or not user_email:
            return jsonify({"error": "Contributor email and user email required"}), 400
        
        from app import get_supabase_client
        client = get_supabase_client()
        if not client:
            return jsonify({"error": "Failed to connect to database"}), 500
        
        result = client.supabase.rpc(
            'revoke_contributor_access',
            {
                'contributor_email': contributor_email,
                'user_email': user_email
            }
        ).execute()
        
        if result.data:
            result_data = result.data[0] if isinstance(result.data, list) else result.data
            if result_data.get('success'):
                # Clear cache
                _get_cached_contributors_flask.clear_all_cache()
                return jsonify(result_data), 200
            else:
                return jsonify(result_data), 400
        else:
            return jsonify({"error": "Failed to revoke access"}), 500
    except Exception as e:
        logger.error(f"Error revoking contributor access: {e}", exc_info=True)
        return jsonify({"error": f"Failed to revoke access: {str(e)}"}), 500

@admin_bp.route('/admin/system')
@require_admin
def system_page():
    """System Monitoring Page"""
    try:
        from flask_auth_utils import get_user_email_flask
        from user_preferences import get_user_theme
        
        user_email = get_user_email_flask()
        user_theme = get_user_theme() or 'system'
        
        # Get navigation context
        from app import get_navigation_context
        nav_context = get_navigation_context(current_page='admin_system')
        
        return render_template('system.html', 
                             user_email=user_email,
                             user_theme=user_theme,
                             **nav_context)
    except Exception as e:
        logger.error(f"Error rendering system page: {e}", exc_info=True)
        # Fallback with minimal context
        try:
            from app import get_navigation_context
            nav_context = get_navigation_context(current_page='admin_system')
        except Exception:
            # If navigation context also fails, use minimal fallback
            nav_context = {}
        return render_template('system.html', 
                             user_email='Admin',
                             user_theme='system',
                             **nav_context)

@admin_bp.route('/api/admin/system/status')
@require_admin
def api_system_status():
    """Get overall system status"""
    try:
        from admin_utils import get_system_status_cached
        
        # Get cached system stats
        status = get_system_status_cached()
        
        # Get recent job logs
        recent_jobs = []
        try:
            from scheduler.scheduler_core import get_job_logs
            # List of key jobs to monitor
            jobs_to_check = ['exchange_rates', 'portfolio_update', 'social_sentiment']
            
            for job_id in jobs_to_check:
                try:
                    logs = get_job_logs(job_id, limit=1)
                    if logs:
                        log = logs[0]
                        recent_jobs.append({
                            'job_id': job_id,
                            'success': log['success'],
                            'message': log['message'],
                            'timestamp': log['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
                        })
                except Exception:
                    pass
        except ImportError:
            pass
            
        return jsonify({
            "status": status,
            "jobs": recent_jobs
        })
    except Exception as e:
        logger.error(f"Error getting system status: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/logs')
@require_admin
def logs_page():
    """Admin logs viewer page"""
    try:
        from flask_auth_utils import get_user_email_flask
        from user_preferences import get_user_theme
        
        user_email = get_user_email_flask()
        user_theme = get_user_theme() or 'system'
        
        # Get navigation context
        from app import get_navigation_context
        nav_context = get_navigation_context(current_page='admin_logs')
        
        return render_template('logs.html', 
                             user_email=user_email,
                             user_theme=user_theme,
                             **nav_context)
    except Exception as e:
        logger.error(f"Error rendering logs page: {e}", exc_info=True)
        # Fallback with minimal context
        try:
            from app import get_navigation_context
            nav_context = get_navigation_context(current_page='admin_logs')
        except Exception:
            # If navigation context also fails, use minimal fallback
            nav_context = {}
        return render_template('logs.html', 
                             user_email='Admin',
                             user_theme='system',
                             **nav_context)

@admin_bp.route('/api/logs/application')
@require_admin
def api_logs_application():
    """Get application logs"""
    try:
        level = request.args.get('level', 'INFO + ERROR')
        limit = int(request.args.get('limit', 100))
        search = request.args.get('search', '')
        page = int(request.args.get('page', 1))
        since_deployment = request.args.get('since_deployment', 'false').lower() == 'true'
        
        # Handle "INFO + ERROR" logic
        if level == "INFO + ERROR":
            level_filter = ["INFO", "ERROR"]
        elif level == "All":
            level_filter = None
        else:
            level_filter = level
            
        exclude_heartbeat = request.args.get('exclude_heartbeat', 'true').lower() == 'true'
        exclude_modules = ['scheduler.scheduler_core.heartbeat'] if exclude_heartbeat else None
        
        all_logs = _get_cached_application_logs(level_filter, search, exclude_modules, since_deployment)
        
        # Pagination
        total = len(all_logs)
        start = (page - 1) * limit
        end = start + limit
        logs = all_logs[start:end]
        
        return jsonify({
            'logs': logs,
            'total': total,
            'page': page,
            'pages': (total + limit - 1) // limit if total > 0 else 1
        })
    except Exception as e:
        logger.error(f"Error fetching logs: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/logs/ollama')
@require_admin
def api_logs_ollama():
    """Get Ollama logs"""
    try:
        limit = int(request.args.get('limit', 100))
        search = request.args.get('search', '')
        page = int(request.args.get('page', 1))
        
        # Validate inputs
        if limit < 1 or limit > 10000:
            limit = 100
        if page < 1:
            page = 1
        
        all_lines = _get_cached_ollama_log_lines()
        
        # Filter by search if provided
        if search:
            search_lower = search.lower()
            all_lines = [line for line in all_lines if line and search_lower in line.lower()]
        
        # Filter out empty lines
        all_lines = [line for line in all_lines if line and line.strip()]
        
        # Pagination
        total = len(all_lines)
        start = (page - 1) * limit
        end = start + limit
        lines = all_lines[start:end]
        
        # Format logs (Ollama logs may not have structured format)
        logs = []
        for line in lines:
            if line and line.strip():  # Only add non-empty lines
                logs.append({
                    'timestamp': '',  # Ollama logs may not have timestamps
                    'level': 'INFO',
                    'module': 'ollama',
                    'message': line.strip()
                })
        
        pages = (total + limit - 1) // limit if total > 0 else 1
        
        return jsonify({
            'logs': logs,
            'total': total,
            'page': page,
            'pages': pages
        })
    except ValueError as e:
        logger.error(f"Invalid parameter in Ollama logs request: {e}")
        return jsonify({"error": f"Invalid parameter: {str(e)}"}), 400
    except Exception as e:
        logger.error(f"Error fetching Ollama logs: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/system/logs/application')
@require_admin
def api_admin_logs_application():
    """Get application logs (admin endpoint)"""
    try:
        level = request.args.get('level', 'INFO + ERROR')
        limit = int(request.args.get('limit', 100))
        search = request.args.get('search', '')
        page = int(request.args.get('page', 1))
        since_deployment = request.args.get('since_deployment', 'false').lower() == 'true'
        
        # Handle "INFO + ERROR" logic
        if level == "INFO + ERROR":
            level_filter = ["INFO", "ERROR"]
        elif level == "All":
            level_filter = None
        else:
            level_filter = level
            
        exclude_heartbeat = request.args.get('exclude_heartbeat', 'true').lower() == 'true'
        exclude_modules = ['scheduler.scheduler_core.heartbeat'] if exclude_heartbeat else None
        
        all_logs = _get_cached_application_logs(level_filter, search, exclude_modules, since_deployment)
        
        # Pagination
        total = len(all_logs)
        start = (page - 1) * limit
        end = start + limit
        logs = all_logs[start:end]
        
        return jsonify({
            'logs': logs,
            'total': total,
            'page': page,
            'pages': (total + limit - 1) // limit if total > 0 else 1
        })
    except Exception as e:
        logger.error(f"Error fetching logs: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/system/docker/containers')
@require_admin
def api_docker_containers():
    """List running docker containers"""
    if not os.path.exists("/var/run/docker.sock") and os.name != 'nt': # Minimal check
         # On Windows it might be different, typically npipe:////./pipe/docker_engine
         pass 

    try:
        import docker
        client = docker.from_env()
        containers = client.containers.list(all=True)
        
        results = []
        for c in containers:
            results.append({
                'id': c.id,
                'name': c.name,
                'status': c.status,
                'image': c.image.tags[0] if c.image.tags else 'unknown'
            })
            
        # Sort Ollama first
        results.sort(key=lambda x: (0 if 'ollama' in x['name'].lower() else 1, x['name']))
        
        return jsonify({"containers": results})
    except ImportError:
        return jsonify({"error": "Docker python library not installed"}), 500
    except Exception as e:
        logger.warning(f"Docker error: {e}")
        return jsonify({"error": f"Docker error: {str(e)}"}), 500

@admin_bp.route('/api/admin/system/docker/logs/<container_id>')
@require_admin
def api_docker_logs(container_id):
    """Get logs for a specific container"""
    try:
        import docker
        client = docker.from_env()
        container = client.containers.get(container_id)
        
        tail = int(request.args.get('tail', 500))
        logs = container.logs(tail=tail).decode('utf-8', errors='replace')
        
        # Split and reverse (newest first)
        lines = logs.split('\n')
        lines.reverse()
        
        return jsonify({
            "logs": "\n".join(lines[:2000]), # Limit return size
            "name": container.name
        })
    except Exception as e:
        logger.error(f"Error fetching docker logs: {e}")
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/system/files')
@require_admin
def api_list_log_files():
    """List available log files"""
    try:
        log_dir = Path(__file__).parent.parent / 'logs'
        if not log_dir.exists():
             return jsonify({"files": []})
             
        files = []
        for f in log_dir.rglob("*.log"):
             files.append(str(f.relative_to(log_dir)))
        for f in log_dir.rglob("*.txt"):
             files.append(str(f.relative_to(log_dir)))
             
        return jsonify({"files": sorted(files)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/system/deployment-info')
@require_admin
def api_deployment_info():
    """Get deployment information from build_stamp.json"""
    try:
        from log_handler import get_deployment_timestamp
        import os
        
        deployment_timestamp = get_deployment_timestamp()
        
        # Try to read full build stamp
        build_info = {}
        build_stamp_paths = [
            os.path.join(os.path.dirname(__file__), '..', 'build_stamp.json'),
            os.path.join(os.path.dirname(os.path.dirname(__file__)), 'build_stamp.json'),
            os.path.join(os.getcwd(), 'build_stamp.json')
        ]
        
        for build_stamp_path in build_stamp_paths:
            if os.path.exists(build_stamp_path):
                with open(build_stamp_path, 'r') as f:
                    build_info = json.load(f)
                break
        
        return jsonify({
            "deployment_timestamp": deployment_timestamp.isoformat() if deployment_timestamp else None,
            "build_info": build_info
        })
    except Exception as e:
        logger.error(f"[System API] Error getting deployment info: {e}", exc_info=True)
        return jsonify({
            "deployment_timestamp": None,
            "build_info": {},
            "error": str(e)
        }), 500

@admin_bp.route('/api/admin/system/cache/clear', methods=['POST'])
@require_admin
def api_clear_cache():
    """Clear all Flask caches"""
    try:
        from flask_cache_utils import clear_all_caches
        
        clear_all_caches()
        logger.info("[System API] All caches cleared by admin")
        
        return jsonify({
            "success": True,
            "message": "All caches cleared successfully"
        })
    except Exception as e:
        logger.error(f"[System API] Error clearing cache: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

@admin_bp.route('/api/admin/system/cache/bump-version', methods=['POST'])
@require_admin
def api_bump_cache_version():
    """Bump cache version to invalidate all cached functions"""
    try:
        from cache_version import bump_cache_version, get_cache_version
        
        old_version = get_cache_version()
        bump_cache_version()
        new_version = get_cache_version()
        
        logger.info(f"[System API] Cache version bumped by admin: {old_version} -> {new_version}")
        
        return jsonify({
            "success": True,
            "message": "Cache version bumped successfully",
            "cache_version": new_version
        })
    except Exception as e:
        logger.error(f"[System API] Error bumping cache version: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

@admin_bp.route('/api/admin/system/files/content')
@require_admin
def api_read_log_file():
    """Read content of a log file"""
    try:
        filename = request.args.get('filename')
        if not filename:
            return jsonify({"error": "Filename required"}), 400
            
        # Security check - ensure no path traversal
        if '..' in filename or filename.startswith('/'):
             return jsonify({"error": "Invalid filename"}), 400
             
        log_dir = Path(__file__).parent.parent / 'logs'
        file_path = log_dir / filename
        
        if not file_path.exists():
            return jsonify({"error": "File not found"}), 404
            
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            # Read last 2000 lines approx
             lines = f.readlines()
             content = "".join(reversed(lines[-2000:]))
             
        return jsonify({"content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==========================================
# Scheduler Routes
# ==========================================

@admin_bp.route('/admin/scheduler')
@require_admin
def scheduler_page():
    """Scheduler/Jobs Management Page"""
    try:
        logger.info("[Scheduler Page] Rendering scheduler page")
        from flask_auth_utils import get_user_email_flask
        from user_preferences import get_user_theme
        from app import get_navigation_context
        from scheduler.scheduler_core import is_scheduler_running
        
        user_email = get_user_email_flask()
        logger.debug(f"[Scheduler Page] User email: {user_email}")
        user_theme = get_user_theme() or 'system'
        
        # Get navigation context
        logger.debug("[Scheduler Page] Getting navigation context...")
        nav_context = get_navigation_context(current_page='admin_scheduler')
        logger.debug(f"[Scheduler Page] Navigation context keys: {list(nav_context.keys())}")
        
        logger.info("[Scheduler Page] Rendering template...")
        return render_template('jobs.html', 
                             user_email=user_email,
                             user_theme=user_theme,
                             **nav_context)
    except Exception as e:
        logger.error(f"Error rendering scheduler page: {e}", exc_info=True)
        # Fallback with minimal context
        try:
            from app import get_navigation_context
            nav_context = get_navigation_context(current_page='admin_scheduler')
        except Exception:
            # If navigation context also fails, use minimal fallback
            nav_context = {}
        # Get scheduler status for menu badge (fallback)
        try:
            from scheduler.scheduler_core import is_scheduler_running
            scheduler_running = is_scheduler_running()
            scheduler_status = 'running' if scheduler_running else 'stopped'
        except Exception:
            scheduler_status = 'stopped'
        
        # Ensure scheduler_status is in nav_context for fallback
        nav_context['scheduler_status'] = scheduler_status
        return render_template('jobs.html', 
                             user_email='Admin',
                             user_theme='system',
                             **nav_context)

@admin_bp.route('/api/admin/scheduler/status')
@require_admin
def api_scheduler_status():
    """Get global scheduler status and jobs list"""
    try:
        logger.info("[Scheduler API] /api/admin/scheduler/status called")
        start_time = time.time()
        
        running = is_scheduler_running()
        logger.debug(f"[Scheduler API] Scheduler running: {running}")
        
        # Get jobs list (even if scheduler is stopped, we want to show available jobs)
        jobs = []
        try:
            logger.info(f"[Scheduler API] Calling get_all_jobs_status()...")
            jobs = get_all_jobs_status()
            logger.info(f"[Scheduler API] get_all_jobs_status() returned {len(jobs)} jobs")
            if jobs:
                logger.info(f"[Scheduler API] Job IDs returned: {[j.get('id', 'NO_ID') for j in jobs[:5]]}")
                # Log trigger info for first few jobs to verify extraction
                for job in jobs[:3]:
                    logger.info(f"[Scheduler API] Job {job.get('id')}: trigger={job.get('trigger')}, name={job.get('name')}")
        except Exception as jobs_error:
            logger.error(f"[Scheduler API] Exception calling get_all_jobs_status(): {jobs_error}", exc_info=True)
            jobs = []
        
        # Safety fallback: If get_all_jobs_status() returns empty, fall back to AVAILABLE_JOBS
        # This should rarely be needed since get_all_jobs_status_batched() handles it, but keep as safety net
        if not jobs:
            logger.warning(f"[Scheduler API] No jobs returned from get_all_jobs_status(). Using safety fallback to AVAILABLE_JOBS...")
            try:
                from scheduler.jobs import AVAILABLE_JOBS
                logger.info(f"[Scheduler API] AVAILABLE_JOBS has {len(AVAILABLE_JOBS)} job definitions")
                
                if AVAILABLE_JOBS:
                    # Extract trigger info properly (same logic as scheduler_core.py)
                    jobs = []
                    for job_id, config in AVAILABLE_JOBS.items():
                        # Extract trigger from config
                        trigger_desc = 'Manual'
                        if 'cron_triggers' in config and config['cron_triggers']:
                            cron_config = config['cron_triggers'][0]
                            hour = cron_config.get('hour', '*')
                            minute = cron_config.get('minute', 0)
                            timezone = cron_config.get('timezone', '')
                            if isinstance(hour, int) and isinstance(minute, int):
                                trigger_desc = f"At {hour:02d}:{minute:02d}"
                                if timezone:
                                    trigger_desc += f" ({timezone})"
                            else:
                                trigger_desc = "Cron schedule"
                        elif config.get('default_interval_minutes', 0) > 0:
                            interval_mins = config['default_interval_minutes']
                            if interval_mins < 60:
                                trigger_desc = f"Every {interval_mins} minute{'s' if interval_mins != 1 else ''}"
                            elif interval_mins < 1440:
                                hours = interval_mins // 60
                                trigger_desc = f"Every {hours} hour{'s' if hours != 1 else ''}"
                            else:
                                days = interval_mins // 1440
                                trigger_desc = f"Every {days} day{'s' if days != 1 else ''}"
                        
                        jobs.append({
                            'id': job_id,
                            'name': config.get('name', job_id),
                            'next_run': None,
                            'is_paused': True,
                            'trigger': trigger_desc,
                            'is_running': False,
                            'running_since': None,
                            'last_error': None,
                            'recent_logs': []
                        })
                    logger.info(f"[Scheduler API] Created {len(jobs)} job statuses from AVAILABLE_JOBS safety fallback")
                else:
                    logger.error("[Scheduler API] AVAILABLE_JOBS is empty! This is a critical error.")
            except Exception as avail_error:
                logger.error(f"[Scheduler API] Error in safety fallback: {avail_error}", exc_info=True)
        
        # Serialize datetime objects
        for job in jobs:
            for key, value in job.items():
                if isinstance(value, datetime):
                    job[key] = value.isoformat()
            
            # Helper for logs
            if 'recent_logs' in job:
                for log in job['recent_logs']:
                    if isinstance(log.get('timestamp'), datetime):
                        log['timestamp'] = log['timestamp'].isoformat()
        
        processing_time = time.time() - start_time
        logger.info(f"[Scheduler API] Status response prepared - running={running}, jobs={len(jobs)}, time={processing_time:.3f}s")
        
        return jsonify({
            "success": True, 
            "scheduler_running": running,
            "running": running,  # Keep for backward compatibility
            "jobs": jobs,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"[Scheduler API] Error getting scheduler status: {e}", exc_info=True)
        return jsonify({"error": str(e), "scheduler_running": False, "jobs": []}), 500

@admin_bp.route('/api/admin/scheduler/start', methods=['POST'])
@require_admin
def api_scheduler_start():
    """Start the scheduler"""
    try:
        from flask_auth_utils import can_modify_data_flask
        if not can_modify_data_flask():
            return jsonify({"error": "Read-only admin cannot control scheduler"}), 403
            
        if is_scheduler_running():
            return jsonify({"success": True, "message": "Scheduler is already running"})
            
        success = start_scheduler()
        if success:
            return jsonify({"success": True, "message": "Scheduler started successfully"})
        else:
            return jsonify({"error": "Failed to start scheduler"}), 500
    except Exception as e:
        logger.error(f"Error starting scheduler: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/scheduler/jobs')
@require_admin
def api_scheduler_jobs_list():
    """Get all jobs status"""
    try:
        jobs = get_all_jobs_status()
        
        # Serialize datetime objects
        for job in jobs:
            for key, value in job.items():
                if isinstance(value, datetime):
                    job[key] = value.isoformat()
            
            # Helper for logs
            if 'recent_logs' in job:
                for log in job['recent_logs']:
                    if isinstance(log.get('timestamp'), datetime):
                        log['timestamp'] = log['timestamp'].isoformat()
        
        return jsonify({"jobs": jobs})
    except Exception as e:
        logger.error(f"Error getting jobs list: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/scheduler/jobs/<job_id>/params')
@require_admin
def api_job_params(job_id):
    """Get parameters for a specific job"""
    try:
        # Find job definition
        # Try exact match first
        job_def = AVAILABLE_JOBS.get(job_id)
        
        # If not found, try to match base ID (remove suffixes like _close, _open from actual ID)
        if not job_def:
            base_id = job_id
            for suffix in ['_close', '_open', '_premarket', '_midmorning', '_powerhour', '_postmarket', '_refresh', '_populate', '_collect', '_scan', '_fetch', '_cleanup', '_scrape']:
                if job_id.endswith(suffix):
                    base_id = job_id[:-len(suffix)]
                    break
            job_def = AVAILABLE_JOBS.get(base_id)
        
        if not job_def:
            return jsonify({"params": {}})
            
        params = job_def.get('parameters', {})
        return jsonify({"params": params})
    except Exception as e:
        logger.error(f"Error getting job params: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/scheduler/jobs/<job_id>/run', methods=['POST'])
@require_admin
def api_run_job(job_id):
    """Run a job manually"""
    try:
        from flask_auth_utils import can_modify_data_flask
        if not can_modify_data_flask():
            return jsonify({"error": "Read-only admin cannot run jobs"}), 403
        
        # Check if scheduler is running
        if not is_scheduler_running():
            return jsonify({"error": "Scheduler is not running. Please start the scheduler first."}), 400
            
        params = request.get_json() or {}
        
        # Convert date strings to date objects if needed
        from datetime import date
        processed_params = {}
        for k, v in params.items():
            if k.endswith('_date') and isinstance(v, str):
                try:
                    processed_params[k] = datetime.fromisoformat(v).date()
                except ValueError:
                    processed_params[k] = v
            else:
                processed_params[k] = v
                
        success = run_job_now(job_id, **processed_params)
        
        if success:
            return jsonify({"success": True, "message": "Job started successfully"})
        else:
            # Check if job exists
            try:
                scheduler = get_scheduler(create=False)
                if scheduler:
                    job = scheduler.get_job(job_id)
                    if not job:
                        return jsonify({"error": f"Job '{job_id}' not found. It may not be registered or may have been removed."}), 404
                    if not job.func:
                        return jsonify({"error": f"Job '{job_id}' has no function attached. This is a configuration error."}), 500
            except Exception as check_error:
                logger.warning(f"Error checking job status: {check_error}")
            
            return jsonify({"error": "Failed to start job. Check server logs for details."}), 500
    except Exception as e:
        logger.error(f"Error running job {job_id}: {e}", exc_info=True)
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@admin_bp.route('/api/admin/scheduler/jobs/<job_id>/pause', methods=['POST'])
@require_admin
def api_pause_job(job_id):
    """Pause a job"""
    try:
        from flask_auth_utils import can_modify_data_flask
        if not can_modify_data_flask():
            return jsonify({"error": "Read-only admin cannot modify jobs"}), 403
            
        pause_job(job_id)
        return jsonify({"success": True, "message": "Job paused"})
    except Exception as e:
        logger.error(f"Error pausing job: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/scheduler/jobs/<job_id>/resume', methods=['POST'])
@require_admin
def api_resume_job(job_id):
    """Resume a job"""
    try:
        from flask_auth_utils import can_modify_data_flask
        if not can_modify_data_flask():
            return jsonify({"error": "Read-only admin cannot modify jobs"}), 403
            
        resume_job(job_id)
        return jsonify({"success": True, "message": "Job resumed"})
    except Exception as e:
        logger.error(f"Error resuming job: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ==========================================
# Trade Entry Routes
# ==========================================

@admin_bp.route('/admin/trade-entry')
@require_admin
def trade_entry_page():
    """Trade Entry Page"""
    try:
        from flask_auth_utils import get_user_email_flask
        from user_preferences import get_user_theme
        
        user_email = get_user_email_flask()
        user_theme = get_user_theme() or 'system'
        
        # Get navigation context
        from app import get_navigation_context
        nav_context = get_navigation_context(current_page='admin_trade_entry')
        
        return render_template('trade_entry.html', 
                             user_email=user_email,
                             user_theme=user_theme,
                             **nav_context)
    except Exception as e:
        logger.error(f"Error rendering trade entry page: {e}", exc_info=True)
        # Fallback with minimal context
        try:
            from app import get_navigation_context
            nav_context = get_navigation_context(current_page='admin_trade_entry')
        except Exception:
            # If navigation context also fails, use minimal fallback
            nav_context = {}
        return render_template('trade_entry.html', 
                             user_email='Admin',
                             user_theme='system',
                             **nav_context)

@admin_bp.route('/api/admin/trades/preview-email', methods=['POST'])
@require_admin
def api_preview_email_trade():
    """Parse trade from email text.
    
    POST /api/admin/trades/preview-email
    
    Request Body:
        text (str): Raw email text containing trade information
        
    Returns:
        JSON response with:
            - success (bool): Whether parsing was successful
            - trade (dict): Parsed trade data with fields:
                - ticker (str): Stock ticker symbol
                - action (str): BUY or SELL
                - shares (float): Number of shares
                - price (float): Price per share
                - cost_basis (float): Total cost
                - currency (str): Currency code
                - timestamp (str): ISO format timestamp
                - reason (str): Trade reason/notes
                - pnl (float): Profit/loss if applicable
            - error (str): Error message if parsing failed
            
    Error Responses:
        400: No email text provided or parsing failed
        500: Server error during parsing
    """
    try:
        data = request.get_json()
        email_text = data.get('text', '')
        
        if not email_text:
            return jsonify({"error": "No email text provided"}), 400
            
        parser = EmailTradeParser()
        trade = parser.parse_email_trade(email_text)
        
        if trade:
            # Serialize trade object
            return jsonify({
                "success": True,
                "trade": {
                    "ticker": trade.ticker,
                    "action": trade.action if hasattr(trade, 'action') and trade.action else 'BUY',
                    "shares": float(trade.shares),
                    "price": float(trade.price),
                    "cost_basis": float(trade.cost_basis),
                    "currency": trade.currency,
                    "timestamp": trade.timestamp.isoformat(),
                    "reason": trade.reason,
                    "pnl": float(trade.pnl) if trade.pnl else 0
                }
            })
        else:
            return jsonify({"success": False, "error": "Could not parse trade from email"}), 400
    except Exception as e:
        logger.error(f"Error parsing email trade: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/trades/submit', methods=['POST'])
@require_admin
def api_submit_trade():
    """Submit a new trade (Manual or Email).
    
    POST /api/admin/trades/submit
    
    Request Body:
        fund (str): Fund name (required)
        ticker (str): Ticker symbol (required)
        action (str): BUY or SELL (default: BUY)
        shares (float): Number of shares (required, > 0)
        price (float): Price per share (required, > 0)
        currency (str): Currency code (default: USD)
        timestamp (str): ISO format timestamp (required)
        reason (str): Trade reason/notes (optional)
        source (str): 'email' or 'manual' (optional, for validation)
        
    Returns:
        JSON response with:
            - success (bool): Whether submission was successful
            - message (str): Success message
            - rebuild_job_id (str): Job ID if backdated rebuild triggered
            - warning (str): Warning message if portfolio update failed
            - error_details (str): Error details if portfolio update failed
            - requires_rebuild (bool): Whether manual rebuild is required
            
    Error Responses:
        400: Invalid trade data or validation failed
        403: Read-only admin cannot submit trades
        500: Server error during submission
    """
    try:
        from flask_auth_utils import can_modify_data_flask
        if not can_modify_data_flask():
            return jsonify({"error": "Read-only admin cannot submit trades"}), 403
            
        data = request.get_json()
        
        # Extract fields
        fund = data.get('fund')
        ticker = data.get('ticker', '').upper()
        action = data.get('action', 'BUY')
        shares = float(data.get('shares', 0))
        price = float(data.get('price', 0))
        currency = data.get('currency', 'USD')
        # Combined date/time from manual entry, or full timestamp from email parse
        timestamp_str = data.get('timestamp') 
        reason = data.get('reason', '')
        
        if not fund or not ticker or shares <= 0 or price <= 0:
             return jsonify({"error": "Invalid trade data"}), 400

        try:
             trade_dt = datetime.fromisoformat(timestamp_str)
        except ValueError:
             return jsonify({"error": "Invalid timestamp format"}), 400

        # Additional validation for email-parsed trades
        if data.get('source') == 'email':
            # Validate parsed trade structure
            if not all([ticker, action in ['BUY', 'SELL'], shares > 0, price > 0]):
                return jsonify({"error": "Invalid parsed trade data"}), 400
            
            # Validate timestamp is reasonable (not more than 1 day in future)
            if trade_dt > datetime.now() + timedelta(days=1):
                return jsonify({"error": "Trade timestamp cannot be in the future"}), 400

        # Calculations
        cost_basis = shares * price
        pnl = 0
        
        # Service role client for admin ops
        admin_client = SupabaseClient(use_service_role=True)
        
        # 1. Ensure ticker exists and metadata is fetched
        try:
            admin_client.ensure_ticker_in_securities(ticker, currency)
        except Exception as e:
            logger.warning(f"Metadata fetch warning for {ticker}: {e}")
            
        # 2. Calculate P&L for SELLs (FIFO)
        if action == "SELL":
            # For bulk uploads or optimizations, we could pre-fetch trades here
            # For now, we pass None to existing_trades, preserving current behavior but enabling future optimization
            pnl = calculate_fifo_pnl(fund, ticker, shares, price, existing_trades=None)
        
        # 3. Format Reason
        final_reason = reason
        if not final_reason:
            final_reason = f"{action} order"
        elif action == "SELL" and "sell" not in final_reason.lower():
             final_reason = f"{final_reason} - SELL"
        elif action == "BUY" and "buy" not in final_reason.lower() and "sell" not in final_reason.lower():
             final_reason = f"{final_reason} - BUY"
             
        # 4. Insert Trade Log
        trade_data = {
            "fund": fund,
            "ticker": ticker,
            "shares": shares,
            "price": price,
            "cost_basis": cost_basis,
            "pnl": pnl,
            "reason": final_reason,
            "currency": currency,
            "date": trade_dt.isoformat()
        }
        admin_client.supabase.table("trade_log").insert(trade_data).execute()
        
        # 5. Process Portfolio Update
        try:
            from decimal import Decimal
            trade_obj = TradeModel(
                ticker=ticker,
                action=action,
                shares=Decimal(str(shares)),
                price=Decimal(str(price)),
                timestamp=trade_dt,
                cost_basis=Decimal(str(cost_basis)),
                pnl=Decimal(str(pnl)) if pnl else None,
                reason=final_reason,
                currency=currency
            )
            
            # Repository resolution
            data_dir = f"trading_data/funds/{fund}"
            try:
                # Try to get data dir from DB
                fund_res = admin_client.supabase.table("funds").select("data_directory").eq("name", fund).execute()
                if fund_res.data:
                     data_dir = fund_res.data[0].get('data_directory', data_dir)
            except: 
                pass
                
            try:
                repository = RepositoryFactory.create_dual_write_repository(data_dir, fund)
            except:
                repository = SupabaseRepository(fund)
                
            processor = TradeProcessor(repository)
            # trade_already_saved=True because we just inserted it above
            processor.process_trade_entry(trade_obj, clear_caches=True, trade_already_saved=True)
            
        except Exception as proc_e:
            logger.error(f"Portfolio processor error: {proc_e}", exc_info=True)
            # Trade was saved but portfolio update failed - return partial success
            return jsonify({
                "success": True,
                "warning": "Trade saved but portfolio update failed. Please rebuild manually.",
                "error_details": str(proc_e),
                "requires_rebuild": True
            }), 200

        # 6. Trigger Rebuild if Backdated
        is_backdated = trade_dt.date() < datetime.now().date()
        job_id = None
        if is_backdated:
            try:
                job_id = trigger_background_rebuild(fund, trade_dt.date())
            except Exception as rb_e:
                logger.error(f"Rebuild trigger error: {rb_e}")

        return jsonify({
            "success": True, 
            "message": f"Verified: {action} {shares} {ticker}",
            "rebuild_job_id": job_id
        })

    except Exception as e:
        logger.error(f"Error submitting trade: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/trades/recent')
@require_admin
def api_recent_trades():
    """Get recent trades for a fund.
    
    GET /api/admin/trades/recent
    
    Query Parameters:
        fund (str): Fund name (required)
        page (int): Page number for pagination (default: 0)
        limit (int): Number of trades per page (default: 20)
        
    Returns:
        JSON response with:
            - trades (list): Array of trade objects
            - total (int): Total number of trades (excluding DRIP)
            - page (int): Current page number
            - pages (int): Total number of pages
            
    Error Responses:
        500: Server error during fetch
    """
    try:
        fund = request.args.get('fund')
        page = int(request.args.get('page', 0))
        limit = int(request.args.get('limit', 20))
        offset = page * limit
        
        if not fund:
            return jsonify({"trades": [], "total": 0})
            
        # Use service role as requested for all admin pages
        client = SupabaseClient(use_service_role=True)
        
        # Get total count (excluding DRIP)
        count_res = client.supabase.table("trade_log")\
            .select("id", count="exact")\
            .eq("fund", fund)\
            .neq("reason", "DRIP")\
            .execute()
        total = count_res.count or 0
        
        # Get data
        data_res = client.supabase.table("trade_log")\
            .select("*")\
            .eq("fund", fund)\
            .neq("reason", "DRIP")\
            .order("date", desc=True)\
            .range(offset, offset + limit - 1)\
            .execute()
            
        trades = data_res.data or []
        
        return jsonify({
            "trades": trades,
            "total": total,
            "page": page,
            "pages": (total + limit - 1) // limit
        })
    except Exception as e:
        logger.error(f"Error fetching recent trades: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# ==========================================
# Contributions Routes
# ==========================================

@admin_bp.route('/admin/contributions')
@require_admin
def contributions_page():
    """Contributions Management Page"""
    try:
        from flask_auth_utils import get_user_email_flask
        from user_preferences import get_user_theme
        
        user_email = get_user_email_flask()
        user_theme = get_user_theme() or 'system'
        
        from app import get_navigation_context
        nav_context = get_navigation_context(current_page='admin_contributions')
        
        return render_template('contributions.html', 
                             user_email=user_email,
                             user_theme=user_theme,
                             **nav_context)
    except Exception as e:
        logger.error(f"Error rendering contributions page: {e}", exc_info=True)
        # Fallback with minimal context
        try:
            from app import get_navigation_context
            nav_context = get_navigation_context(current_page='admin_contributions')
        except Exception:
            # If navigation context also fails, use minimal fallback
            nav_context = {}
        return render_template('contributions.html', 
                             user_email='Admin',
                             user_theme='system',
                             **nav_context)

@admin_bp.route('/api/admin/contributions', methods=['GET'])
@require_admin
def api_get_contributions():
    """Get list of contributions with filters"""
    try:
        fund = request.args.get('fund', 'All')
        c_type = request.args.get('type', 'All')
        search = request.args.get('search', '')
        
        # Use service role as requested
        client = SupabaseClient(use_service_role=True)
        
        query = client.supabase.table("fund_contributions").select("*").order("timestamp", desc=True)
        
        if fund != "All":
            query = query.eq("fund", fund)
        if c_type != "All":
            query = query.eq("contribution_type", c_type)
        if search:
            query = query.ilike("contributor", f"%{search}%")
            
        result = query.execute()
        
        return jsonify({"contributions": result.data or []})
    except Exception as e:
        logger.error(f"Error fetching contributions: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/contributions', methods=['POST'])
@require_admin
def api_add_contribution():
    """Add a new contribution or withdrawal"""
    try:
        from flask_auth_utils import can_modify_data_flask
        if not can_modify_data_flask():
            return jsonify({"error": "Read-only admin cannot add contributions"}), 403
            
        data = request.get_json()
        
        fund = data.get('fund')
        name = data.get('contributor')
        email = data.get('email')
        amount = float(data.get('amount', 0))
        c_type = data.get('type', 'CONTRIBUTION')
        date_str = data.get('date')
        notes = data.get('notes')
        
        if not fund or not name or amount <= 0 or not date_str:
            return jsonify({"error": "Invalid contribution data"}), 400
            
        # Combine date with current time
        try:
            date_obj = datetime.fromisoformat(date_str).date()
            timestamp = datetime.combine(date_obj, datetime.now().time()).isoformat()
        except:
            return jsonify({"error": "Invalid date format"}), 400
            
        payload = {
            "fund": fund,
            "contributor": name,
            "email": email if email else None,
            "amount": amount,
            "contribution_type": c_type,
            "timestamp": timestamp,
            "notes": notes if notes else None
        }
        
        # Service role client
        client = SupabaseClient(use_service_role=True)
        client.supabase.table("fund_contributions").insert(payload).execute()
        
        return jsonify({"success": True, "message": f"{c_type} recorded successfully"})
    except Exception as e:
        logger.error(f"Error adding contribution: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/contributions/summary', methods=['GET'])
@require_admin
def api_contributions_summary():
    """Get contributor summary (aggregated).
    
    GET /api/admin/contributions/summary
    
    Returns:
        JSON response with:
            - summary (list): Array of contributor summary objects with:
                - contributor (str): Contributor name
                - fund (str): Fund name
                - contribution (float): Total contributions
                - withdrawal (float): Total withdrawals
                - net (float): Net contribution (contribution - withdrawal)
                
    Error Responses:
        500: Server error during aggregation
    """
    try:
        # Service role client
        client = SupabaseClient(use_service_role=True)
        
        result = client.supabase.table("fund_contributions").select("contributor, fund, contribution_type, amount").execute()
        
        if not result.data:
            return jsonify({"summary": []})
            
        # Manually aggregate in Python since Supabase JS client groupBy is limited
        # structure: { 'contributor|fund': { name, fund, contribution: 0, withdrawal: 0 } }
        agg = {}
        
        for row in result.data:
            key = f"{row['contributor']}|{row['fund']}"
            if key not in agg:
                agg[key] = {
                    "contributor": row['contributor'],
                    "fund": row['fund'],
                    "contribution": 0,
                    "withdrawal": 0
                }
            
            amt = float(row.get('amount', 0))
            if row.get('contribution_type') == 'CONTRIBUTION':
                agg[key]['contribution'] += amt
            else:
                agg[key]['withdrawal'] += amt
        
        # Convert to list and calculate net
        summary_list = []
        for v in agg.values():
            v['net'] = v['contribution'] - v['withdrawal']
            summary_list.append(v)
            
        return jsonify({"summary": summary_list})
    except Exception as e:
         logger.error(f"Error fetching contribution summary: {e}", exc_info=True)
         return jsonify({"error": str(e)}), 500

# ==========================================
# AI Settings Routes
# ==========================================

@admin_bp.route('/admin/ai-settings')
@require_admin
def ai_settings_page():
    """AI Settings Page"""
    try:
        from flask_auth_utils import get_user_email_flask
        from user_preferences import get_user_theme
        
        user_email = get_user_email_flask()
        user_theme = get_user_theme() or 'system'
        
        from app import get_navigation_context
        nav_context = get_navigation_context(current_page='admin_ai_settings')
        
        return render_template('ai_settings.html', 
                             user_email=user_email,
                             user_theme=user_theme,
                             **nav_context)
    except Exception as e:
        logger.error(f"Error rendering AI settings page: {e}", exc_info=True)
        # Fallback with minimal context
        try:
            from app import get_navigation_context
            nav_context = get_navigation_context(current_page='admin_ai_settings')
        except Exception:
            # If navigation context also fails, use minimal fallback
            nav_context = {}
        return render_template('ai_settings.html', 
                             user_email='Admin',
                             user_theme='system',
                             **nav_context)

@admin_bp.route('/api/admin/ai/status')
@require_admin
def api_ai_status():
    """Check connections status"""
    try:
        # Ollama
        ollama_ok = False
        ollama_msg = ""
        try:
            ollama_ok = check_ollama_health()
            ollama_msg = "Online" if ollama_ok else "Offline"
        except Exception as e:
            ollama_msg = str(e)
            logger.error(f"Error checking Ollama health: {e}", exc_info=True)
             
        # Postgres
        pg_connected, pg_stats = get_postgres_status_cached()
        pg_status = {
            "status": "healthy" if pg_connected else "error",
            "message": f"Connected - {pg_stats.get('total', 0)} articles" if pg_connected and pg_stats else "Not connected"
        }
        
        # WebAI Cookies
        webai_status = {"status": False, "message": "Not configured", "source": None, "has_1psid": False, "has_1psidts": False}
        try:
            from webai_wrapper import check_cookie_config, _load_cookies
            config_status = check_cookie_config()
            
            # Determine cookie source and status
            has_cookies = False
            cookie_source = None
            
            if config_status.get("env_var_exists") and config_status.get("has_secure_1psid"):
                has_cookies = True
                cookie_source = "Environment Variable"
            elif config_status.get("cookie_files", {}).get("webai_cookies.json", {}).get("root_exists"):
                has_cookies = True
                cookie_source = "Cookie File (root)"
            elif config_status.get("cookie_files", {}).get("webai_cookies.json", {}).get("web_exists"):
                has_cookies = True
                cookie_source = "Cookie File (web_dashboard)"
            
            # Check shared volume (Docker container)
            from pathlib import Path
            shared_cookie_path = Path("/shared/cookies/webai_cookies.json")
            if shared_cookie_path.exists():
                has_cookies = True
                cookie_source = "Shared Volume (/shared/cookies)"
            
            if has_cookies:
                try:
                    secure_1psid, secure_1psidts = _load_cookies()
                    webai_status = {
                        "status": bool(secure_1psid),
                        "message": "Configured" if secure_1psid else "Invalid format",
                        "source": cookie_source,
                        "has_1psid": bool(secure_1psid),
                        "has_1psidts": bool(secure_1psidts)
                    }
                except Exception as e:
                    webai_status = {
                        "status": False,
                        "message": f"Error loading: {str(e)[:50]}",
                        "source": cookie_source,
                        "has_1psid": False,
                        "has_1psidts": False
                    }
        except ImportError:
            webai_status = {"status": False, "message": "WebAI wrapper not available", "source": None, "has_1psid": False, "has_1psidts": False}
        except Exception as e:
            logger.error(f"Error checking WebAI cookies: {e}", exc_info=True)
            webai_status = {"status": False, "message": f"Error: {str(e)[:50]}", "source": None, "has_1psid": False, "has_1psidts": False}
        
        return jsonify({
            "ollama": {"status": ollama_ok, "message": ollama_msg},
            "postgres": pg_status,
            "webai": webai_status
        })
    except Exception as e:
        logger.error(f"Error in api_ai_status: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/ai/settings', methods=['GET'])
@require_admin
def api_get_ai_settings():
    """Get system settings"""
    try:
        client = SupabaseClient(use_service_role=True)
        # Using system_settings table or similar KV store
        # Assuming a simple KV store or using a specific row in a settings table
        # For now, let's mock/use what's available or query a 'system_config' table if exists,
        # otherwise defaulting to env vars or safe defaults.
        
        # Checking if we have a table for this. If not, we might need to create it or just return mock for now
        # per the existing 'admin_ai_settings.py' logic.
        
        # Looking at previous context, there is a `system_settings` table usually.
        settings = {}
        try:
            res = client.supabase.table("system_settings").select("*").execute()
            if res.data:
                for row in res.data:
                    settings[row['key']] = row['value']
        except:
            # Table might not exist yet, return defaults
            settings = {
                "auto_blacklist_threshold": "0.15",
                "max_research_batch_size": "50"
            }
            
        return jsonify(settings)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/ai/settings', methods=['POST'])
@require_admin
def api_update_ai_settings():
    """Update system settings"""
    try:
        from flask_auth_utils import can_modify_data_flask
        if not can_modify_data_flask():
            return jsonify({"error": "Read-only admin cannot modify settings"}), 403
            
        data = request.get_json()
        client = SupabaseClient(use_service_role=True)
        
        # Upsert keys
        for key, value in data.items():
            client.supabase.table("system_settings").upsert({
                "key": key, 
                "value": str(value),
                "updated_at": datetime.now().isoformat()
            }).execute()
            
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error updating settings: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/ai/blacklist', methods=['GET'])
@require_admin
def api_get_blacklist():
    """Get research blacklist"""
    try:
        client = SupabaseClient(use_service_role=True)
        # Query research_domain_health table for blacklisted domains
        res = client.supabase.table("research_domain_health").select("*").eq("auto_blacklisted", True).order("auto_blacklisted_at", desc=True).execute()
        return jsonify({"blacklist": res.data or []})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/ai/blacklist', methods=['POST'])
@require_admin
def api_add_blacklist():
    """Add domain to blacklist"""
    try:
        from flask_auth_utils import can_modify_data_flask
        if not can_modify_data_flask():
            return jsonify({"error": "Read-only admin cannot modify blacklist"}), 403
            
        data = request.get_json()
        domain = data.get('domain')
        reason = data.get('reason', 'Manual addition')
        
        if not domain:
            return jsonify({"error": "Domain required"}), 400
            
        client = SupabaseClient(use_service_role=True)
        from datetime import datetime
        now = datetime.now().isoformat()
        
        # Upsert into research_domain_health table
        client.supabase.table("research_domain_health").upsert({
            "domain": domain,
            "auto_blacklisted": True,
            "consecutive_failures": 999,  # High count to ensure it's blacklisted
            "auto_blacklisted_at": now,
            "last_attempt_at": now,
            "last_failure_reason": reason,
            "updated_at": now
        }).execute()
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/ai/blacklist', methods=['DELETE'])
@require_admin
def api_delete_blacklist():
    """Remove domain from blacklist"""
    try:
        from flask_auth_utils import can_modify_data_flask
        if not can_modify_data_flask():
            return jsonify({"error": "Read-only admin cannot modify blacklist"}), 403
            
        domain = request.args.get('domain')
        
        if not domain:
            return jsonify({"error": "Domain required"}), 400
            
        client = SupabaseClient(use_service_role=True)
        from datetime import datetime
        now = datetime.now().isoformat()
        
        # Update research_domain_health table to remove from blacklist
        client.supabase.table("research_domain_health").update({
            "auto_blacklisted": False,
            "consecutive_failures": 0,
            "updated_at": now
        }).eq("domain", domain).execute()
        
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error deleting from blacklist: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/api/admin/ai/cookies/test', methods=['POST'])
@require_admin
def api_test_webai_cookies():
    """Test WebAI cookie connection"""
    try:
        from webai_wrapper import test_webai_connection
        from pathlib import Path
        
        # Find cookie file
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
        
        return jsonify({
            "success": test_result.get("success", False),
            "message": test_result.get("message", "Unknown error"),
            "details": test_result.get("details", {})
        })
    except Exception as e:
        logger.error(f"Error testing WebAI cookies: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

@admin_bp.route('/api/admin/ai/cookies', methods=['GET'])
@require_admin
def api_get_webai_cookies():
    """Get current WebAI cookies (for display/editing)"""
    try:
        from webai_wrapper import _load_cookies
        
        secure_1psid, secure_1psidts = _load_cookies()
        
        cookies = {}
        if secure_1psid:
            cookies["__Secure-1PSID"] = secure_1psid
        if secure_1psidts:
            cookies["__Secure-1PSIDTS"] = secure_1psidts
        
        return jsonify({
            "success": True,
            "cookies": cookies,
            "has_cookies": bool(secure_1psid)
        })
    except Exception as e:
        logger.error(f"Error getting WebAI cookies: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e), "cookies": {}, "has_cookies": False}), 500

@admin_bp.route('/api/admin/ai/cookies/logs', methods=['GET'])
@require_admin
def api_get_cookie_refresher_logs():
    """Get cookie refresher logs"""
    try:
        from pathlib import Path
        
        log_file = Path("/shared/cookies/cookie_refresher.log")
        lines = request.args.get('lines', 100, type=int)
        
        if not log_file.exists():
            return jsonify({
                "success": False,
                "error": "Log file not found",
                "logs": [],
                "message": "Cookie refresher log file does not exist. Logs may not be configured yet."
            })
        
        try:
            # Read last N lines from log file
            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                all_lines = f.readlines()
                # Get last N lines
                log_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
            
            return jsonify({
                "success": True,
                "logs": log_lines,
                "total_lines": len(all_lines),
                "showing_lines": len(log_lines)
            })
        except PermissionError:
            return jsonify({
                "success": False,
                "error": "Permission denied",
                "logs": [],
                "message": "Cannot read log file. Check file permissions."
            }), 403
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e),
                "logs": [],
                "message": f"Error reading log file: {e}"
            }), 500
            
    except Exception as e:
        logger.error(f"Error getting cookie refresher logs: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e), "logs": []}), 500

@admin_bp.route('/api/admin/ai/cookies', methods=['POST'])
@require_admin
def api_update_webai_cookies():
    """Update WebAI cookies"""
    try:
        from flask_auth_utils import can_modify_data_flask
        if not can_modify_data_flask():
            return jsonify({"error": "Read-only admin cannot modify cookies"}), 403
        
        data = request.get_json()
        cookies = data.get("cookies")
        
        if not cookies or not isinstance(cookies, dict):
            return jsonify({"error": "Invalid cookies format. Expected JSON object."}), 400
        
        if "__Secure-1PSID" not in cookies:
            return jsonify({"error": "Missing required cookie: __Secure-1PSID"}), 400
        
        # Save to shared volume (Docker container location)
        from pathlib import Path
        import json
        from datetime import datetime
        
        shared_cookie_path = Path("/shared/cookies/webai_cookies.json")
        shared_cookie_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Prepare cookie data with metadata
        cookie_data = {
            "__Secure-1PSID": cookies.get("__Secure-1PSID", ""),
            "__Secure-1PSIDTS": cookies.get("__Secure-1PSIDTS", ""),
            "_updated_at": datetime.now().isoformat() + "Z",
            "_updated_by": "admin_ui"
        }
        
        # Remove empty values (but keep metadata)
        cookie_data = {k: v for k, v in cookie_data.items() if v or k.startswith("_")}
        
        # Write to shared volume
        with open(shared_cookie_path, 'w', encoding='utf-8') as f:
            json.dump(cookie_data, f, indent=2)
        
        return jsonify({"success": True, "message": f"Cookies saved to {shared_cookie_path}"})
    except PermissionError:
        return jsonify({"error": "Permission denied. Cannot write to /shared/cookies/"}), 403
    except Exception as e:
        logger.error(f"Error updating WebAI cookies: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# Contributor Management Routes
@admin_bp.route('/admin/contributors')
@require_admin
def contributors_page():
    """Contributor management page"""
    from app import get_navigation_context
    nav_context = get_navigation_context('admin_contributors')
    return render_template('contributors.html', **nav_context)

@admin_bp.route('/api/admin/contributors/<contributor_id>/contributions')
@require_admin
def api_admin_contributor_contributions(contributor_id):
    """Get all fund contributions for a contributor"""
    try:
        from app import get_supabase_client
        client = get_supabase_client()
        if not client:
            return jsonify({"error": "Failed to connect to database", "contributions": []}), 500
        
        # Get contributor details
        contrib_result = client.supabase.table("contributors").select("*").eq("id", contributor_id).execute()
        if not contrib_result.data:
            return jsonify({"error": "Contributor not found", "contributions": []}), 404
        
        contributor = contrib_result.data[0]
        
        # Get contributions by contributor_id
        contribs_result = client.supabase.table("fund_contributions")\
            .select("*")\
            .eq("contributor_id", contributor_id)\
            .execute()
        
        # Also get by name (legacy)
        contribs_by_name = client.supabase.table("fund_contributions")\
            .select("*")\
            .eq("contributor", contributor['name'])\
            .execute()
        
        # Combine and deduplicate
        all_contribs = contribs_result.data or []
        contrib_ids = {c.get('id') for c in all_contribs}
        for c in (contribs_by_name.data or []):
            if c.get('id') not in contrib_ids:
                all_contribs.append(c)
        
        return jsonify({
            "contributor": contributor,
            "contributions": all_contribs
        })
    except Exception as e:
        logger.error(f"Error getting contributor contributions: {e}", exc_info=True)
        return jsonify({"error": f"Failed to load contributions: {str(e)}", "contributions": []}), 500

@admin_bp.route('/api/admin/contributors/split', methods=['POST'])
@require_admin
def api_admin_split_contributor():
    """Split a contributor into two accounts"""
    try:
        from app import get_supabase_client
        from flask_auth_utils import can_modify_data_flask
        
        if not can_modify_data_flask():
            return jsonify({"error": "Read-only admin cannot split contributors"}), 403
        
        data = request.get_json()
        source_contributor_id = data.get('source_contributor_id')
        new_contributor_name = data.get('new_contributor_name')
        new_contributor_email = data.get('new_contributor_email')
        contribution_ids = data.get('contribution_ids', [])
        
        if not source_contributor_id or not new_contributor_name or not contribution_ids:
            return jsonify({"error": "Missing required fields"}), 400
        
        client = get_supabase_client()
        if not client:
            return jsonify({"error": "Failed to connect to database"}), 500
        
        # Create new contributor
        new_contrib_data = {
            "name": new_contributor_name,
            "email": new_contributor_email if new_contributor_email else None
        }
        new_contrib_result = client.supabase.table("contributors").insert(new_contrib_data).execute()
        
        if not new_contrib_result.data:
            return jsonify({"error": "Failed to create new contributor"}), 500
        
        new_contrib_id = new_contrib_result.data[0]['id']
        
        # Update selected contributions
        updated_count = 0
        for contrib_id in contribution_ids:
            update_data = {
                "contributor_id": new_contrib_id,
                "contributor": new_contributor_name
            }
            if new_contributor_email:
                update_data["email"] = new_contributor_email
            
            result = client.supabase.table("fund_contributions")\
                .update(update_data)\
                .eq("id", contrib_id)\
                .execute()
            
            if result.data:
                updated_count += 1
        
        # Clear cache
        _get_cached_contributors_flask.clear_all_cache()
        
        return jsonify({
            "success": True,
            "message": f"Split complete! Created new contributor and moved {updated_count} contribution(s)",
            "new_contributor_id": new_contrib_id
        })
    except Exception as e:
        logger.error(f"Error splitting contributor: {e}", exc_info=True)
        return jsonify({"error": f"Failed to split contributor: {str(e)}"}), 500

@admin_bp.route('/api/admin/contributors/merge', methods=['POST'])
@require_admin
def api_admin_merge_contributors():
    """Merge two contributors"""
    try:
        from app import get_supabase_client
        from flask_auth_utils import can_modify_data_flask
        
        if not can_modify_data_flask():
            return jsonify({"error": "Read-only admin cannot merge contributors"}), 403
        
        data = request.get_json()
        source_contributor_id = data.get('source_contributor_id')
        target_contributor_id = data.get('target_contributor_id')
        
        if not source_contributor_id or not target_contributor_id:
            return jsonify({"error": "Missing required fields"}), 400
        
        if source_contributor_id == target_contributor_id:
            return jsonify({"error": "Source and target cannot be the same"}), 400
        
        client = get_supabase_client()
        if not client:
            return jsonify({"error": "Failed to connect to database"}), 500
        
        # Get contributor details
        source_result = client.supabase.table("contributors").select("*").eq("id", source_contributor_id).execute()
        target_result = client.supabase.table("contributors").select("*").eq("id", target_contributor_id).execute()
        
        if not source_result.data or not target_result.data:
            return jsonify({"error": "Contributor not found"}), 404
        
        source_contrib = source_result.data[0]
        target_contrib = target_result.data[0]
        
        # Update all contributions
        update_data = {
            "contributor_id": target_contributor_id,
            "contributor": target_contrib['name']
        }
        if target_contrib.get('email'):
            update_data["email"] = target_contrib['email']
        
        # Update by contributor_id
        client.supabase.table("fund_contributions")\
            .update(update_data)\
            .eq("contributor_id", source_contributor_id)\
            .execute()
        
        # Update by contributor name (legacy)
        client.supabase.table("fund_contributions")\
            .update(update_data)\
            .eq("contributor", source_contrib['name'])\
            .execute()
        
        # Delete source contributor
        client.supabase.table("contributors")\
            .delete()\
            .eq("id", source_contributor_id)\
            .execute()
        
        # Clear cache
        _get_cached_contributors_flask.clear_all_cache()
        
        return jsonify({
            "success": True,
            "message": f"Merged {source_contrib['name']} into {target_contrib['name']}"
        })
    except Exception as e:
        logger.error(f"Error merging contributors: {e}", exc_info=True)
        return jsonify({"error": f"Failed to merge contributors: {str(e)}"}), 500

@admin_bp.route('/api/admin/contributors/<contributor_id>', methods=['PUT'])
@require_admin
def api_admin_update_contributor(contributor_id):
    """Update contributor details"""
    try:
        from app import get_supabase_client
        from flask_auth_utils import can_modify_data_flask
        
        if not can_modify_data_flask():
            return jsonify({"error": "Read-only admin cannot edit contributors"}), 403
        
        data = request.get_json()
        new_name = data.get('name')
        new_email = data.get('email')
        
        if not new_name:
            return jsonify({"error": "Name is required"}), 400
        
        client = get_supabase_client()
        if not client:
            return jsonify({"error": "Failed to connect to database"}), 500
        
        # Get current contributor
        current_result = client.supabase.table("contributors").select("*").eq("id", contributor_id).execute()
        if not current_result.data:
            return jsonify({"error": "Contributor not found"}), 404
        
        current_contrib = current_result.data[0]
        
        # Update contributor
        update_data = {"name": new_name}
        if new_email:
            update_data["email"] = new_email
        else:
            update_data["email"] = None
        
        result = client.supabase.table("contributors")\
            .update(update_data)\
            .eq("id", contributor_id)\
            .execute()
        
        if not result.data:
            return jsonify({"error": "Failed to update contributor"}), 500
        
        # Update fund_contributions if name changed
        if new_name != current_contrib.get('name'):
            client.supabase.table("fund_contributions")\
                .update({"contributor": new_name})\
                .eq("contributor_id", contributor_id)\
                .execute()
            
            # Also update by old name (legacy)
            client.supabase.table("fund_contributions")\
                .update({"contributor": new_name})\
                .eq("contributor", current_contrib.get('name'))\
                .execute()
        
        # Update email in fund_contributions if changed
        if new_email != current_contrib.get('email'):
            if new_email:
                client.supabase.table("fund_contributions")\
                    .update({"email": new_email})\
                    .eq("contributor_id", contributor_id)\
                    .execute()
        
        # Clear cache
        _get_cached_contributors_flask.clear_all_cache()
        
        return jsonify({
            "success": True,
            "message": "Contributor updated successfully"
        })
    except Exception as e:
        logger.error(f"Error updating contributor: {e}", exc_info=True)
        return jsonify({"error": f"Failed to update contributor: {str(e)}"}), 500
