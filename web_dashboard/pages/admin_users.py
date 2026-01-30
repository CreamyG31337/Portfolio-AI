#!/usr/bin/env python3
"""
User & Access Management
========================

Admin page for managing users, roles, fund assignments, and contributor access.
Combines User Management and Contributor Access Management.
"""

import streamlit as st
import sys
import os
from pathlib import Path
import pandas as pd
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from auth_utils import is_authenticated, has_admin_access, can_modify_data, get_user_email, send_magic_link, is_admin, redirect_to_login
from streamlit_utils import get_supabase_client, display_dataframe_with_copy
from supabase import create_client
from navigation import render_navigation

# Import shared utilities
from admin_utils import perf_timer, get_cached_users, get_cached_contributors, get_cached_fund_names

# Page configuration
st.set_page_config(page_title="User & Access Management", page_icon="👥", layout="wide")

# Check authentication - redirect to main page if not logged in
if not is_authenticated():
    redirect_to_login("pages/admin_users.py")

# Refresh token if needed (auto-refresh before expiry)
from auth_utils import refresh_token_if_needed
if not refresh_token_if_needed():
    # Token refresh failed - session is invalid, redirect to login
    from auth_utils import logout_user
    logout_user(return_to="pages/admin_users.py")
    st.stop()

# Check admin access (allows both admin and readonly_admin)
if not has_admin_access():
    st.error("❌ Access Denied: Admin privileges required")
    st.info("Only administrators can access this page.")
    st.stop()

# Navigation
render_navigation(show_ai_assistant=True, show_settings=True)

# Header
st.markdown("# 👥 User & Access Management")
st.caption(f"Logged in as: {get_user_email()}")

# Create tabs for User Management and Contributor Access
tab_users, tab_access = st.tabs([
    "👥 User Management",
    "🔐 Contributor Access"
])

