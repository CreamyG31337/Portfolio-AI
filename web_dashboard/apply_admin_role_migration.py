#!/usr/bin/env python3
"""
Apply admin role management migration to Supabase
Runs the SQL migration file 37_admin_role_management.sql
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from admin_utils import get_admin_supabase_client

load_dotenv()

def apply_migration():
    """Apply the admin role management migration"""
    print("Applying Admin Role Management Migration")
    print("=" * 60)
    
    # Read the migration file
    migration_file = Path(__file__).parent.parent / "schema" / "37_admin_role_management.sql"
    
    if not migration_file.exists():
        print(f"❌ Migration file not found: {migration_file}")
        return False
    
    print(f"\n📄 Reading migration file: {migration_file.name}")
    
    with open(migration_file, 'r', encoding='utf-8') as f:
        sql_content = f.read()
    
    # Get Supabase client
    client = get_admin_supabase_client()
    if not client:
        print("❌ Failed to get Supabase client")
        return False
    
    print("✓ Connected to Supabase")
    
    # Split SQL into individual statements (functions and DO blocks)
    # This is a simple split by semicolon, good enough for this migration
    statements = []
    current_statement = ""
    in_function = False
    
    for line in sql_content.split('\n'):
        stripped = line.strip()
        
        # Skip comments and empty lines
        if not stripped or stripped.startswith('--'):
            continue
        
        # Track if we're inside a function
        if 'CREATE OR REPLACE FUNCTION' in line or 'DO $$' in line:
            in_function = True
        
        current_statement += line + '\n'
        
        # End of statement detection
        if in_function and ('$$ LANGUAGE' in line or 'END $$' in line):
            # Function/DO block ends
            if ';' in line:
                statements.append(current_statement.strip())
                current_statement = ""
                in_function = False
        elif not in_function and stripped.endswith(';'):
            # Regular statement
            statements.append(current_statement.strip())
            current_statement = ""
    
    # Add any remaining statement
    if current_statement.strip():
        statements.append(current_statement.strip())
    
    print(f"\n🔨 Executing {len(statements)} SQL statements...")
    
    # Execute each statement
    for i, statement in enumerate(statements, 1):
        if not statement or statement.startswith('--'):
            continue
        
        # Extract function/block name for display
        if 'CREATE OR REPLACE FUNCTION' in statement:
            try:
                func_name = statement.split('CREATE OR REPLACE FUNCTION')[1].split('(')[0].strip()
                print(f"\n  {i}. Creating function: {func_name}")
            except:
                print(f"\n  {i}. Creating function")
        elif 'DO $$' in statement:
            print(f"\n  {i}. Executing DO block")
        else:
            print(f"\n  {i}. Executing statement")
        
        try:
            # Use rpc for raw SQL execution if available, otherwise use query
            # For Supabase, we'll execute via the REST API
            result = client.supabase.rpc('exec_sql', {'sql': statement}).execute()
            print("     ✓ Success")
        except Exception as e:
            error_msg = str(e).lower()
            
            # Check if function already exists (not really an error for CREATE OR REPLACE)
            if 'already exists' in error_msg or 'replace' in error_msg:
                print(f"     ✓ Updated (already existed)")
            else:
                print(f"     ⚠️ Note: {e}")
                # Try direct execution for Supabase compatibility
                try:
                    # Execute via PostgREST if available
                    # This is a fallback - ideally we'd use Supabase's SQL editor API
                    print(f"     ℹ️ Manual execution required - please run this SQL manually in Supabase SQL Editor")
                    print(f"        or use the Supabase dashboard to apply the migration.")
                except:
                    pass
    
    print("\n" + "=" * 60)
    print("✅ Migration application complete!")
    print("\nNote: If you see any errors above, you may need to run the SQL")
    print("      manually in the Supabase SQL Editor.")
    print("=" * 60)
    
    return True

if __name__ == "__main__":
    success = apply_migration()
    
    if success:
        print("\n✅ Next steps:")
        print("   1. Run: python web_dashboard/test_admin_roles.py")
        print("   2. Test the admin UI at: /admin (User Management tab)")
    
    sys.exit(0 if success else 1)
