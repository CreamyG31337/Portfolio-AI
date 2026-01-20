#!/usr/bin/env python3
"""
Migrate Conflict Scores from Supabase to PostgreSQL
===================================================

Migrates old conflict_score data from Supabase congress_trades.conflict_score column
to PostgreSQL congress_trades_analysis table so it appears in the UI.

This is a one-time migration for trades that were analyzed before the system switched
to storing analysis in PostgreSQL.
"""

import sys
import io
from pathlib import Path

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

from supabase_client import SupabaseClient  # noqa: E402
from postgres_client import PostgresClient  # noqa: E402
from settings import get_summarizing_model  # noqa: E402

def migrate_conflict_scores(dry_run: bool = True):
    """Migrate conflict_score from Supabase to PostgreSQL.

    Args:
        dry_run: If True, only shows what would be migrated without actually doing it
    """
    supabase = SupabaseClient(use_service_role=True)
    postgres = PostgresClient()

    print("\n" + "=" * 80)
    print("MIGRATE CONFLICT SCORES: Supabase → PostgreSQL")
    print("=" * 80)
    print()

    if dry_run:
        print("🔍 DRY RUN MODE - No changes will be made")
        print()

    # Get all trades with conflict_score in Supabase
    print("1. Fetching trades with conflict_score from Supabase...")
    all_trades = []
    batch_size = 1000
    offset = 0

    while True:
        result = supabase.supabase.table('congress_trades')\
            .select('id, conflict_score, notes')\
            .not_.is_('conflict_score', 'null')\
            .range(offset, offset + batch_size - 1)\
            .execute()

        if not result.data:
            break

        all_trades.extend(result.data)

        if len(result.data) < batch_size:
            break

        offset += batch_size

    print(f"   Found {len(all_trades)} trades with conflict_score in Supabase")

    if not all_trades:
        print("\n✅ No trades to migrate!")
        return

    # Check which ones already exist in PostgreSQL
    print("\n2. Checking which trades already have PostgreSQL analysis...")
    trade_ids = [t.get('id') for t in all_trades if t.get('id')]

    if not trade_ids:
        print("   ⚠️  No valid trade IDs found")
        return

    # Check existing records in batches
    existing_ids = set()
    batch_size_check = 100
    for i in range(0, len(trade_ids), batch_size_check):
        batch = trade_ids[i:i + batch_size_check]
        placeholders = ','.join(['%s'] * len(batch))
        existing_result = postgres.execute_query(
            f"SELECT trade_id FROM congress_trades_analysis WHERE trade_id IN ({placeholders})",
            batch
        )
        if existing_result:
            existing_ids.update(r['trade_id'] for r in existing_result)

    # Find trades that need migration
    trades_to_migrate = [
        t for t in all_trades
        if t.get('id') and t.get('id') not in existing_ids
    ]

    print(f"   Found {len(existing_ids)} trades already in PostgreSQL")
    print(f"   Found {len(trades_to_migrate)} trades that need migration")

    if not trades_to_migrate:
        print("\n✅ All trades already migrated!")
        return

    # Show sample
    print("\n3. Sample trades to migrate:")
    for i, trade in enumerate(trades_to_migrate[:5], 1):
        trade_id = trade.get('id', 'N/A')
        score = trade.get('conflict_score', 'N/A')
        notes = trade.get('notes', '')
        notes_preview = notes[:100] if notes else 'N/A'

        # Check if notes looks like reasoning or just a URL
        if notes:
            if notes.strip().startswith('http'):
                notes_type = " (disclosure URL)"
            elif len(notes.strip()) < 50:
                notes_type = " (short/generic)"
            else:
                notes_type = " (likely AI reasoning)"
        else:
            notes_type = " (empty)"

        print(f"   {i}. Trade ID {trade_id}: score={score}, notes={notes_preview}...{notes_type}")

    if not dry_run:
        print("\n4. Migrating to PostgreSQL...")
        model_name = get_summarizing_model()
        migrated = 0
        errors = 0

        for trade in trades_to_migrate:
            try:
                trade_id = trade.get('id')
                conflict_score = float(trade.get('conflict_score', 0.0))
                notes = trade.get('notes', '')

                # Clamp score to 0.0-1.0
                conflict_score = max(0.0, min(1.0, conflict_score))

                # Determine reasoning text
                # The notes field in Supabase was set to the AI reasoning from the analysis
                # Check if notes contains actual reasoning or just a disclosure URL
                if notes:
                    # If notes looks like a URL (starts with http), it's probably just a disclosure link
                    if notes.strip().startswith('http'):
                        reasoning = f"Migrated from Supabase. Original notes (disclosure URL): {notes}\n\nNote: This trade was analyzed before the reasoning field was separated. The AI reasoning may have been lost."
                    # If notes is very short or generic, it might not be the full reasoning
                    elif len(notes.strip()) < 50:
                        reasoning = f"Migrated from Supabase. Original notes: {notes}\n\nNote: This trade was analyzed before the reasoning field was separated. The full AI reasoning may not be available."
                    else:
                        # Notes likely contains the AI reasoning - use it directly
                        reasoning = notes
                else:
                    reasoning = "Migrated from Supabase conflict_score column. No reasoning text was available in the notes field."

                # Insert into PostgreSQL
                postgres.execute_update(
                    """
                    INSERT INTO congress_trades_analysis
                        (trade_id, conflict_score, confidence_score, reasoning, model_used, analysis_version)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (trade_id, model_used, analysis_version)
                    DO UPDATE SET
                        conflict_score = EXCLUDED.conflict_score,
                        confidence_score = EXCLUDED.confidence_score,
                        reasoning = EXCLUDED.reasoning,
                        analyzed_at = NOW()
                    """,
                    (trade_id, conflict_score, 0.75, reasoning, model_name, 1)
                )

                migrated += 1
                if migrated % 10 == 0:
                    print(f"   Migrated {migrated}/{len(trades_to_migrate)}...")

            except Exception as e:
                errors += 1
                print(f"   ⚠️  Error migrating trade {trade.get('id', 'unknown')}: {e}")

        print("\n✅ Migration complete!")
        print(f"   Migrated: {migrated}")
        print(f"   Errors: {errors}")
    else:
        print("\n4. Would migrate to PostgreSQL (DRY RUN - no changes made)")
        print(f"   Would migrate {len(trades_to_migrate)} trades")
        print("\n   To actually migrate, run:")
        print("   python web_dashboard/scripts/migrate_supabase_conflict_scores.py --execute")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Migrate conflict_score from Supabase to PostgreSQL')
    parser.add_argument('--execute', action='store_true', help='Actually perform the migration (default is dry-run)')
    args = parser.parse_args()

    migrate_conflict_scores(dry_run=not args.execute)
