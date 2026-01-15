"""
Generate database schema documentation using SQLAlchemy reflection
and create markdown documentation automatically.
"""
import os
import sys
from pathlib import Path
from sqlalchemy import create_engine, MetaData, inspect
from sqlalchemy.engine import reflection
import json

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

def generate_markdown_schema(db_url: str, output_file: str, db_name: str):
    """Generate markdown documentation for database schema."""
    
    print(f"[*] Generating schema documentation for {db_name}...")
    print(f"    Database URL: {db_url.split('@')[0].split(':')[0]}:***@{db_url.split('@')[1]}")
    
    try:
        # Create engine and reflect database
        engine = create_engine(db_url)
        metadata = MetaData()
        inspector = inspect(engine)
        
        # Get all table names
        table_names = inspector.get_table_names()
        print(f"    Found {len(table_names)} tables")
        
        # Start building markdown
        markdown = f"# {db_name} Database Schema\n\n"
        markdown += f"**Generated:** {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        markdown += f"**Total Tables:** {len(table_names)}\n\n"
        markdown += "---\n\n"
        
        # Table of contents
        markdown += "## Table of Contents\n\n"
        for table_name in sorted(table_names):
            markdown += f"- [{table_name}](#{table_name.replace('_', '-')})\n"
        markdown += "\n---\n\n"
        
        # Document each table
        for table_name in sorted(table_names):
            markdown += f"## {table_name}\n\n"
            
            # Get columns
            columns = inspector.get_columns(table_name)
            markdown += "### Columns\n\n"
            markdown += "| Column | Type | Nullable | Default |\n"
            markdown += "|--------|------|----------|----------|\n"
            
            for col in columns:
                col_name = col['name']
                col_type = str(col['type'])
                nullable = "✓" if col['nullable'] else "✗"
                default = str(col.get('default', '-')) if col.get('default') else '-'
                markdown += f"| `{col_name}` | {col_type} | {nullable} | {default} |\n"
            
            markdown += "\n"
            
            # Get primary keys
            pk_constraint = inspector.get_pk_constraint(table_name)
            if pk_constraint and pk_constraint.get('constrained_columns'):
                markdown += "### Primary Key\n\n"
                pk_cols = ', '.join([f"`{col}`" for col in pk_constraint['constrained_columns']])
                markdown += f"- {pk_cols}\n\n"
            
            # Get foreign keys
            fks = inspector.get_foreign_keys(table_name)
            if fks:
                markdown += "### Foreign Keys\n\n"
                markdown += "| Column | References | On Delete | On Update |\n"
                markdown += "|--------|------------|-----------|------------|\n"
                
                for fk in fks:
                    fk_col = ', '.join([f"`{col}`" for col in fk['constrained_columns']])
                    ref_table = fk['referred_table']
                    ref_col = ', '.join([f"`{col}`" for col in fk['referred_columns']])
                    on_delete = fk.get('ondelete', 'NO ACTION')
                    on_update = fk.get('onupdate', 'NO ACTION')
                    markdown += f"| {fk_col} | `{ref_table}`.{ref_col} | {on_delete} | {on_update} |\n"
                
                markdown += "\n"
            
            # Get indexes
            indexes = inspector.get_indexes(table_name)
            if indexes:
                markdown += "### Indexes\n\n"
                markdown += "| Name | Columns | Unique |\n"
                markdown += "|------|---------|--------|\n"
                
                for idx in indexes:
                    idx_name = idx['name']
                    idx_cols = ', '.join([f"`{col}`" for col in idx['column_names']])
                    is_unique = "✓" if idx.get('unique') else "✗"
                    markdown += f"| `{idx_name}` | {idx_cols} | {is_unique} |\n"
                
                markdown += "\n"
            
            markdown += "---\n\n"
        
        # Write to file
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding='utf-8')
        
        print(f"[OK] Schema documentation written to: {output_file}")
        print(f"     File size: {output_path.stat().st_size:,} bytes")
        
        engine.dispose()
        return True
        
    except Exception as e:
        print(f"[ERROR] Error generating schema documentation: {e}")
        import traceback
        traceback.print_exc()
        return False


