#!/usr/bin/env python3
"""
Set Browser Session Cookie
Logs in via API and provides instructions to set the session cookie in browser
"""

import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import os
import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
APP_DOMAIN = os.getenv("APP_DOMAIN")
if not APP_DOMAIN:
    print("[ERROR] APP_DOMAIN environment variable is required. Please set it in your .env file or environment.")
    sys.exit(1)


def login_and_get_token(email: str, password: str):
    """Login via API and return access token"""
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
            return auth_data.get("access_token")
        else:
            return None
    except Exception as e:
        print(f"Error: {e}")
        return None


if __name__ == "__main__":
    # Load credentials
    credentials_file = Path(__file__).parent / "test_credentials.json"
    if not credentials_file.exists():
        print("[ERROR] test_credentials.json not found")
        sys.exit(1)
    
    with open(credentials_file, 'r') as f:
        credentials = json.load(f)
    
    guest_email = credentials['guest']['email']
    guest_password = credentials['guest']['password']
    
    print("=" * 60)
    print("[INFO] Logging in as guest via API...")
    print("=" * 60)
    
    token = login_and_get_token(guest_email, guest_password)
    
    if token:
        print("\n[OK] Login successful!")
        print("\n[INFO] To set the session cookie in your browser:")
        print("=" * 60)
        print("\n1. Open browser DevTools (F12)")
        print("2. Go to Application/Storage tab")
        print("3. Click 'Cookies' in the left sidebar")
        print(f"4. Select the domain: {APP_DOMAIN}")
        print("5. Add a new cookie with:")
        print(f"   Name: auth_token")
        print(f"   Value: {token}")
        # Extract base domain (e.g., "example.com" from "app.example.com")
        base_domain = APP_DOMAIN.split('.', 1)[-1] if '.' in APP_DOMAIN else APP_DOMAIN
        print(f"   Domain: .{base_domain} (or {APP_DOMAIN})")
        print("   Path: /")
        print("   Secure: (check if HTTPS)")
        print("   HttpOnly: (leave unchecked)")
        print("   SameSite: Lax")
        print("\n6. Refresh the page")
        print("\n" + "=" * 60)
        print(f"\n[INFO] Or use this JavaScript in the browser console:")
        print("=" * 60)
        print(f"\ndocument.cookie = 'auth_token={token}; path=/; domain=.{base_domain}; SameSite=Lax';")
        print("location.reload();")
        print("\n" + "=" * 60)
    else:
        print("[ERROR] Login failed")
        sys.exit(1)

