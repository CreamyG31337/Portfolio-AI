"""
Export clean SQL CREATE TABLE, VIEW, FUNCTION, TRIGGER, POLICY, SEQUENCE, and TYPE statements 
from actual database schema. 

This generates the COMPLETE REAL schema as it exists in production.
"""
import os
import sys
import re
from pathlib import Path
from sqlalchemy import create_engine, inspect, text

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))


def get_pg_definition(engine, query, folder, filename_formatter):
    """Generic helper to fetch definitions from pg_catalog and save to files."""
    try:
        with engine.connect() as conn:
            results = conn.execute(text(query)).fetchall()
            if results:
                folder.mkdir(parents=True, exist_ok=True)
                for row in results:
                    name = row[0]
                    definition = row[1]
                    if not definition.strip().endswith(';'):
                        definition = definition.strip() + ';'
                    
                    file_path = folder / filename_formatter(name)
                    file_path.write_text(definition, encoding='utf-8')
                return len(results)
        return 0
    except Exception as e:
        print(f"    [ERROR] Failed to fetch definitions for {folder.name}: {e}")
        return 0


def export_complete_schema(db_url: str, schema_dir: Path, db_name: str):
    """Export all database objects into a modular structure."""
    
    print(f"[*] Generating complete schema for {db_name}...")
    
    try:
        engine = create_engine(db_url)
        inspector = inspect(engine)
        
        # 1. TYPES (Enums, etc.)
        print(f"    Exporting custom types...")
        type_query = """
            SELECT t.typname, 
                   'CREATE TYPE ' || t.typname || ' AS ENUM (' || 
                   string_agg('''' || e.enumlabel || '''', ', ' ORDER BY e.enumsortorder) || ')'
            FROM pg_type t
            JOIN pg_enum e ON t.oid = e.enumtypid
            JOIN pg_namespace n ON t.typnamespace = n.oid
            WHERE n.nspname = 'public'
            GROUP BY t.typname;
        """
        type_count = get_pg_definition(engine, type_query, schema_dir / "types", lambda name: f"{name}.sql")
        print(f"    Exported {type_count} custom types")

        # 2. SEQUENCES
        print(f"    Exporting sequences...")
        seq_query = """
            SELECT relname, 'CREATE SEQUENCE ' || relname || ';'
            FROM pg_class c
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = 'public' AND c.relkind = 'S';
        """
        seq_count = get_pg_definition(engine, seq_query, schema_dir / "sequences", lambda name: f"{name}.sql")
        print(f"    Exported {seq_count} sequences")

        # 3. TABLES
        table_dir = schema_dir / "tables"
        table_dir.mkdir(parents=True, exist_ok=True)
        table_names = sorted(inspector.get_table_names())
        print(f"    Found {len(table_names)} tables")
        
        for table_name in table_names:
            table_sql = [f"-- Table: {table_name}", f"DROP TABLE IF EXISTS {table_name} CASCADE;", "", f"CREATE TABLE {table_name} ("]
            
            # Columns
            columns = inspector.get_columns(table_name)
            col_defs = []
            for col in columns:
                col_name = col['name']
                col_type = str(col['type'])
                nullable = "" if col['nullable'] else " NOT NULL"
                default = f" DEFAULT {col['default']}" if col.get('default') else ""
                col_defs.append(f"    {col_name} {col_type}{nullable}{default}")
            table_sql.append(",\n".join(col_defs))
            
            # PK
            pk = inspector.get_pk_constraint(table_name)
            if pk and pk.get('constrained_columns'):
                table_sql.append(f",\n    PRIMARY KEY ({', '.join(pk['constrained_columns'])})")
            table_sql.append(");")
            
            # FKs
            fks = inspector.get_foreign_keys(table_name)
            if fks:
                table_sql.append("\n-- Foreign Keys")
                for fk in fks:
                    fk_name = fk.get('name', f"fk_{table_name}_{'_'.join(fk['constrained_columns'])}")
                    table_sql.append(f"ALTER TABLE {table_name} ADD CONSTRAINT {fk_name} FOREIGN KEY ({', '.join(fk['constrained_columns'])}) REFERENCES {fk['referred_table']}({', '.join(fk['referred_columns'])}){f' ON DELETE {fk.get('ondelete')}' if fk.get('ondelete') else ''}{f' ON UPDATE {fk.get('onupdate')}' if fk.get('onupdate') else ''};")
            
            # Indexes
            indexes = inspector.get_indexes(table_name)
            if indexes:
                table_sql.append("\n-- Indexes")
                pk_cols = set(pk.get('constrained_columns', [])) if pk else set()
                for idx in indexes:
                    valid_cols = [col for col in idx['column_names'] if col is not None]
                    if not valid_cols or (set(valid_cols) == pk_cols and len(valid_cols) == len(pk_cols)): continue
                    table_sql.append(f"CREATE {'UNIQUE ' if idx.get('unique') else ''}INDEX {idx['name']} ON {table_name} ({', '.join(valid_cols)});")
            
            (table_dir / f"{table_name}.sql").write_text('\n'.join(table_sql), encoding='utf-8')

        # 4. VIEWS
        print(f"    Exporting views...")
        view_query = "SELECT viewname, 'CREATE OR REPLACE VIEW ' || viewname || ' AS ' || definition FROM pg_views WHERE schemaname = 'public';"
        view_count = get_pg_definition(engine, view_query, schema_dir / "views", lambda name: f"{name}.sql")
        print(f"    Exported {view_count} views")

        # 5. FUNCTIONS
        print(f"    Exporting functions...")
        func_query = """
            SELECT proname, pg_get_functiondef(p.oid)
            FROM pg_proc p
            JOIN pg_namespace n ON p.pronamespace = n.oid
            WHERE n.nspname = 'public' 
              AND p.prokind != 'a'; -- Exclude aggregates
        """
        func_count = get_pg_definition(engine, func_query, schema_dir / "functions", lambda name: f"{name}.sql")
        print(f"    Exported {func_count} functions")

        # 6. TRIGGERS
        print(f"    Exporting triggers...")
        trigger_query = """
            SELECT tgname, pg_get_triggerdef(t.oid)
            FROM pg_trigger t
            JOIN pg_class c ON t.tgrelid = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = 'public' AND NOT t.tgisinternal;
        """
        trigger_count = get_pg_definition(engine, trigger_query, schema_dir / "triggers", lambda name: f"{name}.sql")
        print(f"    Exported {trigger_count} triggers")

        # 7. RLS POLICIES
        print(f"    Exporting RLS policies...")
        policy_query = """
            SELECT tablename, policyname, 
                   'CREATE POLICY "' || policyname || '" ON "' || tablename || '" FOR ' || cmd || 
                   ' TO ' || array_to_string(roles, ', ') || 
                   CASE WHEN qual IS NOT NULL THEN ' USING (' || qual || ')' ELSE '' END || 
                   CASE WHEN with_check IS NOT NULL THEN ' WITH CHECK (' || with_check || ')' ELSE '' END as definition
            FROM pg_policies
            WHERE schemaname = 'public';
        """
        policy_count = 0
        with engine.connect() as conn:
            policies = conn.execute(text(policy_query)).fetchall()
            if policies:
                pol_dir = schema_dir / "policies"
                pol_dir.mkdir(parents=True, exist_ok=True)
                for row in policies:
                    table_name, pol_name, definition = row
                    (pol_dir / f"{table_name}_{pol_name}.sql").write_text(definition + ";", encoding='utf-8')
                    policy_count += 1
        print(f"    Exported {policy_count} policies")

        # 8. MASTER INIT
        init_sql = ["-- Master Init Schema", "-- Generated: " + __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "", 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";', ""]
        # Order matters: Types -> Sequences -> Tables -> Functions -> Views -> Triggers -> Policies
        for subdir in ["types", "sequences", "tables", "functions", "views", "triggers", "policies"]:
            sd = schema_dir / subdir
            if sd.exists():
                init_sql.append(f"-- {subdir.upper()}")
                for f in sorted(sd.glob("*.sql")):
                    init_sql.append(f"\\i {subdir}/{f.name}")
                init_sql.append("")
        
        (schema_dir / "_init_schema.sql").write_text('\n'.join(init_sql), encoding='utf-8')
        
        engine.dispose()
        return True
        
    except Exception as e:
        print(f"[ERROR] Export failed: {e}")
        import traceback; traceback.print_exc()
        return False


def main():
    from dotenv import load_dotenv
    env_file = Path(__file__).parent.parent / "web_dashboard" / ".env"
    load_dotenv(env_file)
    schema_base = Path(__file__).parent.parent / "database" / "schema"
    for db in [{"name": "Supabase Production", "env": "SUPABASE_DATABASE_URL", "folder": "supabase"},
               {"name": "Research Database", "env": "RESEARCH_DATABASE_URL", "folder": "research"}]:
        url = os.getenv(db["env"])
        if url: export_complete_schema(url, schema_base / db["folder"], db["name"])


if __name__ == "__main__":
    main()