def generate_json_schema(db_url: str, output_file: str, db_name: str):
    """Generate JSON schema documentation for programmatic access."""
    
    print(f"[*] Generating JSON schema for {db_name}...")
    
    try:
        engine = create_engine(db_url)
        inspector = inspect(engine)
        
        schema_data = {
            "database_name": db_name,
            "generated_at": __import__('datetime').datetime.now().isoformat(),
            "tables": {}
        }
        
        table_names = inspector.get_table_names()
        
        for table_name in table_names:
            table_data = {
                "columns": [],
                "primary_key": [],
                "foreign_keys": [],
                "indexes": []
            }
            
            # Columns
            for col in inspector.get_columns(table_name):
                table_data["columns"].append({
                    "name": col['name'],
                    "type": str(col['type']),
                    "nullable": col['nullable'],
                    "default": str(col.get('default')) if col.get('default') else None
                })
            
            # Primary key
            pk = inspector.get_pk_constraint(table_name)
            if pk and pk.get('constrained_columns'):
                table_data["primary_key"] = pk['constrained_columns']
            
            # Foreign keys
            for fk in inspector.get_foreign_keys(table_name):
                table_data["foreign_keys"].append({
                    "columns": fk['constrained_columns'],
                    "referenced_table": fk['referred_table'],
                    "referenced_columns": fk['referred_columns'],
                    "on_delete": fk.get('ondelete'),
                    "on_update": fk.get('onupdate')
                })
            
            # Indexes
            for idx in inspector.get_indexes(table_name):
                table_data["indexes"].append({
                    "name": idx['name'],
                    "columns": idx['column_names'],
                    "unique": idx.get('unique', False)
                })
            
            schema_data["tables"][table_name] = table_data
        
        # Write JSON
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(schema_data, indent=2), encoding='utf-8')
        
        print(f"[OK] JSON schema written to: {output_file}")
        
        engine.dispose()
        return True
        
    except Exception as e:
        print(f"[ERROR] Error generating JSON schema: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Generate schema documentation for all databases."""
    
    print("=" * 80)
    print("DATABASE SCHEMA DOCUMENTATION GENERATOR")
    print("=" * 80)
    print()
    
    # Load environment variables
    from dotenv import load_dotenv
    env_file = Path(__file__).parent.parent / "web_dashboard" / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        print(f"[+] Loaded environment from: {env_file}")
    else:
        print("[!] No .env file found, using system environment variables")
    
    print()
    
    # Output directory
    docs_dir = Path(__file__).parent.parent / "docs" / "database"
    
    # Document each database
    databases = [
        {
            "name": "Supabase Production",
            "url_env": "SUPABASE_DATABASE_URL",
            "output_md": docs_dir / "supabase_schema.md",
            "output_json": docs_dir / "supabase_schema.json"
        },
        {
            "name": "Research Database",
            "url_env": "RESEARCH_DATABASE_URL", 
            "output_md": docs_dir / "research_schema.md",
            "output_json": docs_dir / "research_schema.json"
        }
    ]
    
    success_count = 0
    
    for db_config in databases:
        db_url = os.getenv(db_config["url_env"])
        
        if not db_url:
            print(f"[SKIP] Skipping {db_config['name']} - {db_config['url_env']} not set")
            print()
            continue
        
        print(f"[>>] Processing: {db_config['name']}")
        print()
        
        # Generate markdown
        if generate_markdown_schema(db_url, str(db_config["output_md"]), db_config["name"]):
            success_count += 1
        
        print()
        
        # Generate JSON
        if generate_json_schema(db_url, str(db_config["output_json"]), db_config["name"]):
            success_count += 1
        
        print()
        print("-" * 80)
        print()
    
    print("=" * 80)
    print(f"[DONE] Generated {success_count} schema documentation files")
    print(f"[DIR] Output directory: {docs_dir}")
    print("=" * 80)


if __name__ == "__main__":
    main()
