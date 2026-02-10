
import sys
from pathlib import Path
import json

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from supabase_client import SupabaseClient

def main():
    print("LISTING TABLES")
    client = SupabaseClient(use_service_role=True)
    
    # We can't easily query information_schema via the JS client usually unless exposed.
    # But we can try querying standard tables or use a specific function if it exists.
    # Alternatively, let's just try to 'guess' by trying to select from likely names.
    
    candidates = [
        'congress_trades_analysis',
        'congress_trade_analysis',
        'trade_analysis',
        'analysis',
        'congress_trades' # maybe it's a column here?
    ]
    
    for table in candidates:
        try:
            print(f"Checking '{table}'...")
            client.supabase.table(table).select('count', count='exact').limit(1).execute()
            print(f"  [EXISTS] {table}")
        except Exception as e:
            print(f"  [MISSING] {table}: {e}")

    # Also check if 'reasoning' is a column in congress_trades
    try:
        print("Checking 'reasoning' column in congress_trades...")
        res = client.supabase.table('congress_trades').select('reasoning').limit(1).execute()
        print("  [EXISTS] 'reasoning' column found in congress_trades!")
    except Exception as e:
        print(f"  [MISSING] 'reasoning' column: {e}")

if __name__ == "__main__":
    main()
