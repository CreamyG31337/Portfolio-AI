#!/usr/bin/env python3
"""
Apply Supabase Schema for ETF AI Analysis
==========================================

Attempts to apply Supabase schema via RPC if available,
otherwise provides instructions for manual execution.
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from web_dashboard.supabase_client import SupabaseClient

# Load environment variables
env_path = project_root / "web_dashboard" / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()

def apply_supabase_schema():
    """Try to apply Supabase schema via RPC, or show instructions."""
    print("=" * 60)
    print("Applying Supabase Schema for ETF AI Analysis")
    print("=" * 60)
    
    try:
        client = SupabaseClient(use_service_role=True)
        print("[OK] Connected to Supabase")
    except Exception as e:
        print(f"[ERROR] Failed to connect to Supabase: {e}")
        print("\nPlease ensure SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are set")
        return False
    
    schema_files = [
        ("ETF Holdings Changes View", "database/schema/supabase/views/etf_holdings_changes_view.sql"),
        ("AI Analysis Queue Table", "database/schema/supabase/tables/ai_analysis_queue.sql"),
        ("AI Analysis Skip List Table", "database/schema/supabase/tables/ai_analysis_skip_list.sql"),
    ]
    
    success_count = 0
    
    for name, file_path in schema_files:
        full_path = project_root / file_path
        if not full_path.exists():
            print(f"\n[ERROR] File not found: {full_path}")
            continue
        
        print(f"\n[{success_count + 1}/{len(schema_files)}] Applying: {name}")
        
        with open(full_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()
        
        # Try RPC method if available
        try:
            # Try execute_sql RPC (common in Supabase)
            result = client.supabase.rpc('execute_sql', {'query': sql_content}).execute()
            print(f"[OK] Applied via RPC")
            success_count += 1
            continue
        except Exception as rpc_error:
            # Try exec_sql as fallback
            try:
                result = client.supabase.rpc('exec_sql', {'sql': sql_content}).execute()
                print(f"[OK] Applied via RPC (exec_sql)")
                success_count += 1
                continue
            except Exception:
                pass
        
        # RPC not available - show instructions
        print(f"[INFO] RPC method not available. Manual execution required.")
        print(f"\nSQL File: {full_path}")
        print("\n" + "=" * 60)
        print(f"SQL FOR: {name}")
        print("=" * 60)
        print(sql_content)
        print("=" * 60)
        print("\nPlease execute this SQL in Supabase SQL Editor or via psql")
    
    print("\n" + "=" * 60)
    if success_count == len(schema_files):
        print("[OK] All Supabase schema files applied successfully!")
    else:
        print(f"[INFO] {success_count}/{len(schema_files)} files applied automatically")
        print("       Remaining files require manual execution (see above)")
    print("=" * 60)
    
    return success_count == len(schema_files)

if __name__ == "__main__":
    success = apply_supabase_schema()
    sys.exit(0 if success else 1)
