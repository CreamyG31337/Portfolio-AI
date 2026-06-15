#!/usr/bin/env python3
"""Debug return calculation for Lance Colton on Project Chimera"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

from supabase_client import SupabaseClient
from datetime import datetime
import pandas as pd

client = SupabaseClient(use_service_role=True)

print("="*80)
print("DEBUGGING RETURN CALCULATION")
print("="*80)

# Get Lance's contributions
contrib_res = client.supabase.table('fund_contributions')\
    .select('*')\
    .eq('fund', 'Project Chimera')\
    .eq('contributor', 'Lance Colton')\
    .order('timestamp')\
    .execute()

contribs = pd.DataFrame(contrib_res.data)
print(f"\nLance's contributions: {len(contribs)}")
print(f"Total contributed: ${contribs['amount'].sum():,.2f}")
print(f"\nContributions:")
print(contribs[['timestamp', 'amount']].to_string(index=False))

# Get current fund value (latest portfolio positions)
latest_pos = client.supabase.table('portfolio_positions')\
    .select('date, shares, price')\
    .eq('fund', 'Project Chimera')\
    .order('date', desc=True)\
    .limit(100)\
    .execute()

if latest_pos.data:
    latest_df = pd.DataFrame(latest_pos.data)
    latest_date = latest_df['date'].iloc[0][:10]
    total_value = (latest_df['shares'].astype(float) * latest_df['price'].astype(float)).sum()
    print(f"\n\nFund value on {latest_date}: ${total_value:,.2f}")

# Calculate units using NAV
print("\n\nNAV-BASED UNIT CALCULATION:")
print("-"*40)

# Get all portfolio positions for NAV calculation
all_pos = client.supabase.table('portfolio_positions')\
    .select('date, shares, price')\
    .eq('fund', 'Project Chimera')\
    .order('date')\
    .execute()

pos_df = pd.DataFrame(all_pos.data)
pos_df['date_only'] = pos_df['date'].str[:10]
pos_df['value'] = pos_df['shares'].astype(float) * pos_df['price'].astype(float)

# Build historical NAVs
nav_by_date = pos_df.groupby('date_only')['value'].sum().to_dict()

print(f"Historical NAV data points: {len(nav_by_date)}")

# Simulate the return calculation
total_units = 0
user_units = 0
net_contribution = 0

for contrib in contribs.to_dict('records'):
    amount = float(contrib['amount'])
    is_withdrawal = contrib.get('is_withdrawal', False)
    timestamp = pd.to_datetime(contrib['timestamp'])
    date_str = timestamp.strftime('%Y-%m-%d')
    
    if is_withdrawal:
        continue  # Skip for now
    
    net_contribution += amount
    
    # Get NAV for this date
    if total_units == 0:
        nav = 1.0
    elif date_str in nav_by_date:
        nav = nav_by_date[date_str] / total_units
    else:
        nav = 1.0
        print(f"  WARNING: No NAV for {date_str}, using 1.0")
    
    units_purchased = amount / nav
    user_units += units_purchased
    total_units += units_purchased
    
    print(f"{date_str}: ${amount:>8.2f} / NAV {nav:>8.4f} = {units_purchased:>10.4f} units")

print(f"\nSUMMARY:")
print(f"  Total contribution: ${net_contribution:,.2f}")
print(f"  Total units: {user_units:,.4f}")
print(f"  Current NAV: ${total_value / total_units:.4f}" if total_units > 0 else "  N/A")
print(f"  Current value: ${user_units * (total_value / total_units):,.2f}" if total_units > 0 else "  N/A")
print(f"  Return: ${(user_units * (total_value / total_units) - net_contribution):,.2f}" if total_units > 0 else "  N/A")
print(f"  Return %: {((user_units * (total_value / total_units) - net_contribution) / net_contribution * 100):.2f}%" if net_contribution > 0 and total_units > 0 else "  N/A")
