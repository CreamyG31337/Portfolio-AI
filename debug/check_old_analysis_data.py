#!/usr/bin/env python3
"""
Check Old Analysis Data
=======================
Checks if there's old conflict_score data in Supabase that needs migrating to PostgreSQL
"""

import sys
import io
from pathlib import Path
from datetime import datetime, timezone

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

from supabase_client import SupabaseClient
from postgres_client import PostgresClient

def check_old_analysis():
    """Check for old analysis data that needs migrating."""
    supabase = SupabaseClient(use_service_role=True)
    
    print("\n" + "=" * 80)
    print("CHECKING FOR OLD ANALYSIS DATA")
    print("=" * 80)
    print()
    
    # Check Supabase for trades with conflict_score
    print("1. Checking Supabase congress_trades table for conflict_score values...")
    result = supabase.supabase.table('congress_trades')\
        .select('id, conflict_score, notes')\
        .not_.is_('conflict_score', 'null')\
        .limit(100)\
        .execute()
    
    supabase_trades_with_score = len(result.data) if result.data else 0
    print(f"   Found {supabase_trades_with_score} trades with conflict_score in Supabase")
    
    if result.data:
        print("\n   Sample trades with conflict_score:")
        for i, trade in enumerate(result.data[:5], 1):
            trade_id = trade.get('id', 'N/A')
            score = trade.get('conflict_score', 'N/A')
            notes = trade.get('notes', '')[:50] if trade.get('notes') else 'N/A'
            print(f"      {i}. Trade ID {trade_id}: score={score}, notes={notes[:50]}...")
    
    # Check PostgreSQL for existing analysis
    print("\n2. Checking PostgreSQL congress_trades_analysis table...")
    try:
        postgres = PostgresClient()
        pg_result = postgres.execute_query(
            "SELECT COUNT(*) as count FROM congress_trades_analysis WHERE conflict_score IS NOT NULL"
        )
        pg_count = pg_result[0]['count'] if pg_result else 0
        print(f"   Found {pg_count} analysis records in PostgreSQL")
        
        # Check for trades that have Supabase conflict_score but NOT PostgreSQL analysis
        if result.data and supabase_trades_with_score > 0:
            print("\n3. Checking for trades with Supabase conflict_score but missing PostgreSQL analysis...")
            
            trade_ids = [t.get('id') for t in result.data if t.get('id')]
            if trade_ids:
                placeholders = ','.join(['%s'] * len(trade_ids))
                missing_result = postgres.execute_query(
                    f"SELECT trade_id FROM congress_trades_analysis WHERE trade_id IN ({placeholders})",
                    trade_ids
                )
                existing_ids = {r['trade_id'] for r in missing_result} if missing_result else set()
                missing_ids = [tid for tid in trade_ids if tid not in existing_ids]
                
                print(f"   Found {len(missing_ids)} trades with Supabase conflict_score but no PostgreSQL analysis")
                if missing_ids:
                    print(f"   Missing trade IDs: {missing_ids[:10]}{'...' if len(missing_ids) > 10 else ''}")
                    print("\n   ⚠️  These trades need to be migrated to PostgreSQL!")
                    print("   Recommendation: Create a migration script to copy conflict_score from Supabase to PostgreSQL")
    except Exception as e:
        print(f"   ⚠️  Could not check PostgreSQL: {e}")
        print("   (PostgreSQL might not be available)")
    
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()
    print("Current State:")
    print(f"  - Supabase trades with conflict_score: {supabase_trades_with_score}")
    print(f"  - PostgreSQL analysis records: {pg_count if 'pg_count' in locals() else 'N/A'}")
    print()
    print("Note: The UI reads from PostgreSQL congress_trades_analysis table.")
    print("      If there's data in Supabase conflict_score column, it won't show in the UI.")
    print()
    if supabase_trades_with_score > 0:
        print("⚠️  ACTION NEEDED:")
        print("   Consider migrating old Supabase conflict_score data to PostgreSQL")
        print("   OR delete it if it's outdated/duplicate")

if __name__ == "__main__":
    check_old_analysis()
