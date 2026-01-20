#!/usr/bin/env python3
"""
Debug Flask/Supabase Auth.uid() Issue
======================================

This script reproduces the issue where auth.uid() returns NULL in SQL functions
even though the Authorization header is correctly set.

Run this script to diagnose:
1. JWT token format and claims
2. PostgREST header handling
3. Direct SQL execution with and without auth
4. Compare behavior between different auth methods

Usage:
    cd web_dashboard
    python debug/debug_flask_auth.py

Or with a specific token:
    python debug/debug_flask_auth.py --token "your_jwt_token_here"
"""

import os
import sys
import json
import time
import base64
import argparse
import logging
from typing import Optional, Dict, Any

# Add web_dashboard to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment
from dotenv import load_dotenv
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Colors for output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def decode_jwt(token: str) -> Optional[Dict]:
    """Decode JWT token without verification (for inspection)"""
    try:
        parts = token.split('.')
        if len(parts) < 2:
            print(f"{Colors.RED}❌ Token is not a valid JWT (needs at least 2 parts){Colors.RESET}")
            return None
        
        payload = parts[1]
        # Add padding
        payload += '=' * (4 - len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception as e:
        print(f"{Colors.RED}❌ Failed to decode JWT: {e}{Colors.RESET}")
        return None


def inspect_jwt(token: str) -> Dict:
    """Deeply inspect JWT token for PostgREST compatibility"""
    print(f"\n{Colors.BOLD}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.CYAN}JWT TOKEN INSPECTION{Colors.RESET}")
    print(f"{'=' * 80}")
    
    info = {
        "token_length": len(token),
        "parts": len(token.split('.')),
        "valid": False,
        "claims": {}
    }
    
    print(f"\nToken length: {len(token)} chars")
    print(f"Token parts: {len(token.split('.'))}")
    print(f"Token preview: {token[:50]}...{token[-20:]}")
    
    claims = decode_jwt(token)
    if not claims:
        return info
    
    info["valid"] = True
    info["claims"] = claims
    
    print(f"\n{Colors.BOLD}JWT Claims:{Colors.RESET}")
    for key, value in sorted(claims.items()):
        color = Colors.GREEN
        if key in ['sub', 'email', 'role', 'aud', 'exp', 'iat']:
            color = Colors.CYAN
        print(f"  {color}{key}{Colors.RESET}: {value}")
    
    # Check required claims for PostgREST
    print(f"\n{Colors.BOLD}PostgREST Required Claims Check:{Colors.RESET}")
    
    required = ['sub', 'role', 'exp']
    for claim in required:
        if claim in claims:
            print(f"  {Colors.GREEN}✓ {claim}{Colors.RESET}: {claims[claim]}")
        else:
            print(f"  {Colors.RED}✗ {claim}{Colors.RESET}: MISSING!")
            info["valid"] = False
    
    # Check expiration
    if 'exp' in claims:
        exp_time = claims['exp']
        current_time = int(time.time())
        remaining = exp_time - current_time
        if remaining > 0:
            print(f"  {Colors.GREEN}✓ Token expires in {remaining}s ({remaining // 60}m){Colors.RESET}")
        else:
            print(f"  {Colors.RED}✗ Token EXPIRED {abs(remaining)}s ago{Colors.RESET}")
            info["valid"] = False
    
    # Check role
    if 'role' in claims:
        role = claims['role']
        if role in ['authenticated', 'service_role', 'anon']:
            print(f"  {Colors.GREEN}✓ Role '{role}' is valid for PostgREST{Colors.RESET}")
        else:
            print(f"  {Colors.YELLOW}⚠ Role '{role}' may not be recognized by PostgREST{Colors.RESET}")
    
    # Check aud (audience) - Supabase requires this
    if 'aud' in claims:
        aud = claims['aud']
        if aud == 'authenticated':
            print(f"  {Colors.GREEN}✓ Audience '{aud}' matches Supabase expectation{Colors.RESET}")
        else:
            print(f"  {Colors.YELLOW}⚠ Audience '{aud}' - Supabase typically expects 'authenticated'{Colors.RESET}")
    
    return info


def test_rpc_with_postgrest_client(token: str, user_id: str):
    """Test RPC using the Supabase Python client's postgrest"""
    print(f"\n{Colors.BOLD}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.CYAN}TEST: SupabaseClient.rpc() Method{Colors.RESET}")
    print(f"{'=' * 80}")
    
    try:
        from supabase_client import SupabaseClient
        
        # Create client with user token
        print(f"\nCreating SupabaseClient with user_token...")
        client = SupabaseClient(user_token=token)
        
        # Check if token was stored
        if hasattr(client, '_user_token') and client._user_token:
            print(f"  {Colors.GREEN}✓ Token stored in client._user_token{Colors.RESET}")
        else:
            print(f"  {Colors.RED}✗ Token NOT stored in client._user_token{Colors.RESET}")
        
        # Check postgrest headers before call
        if hasattr(client.supabase, 'postgrest'):
            postgrest = client.supabase.postgrest
            if hasattr(postgrest, 'session') and hasattr(postgrest.session, 'headers'):
                auth_header = postgrest.session.headers.get('Authorization', '')
                if auth_header:
                    print(f"  {Colors.GREEN}✓ Authorization header present: {auth_header[:30]}...{Colors.RESET}")
                else:
                    print(f"  {Colors.RED}✗ Authorization header NOT present in postgrest.session.headers{Colors.RESET}")
        
        # Test get_user_preferences (doesn't require user_uuid)
        print(f"\n--- Test 1: get_user_preferences (uses auth.uid()) ---")
        try:
            result = client.rpc('get_user_preferences', {})
            print(f"  Result type: {type(result.data).__name__}")
            print(f"  Result data: {result.data}")
            if result.data:
                print(f"  {Colors.GREEN}✓ SUCCESS - auth.uid() working!{Colors.RESET}")
            else:
                print(f"  {Colors.YELLOW}⚠ Returned empty/NULL - auth.uid() might be NULL{Colors.RESET}")
        except Exception as e:
            print(f"  {Colors.RED}✗ Error: {e}{Colors.RESET}")
        
        # Test set_user_preference WITHOUT passing user_uuid
        print(f"\n--- Test 2: set_user_preference WITHOUT user_uuid (relies on auth.uid()) ---")
        try:
            result = client.rpc('set_user_preference', {
                'pref_key': 'debug_test_key',
                'pref_value': json.dumps('debug_test_value_' + str(int(time.time())))
            })
            print(f"  Result type: {type(result.data).__name__}")
            print(f"  Result data: {result.data}")
            if result.data is True:
                print(f"  {Colors.GREEN}✓ SUCCESS - auth.uid() working!{Colors.RESET}")
            elif result.data is False:
                print(f"  {Colors.RED}✗ FAILED - auth.uid() returned NULL{Colors.RESET}")
            else:
                print(f"  {Colors.YELLOW}⚠ Unexpected result{Colors.RESET}")
        except Exception as e:
            print(f"  {Colors.RED}✗ Error: {e}{Colors.RESET}")
        
        # Test set_user_preference WITH explicit user_uuid
        print(f"\n--- Test 3: set_user_preference WITH explicit user_uuid ---")
        try:
            result = client.rpc('set_user_preference', {
                'pref_key': 'debug_test_key',
                'pref_value': json.dumps('debug_test_value_explicit_' + str(int(time.time()))),
                'user_uuid': user_id
            })
            print(f"  Result type: {type(result.data).__name__}")
            print(f"  Result data: {result.data}")
            if result.data is True:
                print(f"  {Colors.GREEN}✓ SUCCESS with explicit user_uuid{Colors.RESET}")
            else:
                print(f"  {Colors.RED}✗ FAILED even with explicit user_uuid{Colors.RESET}")
        except Exception as e:
            print(f"  {Colors.RED}✗ Error: {e}{Colors.RESET}")
        
    except Exception as e:
        print(f"{Colors.RED}✗ Failed to create SupabaseClient: {e}{Colors.RESET}")
        import traceback
        traceback.print_exc()


def test_direct_http_request(token: str, user_id: str):
    """Test RPC using direct HTTP requests (bypassing Python client)"""
    print(f"\n{Colors.BOLD}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.CYAN}TEST: Direct HTTP Request to PostgREST{Colors.RESET}")
    print(f"{'=' * 80}")
    
    import requests
    
    supabase_url = os.getenv("SUPABASE_URL")
    anon_key = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    
    if not supabase_url or not anon_key:
        print(f"{Colors.RED}✗ SUPABASE_URL or SUPABASE_PUBLISHABLE_KEY not set{Colors.RESET}")
        return
    
    # Test 1: get_user_preferences
    print(f"\n--- Test 1: get_user_preferences ---")
    try:
        response = requests.post(
            f"{supabase_url}/rest/v1/rpc/get_user_preferences",
            headers={
                "apikey": anon_key,
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={}
        )
        print(f"  Status: {response.status_code}")
        print(f"  Response: {response.text[:500]}")
        if response.status_code == 200 and response.json():
            print(f"  {Colors.GREEN}✓ SUCCESS{Colors.RESET}")
        else:
            print(f"  {Colors.YELLOW}⚠ Empty response - check logs{Colors.RESET}")
    except Exception as e:
        print(f"  {Colors.RED}✗ Error: {e}{Colors.RESET}")
    
    # Test 2: set_user_preference WITHOUT user_uuid
    print(f"\n--- Test 2: set_user_preference WITHOUT user_uuid ---")
    try:
        response = requests.post(
            f"{supabase_url}/rest/v1/rpc/set_user_preference",
            headers={
                "apikey": anon_key,
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={
                "pref_key": "debug_http_test",
                "pref_value": json.dumps("http_value_" + str(int(time.time())))
            }
        )
        print(f"  Status: {response.status_code}")
        print(f"  Response: {response.text}")
        if response.status_code == 200 and response.json() is True:
            print(f"  {Colors.GREEN}✓ SUCCESS - auth.uid() working via HTTP!{Colors.RESET}")
        elif response.status_code == 200 and response.json() is False:
            print(f"  {Colors.RED}✗ FAILED - auth.uid() returned NULL{Colors.RESET}")
        else:
            print(f"  {Colors.YELLOW}⚠ Unexpected response{Colors.RESET}")
    except Exception as e:
        print(f"  {Colors.RED}✗ Error: {e}{Colors.RESET}")
    
    # Test 3: set_user_preference WITH explicit user_uuid
    print(f"\n--- Test 3: set_user_preference WITH user_uuid ---")
    try:
        response = requests.post(
            f"{supabase_url}/rest/v1/rpc/set_user_preference",
            headers={
                "apikey": anon_key,
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={
                "pref_key": "debug_http_test",
                "pref_value": json.dumps("http_value_explicit_" + str(int(time.time()))),
                "user_uuid": user_id
            }
        )
        print(f"  Status: {response.status_code}")
        print(f"  Response: {response.text}")
        if response.status_code == 200 and response.json() is True:
            print(f"  {Colors.GREEN}✓ SUCCESS with explicit user_uuid{Colors.RESET}")
        else:
            print(f"  {Colors.RED}✗ FAILED{Colors.RESET}")
    except Exception as e:
        print(f"  {Colors.RED}✗ Error: {e}{Colors.RESET}")


def test_auth_uid_directly(token: str):
    """Test auth.uid() directly via a simple RPC call"""
    print(f"\n{Colors.BOLD}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.CYAN}TEST: Direct auth.uid() Check via SQL{Colors.RESET}")
    print(f"{'=' * 80}")
    
    import requests
    
    supabase_url = os.getenv("SUPABASE_URL")
    anon_key = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    
    # The is_admin function uses auth.uid() - let's see what it returns
    print(f"\n--- Calling is_admin() which uses auth.uid() internally ---")
    try:
        # First, decode the token to get the user_id
        claims = decode_jwt(token)
        user_id = claims.get('sub') if claims else None
        
        # Call is_admin with the user_uuid
        response = requests.post(
            f"{supabase_url}/rest/v1/rpc/is_admin",
            headers={
                "apikey": anon_key,
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={"user_uuid": user_id}
        )
        print(f"  Status: {response.status_code}")
        print(f"  Response: {response.text}")
    except Exception as e:
        print(f"  {Colors.RED}✗ Error: {e}{Colors.RESET}")


def get_token_from_test_login():
    """Try to get a fresh token by logging in with test credentials"""
    print(f"\n{Colors.BOLD}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.CYAN}ATTEMPTING TEST LOGIN{Colors.RESET}")
    print(f"{'=' * 80}")
    
    import requests
    
    # Try to read test credentials
    creds_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'test_credentials.json')
    if not os.path.exists(creds_file):
        print(f"  {Colors.YELLOW}No test_credentials.json found{Colors.RESET}")
        return None, None
    
    try:
        with open(creds_file) as f:
            creds = json.load(f)
        
        email = creds.get('email') or creds.get('test_email')
        password = creds.get('password') or creds.get('test_password')
        
        if not email or not password:
            print(f"  {Colors.YELLOW}Credentials file missing email/password{Colors.RESET}")
            return None, None
        
        supabase_url = os.getenv("SUPABASE_URL")
        anon_key = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
        
        print(f"  Logging in as: {email}")
        
        response = requests.post(
            f"{supabase_url}/auth/v1/token?grant_type=password",
            headers={
                "apikey": anon_key,
                "Content-Type": "application/json"
            },
            json={
                "email": email,
                "password": password
            }
        )
        
        if response.status_code == 200:
            auth_data = response.json()
            token = auth_data.get('access_token')
            user = auth_data.get('user', {})
            user_id = user.get('id')
            print(f"  {Colors.GREEN}✓ Login successful!{Colors.RESET}")
            print(f"  User ID: {user_id}")
            return token, user_id
        else:
            print(f"  {Colors.RED}✗ Login failed: {response.text}{Colors.RESET}")
            return None, None
            
    except Exception as e:
        print(f"  {Colors.RED}✗ Error: {e}{Colors.RESET}")
        return None, None


def main():
    parser = argparse.ArgumentParser(description='Debug Flask/Supabase auth.uid() issue')
    parser.add_argument('--token', help='JWT token to test (base64 encoded)')
    parser.add_argument('--user-id', help='User UUID (extracted from token if not provided)')
    parser.add_argument('--login', action='store_true', help='Attempt test login to get fresh token')
    args = parser.parse_args()
    
    print(f"{Colors.BOLD}")
    print("=" * 80)
    print("  FLASK SUPABASE AUTH.UID() DEBUG TOOL")
    print("=" * 80)
    print(f"{Colors.RESET}")
    
    token = args.token
    user_id = args.user_id
    
    # If no token provided, try test login
    if not token:
        if args.login or not token:
            token, user_id = get_token_from_test_login()
    
    if not token:
        print(f"\n{Colors.RED}No token available. Please either:")
        print(f"  1. Pass --token 'your_jwt_token'")
        print(f"  2. Create test_credentials.json with email/password")
        print(f"  3. Set up proper test authentication{Colors.RESET}")
        sys.exit(1)
    
    # Inspect the JWT
    jwt_info = inspect_jwt(token)
    
    # Extract user_id if not provided
    if not user_id and jwt_info.get('valid'):
        user_id = jwt_info['claims'].get('sub')
        print(f"\nExtracted user_id from token: {user_id}")
    
    if not user_id:
        print(f"\n{Colors.RED}Could not determine user_id{Colors.RESET}")
        sys.exit(1)
    
    # Run tests
    test_auth_uid_directly(token)
    test_direct_http_request(token, user_id)
    test_rpc_with_postgrest_client(token, user_id)
    
    print(f"\n{Colors.BOLD}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.CYAN}SUMMARY{Colors.RESET}")
    print(f"{'=' * 80}")
    print(f"""
If the direct HTTP test SUCCEEDS but SupabaseClient.rpc() FAILS:
  → Problem is in Python client header setting
  
If both tests show auth.uid() = NULL:
  → Problem is in JWT format or PostgREST JWT configuration
  
If tests with explicit user_uuid SUCCEED but without FAIL:
  → auth.uid() is not being populated from Authorization header
  
Check Supabase Dashboard → Logs → Edge Functions / PostgREST for more details.
""")


if __name__ == "__main__":
    main()
