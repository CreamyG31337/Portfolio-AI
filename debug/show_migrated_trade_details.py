#!/usr/bin/env python3
"""
Show Migrated Trade Details
===========================
Shows details of a migrated trade so you can verify the migration worked correctly
"""

import sys
import io
from pathlib import Path

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
from settings import get_summarizing_model

def show_migrated_trade_details():
    """Show details of a migrated trade."""
    supabase = SupabaseClient(use_service_role=True)
    postgres = PostgresClient()
    
    print("\n" + "=" * 80)
    print("MIGRATED TRADE DETAILS")
    print("=" * 80)
    print()
    
    # Find a trade that has conflict_score in Supabase (old system) AND exists in PostgreSQL
    print("1. Finding a trade that was migrated from Supabase...")
    
    # First, get trades with conflict_score in Supabase
    supabase_trades = supabase.supabase.table('congress_trades')\
        .select('id, conflict_score, notes')\
        .not_.is_('conflict_score', 'null')\
        .limit(10)\
        .execute()
    
    if not supabase_trades.data:
        print("   ⚠️  No trades with conflict_score found in Supabase")
        return
    
    # Check which ones exist in PostgreSQL
    trade_ids = [t.get('id') for t in supabase_trades.data if t.get('id')]
    if not trade_ids:
        print("   ⚠️  No valid trade IDs found")
        return
    
    placeholders = ','.join(['%s'] * len(trade_ids))
    pg_result = postgres.execute_query(
        f"""
        SELECT trade_id, conflict_score, confidence_score, reasoning, model_used, analyzed_at
        FROM congress_trades_analysis 
        WHERE trade_id IN ({placeholders})
        LIMIT 1
        """,
        trade_ids
    )
    
    # Find first trade with conflict_score in Supabase
    trade_to_show = supabase_trades.data[0]
    trade_id = trade_to_show.get('id')
    
    # Check if it's already migrated
    pg_result = postgres.execute_query(
        """
        SELECT trade_id, conflict_score, confidence_score, reasoning, model_used, analyzed_at
        FROM congress_trades_analysis 
        WHERE trade_id = %s
        """,
        [trade_id]
    )
    
    if pg_result:
        migrated = pg_result[0]
        print(f"   Found migrated trade ID: {trade_id} (already in PostgreSQL)")
        is_migrated = True
    else:
        print(f"   Found trade ID: {trade_id} (NOT yet migrated - showing what WOULD be migrated)")
        is_migrated = False
        migrated = None
    
    print()
    
    # Get the original trade from Supabase
    print("2. Fetching original trade from Supabase...")
    supabase_result = supabase.supabase.table('congress_trades')\
        .select('id, ticker, politician_id, chamber, transaction_date, type, conflict_score, notes, created_at')\
        .eq('id', trade_id)\
        .execute()
    
    if not supabase_result.data:
        print(f"   ⚠️  Trade {trade_id} not found in Supabase")
        return
    
    original = supabase_result.data[0]
    
    print("=" * 80)
    print("ORIGINAL TRADE (Supabase)")
    print("=" * 80)
    print()
    print(f"Trade ID:     {original.get('id', 'N/A')}")
    print(f"Ticker:       {original.get('ticker', 'N/A')}")
    print(f"Politician ID: {original.get('politician_id', 'N/A')}")
    print(f"Chamber:      {original.get('chamber', 'N/A')}")
    print(f"Date:         {original.get('transaction_date', 'N/A')}")
    print(f"Type:         {original.get('type', 'N/A')}")
    print(f"Conflict Score: {original.get('conflict_score', 'N/A')}")
    print(f"Created At:   {original.get('created_at', 'N/A')}")
    print()
    print("Original Notes (from Supabase):")
    print("-" * 80)
    notes = original.get('notes', '')
    if notes:
        print(notes)
        print(f"\n(Length: {len(notes)} characters)")
    else:
        print("(Empty)")
    print()
    
    if is_migrated:
        print("=" * 80)
        print("MIGRATED ANALYSIS (PostgreSQL)")
        print("=" * 80)
        print()
        print(f"Trade ID:        {migrated['trade_id']}")
        print(f"Conflict Score:  {migrated['conflict_score']}")
        print(f"Confidence:      {migrated['confidence_score']}")
        print(f"Model Used:      {migrated['model_used']}")
        print(f"Analyzed At:     {migrated['analyzed_at']}")
        print()
        print("AI Reasoning (migrated to PostgreSQL):")
        print("-" * 80)
        reasoning = migrated.get('reasoning', '')
        if reasoning:
            print(reasoning)
            print(f"\n(Length: {len(reasoning)} characters)")
        else:
            print("(Empty)")
        print()
    else:
        print("=" * 80)
        print("WHAT WOULD BE MIGRATED (Preview)")
        print("=" * 80)
        print()
        print("If migration runs, this would be saved to PostgreSQL:")
        print()
        print(f"Trade ID:        {trade_id}")
        print(f"Conflict Score:  {trade_to_show.get('conflict_score', 'N/A')}")
        print(f"Confidence:      0.75 (default)")
        print(f"Model Used:      {get_summarizing_model() if 'get_summarizing_model' in dir() else 'granite3.3:8b'}")
        print()
        print("AI Reasoning (would be migrated from Supabase notes):")
        print("-" * 80)
        notes = original.get('notes', '')
        if notes:
            # Show what the migration script would do
            if notes.strip().startswith('http'):
                reasoning = f"Migrated from Supabase. Original notes (disclosure URL): {notes}\n\nNote: This trade was analyzed before the reasoning field was separated. The AI reasoning may have been lost."
            elif len(notes.strip()) < 50:
                reasoning = f"Migrated from Supabase. Original notes: {notes}\n\nNote: This trade was analyzed before the reasoning field was separated. The full AI reasoning may not be available."
            else:
                reasoning = notes
            print(reasoning)
            print(f"\n(Length: {len(reasoning)} characters)")
        else:
            reasoning = "Migrated from Supabase conflict_score column. No reasoning text was available in the notes field."
            print(reasoning)
        print()
    
    print("=" * 80)
    print("COMPARISON")
    print("=" * 80)
    print()
    if is_migrated:
        print(f"Supabase conflict_score: {original.get('conflict_score', 'N/A')}")
        print(f"PostgreSQL conflict_score: {migrated['conflict_score']}")
        print(f"Match: {'✅' if str(original.get('conflict_score', '')) == str(migrated['conflict_score']) else '❌'}")
        print()
        print(f"Supabase notes length: {len(notes)} characters")
        print(f"PostgreSQL reasoning length: {len(migrated.get('reasoning', ''))} characters")
        
        if notes and migrated.get('reasoning'):
            if notes.strip() == migrated['reasoning'].strip():
                print("Content match: ✅ (exact match)")
            elif notes.strip() in migrated['reasoning'] or migrated['reasoning'].strip() in notes:
                print("Content match: ⚠️  (partial match - reasoning may have been modified)")
            else:
                print("Content match: ❌ (different content)")
    else:
        print(f"Supabase conflict_score: {original.get('conflict_score', 'N/A')}")
        print(f"Would migrate as: {trade_to_show.get('conflict_score', 'N/A')}")
        print()
        print(f"Supabase notes length: {len(notes)} characters")
        if notes:
            if notes.strip().startswith('http'):
                print("Notes type: ⚠️  Disclosure URL (not AI reasoning)")
            elif len(notes.strip()) < 50:
                print("Notes type: ⚠️  Short/generic text (may not be full reasoning)")
            else:
                print("Notes type: ✅ Likely contains AI reasoning")
    
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()
    print("This shows:")
    print("  1. The original trade data from Supabase (with conflict_score and notes)")
    print("  2. The migrated analysis data in PostgreSQL (with reasoning)")
    print("  3. A comparison to verify the migration preserved the data correctly")
    print()
    print("If the reasoning looks correct, the migration worked! ✅")

if __name__ == "__main__":
    show_migrated_trade_details()
