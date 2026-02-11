import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()

def main():
    supabase_url = os.getenv("SUPABASE_URL")
    # Try multiple env var names for the service key
    service_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    
    if not supabase_url or not service_key:
        print("[ERROR] Missing SUPABASE_URL or SUPABASE_SECRET_KEY/SUPABASE_SERVICE_ROLE_KEY")
        return

    print(f"Connecting to {supabase_url}...")
    supabase = create_client(supabase_url, service_key)
    
    email = "guest.test@tradingbot.local"
    fund = "TFSA"
    
    print(f"Assigning {fund} to {email}...")
    
    # 1. Get User ID
    res = supabase.table("user_profiles").select("user_id").eq("email", email).execute()
    if not res.data:
        print("[ERROR] User not found in user_profiles")
        return
        
    user_id = res.data[0]['user_id']
    print(f"Found User ID: {user_id}")
    
    # 2. Assign Fund
    data = {
        "user_id": user_id,
        "fund_name": fund
    }
    
    res = supabase.table("user_funds").upsert(data, on_conflict="user_id,fund_name").execute()
    print(f"Result: {res.data}")
    print("[SUCCESS] Fund assigned.")

if __name__ == "__main__":
    main()
