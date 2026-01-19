#!/usr/bin/env python3
"""
Check Old Notes Content
=======================
Checks what's actually in the notes field for old trades with conflict_score
to see if it contains AI reasoning or just generic notes
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

def check_notes_content():
    """Check what's in the notes field for old trades."""
    supabase = SupabaseClient(use_service_role=True)
    
    print("\n" + "=" * 80)
    print("CHECKING NOTES FIELD CONTENT")
    print("=" * 80)
    print()
    
    # Get trades with conflict_score
    result = supabase.supabase.table('congress_trades')\
        .select('id, ticker, politician, conflict_score, notes')\
        .not_.is_('conflict_score', 'null')\
        .limit(20)\
        .execute()
    
    if not result.data:
        print("No trades found with conflict_score")
        return
    
    print(f"Found {len(result.data)} trades with conflict_score\n")
    print("=" * 80)
    print("SAMPLE NOTES CONTENT:")
    print("=" * 80)
    print()
    
    for i, trade in enumerate(result.data[:10], 1):
        trade_id = trade.get('id', 'N/A')
        ticker = trade.get('ticker', 'N/A')
        politician = trade.get('politician', 'N/A')
        score = trade.get('conflict_score', 'N/A')
        notes = trade.get('notes', '')
        
        print(f"{i}. Trade ID {trade_id} | {ticker} | {politician[:30]}")
        print(f"   Score: {score}")
        print(f"   Notes length: {len(notes) if notes else 0} characters")
        
        if notes:
            # Show first 200 chars
            preview = notes[:200]
            print(f"   Preview: {preview}...")
            
            # Check if it looks like AI reasoning
            ai_indicators = ['analysis', 'reasoning', 'conflict', 'committee', 'regulation', 
                           'potential', 'risk', 'indicates', 'suggests', 'because']
            has_ai_content = any(indicator.lower() in notes.lower() for indicator in ai_indicators)
            
            if has_ai_content:
                print("   ✅ Looks like AI reasoning")
            else:
                print("   ⚠️  Doesn't look like AI reasoning (might be disclosure URL or generic note)")
        else:
            print("   ⚠️  No notes field")
        
        print()
    
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()
    print("If notes contain AI reasoning, migration script will preserve it.")
    print("If notes are just disclosure URLs or generic text, we may need to:")
    print("  1. Re-analyze these trades with current AI")
    print("  2. Or mark them as needing re-analysis")

if __name__ == "__main__":
    check_notes_content()
