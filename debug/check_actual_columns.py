"""
Check what values the dashboard ACTUALLY uses vs what I calculated
"""
import os
import sys
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web_dashboard.supabase_client import SupabaseClient

def check_actual_columns():
    client = SupabaseClient()
    fund = "Project Chimera"
    
    # Fetch using SAME columns as dashboard (flask_data_utils / portfolio_metrics)
    all_rows = []
    offset = 0
    
    while True:
        result = client.supabase.table("portfolio_positions").select(
            "date, total_value, cost_basis, pnl, fund, currency, "
            "total_value_base, cost_basis_base, pnl_base, base_currency"
        ).eq("fund", fund).order("date").range(offset, offset + 1000 - 1).execute()
        
        if not result.data:
            break
        all_rows.extend(result.data)
        if len(result.data) < 1000:
            break
        offset += 1000
    
    print(f"Fetched {len(all_rows)} records")
    
    df = pd.DataFrame(all_rows)
    df['date'] = pd.to_datetime(df['date'])
    
    # Check for NULL values in key columns
    print("\nNULL value counts:")
    for col in ['total_value', 'cost_basis', 'pnl', 'total_value_base', 'cost_basis_base']:
        null_count = df[col].isnull().sum()
        print(f"  {col}: {null_count} ({null_count/len(df)*100:.1f}%)")
    
    # Check Dec 22 specifically
    dec22 = df[df['date'].dt.date.astype(str) == '2025-12-22']
    print(f"\nDec 22 records: {len(dec22)}")
    if not dec22.empty:
        print(f"  total_value sum: ${dec22['total_value'].sum():,.2f}")
        print(f"  cost_basis sum: ${dec22['cost_basis'].sum():,.2f}")
        print(f"  total_value_base sum: {dec22['total_value_base'].sum()}")
        print(f"  cost_basis_base sum: {dec22['cost_basis_base'].sum()}")
        
        # Are they NULL?
        print(f"\n  total_value NULLs: {dec22['total_value'].isnull().sum()}")
        print(f"  total_value_base NULLs: {dec22['total_value_base'].isnull().sum()}")

if __name__ == "__main__":
    check_actual_columns()
