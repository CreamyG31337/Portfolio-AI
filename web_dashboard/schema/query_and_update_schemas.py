#!/usr/bin/env python3
"""
Query actual database schemas and update CREATE TABLE statements in schema files.
This ensures schema files reflect the current database structure.
"""

import os
import sys
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / 'web_dashboard'))

try:
    from postgres_client import PostgresClient
except ImportError as e:
    print(f"ERROR: Error importing PostgresClient: {e}")
    sys.exit(1)

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("ERROR: psycopg2 not installed. Install with: pip install psycopg2-binary")
    sys.exit(1)


def get_postgres_table_schema(table_name: str) -> List[Dict[str, any]]:
    """Get table schema from Postgres using information_schema"""
    try:
        client = PostgresClient()
        
        query = """
        SELECT 
            column_name,
            data_type,
            character_maximum_length,
            numeric_precision,
            numeric_scale,
            is_nullable,
            column_default,
            is_generated,
            generation_expression
        FROM information_schema.columns
        WHERE table_schema = 'public' 
          AND table_name = %s
        ORDER BY ordinal_position;
        """
        
        result = client.execute_query(query, (table_name,))
        return result
        
    except Exception as e:
        print(f"ERROR: Error getting Postgres schema for {table_name}: {e}")
        return []