# Tab 1: User Management
with tab_users:
    st.header("👥 User Management")
    st.caption("Manage users, roles, and fund assignments")
    
    client = get_supabase_client()
    if not client:
        st.error("Failed to connect to database")
    else:
        # Get all users with their fund assignments (using cache)
        with st.spinner("Loading users..."):
            try:
                with perf_timer("User Management Load"):
                    users_df = pd.DataFrame(get_cached_users())
                
                if not users_df.empty:
                    # Get available funds from cache for use in action menus
                    available_funds = get_cached_fund_names()
                    current_user_email = get_user_email()
                    
                    # Display users in consolidated table with inline actions
                    st.subheader("All Users")
                    st.caption(f"{len(users_df)} registered users")
                    
                    # Table with actions for each user
                    for idx, row in users_df.iterrows():
                        email = row.get('email', '')
                        full_name = row.get('full_name', 'N/A')
                        role = row.get('role', 'user')
                        funds_list = row.get('funds', [])
                        
                        # User info and role badge
                        col_info, col_role, col_funds, col_actions = st.columns([3, 1, 2, 2])
                        
                        with col_info:
                            st.markdown(f"**{full_name}**")
                            st.caption(email)
                        
                        with col_role:
                            if role == 'admin':
                                st.markdown("🔑 **Admin**")
                            elif role == 'readonly_admin':
                                st.markdown("👁️ **Read-Only**")
                            else:
                                st.caption("👤 User")
                        
                        with col_funds:
                            if funds_list:
                                funds_str = ", ".join(funds_list)
                                if len(funds_str) > 30:
                                    funds_str = funds_str[:27] + "..."
                                st.caption(f"📊 {funds_str}")
                            else:
                                st.caption("📊 No funds")
                        
                        with col_actions:
                            # Use popover for actions menu
                            with st.popover("⚙️ Actions", use_container_width=True):
                                st.markdown(f"**Actions for {full_name}**")
                                st.divider()
                                
                                # Admin role management
                                st.markdown("**🔑 Role Management**")
                                is_self = (email == current_user_email)

                                if is_self:
                                    st.caption("⚠️ Cannot modify your own role")
                                elif role == 'admin':
                                    # Demote to readonly_admin or user
                                    col_readonly, col_user = st.columns(2)
                                    with col_readonly:
                                        if st.button("👁️ Read-Only", key=f"demote_readonly_{idx}_{email}", use_container_width=True, disabled=not can_modify_data()):
                                            if not can_modify_data():
                                                st.error("❌ Read-only admin cannot modify user roles")
                                                st.stop()
                                            try:
                                                result = client.supabase.rpc(
                                                    'set_user_role',
                                                    {'user_email': email, 'new_role': 'readonly_admin'}
                                                ).execute()

                                                result_data = result.data
                                                if isinstance(result_data, list) and len(result_data) > 0:
                                                    result_data = result_data[0]

                                                if result_data and result_data.get('success'):
                                                    st.cache_data.clear()
                                                    st.toast(f"✅ {result_data.get('message')}", icon="✅")
                                                    st.rerun()
                                                else:
                                                    st.error(f"❌ {result_data.get('message', 'Failed to change role')}")
                                            except Exception as e:
                                                st.error(f"Error: {e}")
                                    with col_user:
                                        if st.button("👤 User", key=f"demote_touser_{idx}_{email}", use_container_width=True, disabled=not can_modify_data()):
                                            if not can_modify_data():
                                                st.error("❌ Read-only admin cannot modify user roles")
                                                st.stop()
                                            try:
                                                result = client.supabase.rpc(
                                                    'set_user_role',
                                                    {'user_email': email, 'new_role': 'user'}
                                                ).execute()

                                                result_data = result.data
                                                if isinstance(result_data, list) and len(result_data) > 0:
                                                    result_data = result_data[0]

                                                if result_data and result_data.get('success'):
                                                    st.cache_data.clear()
                                                    st.toast(f"✅ {result_data.get('message')}", icon="✅")
                                                    st.rerun()
                                                else:
                                                    st.error(f"❌ {result_data.get('message', 'Failed to change role')}")
                                            except Exception as e:
                                                st.error(f"Error: {e}")
                                elif role == 'readonly_admin':
                                    # Promote to admin or demote to user
                                    col_promote, col_demote = st.columns(2)
                                    with col_promote:
                                        if st.button("🔑 Full Admin", key=f"promote_admin_{idx}_{email}", use_container_width=True, disabled=not can_modify_data()):
                                            if not can_modify_data():
                                                st.error("❌ Read-only admin cannot modify user roles")
                                                st.stop()
                                            try:
                                                result = client.supabase.rpc(
                                                    'set_user_role',
                                                    {'user_email': email, 'new_role': 'admin'}
                                                ).execute()

                                                result_data = result.data
                                                if isinstance(result_data, list) and len(result_data) > 0:
                                                    result_data = result_data[0]

                                                if result_data and result_data.get('success'):
                                                    st.cache_data.clear()
                                                    st.toast(f"✅ {result_data.get('message')}", icon="✅")
                                                    st.rerun()
                                                else:
                                                    st.error(f"❌ {result_data.get('message', 'Failed to change role')}")
                                            except Exception as e:
                                                st.error(f"Error: {e}")
                                    with col_demote:
                                        if st.button("👤 User", key=f"demote_user_{idx}_{email}", use_container_width=True, disabled=not can_modify_data()):
                                            if not can_modify_data():
                                                st.error("❌ Read-only admin cannot modify user roles")
                                                st.stop()
                                            try:
                                                result = client.supabase.rpc(
                                                    'set_user_role',
                                                    {'user_email': email, 'new_role': 'user'}
                                                ).execute()

                                                result_data = result.data
                                                if isinstance(result_data, list) and len(result_data) > 0:
                                                    result_data = result_data[0]

                                                if result_data and result_data.get('success'):
                                                    st.cache_data.clear()
                                                    st.toast(f"✅ {result_data.get('message')}", icon="✅")
                                                    st.rerun()
                                                else:
                                                    st.error(f"❌ {result_data.get('message', 'Failed to change role')}")
                                            except Exception as e:
                                                st.error(f"Error: {e}")
                                else:
                                    # Regular user - can promote to readonly_admin or full admin
                                    col_readonly, col_full = st.columns(2)
                                    with col_readonly:
                                        if st.button("👁️ Read-Only", key=f"grant_readonly_{idx}_{email}", use_container_width=True, disabled=not can_modify_data()):
                                            if not can_modify_data():
                                                st.error("❌ Read-only admin cannot modify user roles")
                                                st.stop()
                                            try:
                                                result = client.supabase.rpc(
                                                    'set_user_role',
                                                    {'user_email': email, 'new_role': 'readonly_admin'}
                                                ).execute()

                                                result_data = result.data
                                                if isinstance(result_data, list) and len(result_data) > 0:
                                                    result_data = result_data[0]

                                                if result_data and result_data.get('success'):
                                                    st.cache_data.clear()
                                                    st.toast(f"✅ {result_data.get('message')}", icon="✅")
                                                    st.rerun()
                                                else:
                                                    st.error(f"❌ {result_data.get('message', 'Failed to change role')}")
                                            except Exception as e:
                                                st.error(f"Error: {e}")
                                    with col_full:
                                        if st.button("🔑 Full Admin", key=f"grant_admin_{idx}_{email}", use_container_width=True, disabled=not can_modify_data()):
                                            if not can_modify_data():
                                                st.error("❌ Read-only admin cannot modify user roles")
                                                st.stop()
                                            try:
                                                result = client.supabase.rpc(
                                                    'set_user_role',
                                                    {'user_email': email, 'new_role': 'admin'}
                                                ).execute()

                                                result_data = result.data
                                                if isinstance(result_data, list) and len(result_data) > 0:
                                                    result_data = result_data[0]

                                                if result_data and result_data.get('success'):
                                                    st.cache_data.clear()
                                                    st.toast(f"✅ {result_data.get('message')}", icon="✅")
                                                    st.rerun()
                                                else:
                                                    st.error(f"❌ {result_data.get('message', 'Failed to change role')}")
                                            except Exception as e:
                                                st.error(f"Error: {e}")
                                
                                st.divider()
                                
                                # Fund management
                                st.markdown("**📊 Fund Management**")
                                
                                # Assign fund
                                assign_fund = st.selectbox(
                                    "Assign Fund",
                                    options=[""] + available_funds,
                                    key=f"assign_fund_select_{idx}_{email}"
                                )
                                if st.button("➕ Assign", key=f"assign_fund_btn_{idx}_{email}", disabled=(not assign_fund or not can_modify_data()), use_container_width=True):
                                    if not can_modify_data():
                                        st.error("❌ Read-only admin cannot assign funds to users")
                                        st.stop()
                                    try:
                                        result = client.supabase.rpc(
                                            'assign_fund_to_user',
                                            {'user_email': email, 'fund_name': assign_fund}
                                        ).execute()
                                        
                                        result_data = result.data
                                        if isinstance(result_data, list) and len(result_data) > 0:
                                            result_data = result_data[0]
                                        
                                        if result_data and result_data.get('success'):
                                            st.cache_data.clear()
                                            st.toast(f"✅ {result_data.get('message')}", icon="✅")
                                            st.rerun()
                                        elif result_data and result_data.get('already_assigned'):
                                            st.warning(f"⚠️ {result_data.get('message')}")
                                        else:
                                            st.error(f"❌ {result_data.get('message', 'Failed to assign fund')}")
                                    except Exception as e:
                                        st.error(f"Error: {e}")
                                
                                # Remove fund
                                if funds_list:
                                    remove_fund = st.selectbox(
                                        "Remove Fund",
                                        options=[""] + funds_list,
                                        key=f"remove_fund_select_{idx}_{email}"
                                    )
                                    if st.button("➖ Remove", key=f"remove_fund_btn_{idx}_{email}", disabled=(not remove_fund or not can_modify_data()), use_container_width=True):
                                        if not can_modify_data():
                                            st.error("❌ Read-only admin cannot remove funds from users")
                                            st.stop()
                                        try:
                                            result = client.supabase.rpc(
                                                'remove_fund_from_user',
                                                {'user_email': email, 'fund_name': remove_fund}
                                            ).execute()
                                            
                                            if result.data:
                                                st.cache_data.clear()
                                                st.toast(f"✅ Removed {remove_fund} from {email}", icon="✅")
                                                st.rerun()
                                            else:
                                                st.warning("No assignment found")
                                        except Exception as e:
                                            st.error(f"Error: {e}")
                                else:
                                    st.caption("_No funds assigned_")
                                
                                st.divider()
                                
                                # Other actions
                                st.markdown("**📧 Other Actions**")
                                
                                # Send invite - allow if inviting self, block if inviting others
                                can_send_invite = can_modify_data() or (email == get_user_email())
                                if st.button("📧 Send Invite", key=f"invite_btn_{idx}_{email}", disabled=not can_send_invite, use_container_width=True):
                                    if not can_send_invite:
                                        st.error("❌ Read-only admin can only send invites to themselves")
                                        st.stop()
                                    try:
                                        result = send_magic_link(email)
                                        if result and result.get('success'):
                                            st.toast(f"✅ Invite sent to {email}", icon="✅")
                                        else:
                                            error_msg = result.get('error', 'Unknown error') if result else 'Failed to send'
                                            st.error(f"Failed: {error_msg}")
                                    except Exception as e:
                                        st.error(f"Error: {e}")
                                
                                st.divider()
                                
                                # Delete user (with confirmation)
                                st.markdown("**🗑️ Delete User**")
                                st.caption("⚠️ Cannot undo. Contributors cannot be deleted.")
                                
                                delete_confirm_key = f"delete_confirm_{idx}_{email}"
                                if delete_confirm_key not in st.session_state:
                                    st.session_state[delete_confirm_key] = False
                                
                                if not st.session_state[delete_confirm_key]:
                                    if st.button("🗑️ Delete User", key=f"delete_init_{idx}_{email}", type="secondary", use_container_width=True, disabled=not can_modify_data()):
                                        if not can_modify_data():
                                            st.error("❌ Read-only admin cannot delete users")
                                            st.stop()
                                        st.session_state[delete_confirm_key] = True
                                        st.rerun()
                                else:
                                    st.warning(f"Confirm delete {email}?")
                                    col_yes, col_no = st.columns(2)
                                    with col_yes:
                                        if st.button("✓ Yes", key=f"delete_yes_{idx}_{email}", type="primary", disabled=not can_modify_data()):
                                            if not can_modify_data():
                                                st.error("❌ Read-only admin cannot delete users")
                                                st.stop()
                                            try:
                                                result = client.supabase.rpc(
                                                    'delete_user_safe',
                                                    {'user_email': email}
                                                ).execute()
                                                
                                                if result.data:
                                                    if result.data.get('success'):
                                                        st.cache_data.clear()
                                                        st.toast(f"✅ {result.data.get('message')}", icon="✅")
                                                        st.session_state[delete_confirm_key] = False
                                                        st.rerun()
                                                    else:
                                                        st.error(f"🚫 {result.data.get('message')}")
                                                        st.session_state[delete_confirm_key] = False
                                                else:
                                                    st.error("Failed to delete user")
                                            except Exception as e:
                                                st.error(f"Error: {e}")
                                                st.session_state[delete_confirm_key] = False
                                    with col_no:
                                        if st.button("✗ No", key=f"delete_no_{idx}_{email}"):
                                            st.session_state[delete_confirm_key] = False
                                            st.rerun()
                        
                        st.divider()
                    
                    st.divider()
                    
                    # Update contributor email section (keep this separate)
                    st.subheader("Update Contributor Email")
                    st.caption("Change a contributor's email address (updates contributors table and fund_contributions records)")
                    
                    col_email1, col_email2 = st.columns(2)
                    
                    with col_email1:
                        # Get all contributors from both sources
                        contributor_options = [""]
                        contributor_map = {}  # Maps display string to (contributor_name, contributor_id, current_email, is_user)
                        
                        # 1. Get contributors from contributors table
                        try:
                            contributors_list = get_cached_contributors()
                            for c in contributors_list:
                                name = c.get('name', '')
                                email = c.get('email') or ""
                                contrib_id = c.get('id')
                                
                                if name:
                                    if email:
                                        display_label = f"{name} ({email}) [Contributor]"
                                    else:
                                        display_label = f"{name} (no email) [Contributor]"
                                    
                                    contributor_options.append(display_label)
                                    contributor_map[display_label] = {
                                        'name': name,
                                        'id': contrib_id,
                                        'email': email,
                                        'is_user': False,
                                        'type': 'contributor'
                                    }
                        except Exception as e:
                            st.warning(f"Could not load contributors table: {e}")
                        
                        # 2. Get unique contributors from fund_contributions
                        try:
                            # Get all unique contributors from fund_contributions
                            all_contribs = []
                            batch_size = 1000
                            offset = 0
                            
                            while True:
                                result = client.supabase.table("fund_contributions")\
                                    .select("contributor, email")\
                                    .range(offset, offset + batch_size - 1)\
                                    .execute()
                                
                                if not result.data:
                                    break
                                
                                all_contribs.extend(result.data)
                                
                                if len(result.data) < batch_size:
                                    break
                                
                                offset += batch_size
                                if offset > 50000:
                                    break
                            
                            # Group by contributor name, get most common email
                            from collections import defaultdict
                            contrib_dict = defaultdict(lambda: {'emails': [], 'count': 0})
                            
                            for record in all_contribs:
                                name = record.get('contributor', '').strip()
                                email = record.get('email', '').strip() if record.get('email') else ""
                                if name:
                                    contrib_dict[name]['count'] += 1
                                    if email:
                                        contrib_dict[name]['emails'].append(email)
                            
                            # Add contributors from fund_contributions that aren't already in the list
                            for name, data in contrib_dict.items():
                                # Get most common email
                                emails = data['emails']
                                most_common_email = max(set(emails), key=emails.count) if emails else ""
                                
                                # Check if already added from contributors table
                                already_added = any(
                                    c['name'] == name and c['type'] == 'contributor' 
                                    for c in contributor_map.values()
                                )
                                
                                if not already_added:
                                    if most_common_email:
                                        display_label = f"{name} ({most_common_email}) [From Contributions]"
                                    else:
                                        display_label = f"{name} (no email) [From Contributions]"
                                    
                                    # Only add if not already in options
                                    if display_label not in contributor_options:
                                        contributor_options.append(display_label)
                                        contributor_map[display_label] = {
                                            'name': name,
                                            'id': None,  # No ID from fund_contributions
                                            'email': most_common_email,
                                            'is_user': False,
                                            'type': 'fund_contribution'
                                        }
                        except Exception as e:
                            st.warning(f"Could not load contributors from fund_contributions: {e}")
                        
                        # 3. Also add registered users who might not be contributors yet
                        for _, row in users_df.iterrows():
                            user_id = row['user_id']
                            full_name = row.get('full_name') or ""
                            email = row.get('email') or ""
                            
                            # Check if this user is already in the list as a contributor
                            already_listed = any(
                                c['email'] == email and email 
                                for c in contributor_map.values()
                            )
                            
                            if not already_listed:
                                if full_name and email:
                                    display_label = f"{full_name} ({email}) [Registered User]"
                                elif full_name:
                                    display_label = f"{full_name} (no email) [Registered User]"
                                elif email:
                                    display_label = f"{email} [Registered User]"
                                else:
                                    user_id_str = str(user_id)
                                    display_label = f"User {user_id_str[:8]}... (no name/email) [Registered User]"
                                
                                contributor_options.append(display_label)
                                contributor_map[display_label] = {
                                    'name': full_name or email or f"User {str(user_id)[:8]}",
                                    'id': user_id,
                                    'email': email,
                                    'is_user': True,
                                    'type': 'user'
                                }
                        
                        selected_contributor_display = st.selectbox(
                            "Select Contributor/User to Update",
                            options=contributor_options,
                            key="update_email_select"
                        )
                        
                        # Get the selected contributor info
                        selected_contributor = contributor_map.get(selected_contributor_display) if selected_contributor_display else None
                        current_contributor_email = selected_contributor.get('email') if selected_contributor else None
                    
                    with col_email2:
                        # Show current email and type if available
                        if selected_contributor:
                            contrib_type = selected_contributor.get('type', 'unknown')
                            if contrib_type == 'contributor':
                                st.caption("Type: Contributor (from contributors table)")
                            elif contrib_type == 'fund_contribution':
                                st.caption("Type: Contributor (from fund_contributions)")
                            elif contrib_type == 'user':
                                st.caption("Type: Registered User")
                            
                            if current_contributor_email:
                                st.caption(f"Current email: {current_contributor_email}")
                            else:
                                st.caption("Current email: None")
                        
                        new_user_email = st.text_input(
                            "New Email Address",
                            key="new_user_email",
                            placeholder="Enter new email address",
                            disabled=not selected_contributor
                        )
                    
                    if st.button("✏️ Update Email", type="primary", disabled=not can_modify_data()):
                        if not can_modify_data():
                            st.error("❌ Read-only admin cannot update contributor emails")
                            st.stop()
                        if not selected_contributor:
                            st.error("Please select a contributor/user to update")
                        elif not new_user_email:
                            st.error("Please enter a new email address")
                        elif current_contributor_email and current_contributor_email == new_user_email:
                            st.warning("New email must be different from current email")
                        else:
                            try:
                                # Validate email format
                                import re
                                email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                                if not re.match(email_pattern, new_user_email):
                                    st.error("Invalid email format")
                                else:
                                    contrib_type = selected_contributor.get('type')
                                    contrib_name = selected_contributor.get('name')
                                    contrib_id = selected_contributor.get('id')
                                    
                                    updates_made = []
                                    
                                    # Update based on type
                                    if contrib_type == 'contributor' and contrib_id:
                                        # Update contributors table
                                        try:
                                            client.supabase.table("contributors").update(
                                                {"email": new_user_email}
                                            ).eq("id", contrib_id).execute()
                                            updates_made.append("contributors table")
                                        except Exception as e:
                                            st.warning(f"Could not update contributors table: {e}")
                                    
                                    # Always update fund_contributions for this contributor name
                                    try:
                                        client.supabase.table("fund_contributions").update(
                                            {"email": new_user_email}
                                        ).eq("contributor", contrib_name).execute()
                                        updates_made.append("fund_contributions records")
                                    except Exception as e:
                                        st.warning(f"Could not update fund_contributions: {e}")
                                    
                                    # If it's a registered user, also update auth
                                    if contrib_type == 'user' and contrib_id:
                                        try:
                                            # Use service role client for admin operations
                                            supabase_url = os.getenv("SUPABASE_URL")
                                            service_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
                                            
                                            if supabase_url and service_key:
                                                admin_client = create_client(supabase_url, service_key)
                                                
                                                # Check if email already exists in auth.users
                                                users_response = admin_client.auth.admin.list_users()
                                                users_list = users_response if isinstance(users_response, list) else getattr(users_response, 'users', [])
                                                
                                                email_exists = False
                                                for u in users_list:
                                                    check_email = u.email if hasattr(u, 'email') else u.get('email') if isinstance(u, dict) else None
                                                    if check_email and check_email.lower() == new_user_email.lower():
                                                        # Check if it's the same user
                                                        check_id = u.id if hasattr(u, 'id') else u.get('id') if isinstance(u, dict) else None
                                                        if str(check_id) != str(contrib_id):
                                                            email_exists = True
                                                            break
                                                
                                                if email_exists:
                                                    st.error(f"Email {new_user_email} is already in use by another user")
                                                else:
                                                    # Update email in auth.users using admin API
                                                    update_response = admin_client.auth.admin.update_user_by_id(
                                                        contrib_id,
                                                        {"email": new_user_email}
                                                    )
                                                    
                                                    if update_response and update_response.user:
                                                        updates_made.append("auth.users")
                                                        
                                                        # Also update email in user_profiles table
                                                        try:
                                                            client.supabase.table("user_profiles").update(
                                                                {"email": new_user_email}
                                                            ).eq("user_id", contrib_id).execute()
                                                            updates_made.append("user_profiles")
                                                        except Exception as profile_error:
                                                            st.warning(f"Note: Could not update user_profiles: {profile_error}")
                                                    else:
                                                        st.error("Failed to update email in auth.users")
                                            else:
                                                st.warning("Admin credentials not configured - could not update auth.users")
                                        except Exception as auth_error:
                                            st.warning(f"Could not update auth.users: {auth_error}")
                                    
                                    if updates_made:
                                        # Clear caches
                                        st.cache_data.clear()
                                        display_name = selected_contributor_display.split(" (")[0] if " (" in selected_contributor_display else selected_contributor_display
                                        st.toast(f"✅ Email updated for {display_name} in: {', '.join(updates_made)}", icon="✅")
                                        st.rerun()
                                    else:
                                        st.error("No updates were made")
                            except Exception as e:
                                st.error(f"Error updating email: {e}")
                                import traceback
                                st.code(traceback.format_exc())
                else:
                    st.info("No users found")
            except Exception as e:
                st.error(f"Error loading users: {e}")

        
        # Unregistered contributors section
        st.divider()
        st.subheader("📨 Unregistered Contributors")
        st.caption("Contributors with fund contributions who haven't created an account yet")
        
        try:
            contrib_result = client.supabase.rpc('list_unregistered_contributors').execute()
            
            if contrib_result.data and len(contrib_result.data) > 0:
                contrib_df = pd.DataFrame(contrib_result.data)
                
                # Display contributors with invite buttons
                for idx, row in contrib_df.iterrows():
                    with st.container():
                        col_info, col_action = st.columns([3, 1])
                        
                        # Handle missing email
                        email_display = row['email'] if row.get('email') else "No Email"
                        has_email = bool(row.get('email'))
                        
                        with col_info:
                            funds_str = ", ".join(row['funds']) if row['funds'] else "None"
                            st.markdown(f"**{row['contributor']}** ({email_display})")
                            st.caption(f"Funds: {funds_str} | Contribution: ${row['total_contribution']:,.2f}")
                        
                        with col_action:
                            if has_email:
                                # Allow readonly_admin to send invite to themselves
                                invite_email = row['email']
                                can_send_invite = can_modify_data() or (invite_email == get_user_email())
                                if st.button("📧 Send Invite", key=f"invite_{idx}", disabled=not can_send_invite):
                                    if not can_send_invite:
                                        st.error("❌ Read-only admin can only send invites to themselves")
                                        st.stop()
                                    try:
                                        result = send_magic_link(invite_email)
                                        if result and result.get('success'):
                                            st.success(f"Invite sent to {row['email']}")
                                        else:
                                            error_msg = result.get('error', 'Unknown error') if result else 'Failed to send'
                                            st.error(f"Failed: {error_msg}")
                                    except Exception as e:
                                        st.error(f"Error: {e}")
                            else:
                                st.warning("⚠️ Add email to invite")
                        
                        st.divider()
            else:
                st.success("✅ All contributors have registered accounts!")
        except Exception as e:
            st.warning(f"Could not load unregistered contributors: {e}")
            st.info("You may need to run the `list_unregistered_contributors` SQL function in Supabase.")

