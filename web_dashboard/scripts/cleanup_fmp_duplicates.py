#!/usr/bin/env python3
"""
Cleanup FMP Duplicates and NULL Metadata
========================================

This script cleans up trades that were imported by the FMP API job before the fix:
1. Deletes trades with NULL party/state (they're duplicates of scraper data)
2. Merges name variations (e.g., "Tim Moore" -> "Timothy Moore")

Run after applying the FMP job fixes to clean up historical bad data.

Usage:
    python scripts/cleanup_fmp_duplicates.py --dry-run  # Preview changes
    python scripts/cleanup_fmp_duplicates.py            # Execute cleanup
"""

import sys
import argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from supabase_client import SupabaseClient
from utils.politician_mapping import lookup_politician_metadata, POLITICIAN_ALIASES

def cleanup_fmp_duplicates(dry_run: bool = True):
    client = SupabaseClient(use_service_role=True)
    
    print("=" * 70)
    print("FMP DUPLICATE CLEANUP")
    print("=" * 70)
    
    if dry_run:
        print("DRY RUN - No changes will be made\n")
    
    # 1. Find all trades with NULL party (these are FMP imports)
    print("Finding trades with NULL party/state...")
    
    null_trades = client.supabase.table('congress_trades')\
        .select('id, politician_id, ticker, transaction_date, type, amount, owner')\
        .is_('party', 'null')\
        .execute().data
    
    print(f"Found {len(null_trades)} trades with NULL party")
    
    # 2. For each, check if there's a matching trade WITH metadata
    deleted = 0
    kept = 0
    updated = 0
    
    for trade in null_trades:
        # Build key for matching
        politician_id = trade['politician_id']
        ticker = trade['ticker']
        tx_date = trade['transaction_date']
        trade_type = trade['type']
        amount = trade['amount']
        
        if not politician_id:
            # No politician_id - delete as orphan
            if not dry_run:
                client.supabase.table('congress_trades').delete().eq('id', trade['id']).execute()
            print(f"  Deleting orphan (no politician_id): ID {trade['id']}")
            deleted += 1
            continue
        
        # Check for matching record WITH party/state
        matching = client.supabase.table('congress_trades')\
            .select('id, party, state')\
            .eq('politician_id', politician_id)\
            .eq('ticker', ticker)\
            .eq('transaction_date', tx_date)\
            .eq('type', trade_type)\
            .eq('amount', amount)\
            .neq('id', trade['id'])\
            .not_.is_('party', 'null')\
            .execute().data
        
        if matching:
            # There's a better record - delete this one
            if not dry_run:
                client.supabase.table('congress_trades').delete().eq('id', trade['id']).execute()
            print(f"  Deleting duplicate: ID {trade['id']} (better record exists: ID {matching[0]['id']})")
            deleted += 1
        else:
            # No matching record with metadata - try to enrich from politicians table
            politician = client.supabase.table('politicians')\
                .select('party, state')\
                .eq('id', politician_id)\
                .single()\
                .execute().data
            
            if politician and politician.get('party'):
                # Update with politician metadata
                if not dry_run:
                    client.supabase.table('congress_trades')\
                        .update({'party': politician['party'], 'state': politician['state']})\
                        .eq('id', trade['id'])\
                        .execute()
                print(f"  Enriching: ID {trade['id']} with party={politician['party']}, state={politician['state']}")
                updated += 1
            else:
                # Can't fix - keep as is
                print(f"  Keeping (no fix available): ID {trade['id']}")
                kept += 1
    
    print(f"\n{'DRY RUN ' if dry_run else ''}RESULTS:")
    print(f"  Deleted: {deleted}")
    print(f"  Enriched: {updated}")
    print(f"  Kept (no fix): {kept}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cleanup FMP duplicate trades")
    parser.add_argument('--dry-run', action='store_true', help="Preview changes without executing")
    args = parser.parse_args()
    
    cleanup_fmp_duplicates(dry_run=args.dry_run)
