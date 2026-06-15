#!/usr/bin/env python3
"""Check what NAV values get_historical_fund_values is returning for Lance's contribution dates"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

from supabase_client import SupabaseClient
from datetime import datetime
import pandas as pd

client = SupabaseClient(use_service_role=True)

# Get Lance's contribution dates
print("="*80)
print("CHECKING NAV VALUES FOR LANCE'S CONTRIBUTIONS")
print("="*80)

contrib_res = client.supabase.table('fund_contributions').select('*').eq('contributor', 'Lance Colton').order('timestamp').execute()
df = pd.DataFrame(contrib_res.data)

print(f"\nLance's contributions:")
for row in df.to_dict('records'):
    date_str = row['timestamp'][:10]
    print(f"  {date_str}: ${row['amount']:,.2f}")

# For each date, check what the portfolio value was
print("\n" + "="*80)
print("PORTFOLIO VALUES ON EACH DATE")
print("="*80)

for row in df.to_dict('records'):
    contrib_date = row['timestamp'][:10]
    
    # Get portfolio positions for that date
    pos_res = client.supabase.table('portfolio_positions').select('date, total_value').eq('fund', 'Project Chimera').eq('date', contrib_date).execute()
    
    if pos_res.data:
        total = sum(float(p['total_value']) for p in pos_res.data)
        print(f"\n{contrib_date}:")
        print(f"  Portfolio records: {len(pos_res.data)}")
        print(f"  Total portfolio value: ${total:,.2f}")
    else:
        # Try closest date before
        pos_res = client.supabase.table('portfolio_positions').select('date, total_value').eq('fund', 'Project Chimera').lt('date', contrib_date).order('date', desc=True).limit(100).execute()
        if pos_res.data:
            # Get unique dates
            dates = sorted(set(p['date'][:10] for p in pos_res.data), reverse=True)
            closest = dates[0] if dates else None
            if closest:
                closest_records = [p for p in pos_res.data if p['date'][:10] == closest]
                total = sum(float(p['total_value']) for p in closest_records)
                print(f"\n{contrib_date}: NO DATA, using {closest}")
                print(f"  Portfolio records: {len(closest_records)}")
                print(f"  Total portfolio value: ${total:,.2f}")
        else:
            print(f"\n{contrib_date}: NO DATA FOUND!")

# Check first portfolio date
print("\n" + "="*80)
print("FUND HISTORY")
print("="*80)
first_pos = client.supabase.table('portfolio_positions').select('date, total_value').eq('fund', 'Project Chimera').order('date').limit(1).execute()
if first_pos.data:
    print(f"First portfolio date: {first_pos.data[0]['date'][:10]}")

# Check what dates have portfolio data
all_dates = client.supabase.table('portfolio_positions').select('date').eq('fund', 'Project Chimera').execute()
if all_dates.data:
    dates_df = pd.DataFrame(all_dates.data)
    dates_df['date'] = dates_df['date'].str[:10]
    unique_dates = sorted(dates_df['date'].unique())
    print(f"\nTotal unique dates with portfolio data: {len(unique_dates)}")
    print(f"Date range: {unique_dates[0]} to {unique_dates[-1]}")
    
    # Show dates around Sept 7
    sept_dates = [d for d in unique_dates if d.startswith('2025-09')]
    print(f"\nSeptember dates: {sept_dates}")
