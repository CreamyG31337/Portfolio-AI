#!/usr/bin/env python3
"""
Migrate trades from politicians with temporary bioguide IDs to ones with proper IDs
"""
import sys
import io
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from dotenv import load_dotenv  # noqa: E402
from supabase_client import SupabaseClient  # noqa: E402

env_path = project_root / 'web_dashboard' / '.env'
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()

def migrate_trades_to_proper_bioguide_ids(dry_run: bool = True):
    """Migrate trades from temp bioguide IDs to proper ones."""
    client = SupabaseClient(use_service_role=True)

    print("="*70)
    print("MIGRATE TRADES TO PROPER BIOGUIDE IDs")
    print("="*70)
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE UPDATE'}")
    print()

    # Step 1: Find all politicians with temporary bioguide IDs
    print("Step 1: Finding politicians with temporary bioguide IDs...")
    print("-" * 70)

    all_pols = client.supabase.table('politicians')\
        .select('id, name, bioguide_id')\
        .not_.is_('bioguide_id', 'null')\
        .execute()

    tmp_pols = {p['id']: p for p in all_pols.data if p.get('bioguide_id', '').startswith('TMP')}
    print(f"   Found {len(tmp_pols)} politicians with temporary bioguide IDs")

    # Step 2: Find corresponding politicians with proper bioguide IDs (by name)
    print("\nStep 2: Finding corresponding politicians with proper bioguide IDs...")
    print("-" * 70)

    migrations = []  # (old_id, new_id, name, bioguide_id)

    for old_id, old_pol in tmp_pols.items():
        name = old_pol['name']

        # Find politicians with same name but proper bioguide ID
        result = client.supabase.table('politicians')\
            .select('id, name, bioguide_id')\
            .eq('name', name)\
            .not_.like('bioguide_id', 'TMP%')\
            .not_.is_('bioguide_id', 'null')\
            .execute()

        if result.data:
            new_pol = result.data[0]  # Take first match
            migrations.append({
                'old_id': old_id,
                'new_id': new_pol['id'],
                'name': name,
                'bioguide_id': new_pol['bioguide_id']
            })
            print(f"   {name}: ID {old_id} -> ID {new_pol['id']} (bioguide: {new_pol['bioguide_id']})")
        else:
            print(f"   {name}: No proper bioguide ID found (keeping old ID {old_id})")

    print(f"\n   Found {len(migrations)} politicians to migrate")

    if not migrations:
        print("\nNo migrations needed.")
        return

    # Step 3: Count trades to migrate
    print("\nStep 3: Counting trades to migrate...")
    print("-" * 70)

    total_trades = 0
    for mig in migrations:
        count_result = client.supabase.table('congress_trades')\
            .select('id', count='exact')\
            .eq('politician_id', mig['old_id'])\
            .execute()

        count = count_result.count if hasattr(count_result, 'count') else len(count_result.data)
        mig['trade_count'] = count
        total_trades += count

        if count > 0:
            print(f"   {mig['name']}: {count} trades")

    print(f"\n   Total trades to migrate: {total_trades}")

    # Step 4: Migrate trades
    if total_trades == 0:
        print("\nNo trades to migrate.")
    else:
        print("\nStep 4: Migrating trades...")
        print("-" * 70)

        if not dry_run:
            migrated = 0
            for mig in migrations:
                if mig['trade_count'] == 0:
                    continue

                try:
                    client.supabase.table('congress_trades')\
                        .update({'politician_id': mig['new_id']})\
                        .eq('politician_id', mig['old_id'])\
                        .execute()

                    migrated += mig['trade_count']
                    print(f"   [OK] {mig['name']}: Migrated {mig['trade_count']} trades")
                except Exception as e:
                    print(f"   [ERROR] {mig['name']}: Failed to migrate: {e}")

            print(f"\n   [OK] Successfully migrated {migrated} trades")
        else:
            print("   [DRY RUN] Would migrate the following:")
            for mig in migrations[:10]:
                if mig['trade_count'] > 0:
                    print(f"      {mig['name']}: {mig['trade_count']} trades (ID {mig['old_id']} -> {mig['new_id']})")
            if len([m for m in migrations if m['trade_count'] > 0]) > 10:
                print("      ... and more")

    # Step 5: Delete old politicians
    print("\nStep 5: Deleting old politicians with temporary IDs...")
    print("-" * 70)

    old_ids_to_delete = [m['old_id'] for m in migrations]

    if not dry_run:
        # Delete in batches
        BATCH_SIZE = 10
        deleted = 0
        for i in range(0, len(old_ids_to_delete), BATCH_SIZE):
            batch = old_ids_to_delete[i:i+BATCH_SIZE]
            try:
                client.supabase.table('politicians')\
                    .delete()\
                    .in_('id', batch)\
                    .execute()
                deleted += len(batch)
                print(f"   Deleted batch {i//BATCH_SIZE + 1}: {len(batch)} politicians")
            except Exception as e:
                print(f"   [ERROR] Failed to delete batch: {e}")

        print(f"\n   [OK] Successfully deleted {deleted} old politicians")
    else:
        print(f"   [DRY RUN] Would delete {len(old_ids_to_delete)} politicians")
        for mig in migrations[:5]:
            print(f"      - ID {mig['old_id']}: {mig['name']}")
        if len(migrations) > 5:
            print(f"      ... and {len(migrations) - 5} more")

    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(f"Politicians to migrate: {len(migrations)}")
    print(f"Trades to migrate: {total_trades}")
    print(f"Old politicians to delete: {len(old_ids_to_delete)}")

    if dry_run:
        print("\n[INFO] This was a dry run. Use --force to apply changes.")
    print("="*70)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Migrate trades to proper bioguide IDs')
    parser.add_argument('--dry-run', action='store_true', default=True, help='Dry run mode (default)')
    parser.add_argument('--force', action='store_true', help='Actually apply changes')
    args = parser.parse_args()

    dry_run = not args.force

    if not dry_run:
        if sys.stdin.isatty():
            response = input("\n⚠️  This will migrate trades and delete old politicians. Continue? (yes/no): ")
            if response.lower() != 'yes':
                print("Aborted.")
                sys.exit(0)
        else:
            print("\n⚠️  Running in non-interactive mode - proceeding with migration...")

    migrate_trades_to_proper_bioguide_ids(dry_run=dry_run)


