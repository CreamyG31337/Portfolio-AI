import sys
import os
import pandas as pd
from datetime import datetime

# Explicitly add the web_dashboard directory to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
# Assumes script is in web_dashboard/debug/
web_dashboard_dir = os.path.abspath(os.path.join(current_dir, '..'))

if web_dashboard_dir not in sys.path:
    sys.path.append(web_dashboard_dir)

print(f"Added to sys.path: {web_dashboard_dir}")

try:
    from supabase_client import SupabaseClient
    from dotenv import load_dotenv
except ImportError as e:
    print(f"ImportError: {e}")
    # Try adding one level up just in case
    root_dir = os.path.abspath(os.path.join(web_dashboard_dir, '..'))
    sys.path.append(root_dir)
    print(f"Added root to sys.path: {root_dir}")
    from web_dashboard.supabase_client import SupabaseClient
    from dotenv import load_dotenv

load_dotenv()

def check_duplicates():
    try:
        # USE SERVICE ROLE TO BYPASS RLS
        client = SupabaseClient(use_service_role=True)
    except Exception as e:
        print(f"Failed to initialize SupabaseClient: {e}")
        return

    # Query all positions for Project Chimera
    print("Querying portfolio_positions for Project Chimera (Admin)...")
    
    # We paginate just in case
    all_rows = []
    batch_size = 1000
    offset = 0
    
    while True:
        try:
            query = client.supabase.table("portfolio_positions") \
                .select("*") \
                .eq("fund", "Project Chimera") \
                .range(offset, offset + batch_size - 1)
            
            result = query.execute()
            
            if not result.data:
                break
                
            all_rows.extend(result.data)
            
            if len(result.data) < batch_size:
                break
                
            offset += batch_size
            print(f"Fetched {len(all_rows)} rows...")
            
        except Exception as e:
            print(f"Error fetching data: {e}")
            break
            
    if not all_rows:
        print("No data found for Project Chimera.")
        return

    df = pd.DataFrame(all_rows)
    print(f"Total rows: {len(df)}")
    
    if df.empty:
        return
        
    # Convert date to datetime
    if 'date' in df.columns:
        df['date_dt'] = pd.to_datetime(df['date'])
        df['date_key'] = df['date'].astype(str).str[:10]
    
    # Check logic used in portfolio_metrics / flask_data_utils: date_key (YYYY-MM-DD) and ticker
    duplicates_logic = df[df.duplicated(subset=['date_key', 'ticker'], keep=False)]
    
    if not duplicates_logic.empty:
        print(f"\nCRITICAL (dashboard logic): Found {len(duplicates_logic)} duplicates based on date_key and ticker!")
        
        # Show detail of duplicates to see if they are identical or different
        print("\nDetail of duplicates (sorted by ticker, date):")
        # Select relevant columns to inspect
        cols = ['date', 'date_key', 'ticker', 'shares', 'price', 'total_value', 'id']
        if 'created_at' in df.columns:
            cols.append('created_at')
            
        # Group by ticker and date_key to show them together
        dup_groups = duplicates_logic.groupby(['ticker', 'date_key'])
        
        count = 0
        for name, group in dup_groups:
            print(f"\n--- Ticker: {name[0]}, DateKey: {name[1]} ---")
            print(group[cols].to_string(index=False))
            
            count += 1
            if count >= 5:
                print("\n... (showing first 5 groups of duplicates only) ...")
                break
    else:
        print("No duplicates based on date_key and ticker.")

if __name__ == "__main__":
    check_duplicates()
