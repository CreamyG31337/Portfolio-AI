#!/usr/bin/env python3
"""
Simple ETF AI Analysis Test
============================

Tests services without importing scheduler (avoids SQLAlchemy circular import).
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
web_dashboard_path = project_root / "web_dashboard"
sys.path.insert(1, str(web_dashboard_path))

from dotenv import load_dotenv

# Load environment variables
env_path = web_dashboard_path / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()

def test_supabase_schema():
    """Test if Supabase schema exists."""
    print("\n" + "=" * 60)
    print("Testing Supabase Schema")
    print("=" * 60)
    
    try:
        from supabase_client import SupabaseClient
        supabase = SupabaseClient(use_service_role=True)
        
        # Test view
        print("\n[1/3] Testing etf_holdings_changes view...")
        try:
            result = supabase.supabase.from_('etf_holdings_changes') \
                .select('*') \
                .limit(1) \
                .execute()
            print("[OK] View exists and is queryable")
            view_ok = True
        except Exception as e:
            print(f"[ERROR] View not found: {e}")
            print("   → Need to run: database/schema/supabase/views/etf_holdings_changes_view.sql")
            view_ok = False
        
        # Test queue table
        print("\n[2/3] Testing ai_analysis_queue table...")
        try:
            result = supabase.supabase.table('ai_analysis_queue') \
                .select('*') \
                .limit(1) \
                .execute()
            print("[OK] Table exists and is queryable")
            queue_ok = True
        except Exception as e:
            print(f"[ERROR] Table not found: {e}")
            print("   → Need to run: database/schema/supabase/tables/ai_analysis_queue.sql")
            queue_ok = False
        
        # Test skip list table
        print("\n[3/3] Testing ai_analysis_skip_list table...")
        try:
            result = supabase.supabase.table('ai_analysis_skip_list') \
                .select('*') \
                .limit(1) \
                .execute()
            print("[OK] Table exists and is queryable")
            skip_ok = True
        except Exception as e:
            print(f"[ERROR] Table not found: {e}")
            print("   → Need to run: database/schema/supabase/tables/ai_analysis_skip_list.sql")
            skip_ok = False
        
        return view_ok and queue_ok and skip_ok
        
    except Exception as e:
        print(f"[ERROR] Failed to connect to Supabase: {e}")
        return False

def test_research_db_schema():
    """Test if Research DB schema exists."""
    print("\n" + "=" * 60)
    print("Testing Research DB Schema")
    print("=" * 60)
    
    try:
        from postgres_client import PostgresClient
        postgres = PostgresClient()
        
        print("\n[1/1] Testing ticker_analysis table...")
        result = postgres.execute_query("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
              AND table_name = 'ticker_analysis'
        """)
        
        if result:
            print("[OK] Table exists")
            return True
        else:
            print("[ERROR] Table not found")
            print("   → Need to run: database/schema/research/tables/ticker_analysis.sql")
            return False
            
    except Exception as e:
        print(f"[ERROR] Failed to connect to Research DB: {e}")
        return False

def test_services_direct():
    """Test services without scheduler imports."""
    print("\n" + "=" * 60)
    print("Testing Services (Direct Import)")
    print("=" * 60)
    
    try:
        print("\n[1/2] Testing ETF Group Analysis Service...")
        # Import without scheduler dependency
        from supabase_client import SupabaseClient
        from postgres_client import PostgresClient
        from ollama_client import get_ollama_client
        from research_repository import ResearchRepository
        
        # Import ETF_NAMES directly to avoid scheduler import
        ETF_NAMES = {
            "ARKK": "ARK Innovation ETF",
            "ARKQ": "ARK Autonomous Technology & Robotics ETF",
            "ARKW": "ARK Next Generation Internet ETF",
            "ARKG": "ARK Genomic Revolution ETF",
            "ARKF": "ARK Fintech Innovation ETF",
            "ARKX": "ARK Space Exploration & Innovation ETF",
            "IZRL": "ARK Israel Innovative Technology ETF",
            "PRNT": "The 3D Printing ETF",
            "IVV": "iShares Core S&P 500 ETF",
            "IWM": "iShares Russell 2000 ETF",
            "IWC": "iShares Micro-Cap ETF",
            "IWO": "iShares Russell 2000 Growth ETF",
        }
        
        # Temporarily patch ETF_NAMES in the module
        import etf_group_analysis
        etf_group_analysis.ETF_NAMES = ETF_NAMES
        
        from etf_group_analysis import ETFGroupAnalysisService
        
        supabase = SupabaseClient(use_service_role=True)
        postgres = PostgresClient()
        ollama = get_ollama_client()
        repo = ResearchRepository(postgres_client=postgres)
        
        service = ETFGroupAnalysisService(ollama, supabase, repo)
        print("[OK] Service created successfully")
        
        print("\n[2/2] Testing Ticker Analysis Service...")
        from ai_skip_list_manager import AISkipListManager
        from ticker_analysis_service import TickerAnalysisService
        
        skip_list = AISkipListManager(supabase)
        service2 = TickerAnalysisService(ollama, supabase, postgres, skip_list)
        print("[OK] Service created successfully")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Service test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests."""
    print("=" * 60)
    print("ETF AI Analysis - Simple Test Suite")
    print("=" * 60)
    
    results = []
    
    # Test schemas
    results.append(("Supabase Schema", test_supabase_schema()))
    results.append(("Research DB Schema", test_research_db_schema()))
    
    # Test services
    results.append(("Services (Direct)", test_services_direct()))
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "[OK]" if result else "[FAIL]"
        print(f"{status} {name}")
    
    print(f"\n{passed}/{total} tests passed")
    
    if passed == total:
        print("\n✅ All tests passed! Ready to run jobs.")
    else:
        print("\n[WARNING] Some tests failed.")
        print("\nNEXT STEPS:")
        print("1. Apply Supabase schema files:")
        print("   - database/schema/supabase/views/etf_holdings_changes_view.sql")
        print("   - database/schema/supabase/tables/ai_analysis_queue.sql")
        print("   - database/schema/supabase/tables/ai_analysis_skip_list.sql")
        print("\n2. Re-run this test to verify")
        print("\n3. Then test the actual jobs")

if __name__ == "__main__":
    main()