def get_supabase_table_schema(table_name: str) -> Optional[List[Dict[str, any]]]:
    """Get table schema from Supabase using direct Postgres connection"""
    supabase_db_url = os.getenv("SUPABASE_DB_URL")
    
    if not supabase_db_url:
        print(f"WARNING: SUPABASE_DB_URL not set - cannot query Supabase directly")
        print(f"   To query Supabase, set SUPABASE_DB_URL in .env")
        print(f"   Format: postgresql://postgres:[password]@[host]:5432/postgres")
        return None
    
    try:
        conn = psycopg2.connect(supabase_db_url)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        query = """
        SELECT 
            column_name,
            data_type,
            character_maximum_length,
            numeric_precision,
            numeric_scale,
            is_nullable,
            column_default,
            is_generated,
            generation_expression
        FROM information_schema.columns
        WHERE table_schema = 'public' 
          AND table_name = %s
        ORDER BY ordinal_position;
        """
        
        cursor.execute(query, (table_name,))
        result = [dict(row) for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        
        return result
        
    except Exception as e:
        print(f"ERROR: Error getting Supabase schema for {table_name}: {e}")
        return None


def format_data_type(col: Dict[str, any]) -> str:
    """Format PostgreSQL data type from information_schema"""
    data_type = col['data_type']
    max_len = col.get('character_maximum_length')
    precision = col.get('numeric_precision')
    scale = col.get('numeric_scale')
    
    # Handle specific types
    if data_type in ['character varying', 'varchar']:
        return f"VARCHAR({max_len})" if max_len else "VARCHAR"
    elif data_type == 'character':
        return f"CHAR({max_len})" if max_len else "CHAR"
    elif data_type in ['numeric', 'decimal']:
        if precision and scale is not None:
            return f"NUMERIC({precision}, {scale})"
        elif precision:
            return f"NUMERIC({precision})"
        return "NUMERIC"
    elif data_type == 'timestamp with time zone':
        return "TIMESTAMPTZ"
    elif data_type == 'timestamp without time zone':
        return "TIMESTAMP"
    elif data_type == 'double precision':
        return "DOUBLE PRECISION"
    elif data_type == 'real':
        return "REAL"
    elif data_type == 'integer':
        return "INTEGER"
    elif data_type == 'bigint':
        return "BIGINT"
    elif data_type == 'smallint':
        return "SMALLINT"
    elif data_type == 'boolean':
        return "BOOLEAN"
    elif data_type == 'text':
        return "TEXT"
    elif data_type == 'uuid':
        return "UUID"
    elif data_type.startswith('vector'):
        return data_type.upper()
    elif data_type == 'jsonb':
        return "JSONB"
    elif data_type == 'json':
        return "JSON"
    elif data_type == 'serial':
        return "SERIAL"
    elif data_type == 'bigserial':
        return "BIGSERIAL"
    else:
        return data_type.upper()


def format_column_definition(col: Dict[str, any]) -> str:
    """Format a column definition from information_schema data"""
    name = col['column_name']
    data_type = format_data_type(col)
    
    parts = [f"    {name} {data_type}"]
    
    # Handle NOT NULL
    if col.get('is_nullable') == 'NO':
        parts.append("NOT NULL")
    
    # Handle DEFAULT
    default = col.get('column_default')
    if default:
        default = default.strip()
        # Clean up default value
        if default.startswith("nextval("):
            # SERIAL sequence - handled by SERIAL type
            pass
        elif default.startswith("'") and default.endswith("'"):
            parts.append(f"DEFAULT {default}")
        elif default.upper() in ['NOW()', 'CURRENT_TIMESTAMP', 'CURRENT_DATE']:
            parts.append(f"DEFAULT {default}")
        elif 'uuid_generate_v4()' in default or 'gen_random_uuid()' in default:
            if 'gen_random_uuid()' in default:
                parts.append("DEFAULT gen_random_uuid()")
            else:
                parts.append("DEFAULT uuid_generate_v4()")
        elif default.replace('.', '').replace('-', '').isdigit():
            parts.append(f"DEFAULT {default}")
        elif default.upper() in ['TRUE', 'FALSE']:
            parts.append(f"DEFAULT {default.upper()}")
        else:
            # Remove type casts for readability
            default_clean = re.sub(r'::\w+(\[\])?', '', default)
            parts.append(f"DEFAULT {default_clean}")
    
    # Handle GENERATED columns
    if col.get('is_generated') == 'ALWAYS':
        gen_expr = col.get('generation_expression')
        if gen_expr:
            gen_expr = gen_expr.strip()
            parts.append(f"GENERATED ALWAYS AS ({gen_expr}) STORED")
    
    return " ".join(parts)


def get_table_constraints(table_name: str, database: str = 'postgres') -> Tuple[List[str], Optional[str]]:
    """Get table constraints (PRIMARY KEY, UNIQUE, FOREIGN KEY, etc.)
    Returns (constraints_list, primary_key_column)
    """
    constraints = []
    pk_column = None
    
    try:
        if database == 'postgres':
            client = PostgresClient()
            
            # Get primary key
            pk_query = """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = %s::regclass
              AND i.indisprimary;
            """
            pk_result = client.execute_query(pk_query, (table_name,))
            if pk_result:
                pk_cols = [row['attname'] for row in pk_result]
                if len(pk_cols) == 1:
                    pk_column = pk_cols[0]
                    # Don't add PRIMARY KEY constraint if it's a single column (handled in column definition)
                else:
                    constraints.append(f"PRIMARY KEY ({', '.join(pk_cols)})")
            
            # Get unique constraints (excluding primary key)
            unique_query = """
            SELECT
                conname as constraint_name,
                array_agg(a.attname ORDER BY array_position(con.conkey, a.attnum)) as columns
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
            JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = ANY(con.conkey)
            WHERE nsp.nspname = 'public'
              AND rel.relname = %s
              AND con.contype = 'u'
              AND NOT con.conindid IN (
                  SELECT indexrelid FROM pg_index WHERE indisprimary = true
              )
            GROUP BY conname;
            """
            unique_result = client.execute_query(unique_query, (table_name,))
            for row in unique_result:
                cols = row['columns']
                if len(cols) == 1:
                    constraints.append(f"UNIQUE ({cols[0]})")
                else:
                    constraints.append(f"UNIQUE ({', '.join(cols)})")
            
            # Get foreign keys
            fk_query = """
            SELECT
                tc.constraint_name,
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
              ON ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'public'
              AND tc.table_name = %s;
            """
            fk_result = client.execute_query(fk_query, (table_name,))
            for row in fk_result:
                constraints.append(
                    f"FOREIGN KEY ({row['column_name']}) "
                    f"REFERENCES {row['foreign_table_name']}({row['foreign_column_name']})"
                )
        
        elif database == 'supabase':
            supabase_db_url = os.getenv("SUPABASE_DB_URL")
            if not supabase_db_url:
                return constraints, pk_column
            
            conn = psycopg2.connect(supabase_db_url)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Get primary key
            pk_query = """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = %s::regclass
              AND i.indisprimary;
            """
            cursor.execute(pk_query, (table_name,))
            pk_result = cursor.fetchall()
            if pk_result:
                pk_cols = [row['attname'] for row in pk_result]
                if len(pk_cols) == 1:
                    pk_column = pk_cols[0]
                else:
                    constraints.append(f"PRIMARY KEY ({', '.join(pk_cols)})")
            
            # Get unique constraints
            unique_query = """
            SELECT
                conname as constraint_name,
                array_agg(a.attname ORDER BY array_position(con.conkey, a.attnum)) as columns
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
            JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = ANY(con.conkey)
            WHERE nsp.nspname = 'public'
              AND rel.relname = %s
              AND con.contype = 'u'
              AND NOT con.conindid IN (
                  SELECT indexrelid FROM pg_index WHERE indisprimary = true
              )
            GROUP BY conname;
            """
            cursor.execute(unique_query, (table_name,))
            for row in cursor.fetchall():
                cols = row['columns']
                if len(cols) == 1:
                    constraints.append(f"UNIQUE ({cols[0]})")
                else:
                    constraints.append(f"UNIQUE ({', '.join(cols)})")
            
            # Get foreign keys
            fk_query = """
            SELECT
                tc.constraint_name,
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
              ON ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'public'
              AND tc.table_name = %s;
            """
            cursor.execute(fk_query, (table_name,))
            for row in cursor.fetchall():
                constraints.append(
                    f"FOREIGN KEY ({row['column_name']}) "
                    f"REFERENCES {row['foreign_table_name']}({row['foreign_column_name']})"
                )
            
            cursor.close()
            conn.close()
        
    except Exception as e:
        print(f"WARNING: Error getting constraints for {table_name}: {e}")
    
    return constraints, pk_column


def generate_create_table_statement(table_name: str, columns: List[Dict[str, any]], 
                                    constraints: List[str], pk_column: Optional[str]) -> str:
    """Generate a CREATE TABLE statement from column definitions"""
    lines = [f"CREATE TABLE IF NOT EXISTS {table_name} ("]
    
    # Add columns
    col_defs = []
    for col in columns:
        col_def = format_column_definition(col)
        
        # Add PRIMARY KEY to column definition if it's the primary key
        # But only if it's not already there (check the whole definition)
        if pk_column and col['column_name'] == pk_column:
            # Check if PRIMARY KEY is already anywhere in the definition (case-insensitive)
            col_def_upper = col_def.upper()
            if "PRIMARY KEY" not in col_def_upper:
                # Replace NOT NULL with PRIMARY KEY, or add PRIMARY KEY before DEFAULT if present
                if "NOT NULL" in col_def:
                    col_def = col_def.replace("NOT NULL", "PRIMARY KEY")
                elif "DEFAULT" in col_def:
                    # Insert PRIMARY KEY before DEFAULT
                    idx = col_def.find("DEFAULT")
                    col_def = col_def[:idx].rstrip() + " PRIMARY KEY " + col_def[idx:]
                else:
                    col_def += " PRIMARY KEY"
        
        col_defs.append(col_def)
    
    # Join columns with commas
    for i, col_def in enumerate(col_defs):
        if i < len(col_defs) - 1 or constraints:
            lines.append(col_def + ",")
        else:
            lines.append(col_def)
    
    # Add constraints if any
    if constraints:
        for i, constraint in enumerate(constraints):
            if i < len(constraints) - 1:
                lines.append(f"    {constraint},")
            else:
                lines.append(f"    {constraint}")
    
    lines.append(");")
    
    return '\n'.join(lines)


def find_create_table_statements(content: str) -> List[Tuple[int, int, str, str]]:
    """Find all CREATE TABLE statements in content
    Returns list of (start_line, end_line, table_name, full_statement)
    """
    statements = []
    lines = content.split('\n')
    
    i = 0
    while i < len(lines):
        line = lines[i]
        # Look for CREATE TABLE
        match = re.match(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_]+)', line, re.IGNORECASE)
        if match:
            table_name = match.group(1)
            start_line = i
            
            # Find the end of the CREATE TABLE statement (closing parenthesis)
            paren_count = 0
            end_line = i
            in_string = False
            string_char = None
            
            for j in range(i, len(lines)):
                line_text = lines[j]
                if not line_text:  # Skip empty lines
                    continue
                for char in line_text:
                    if char in ("'", '"') and (j == i or (j > 0 and len(lines[j-1]) > 0 and lines[j-1][-1] != '\\')):
                        if not in_string:
                            in_string = True
                            string_char = char
                        elif char == string_char:
                            in_string = False
                            string_char = None
                    
                    if not in_string:
                        if char == '(':
                            paren_count += 1
                        elif char == ')':
                            paren_count -= 1
                            if paren_count == 0:
                                end_line = j
                                break
                
                if paren_count == 0:
                    break
            
            # Extract the full statement
            full_statement = '\n'.join(lines[start_line:end_line+1])
            statements.append((start_line, end_line, table_name, full_statement))
            i = end_line + 1
        else:
            i += 1
    
    return statements


