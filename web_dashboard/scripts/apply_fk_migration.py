#!/usr/bin/env python3
"""Apply foreign key migration"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from supabase_client import SupabaseClient

def apply_migration():
    """Apply the foreign key migration"""
    client = SupabaseClient(use_service_role=True)

    # Read the SQL file
    sql_file = Path(__file__).parent.parent / "schema" / "31_add_ticker_foreign_keys.sql"
    with open(sql_file, 'r', encoding='utf-8') as f:
        sql = f.read()

    # Remove the commented VALIDATE statements and the DO block at the end
    # We'll just run the ALTER TABLE and CREATE INDEX statements
    lines = sql.split('\n')
    migration_sql = []
    for line in lines:
        # Skip comments and the DO block
        if line.strip().startswith('--') or line.strip().startswith('/*') or line.strip().startswith('*/') or line.strip().startswith('DO $$') or line.strip().startswith('BEGIN') or line.strip().startswith('END $$'):
            continue
        if line.strip() and not line.strip().startswith('--'):
            migration_sql.append(line)

    # Join and execute
    migration_sql_str = '\n'.join(migration_sql)

    print("Applying foreign key migration...")
    print("=" * 80)

    # Try using Supabase RPC first, then fall back to psycopg2
    import os
    from dotenv import load_dotenv
    load_dotenv()

    # Try RPC method first
    try:
        print("Attempting to execute via Supabase RPC...")
        # Split into individual statements (excluding comments and DO block)
        statements = []
        for line in lines:
            line = line.strip()
            # Skip empty lines, comments, and DO block
            if not line or line.startswith('--') or line.startswith('/*') or line.startswith('*/'):
                continue
            if line.startswith('DO $$') or line.startswith('BEGIN') or line.startswith('END $$') or line.startswith('RAISE NOTICE'):
                continue
            # Collect SQL statements
            if line and not line.startswith('--'):
                statements.append(line)

        # Join and split by semicolon
        full_sql = '\n'.join(statements)
        sql_statements = [s.strip() for s in full_sql.split(';') if s.strip()]

        # Try exec_sql RPC
        for stmt in sql_statements:
            if stmt:
                print(f"Executing via RPC: {stmt[:70]}...")
                try:
                    result = client.supabase.rpc('exec_sql', {'sql': stmt + ';'}).execute()
                    print(f"  [OK]")
                except Exception as rpc_error:
                    # Try execute_sql
                    try:
                        result = client.supabase.rpc('execute_sql', {'query': stmt + ';'}).execute()
                        print(f"  [OK]")
                    except Exception as rpc_error2:
                        print(f"  [WARN] RPC failed: {rpc_error2}")
                        raise rpc_error2

        print("\n[OK] Migration applied successfully via RPC!")
        print("\nNext steps:")
        print("  1. Verify all tickers exist (already done)")
        print("  2. Uncomment VALIDATE CONSTRAINT statements in the SQL file")
        print("  3. Run this script again to validate constraints")
        return

    except Exception as rpc_err:
        print(f"[WARN] RPC method failed: {rpc_err}")
        print("Falling back to direct database connection...")

    # Fall back to psycopg2
    db_url = os.getenv('SUPABASE_DATABASE_URL') or os.getenv('SUPABASE_DB_URL')
    if not db_url:
        print("[ERROR] SUPABASE_DATABASE_URL or SUPABASE_DB_URL not found in environment variables")
        print("Please set one of these variables to apply the migration.")
        return

    try:
        import psycopg2
    except ImportError:
        print("[ERROR] psycopg2 not installed. Install with: pip install psycopg2-binary")
        return

    # Split into individual statements (excluding comments and DO block)
    statements = []
    for line in lines:
        line = line.strip()
        # Skip empty lines, comments, and DO block
        if not line or line.startswith('--') or line.startswith('/*') or line.startswith('*/'):
            continue
        if line.startswith('DO $$') or line.startswith('BEGIN') or line.startswith('END $$') or line.startswith('RAISE NOTICE'):
            continue
        # Collect SQL statements
        if line and not line.startswith('--'):
            statements.append(line)

    # Join and split by semicolon
    full_sql = '\n'.join(statements)
    sql_statements = [s.strip() for s in full_sql.split(';') if s.strip()]

    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = False  # Use transactions

        # Execute each statement
        for stmt in sql_statements:
            if stmt:
                print(f"Executing: {stmt[:70]}...")
                try:
                    cur = conn.cursor()
                    cur.execute(stmt)
                    conn.commit()
                    cur.close()
                    print(f"  [OK]")
                except Exception as stmt_err:
                    # Rollback on error
                    conn.rollback()
                    # Check if it's a "already exists" error
                    error_str = str(stmt_err)
                    if 'already exists' in error_str.lower() or 'duplicate' in error_str.lower():
                        print(f"  [SKIP] Constraint already exists")
                    else:
                        print(f"  [ERROR] {stmt_err}")
                        raise

        conn.close()
        print("\n[OK] Migration applied successfully!")
        print("\nNext steps:")
        print("  1. Verify all tickers exist (already done)")
        print("  2. Uncomment VALIDATE CONSTRAINT statements in the SQL file")
        print("  3. Run this script again to validate constraints")

    except Exception as e:
        print(f"\n[ERROR] Migration failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    apply_migration()
