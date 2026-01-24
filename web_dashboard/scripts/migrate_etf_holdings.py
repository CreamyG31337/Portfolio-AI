#!/usr/bin/env python3
"""
Migrate ETF Holdings Data from Supabase to Research DB
======================================================

This script migrates existing ETF holdings data from Supabase
to the Research DB. It handles:

1. Compares row counts between databases
2. Finds missing dates in Research DB
3. Copies missing data in batches
4. Verifies data integrity

Usage:
    cd web_dashboard
    python scripts/migrate_etf_holdings.py [--dry-run]
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime

# Add project paths
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

from dotenv import load_dotenv
load_dotenv(project_root / 'web_dashboard' / '.env')

from supabase_client import SupabaseClient
from postgres_client import PostgresClient


def get_supabase_stats(supabase: SupabaseClient):
    """Get stats from Supabase etf_holdings_log"""
    # Get total count
    result = supabase.supabase.table('etf_holdings_log').select('*', count='exact').limit(0).execute()
    total_count = result.count or 0
    
    # Get date range
    min_date_res = supabase.supabase.table('etf_holdings_log').select('date').order('date', desc=False).limit(1).execute()
    max_date_res = supabase.supabase.table('etf_holdings_log').select('date').order('date', desc=True).limit(1).execute()
    
    min_date = min_date_res.data[0]['date'] if min_date_res.data else None
    max_date = max_date_res.data[0]['date'] if max_date_res.data else None
    
    # Get distinct dates
    dates = set()
    offset = 0
    page_size = 1000
    while True:
        res = supabase.supabase.table('etf_holdings_log').select('date').range(offset, offset + page_size - 1).execute()
        if not res.data:
            break
        dates.update(row['date'] for row in res.data)
        if len(res.data) < page_size:
            break
        offset += page_size
    
    return {
        'total_count': total_count,
        'min_date': min_date,
        'max_date': max_date,
        'dates': dates
    }


def get_research_stats(postgres: PostgresClient):
    """Get stats from Research DB etf_holdings_log"""
    result = postgres.execute_query("SELECT COUNT(*) as cnt FROM etf_holdings_log")
    total_count = result[0]['cnt'] if result else 0
    
    result = postgres.execute_query("SELECT MIN(date) as min_date, MAX(date) as max_date FROM etf_holdings_log")
    min_date = str(result[0]['min_date']) if result and result[0]['min_date'] else None
    max_date = str(result[0]['max_date']) if result and result[0]['max_date'] else None
    
    result = postgres.execute_query("SELECT DISTINCT date FROM etf_holdings_log")
    dates = set(str(row['date']) for row in result) if result else set()
    
    return {
        'total_count': total_count,
        'min_date': min_date,
        'max_date': max_date,
        'dates': dates
    }


def fetch_supabase_data_for_date(supabase: SupabaseClient, target_date: str):
    """Fetch all holdings for a specific date from Supabase"""
    all_rows = []
    offset = 0
    page_size = 1000
    
    while True:
        result = supabase.supabase.table('etf_holdings_log').select('*').eq('date', target_date).range(offset, offset + page_size - 1).execute()
        if not result.data:
            break
        all_rows.extend(result.data)
        if len(result.data) < page_size:
            break
        offset += page_size
    
    return all_rows


def insert_rows_to_research(postgres: PostgresClient, rows: list, dry_run: bool = False):
    """Insert rows into Research DB"""
    if not rows:
        return 0
    
    if dry_run:
        return len(rows)
    
    # Use batch insert with ON CONFLICT
    inserted = 0
    batch_size = 500
    
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        
        # Build values
        values = []
        params = []
        for j, row in enumerate(batch):
            base_idx = j * 8
            values.append(f"(${base_idx + 1}, ${base_idx + 2}, ${base_idx + 3}, ${base_idx + 4}, ${base_idx + 5}, ${base_idx + 6}, ${base_idx + 7}, ${base_idx + 8})")
            params.extend([
                row['date'],
                row['etf_ticker'],
                row['holding_ticker'],
                row.get('holding_name'),
                row.get('shares_held'),
                row.get('weight_percent'),
                row.get('market_value'),
                row.get('created_at')
            ])
        
        sql = f"""
            INSERT INTO etf_holdings_log 
            (date, etf_ticker, holding_ticker, holding_name, shares_held, weight_percent, market_value, created_at)
            VALUES {', '.join(values)}
            ON CONFLICT (date, etf_ticker, holding_ticker) DO UPDATE SET
                holding_name = EXCLUDED.holding_name,
                shares_held = EXCLUDED.shares_held,
                weight_percent = EXCLUDED.weight_percent,
                market_value = EXCLUDED.market_value
        """
        
        # Use raw connection for batch insert
        with postgres.get_connection() as conn:
            cursor = conn.cursor()
            # Convert params to tuple for execute
            # psycopg2 uses %s not $N
            sql_psycopg = sql.replace('$', '%')
            for idx in range(len(params), 0, -1):
                sql_psycopg = sql_psycopg.replace(f'%{idx}', '%s')
            cursor.execute(sql_psycopg, params)
            conn.commit()
        
        inserted += len(batch)
    
    return inserted


def main():
    parser = argparse.ArgumentParser(description='Migrate ETF holdings from Supabase to Research DB')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be migrated without making changes')
    args = parser.parse_args()
    
    print("=" * 60)
    print("ETF Holdings Data Migration")
    print("=" * 60)
    
    if args.dry_run:
        print("\n[DRY RUN MODE - No changes will be made]\n")
    
    # Connect to databases
    print("Connecting to databases...")
    supabase = SupabaseClient(use_service_role=True)  # Need service role to bypass RLS
    postgres = PostgresClient()
    
    # Get stats
    print("\nGathering statistics...")
    print("  Fetching Supabase stats...")
    sb_stats = get_supabase_stats(supabase)
    print("  Fetching Research DB stats...")
    pg_stats = get_research_stats(postgres)
    
    print("\n--- Supabase ---")
    print(f"  Total rows: {sb_stats['total_count']:,}")
    print(f"  Date range: {sb_stats['min_date']} to {sb_stats['max_date']}")
    print(f"  Distinct dates: {len(sb_stats['dates'])}")
    
    print("\n--- Research DB ---")
    print(f"  Total rows: {pg_stats['total_count']:,}")
    print(f"  Date range: {pg_stats['min_date']} to {pg_stats['max_date']}")
    print(f"  Distinct dates: {len(pg_stats['dates'])}")
    
    # Find missing dates
    missing_dates = sb_stats['dates'] - pg_stats['dates']
    
    if not missing_dates:
        print("\n[OK] All dates from Supabase exist in Research DB!")
        
        # Check if counts match
        if sb_stats['total_count'] != pg_stats['total_count']:
            print(f"\n[WARN] Row counts differ: Supabase={sb_stats['total_count']:,}, Research={pg_stats['total_count']:,}")
            print("  This may indicate partial data for some dates.")
        else:
            print(f"\n[OK] Row counts match: {sb_stats['total_count']:,}")
        return
    
    print(f"\n--- Migration Required ---")
    print(f"  Missing dates in Research DB: {len(missing_dates)}")
    missing_sorted = sorted(missing_dates)
    print(f"  Range: {missing_sorted[0]} to {missing_sorted[-1]}")
    
    if len(missing_dates) <= 10:
        print(f"  Dates: {', '.join(missing_sorted)}")
    
    # Migrate each missing date
    print("\n--- Migrating Data ---")
    total_migrated = 0
    
    for i, target_date in enumerate(sorted(missing_dates)):
        print(f"\n[{i+1}/{len(missing_dates)}] Processing {target_date}...")
        
        rows = fetch_supabase_data_for_date(supabase, target_date)
        print(f"  Fetched {len(rows):,} rows from Supabase")
        
        if rows:
            inserted = insert_rows_to_research(postgres, rows, dry_run=args.dry_run)
            print(f"  {'Would insert' if args.dry_run else 'Inserted'} {inserted:,} rows")
            total_migrated += inserted
    
    print("\n" + "=" * 60)
    print("Migration Summary")
    print("=" * 60)
    print(f"  Dates migrated: {len(missing_dates)}")
    print(f"  Rows {'would be' if args.dry_run else ''} migrated: {total_migrated:,}")
    
    if not args.dry_run:
        # Verify
        print("\nVerifying...")
        pg_stats_after = get_research_stats(postgres)
        print(f"  Research DB rows after: {pg_stats_after['total_count']:,}")
        print(f"  Supabase rows: {sb_stats['total_count']:,}")
        
        if pg_stats_after['total_count'] >= sb_stats['total_count']:
            print("\n[OK] Migration successful!")
        else:
            diff = sb_stats['total_count'] - pg_stats_after['total_count']
            print(f"\n[WARN] {diff:,} rows still missing - may need to re-run")


if __name__ == '__main__':
    main()
