#!/usr/bin/env python3
"""
Test ETF AI Analysis Jobs
==========================

Tests the ETF group analysis and ticker analysis jobs to identify any errors.
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
        except Exception as e:
            print(f"[ERROR] View not found or not accessible: {e}")
            print("   → Need to run: database/schema/supabase/views/etf_holdings_changes_view.sql")
            return False
        
        # Test queue table
        print("\n[2/3] Testing ai_analysis_queue table...")
        try:
            result = supabase.supabase.table('ai_analysis_queue') \
                .select('*') \
                .limit(1) \
                .execute()
            print("[OK] Table exists and is queryable")
        except Exception as e:
            print(f"[ERROR] Table not found: {e}")
            print("   → Need to run: database/schema/supabase/tables/ai_analysis_queue.sql")
            return False
        
        # Test skip list table
        print("\n[3/3] Testing ai_analysis_skip_list table...")
        try:
            result = supabase.supabase.table('ai_analysis_skip_list') \
                .select('*') \
                .limit(1) \
                .execute()
            print("[OK] Table exists and is queryable")
        except Exception as e:
            print(f"[ERROR] Table not found: {e}")
            print("   → Need to run: database/schema/supabase/tables/ai_analysis_skip_list.sql")
            return False
        
        return True
        
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

def test_etf_group_analysis_service():
    """Test ETF group analysis service initialization."""
    print("\n" + "=" * 60)
    print("Testing ETF Group Analysis Service")
    print("=" * 60)
    
    try:
        from supabase_client import SupabaseClient
        from postgres_client import PostgresClient
        from ollama_client import get_ollama_client
        from research_repository import ResearchRepository
        from etf_group_analysis import ETFGroupAnalysisService
        
        print("\n[1/4] Initializing clients...")
        supabase = SupabaseClient(use_service_role=True)
        postgres = PostgresClient()
        ollama = get_ollama_client()
        repo = ResearchRepository(postgres_client=postgres)
        
        if not ollama:
            print("[WARNING] Ollama not available - service will work but can't analyze")
        
        print("[OK] Clients initialized")
        
        print("\n[2/4] Creating service...")
        service = ETFGroupAnalysisService(ollama, supabase, repo)
        print("[OK] Service created")
        
        print("\n[3/4] Testing get_changes_for_date (sample ETF/date)...")
        # Try to get changes for a recent date
        today = datetime.now(timezone.utc).date()
        test_etf = "IWC"  # Common ETF
        
        changes = service.get_changes_for_date(test_etf, datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc))
        print(f"[OK] Query executed. Found {len(changes)} changes for {test_etf} on {today}")
        
        if changes:
            print(f"   Sample change: {changes[0]}")
        
        print("\n[4/4] Testing format_changes_for_llm...")
        if changes:
            formatted = service.format_changes_for_llm(changes[:5])  # Just test with 5
            print(f"[OK] Formatting works. Output length: {len(formatted)} chars")
        else:
            print("[INFO] No changes to format (this is OK)")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Service test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_ticker_analysis_service():
    """Test ticker analysis service initialization."""
    print("\n" + "=" * 60)
    print("Testing Ticker Analysis Service")
    print("=" * 60)
    
    try:
        from supabase_client import SupabaseClient
        from postgres_client import PostgresClient
        from ollama_client import get_ollama_client
        from ai_skip_list_manager import AISkipListManager
        from ticker_analysis_service import TickerAnalysisService
        
        print("\n[1/5] Initializing clients...")
        supabase = SupabaseClient(use_service_role=True)
        postgres = PostgresClient()
        ollama = get_ollama_client()
        
        if not ollama:
            print("[WARNING] Ollama not available - service will work but can't analyze")
        
        print("[OK] Clients initialized")
        
        print("\n[2/5] Creating skip list manager...")
        skip_list = AISkipListManager(supabase)
        print("[OK] Skip list manager created")
        
        print("\n[3/5] Creating service...")
        service = TickerAnalysisService(ollama, supabase, postgres, skip_list)
        print("[OK] Service created")
        
        print("\n[4/5] Testing get_tickers_to_analyze...")
        tickers = service.get_tickers_to_analyze()
        print(f"[OK] Found {len(tickers)} tickers to analyze")
        if tickers:
            print(f"   Sample: {tickers[0]} (priority={tickers[0][1]})")
        
        print("\n[5/5] Testing gather_ticker_data (sample ticker)...")
        if tickers:
            test_ticker = tickers[0][0]
            print(f"   Testing with ticker: {test_ticker}")
            data = service.gather_ticker_data(test_ticker)
            print(f"[OK] Data gathered:")
            print(f"   - Fundamentals: {'Yes' if data.get('fundamentals') else 'No'}")
            print(f"   - ETF changes: {len(data.get('etf_changes', []))}")
            print(f"   - Congress trades: {len(data.get('congress_trades', []))}")
            print(f"   - Signals: {'Yes' if data.get('signals') else 'No'}")
            print(f"   - Research articles: {len(data.get('research_articles', []))}")
        else:
            print("[INFO] No tickers to test with (this is OK)")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Service test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_job_functions():
    """Test job functions can be imported and called."""
    print("\n" + "=" * 60)
    print("Testing Job Functions")
    print("=" * 60)
    
    try:
        print("\n[1/2] Testing ETF group analysis job import...")
        from scheduler.jobs_etf_analysis import etf_group_analysis_job
        print("[OK] Job function imported")
        
        print("\n[2/2] Testing ticker analysis job import...")
        from scheduler.jobs_ticker_analysis import ticker_analysis_job
        print("[OK] Job function imported")
        
        print("\n[INFO] Job functions are importable. To actually run them:")
        print("   - ETF Group: from scheduler.jobs_etf_analysis import etf_group_analysis_job; etf_group_analysis_job()")
        print("   - Ticker: from scheduler.jobs_ticker_analysis import ticker_analysis_job; ticker_analysis_job()")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Job import failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests."""
    print("=" * 60)
    print("ETF AI Analysis Jobs - Test Suite")
    print("=" * 60)
    
    results = []
    
    # Test schemas
    results.append(("Supabase Schema", test_supabase_schema()))
    results.append(("Research DB Schema", test_research_db_schema()))
    
    # Test services
    results.append(("ETF Group Analysis Service", test_etf_group_analysis_service()))
    results.append(("Ticker Analysis Service", test_ticker_analysis_service()))
    
    # Test jobs
    results.append(("Job Functions", test_job_functions()))
    
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
        print("\n✅ All tests passed! Jobs should be ready to run.")
    else:
        print("\n⚠️  Some tests failed. Fix issues before running jobs.")
        print("\nNext steps:")
        print("1. Apply missing Supabase schema files if needed")
        print("2. Fix any import or initialization errors")
        print("3. Re-run this test script")

if __name__ == "__main__":
    main()
