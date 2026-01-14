#!/usr/bin/env python3
"""
Fix Invalid Politician IDs (Simplified)
========================================

This script fixes the invalid politician_id values we identified.
Uses the known mapping from our investigation.

Usage:
    python web_dashboard/scripts/fix_invalid_politician_ids_simple.py [--dry-run] [--force]
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional
from collections import Counter
import argparse

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

# Fix Windows console encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from dotenv import load_dotenv
env_path = project_root / 'web_dashboard' / '.env'
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()

from supabase_client import SupabaseClient
from utils.politician_mapping import resolve_politician_name
import random
import string

# Known mapping from our investigation: invalid_id -> politician_name
INVALID_ID_TO_NAME = {
    5411: "Joshua Gottheimer", 5414: "Thomas Kean Jr", 5434: "William Keating",
    5453: "Michael Burgess", 5449: "Earl Blumenauer", 5489: "Valerie Hoyle",
    5446: "Thomas Carper", 5447: "Peter Sessions", 5487: "Lisa McClain",
    5456: "Kathy Manning", 5406: "Jonathan Jackson", 5436: "Mark Green",
    5457: "Stephen Lynch", 5445: "James Hill", 5439: "David Joyce",
    5471: "John Curtis", 5421: "Rick Allen", 5475: "Robert Wittman",
    5417: "Bob Latta", 5431: "Deborah Dingell", 5430: "Neal Dunn",
    5442: "Stephen Cohen", 5412: "Gregory Landsman", 5443: "Laurel Lee",
    5423: "Thomas Suozzi", 5452: "Gary Peters", 5407: "Gerry Connolly",
    5428: "Suzanne Lee", 5438: "Ronald Wyden", 5448: "George Kelly",
    5479: "Jennifer McClellan", 5466: "Katherine Clark", 5467: "Garret Graves",
    5427: "Jamin Raskin", 5451: "Deborah Wasserman Schultz", 5413: "Suzan DelBene",
    5437: "John Knott", 5440: "Gus Bilirakis", 5484: "James Scott",
    5418: "John McGuire III", 5422: "John Neely Kennedy", 5469: "Gerald Moran",
    5409: "John Hickenlooper", 5491: "Robert Aderholt"
}

def get_politician_id_by_name(client: SupabaseClient, politician_name: str) -> Optional[int]:
    """Get politician ID by name."""
    canonical_name, bioguide_id = resolve_politician_name(politician_name)
    
    # Try exact match
    result = client.supabase.table('politicians')\
        .select('id, name')\
        .eq('name', canonical_name)\
        .limit(1)\
        .execute()
    
    if result.data:
        return result.data[0]['id']
    
    # Try by bioguide if available
    if bioguide_id:
        result = client.supabase.table('politicians')\
            .select('id')\
            .eq('bioguide_id', bioguide_id)\
            .limit(1)\
            .execute()
        
        if result.data:
            return result.data[0]['id']
    
    return None

def create_politician(
    client: SupabaseClient,
    politician_name: str,
    party: Optional[str],
    state: Optional[str],
    chamber: Optional[str]
) -> Optional[int]:
    """Create a politician record."""
    canonical_name, bioguide_id = resolve_politician_name(politician_name)
    
    if not bioguide_id:
        suffix = ''.join(random.choices(string.digits, k=6))
        bioguide_id = f"TMP{suffix}"
    
    if not party:
        party = 'Unknown'
    if not state:
        state = 'US'
    if not chamber:
        chamber = 'House'
    
    try:
        insert_result = client.supabase.table('politicians').insert({
            'name': canonical_name,
            'bioguide_id': bioguide_id,
            'party': party,
            'state': state,
            'chamber': chamber
        }).execute()
        
        if insert_result.data:
            return insert_result.data[0]['id']
    except Exception as e:
        print(f"      [ERROR] Failed to create: {e}")
        return None
    
    return None

def fix_invalid_ids(dry_run: bool = True):
    """Fix invalid politician IDs."""
    client = SupabaseClient(use_service_role=True)
    
    print("="*70)
    print("FIX INVALID POLITICIAN IDs (SIMPLIFIED)")
    print("="*70)
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE UPDATE'}")
    print()
    
    # Step 1: Get all trades with invalid IDs
    print("Step 1: Finding trades with invalid politician_id...")
    print("-" * 70)
    
    invalid_ids = list(INVALID_ID_TO_NAME.keys())
    all_invalid_trades = []
    
    # Query in batches
    for i in range(0, len(invalid_ids), 10):
        batch = invalid_ids[i:i+10]
        trades = client.supabase.table('congress_trades')\
            .select('id, politician_id, party, state, chamber')\
            .in_('politician_id', batch)\
            .execute()
        
        for trade in trades.data:
            trade['politician'] = INVALID_ID_TO_NAME.get(trade['politician_id'], 'Unknown')
            all_invalid_trades.append(trade)
    
    print(f"   Found {len(all_invalid_trades)} trades with invalid politician_id")
    
    if not all_invalid_trades:
        print("   [OK] No invalid trades found!")
        return
    
    # Step 2: Group by politician name
    print("\nStep 2: Grouping by politician...")
    print("-" * 70)
    
    trades_by_politician: Dict[str, List[Dict]] = {}
    for trade in all_invalid_trades:
        name = trade['politician']
        if name not in trades_by_politician:
            trades_by_politician[name] = []
        trades_by_politician[name].append(trade)
    
    print(f"   Found {len(trades_by_politician)} unique politicians")
    
    # Step 3: Resolve correct IDs
    print("\nStep 3: Resolving correct politician IDs...")
    print("-" * 70)
    
    fixes: List[tuple] = []  # (trade_id, new_politician_id, politician_name)
    politicians_to_create = []
    
    for politician_name, trades in sorted(trades_by_politician.items()):
        print(f"\n   {politician_name} ({len(trades)} trades)")
        
        # Show current invalid ID
        current_invalid_id = trades[0].get('politician_id')
        print(f"      Current invalid ID: {current_invalid_id}")
        
        # Try to find existing politician
        politician_id = get_politician_id_by_name(client, politician_name)
        
        if politician_id:
            # Verify the ID actually exists in database
            verify = client.supabase.table('politicians')\
                .select('id')\
                .eq('id', politician_id)\
                .execute()
            
            if not verify.data:
                print(f"      [ERROR] Lookup returned ID {politician_id} but it doesn't exist in database!")
                politician_id = None  # Treat as not found
            elif politician_id == current_invalid_id:
                print(f"      [WARNING] Lookup returned same invalid ID {politician_id}")
                # This shouldn't happen - the ID is invalid, so lookup should return None
                # or a different ID. Treat as not found and create new politician.
                print(f"      [ACTION] Will create new politician instead")
                politician_id = None
            else:
                print(f"      [FOUND] Correct ID: {politician_id}")
                for trade in trades:
                    fixes.append((trade['id'], politician_id, politician_name))
        
        if not politician_id:
            print(f"      [NOT FOUND] Need to create")
            
            # Get metadata from trades
            party_counts = Counter(t.get('party') for t in trades if t.get('party'))
            party = party_counts.most_common(1)[0][0] if party_counts else None

            state_counts = Counter(t.get('state') for t in trades if t.get('state'))
            state = state_counts.most_common(1)[0][0] if state_counts else None

            chamber_counts = Counter(t.get('chamber') for t in trades if t.get('chamber'))
            chamber = chamber_counts.most_common(1)[0][0] if chamber_counts else None
            
            # Use first non-None value if max doesn't work
            if not party:
                party = next((t.get('party') for t in trades if t.get('party')), None)
            if not state:
                state = next((t.get('state') for t in trades if t.get('state')), None)
            if not chamber:
                chamber = next((t.get('chamber') for t in trades if t.get('chamber')), None)
            
            print(f"      Metadata: party={party}, state={state}, chamber={chamber}")
            
            if not dry_run:
                new_id = create_politician(client, politician_name, party, state, chamber)
                if new_id:
                    print(f"      [CREATED] ID: {new_id}")
                    for trade in trades:
                        fixes.append((trade['id'], new_id, politician_name))
                else:
                    print(f"      [ERROR] Failed to create")
            else:
                politicians_to_create.append({
                    'name': politician_name,
                    'party': party,
                    'state': state,
                    'chamber': chamber
                })
    
    # Step 4: Update trades
    print("\nStep 4: Updating trades...")
    print("-" * 70)
    
    valid_fixes = [f for f in fixes if f[1] is not None]
    
    print(f"   Trades to fix: {len(valid_fixes)}")
    
    if valid_fixes and not dry_run:
        # Group by politician_id for batch updates
        updates_by_pid: Dict[int, List[int]] = {}
        for trade_id, politician_id, _ in valid_fixes:
            if politician_id not in updates_by_pid:
                updates_by_pid[politician_id] = []
            updates_by_pid[politician_id].append(trade_id)
        
        total_updated = 0
        for politician_id, trade_ids in updates_by_pid.items():
            for trade_id in trade_ids:
                try:
                    client.supabase.table('congress_trades')\
                        .update({'politician_id': politician_id})\
                        .eq('id', trade_id)\
                        .execute()
                    total_updated += 1
                except Exception as e:
                    print(f"   [ERROR] Failed to update trade {trade_id}: {e}")
            
            print(f"   Updated {len(trade_ids)} trades -> politician_id {politician_id}")
        
        print(f"\n   [OK] Successfully updated {total_updated} trades")
    elif valid_fixes and dry_run:
        print(f"   [DRY RUN] Would update {len(valid_fixes)} trades")
        if politicians_to_create:
            print(f"\n   [DRY RUN] Would create {len(politicians_to_create)} politicians:")
            for pol in politicians_to_create[:5]:
                print(f"      - {pol['name']} ({pol['party']}, {pol['state']}, {pol['chamber']})")
            if len(politicians_to_create) > 5:
                print(f"      ... and {len(politicians_to_create) - 5} more")
    
    # Step 5: Validate
    print("\nStep 5: Validating...")
    print("-" * 70)
    
    if not dry_run:
        # Re-check invalid IDs
        remaining = client.supabase.table('congress_trades')\
            .select('id', count='exact')\
            .in_('politician_id', invalid_ids)\
            .execute()
        
        remaining_count = remaining.count if hasattr(remaining, 'count') else len(remaining.data)
        
        if remaining_count == 0:
            print("   [OK] All invalid IDs have been fixed!")
        else:
            print(f"   [WARNING] {remaining_count} trades still have invalid IDs")
    else:
        print("   [DRY RUN] Skipping validation")
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(f"Invalid trades found: {len(all_invalid_trades)}")
    print(f"Politicians to create: {len(politicians_to_create) if dry_run else 0}")
    print(f"Trades that will be fixed: {len(valid_fixes)}")
    
    if dry_run:
        print("\n[INFO] This was a dry run. Use --force to apply changes.")
    print("="*70)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Fix invalid politician IDs')
    parser.add_argument('--dry-run', action='store_true', default=True, help='Dry run mode (default)')
    parser.add_argument('--force', action='store_true', help='Actually apply changes')
    args = parser.parse_args()
    
    dry_run = not args.force
    
    if not dry_run:
        # Skip interactive prompt in non-interactive environments
        import sys
        if sys.stdin.isatty():
            response = input("\n⚠️  This will modify the database. Continue? (yes/no): ")
            if response.lower() != 'yes':
                print("Aborted.")
                sys.exit(0)
        else:
            print("\n⚠️  Running in non-interactive mode - proceeding with database modifications...")
    
    fix_invalid_ids(dry_run=dry_run)

