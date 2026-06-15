#!/usr/bin/env python3
"""Check NUE position specifically in portfolio_positions"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

from supabase_client import SupabaseClient
import pandas as pd

client = SupabaseClient(use_service_role=True)

print("="*80)
print("Checking NUE in portfolio_positions table")
print("="*80)

# Check all funds for NUE
result = client.supabase.table('portfolio_positions')\
    .select('*')\
    .eq('ticker', 'NUE')\
    .order('date', desc=True)\
    .limit(20)\
    .execute()

if not result.data:
    print("NUE not found in portfolio_positions!")
    sys.exit(1)

df = pd.DataFrame(result.data)
print(f"\nFound {len(df)} NUE records in portfolio_positions")

# Group by fund
for fund in df['fund'].unique():
    fund_df = df[df['fund'] == fund]
    latest = fund_df.iloc[0]  # Most recent
    
    print(f"\n{'='*80}")
    print(f"NUE in fund: {fund}")
    print(f"{'='*80}")
    
    print(f"Latest record (date: {latest.get('date', 'UNKNOWN')}):")
    print(f"  Shares: {latest.get('shares', 0)}")
    print(f"  Price: ${latest.get('price', 0):.2f}")
    print(f"  Cost Basis: ${latest.get('cost_basis', 0):.2f}")
    print(f"  Currency: {latest.get('currency', 'UNKNOWN')}")
    print(f"  Market Value (shares * price): ${float(latest.get('shares', 0)) * float(latest.get('price', 0)):.2f}")
    print(f"  Calculated P&L: ${(float(latest.get('shares', 0)) * float(latest.get('price', 0))) - float(latest.get('cost_basis', 0)):.2f}")
    
    # Check if shares > 0 (required for latest_positions view)
    if float(latest.get('shares', 0)) <= 0:
        print(f"  ⚠️  ISSUE: Shares <= 0, so this won't appear in latest_positions view!")
    
    # Show all records for this fund
    print(f"\n  All records for {fund}:")
    for row in fund_df.to_dict('records'):
        date = row.get('date', 'UNKNOWN')
        shares = row.get('shares', 0)
        price = row.get('price', 0)
        cost_basis = row.get('cost_basis', 0)
        market_value = float(shares) * float(price) if shares and price else 0
        pnl = market_value - float(cost_basis) if cost_basis else 0
        
        print(f"    {date}: Shares={shares}, Price=${price:.2f}, Cost=${cost_basis:.2f}, Value=${market_value:.2f}, P&L=${pnl:.2f}")

# Also check latest_positions view with explicit query
print(f"\n{'='*80}")
print("Checking latest_positions view directly:")
print(f"{'='*80}")

lp_result = client.supabase.table('latest_positions')\
    .select('*')\
    .eq('ticker', 'NUE')\
    .execute()

if lp_result.data:
    print(f"Found {len(lp_result.data)} NUE records in latest_positions view")
    for row in lp_result.data:
        print(f"  {row.get('fund', 'UNKNOWN')}: Shares={row.get('shares', 0)}, P&L=${row.get('unrealized_pnl', 0):.2f}")
else:
    print("NUE not found in latest_positions view")
    print("This could mean:")
    print("  1. Shares <= 0 in the latest portfolio_positions record")
    print("  2. No records exist for NUE")
    print("  3. View needs to be refreshed")

