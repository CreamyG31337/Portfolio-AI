#!/usr/bin/env python3
"""
Apply ETF AI Analysis Schema
============================

Applies the database schema for ETF AI analysis:
1. ETF holdings changes view (Supabase)
2. Ticker analysis table (Research DB)
3. AI analysis queue table (Supabase)
4. AI analysis skip list table (Supabase)
"""

import os
import sys
from pathlib import Path

# Repo root + web_dashboard (postgres_client imports env_loader as a top-level module)
project_root = Path(__file__).resolve().parent.parent.parent
web_dashboard_dir = project_root / "web_dashboard"
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(web_dashboard_dir))

from dotenv import load_dotenv

# Load environment variables
env_path = project_root / "web_dashboard" / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()

def apply_research_db_schema():
    """Apply ticker_analysis table to Research DB."""
    try:
        from postgres_client import PostgresClient
        
        print("\n[1/2] Applying Research DB schema (ticker_analysis table)...")
        
        research_db_url = os.getenv("RESEARCH_DATABASE_URL")
        if not research_db_url:
            print("[ERROR] RESEARCH_DATABASE_URL not set in environment")
            return False
        
        client = PostgresClient()
        if not client.test_connection():
            print("[ERROR] Failed to connect to Research DB")
            return False
        
        # Read and execute ticker_analysis.sql
        schema_file = project_root / "database" / "schema" / "research" / "tables" / "ticker_analysis.sql"
        if not schema_file.exists():
            print(f"[ERROR] Schema file not found: {schema_file}")
            return False
        
        with open(schema_file, 'r', encoding='utf-8') as f:
            sql_content = f.read()
        
        # Execute SQL
        with client.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql_content)
            conn.commit()
        
        print("[OK] ticker_analysis table created in Research DB")

        meta_file = project_root / "database" / "schema" / "research" / "tables" / "ticker_meta_analysis.sql"
        if meta_file.exists():
            with open(meta_file, "r", encoding="utf-8") as f:
                meta_sql = f.read()
            with client.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(meta_sql)
                conn.commit()
            print("[OK] ticker_meta_analysis table applied in Research DB")
        else:
            print(f"[WARN] Meta schema file missing: {meta_file}")

        for rel in (
            "database/schema/research/tables/market_daily_brief.sql",
            "database/schema/research/tables/ui_ai_summary.sql",
            "database/schema/research/tables/ui_ai_rollup_fund.sql",
            "database/schema/research/tables/action_queue_ai_review.sql",
        ):
            p = project_root / rel
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    sql = f.read()
                with client.get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute(sql)
                    conn.commit()
                print(f"[OK] Applied research schema: {p.name}")
            else:
                print(f"[WARN] Research schema file missing: {p}")

        return True
        
    except Exception as e:
        print(f"[ERROR] Failed to apply Research DB schema: {e}")
        import traceback
        traceback.print_exc()
        return False

def apply_supabase_schema():
    """Apply Supabase schema (view + tables).
    
    Note: Supabase Python client doesn't support direct SQL execution.
    This function prints instructions for manual execution.
    """
    print("\n[2/2] Supabase schema files (view + tables)...")
    print("\n[WARNING] Supabase Python client doesn't support direct SQL execution.")
    print("   Please apply these migrations using one of these methods:\n")
    
    schema_files = [
        ("ETF Holdings Changes View", "database/schema/supabase/views/etf_holdings_changes_view.sql"),
        ("AI Analysis Queue Table", "database/schema/supabase/tables/ai_analysis_queue.sql"),
        ("AI Analysis Skip List Table", "database/schema/supabase/tables/ai_analysis_skip_list.sql"),
    ]
    
    print("   METHOD 1: Supabase SQL Editor (Recommended)")
    print("   1. Go to your Supabase dashboard")
    print("   2. Navigate to SQL Editor")
    print("   3. Copy and paste each SQL file below\n")
    
    for name, file_path in schema_files:
        full_path = project_root / file_path
        if full_path.exists():
            print(f"   {name}:")
            print(f"   {full_path}\n")
            with open(full_path, 'r', encoding='utf-8') as f:
                sql_content = f.read()
            print("=" * 60)
            print(f"SQL FOR: {name}")
            print("=" * 60)
            print(sql_content)
            print("=" * 60)
            print()
    
    print("\n   METHOD 2: Supabase CLI")
    for name, file_path in schema_files:
        print(f"   supabase db execute -f {file_path}")
    
    print("\n   METHOD 3: Direct psql connection")
    print("   (If you have direct database access)")
    
    return True

def main():
    """Main execution."""
    print("=" * 60)
    print("ETF AI Analysis Schema Application")
    print("=" * 60)
    
    # Apply Research DB schema (can be done programmatically)
    research_success = apply_research_db_schema()
    
    # Show Supabase instructions (manual execution required)
    supabase_info = apply_supabase_schema()
    
    print("\n" + "=" * 60)
    if research_success:
        print("[OK] Research DB schema applied successfully")
    else:
        print("[ERROR] Research DB schema application failed")
    
    if supabase_info:
        print("[INFO] Supabase schema files ready for manual execution")
    print("=" * 60)
    
    return research_success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