# Tab 2: Contributor Access Management
with tab_access:
    st.header("🔐 Contributor Access Management")
    st.caption("Manage which users can view/manage which contributors' accounts")
    
    client = get_supabase_client()
    if not client:
        st.error("Failed to connect to database")
    else:
        try:
            # Check if contributors table exists
            # Try a simple query - if it fails, it could be missing table or RLS blocking
            has_contributors_table = False
            table_error = None
            try:
                # Try to query the table (even if empty, this should work if table exists)
                contributors_result = client.supabase.table("contributors").select("id").limit(1).execute()
                has_contributors_table = True
            except Exception as e:
                table_error = str(e)
                # Check if it's a "relation does not exist" error (table actually missing)
                if "does not exist" in table_error.lower() or "relation" in table_error.lower() or "42P01" in table_error:
                    st.warning("⚠️ Contributors table not found. Run migration DF_009 first.")
                else:
                    # Other error - could be RLS, permissions, or table exists but empty
                    # For admins, try to proceed anyway (they should have access)
                    if is_admin():
                        st.info("ℹ️ Note: Contributors table may exist but query returned no results or was blocked by RLS.")
                        st.info("💡 Proceeding anyway - you're admin so you should have access.")
                        has_contributors_table = True  # Assume it exists for admins
                    else:
                        st.warning(f"⚠️ Could not access contributors table: {table_error}")
                        st.info("💡 The table might exist but RLS is blocking access. Contact an admin.")
            
            if has_contributors_table:
                # Get all contributors (using cache)
                contributors_list = get_cached_contributors()
                
                # Get all users (using cache)
                users_list = get_cached_users()
                
                if contributors_list:
                    st.subheader("Grant Access")
                    st.caption("Allow a user to view/manage a contributor's account")
                    
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        # Contributor selector
                        contributor_options = {f"{c['name']} ({c['email'] or 'No email'})": c['id'] for c in contributors_list}
                        selected_contributor_display = st.selectbox(
                            "Contributor",
                            options=[""] + list(contributor_options.keys()),
                            key="grant_contributor"
                        )
                        selected_contributor_id = contributor_options.get(selected_contributor_display) if selected_contributor_display else None
                    
                    with col2:
                        # User selector
                        user_options = {u['email']: u['user_id'] for u in users_list if u.get('user_id')}
                        selected_user_email = st.selectbox(
                            "User Email",
                            options=[""] + list(user_options.keys()),
                            key="grant_user"
                        )
                        selected_user_id = user_options.get(selected_user_email) if selected_user_email else None
                    
                    with col3:
                        access_level = st.selectbox(
                            "Access Level",
                            options=["viewer", "manager", "owner"],
                            key="grant_access_level",
                            help="viewer: Can view data | manager: Can view and manage | owner: Full control"
                        )
                    
                    if st.button("🔐 Grant Access", type="primary"):
                        if not selected_contributor_id or not selected_user_id:
                            st.error("Please select both contributor and user")
                        else:
                            try:
                                result = client.supabase.rpc(
                                    'grant_contributor_access',
                                    {
                                        'contributor_email': next((c['email'] for c in contributors_list if c['id'] == selected_contributor_id), ''),
                                        'user_email': selected_user_email,
                                        'access_level': access_level
                                    }
                                ).execute()
                                
                                if result.data:
                                    result_data = result.data[0] if isinstance(result.data, list) else result.data
                                    if result_data.get('success'):
                                        st.toast(f"✅ {result_data.get('message')}", icon="✅")
                                        st.rerun()
                                    else:
                                        st.error(f"❌ {result_data.get('message')}")
                            except Exception as e:
                                st.error(f"Error granting access: {e}")
                    
                    st.divider()
                    
                    # View current access
                    st.subheader("Current Access")
                    st.caption("View all contributor-user access relationships")
                    
                    try:
                        access_result = client.supabase.table("contributor_access").select(
                            "id, contributor_id, user_id, access_level, granted_at"
                        ).execute()
                        
                        if access_result.data:
                            # Get contributor and user details
                            access_list = []
                            for access in access_result.data:
                                # Get contributor details
                                contrib = next((c for c in contributors_list if c['id'] == access['contributor_id']), {})
                                # Get user details
                                user = next((u for u in users_list if u.get('user_id') == access['user_id']), {})
                                
                                access_list.append({
                                    "Contributor": contrib.get('name', 'Unknown'),
                                    "Contributor Email": contrib.get('email', 'No email'),
                                    "User Email": user.get('email', 'Unknown'),
                                    "User Name": user.get('full_name', ''),
                                    "Access Level": access.get('access_level', 'viewer'),
                                    "Granted": access.get('granted_at', '')[:10] if access.get('granted_at') else ''
                                })
                            
                            access_df = pd.DataFrame(access_list)
                            display_dataframe_with_copy(access_df, label="Contributor Access", key_suffix="access", use_container_width=True)
                            
                            # Revoke access section
                            st.subheader("Revoke Access")
                            col_rev1, col_rev2 = st.columns(2)
                            
                            with col_rev1:
                                revoke_contributor = st.selectbox(
                                    "Contributor",
                                    options=[""] + list(contributor_options.keys()),
                                    key="revoke_contributor"
                                )
                            
                            with col_rev2:
                                revoke_user = st.selectbox(
                                    "User Email",
                                    options=[""] + list(user_options.keys()),
                                    key="revoke_user"
                                )
                            
                            if st.button("🚫 Revoke Access", type="secondary"):
                                if not revoke_contributor or not revoke_user:
                                    st.error("Please select both contributor and user")
                                else:
                                    try:
                                        revoke_contributor_id = contributor_options.get(revoke_contributor)
                                        result = client.supabase.rpc(
                                            'revoke_contributor_access',
                                            {
                                                'contributor_email': next((c['email'] for c in contributors_list if c['id'] == revoke_contributor_id), ''),
                                                'user_email': revoke_user
                                            }
                                        ).execute()
                                        
                                        if result.data:
                                            result_data = result.data[0] if isinstance(result.data, list) else result.data
                                            if result_data.get('success'):
                                                st.toast(f"✅ {result_data.get('message')}", icon="✅")
                                                st.rerun()
                                            else:
                                                st.error(f"❌ {result_data.get('message')}")
                                    except Exception as e:
                                        st.error(f"Error revoking access: {e}")
                        else:
                            st.info("No access records found. Grant access to link users to contributors.")
                    except Exception as e:
                        st.warning(f"Could not load access records: {e}")
                        st.info("Make sure the contributor_access table exists (run migration DF_009)")
                else:
                    st.info("No contributors found. Add contributors in the Contributions tab.")
        except Exception as e:
            st.error(f"Error loading contributor access: {e}")

