#!/usr/bin/env python3
"""Fix company name in securities table for VEE.TO."""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

from web_dashboard.supabase_client import SupabaseClient

def fix_vee_company_name():
    """Fix the long company name for VEE.TO in securities table."""
    print("Fixing VEE.TO company name in securities table...")
    print("=" * 60)
    
    # Initialize Supabase client with service role to bypass RLS
    client = SupabaseClient(use_service_role=True)
    
    if not client.supabase:
        print("ERROR: Failed to connect to Supabase")
        return
    
    print("Connected to Supabase")
    
    # Check current value
    result = client.supabase.table("securities")\
        .select("ticker, company_name")\
        .eq("ticker", "VEE.TO")\
        .execute()
    
    if result.data:
        current_name = result.data[0].get('company_name', '')
        print(f"\nCurrent company_name: {current_name}")
        print(f"   Length: {len(current_name)} characters")
    else:
        print("\nWARNING: VEE.TO not found in securities table")
        return
    
    # Correct name
    correct_name = "Vanguard FTSE Emerging Markets All Cap Index ETF"
    print(f"\nCorrect company_name: {correct_name}")
    print(f"   Length: {len(correct_name)} characters")
    
    # Update using upsert (as other scripts do)
    print("\nUpdating using upsert...")
    try:
        securities_data = [{
            'ticker': 'VEE.TO',
            'company_name': correct_name
        }]
        
        upsert_result = client.supabase.table("securities")\
            .upsert(securities_data, on_conflict="ticker")\
            .execute()
        
        if upsert_result.data:
            print(f"Upsert result: {len(upsert_result.data)} row(s) updated")
            print(f"Updated data: {upsert_result.data}")
        else:
            print("WARNING: Upsert returned no data - may not have updated")
        
        # Wait a moment for database to sync
        import time
        time.sleep(0.5)
        
        # Verify
        verify_result = client.supabase.table("securities")\
            .select("ticker, company_name")\
            .eq("ticker", "VEE.TO")\
            .execute()
        
        if verify_result.data:
            new_name = verify_result.data[0].get('company_name', '')
            print(f"\nVerified company_name: {new_name}")
            if new_name == correct_name:
                print("SUCCESS: Company name correctly updated!")
            else:
                print(f"WARNING: Expected '{correct_name}' but got '{new_name}'")
        
    except Exception as e:
        print(f"ERROR updating: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("Done!")

if __name__ == "__main__":
    fix_vee_company_name()