def update_schema_file(file_path: Path, table_mapping: Dict[str, str]) -> bool:
    """Update CREATE TABLE statements in a schema file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        statements = find_create_table_statements(content)
        
        if not statements:
            print(f"  No CREATE TABLE statements found in {file_path.name}")
            return False
        
        updated = False
        for start_line, end_line, table_name, old_statement in statements:
            print(f"  Found table: {table_name}")
            
            # Determine which database to query
            database = table_mapping.get(table_name, 'supabase')  # Default to Supabase
            
            # Get current schema
            if database == 'postgres':
                columns = get_postgres_table_schema(table_name)
            else:
                columns = get_supabase_table_schema(table_name)
            
            if not columns:
                print(f"    WARNING: Could not get schema for {table_name}, skipping")
                continue
            
            # Get constraints
            constraints, pk_column = get_table_constraints(table_name, database)
            
            # Generate new CREATE TABLE statement
            new_statement = generate_create_table_statement(table_name, columns, constraints, pk_column)
            
            # Replace in content
            lines = content.split('\n')
            new_lines = lines[:start_line] + new_statement.split('\n') + lines[end_line+1:]
            content = '\n'.join(new_lines)
            updated = True
            print(f"    Updated {table_name}")
        
        if updated and content != original_content:
            # Backup original file
            backup_path = file_path.with_suffix(file_path.suffix + '.bak')
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(original_content)
            
            # Write updated content
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            print(f"  Updated {file_path.name} (backup saved to {backup_path.name})")
            return True
        else:
            print(f"  No changes needed for {file_path.name}")
            return False
            
    except Exception as e:
        print(f"  ERROR: Error updating {file_path.name}: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main function to update all schema files"""
    schema_dir = Path(__file__).parent
    
    print("Scanning schema files for CREATE TABLE statements...")
    
    # Find all SQL schema files
    schema_files = sorted(schema_dir.glob("*.sql"))
    schema_files = [f for f in schema_files if f.name != "README.md"]
    
    # Also check supabase subdirectory
    supabase_dir = schema_dir / "supabase"
    if supabase_dir.exists():
        schema_files.extend(supabase_dir.glob("*.sql"))
    
    print(f"Found {len(schema_files)} schema files\n")
    
    # Map tables to databases
    # Tables in Supabase
    supabase_tables = {
        'portfolio_positions', 'trade_log', 'cash_balances', 'performance_metrics',
        'user_funds', 'user_profiles', 'fund_thesis', 'fund_thesis_pillars',
        'fund_contributions', 'exchange_rates', 'user_preferences', 'rss_feeds',
        'job_executions', 'social_metrics', 'social_posts', 'sentiment_sessions',
        'congress_trades', 'congress_trade_sessions',
        'committees', 'watchlist', 'politicians'
    }
    
    # Tables in Postgres (Research DB)
    postgres_tables = {
        'research_articles', 'congress_trades_analysis', 'social_sentiment_analysis',
        'extracted_tickers', 'post_summaries', 'market_relationships',
        'youtube_sources', 'rss_feeds',
    }
    
    table_mapping = {}
    for table in supabase_tables:
        table_mapping[table] = 'supabase'
    for table in postgres_tables:
        table_mapping[table] = 'postgres'
    
    # Process each schema file
    updated_count = 0
    for schema_file in schema_files:
        print(f"Processing {schema_file.name}...")
        if update_schema_file(schema_file, table_mapping):
            updated_count += 1
        print()
    
    print(f"Done! Updated {updated_count} schema files")
    if updated_count > 0:
        print("Backup files (.bak) were created for safety")
        print("Please review the changes before committing")


if __name__ == "__main__":
    main()

