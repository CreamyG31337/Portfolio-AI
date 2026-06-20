#!/usr/bin/env python3
"""Check ALL positions in latest_positions for zero P&L, including any that might match CTRN/NUE"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

from supabase_client import SupabaseClient
import pandas as pd

client = SupabaseClient(use_service_role=True)

print("="*80)
print("Checking ALL positions in latest_positions view")
print("="*80)

# Get ALL positions with pagination
all_rows = []
batch_size = 1000
offset = 0

while True:
    result = client.supabase.table('latest_positions')\
        .select('*')\
        .range(offset, offset + batch_size - 1)\
        .execute()
    
    if not result.data:
        break
    
    all_rows.extend(result.data)
    
    if len(result.data) < batch_size:
        break
    
    offset += batch_size
    
    if offset > 50000:
        print("Warning: Reached 50,000 row safety limit")
        break

if not all_rows:
    print("No positions found!")
    sys.exit(1)

df = pd.DataFrame(all_rows)
print(f"\nTotal positions: {len(df)}")

# Check for zero P&L
zero_pnl = df[df['unrealized_pnl'].abs() < 0.01].copy()

print(f"\n{'='*80}")
print(f"Positions with P&L = 0 (or very close to 0): {len(zero_pnl)}")
print(f"{'='*80}")

if len(zero_pnl) > 0:
    for row in zero_pnl.to_dict('records'):
        ticker = row.get('ticker', 'UNKNOWN')
        fund = row.get('fund', 'UNKNOWN')
        shares = float(row.get('shares', 0))
        price = float(row.get('current_price', 0) or row.get('price', 0))
        cost_basis = float(row.get('cost_basis', 0))
        market_value = float(row.get('market_value', 0))
        unrealized_pnl = float(row.get('unrealized_pnl', 0))
        currency = row.get('currency', 'UNKNOWN')
        
        calculated_pnl = market_value - cost_basis
        
        print(f"\n  {ticker} ({fund}):")
        print(f"    Shares: {shares}")
        print(f"    Price: ${price:.2f} ({currency})")
        print(f"    Cost Basis: ${cost_basis:.2f}")
        print(f"    Market Value: ${market_value:.2f}")
        print(f"    Unrealized P&L (view): ${unrealized_pnl:.2f}")
        print(f"    Calculated P&L: ${calculated_pnl:.2f}")
        
        if abs(cost_basis - market_value) < 0.01:
            print(f"    ⚠️  Cost basis equals market value!")
            if shares > 0 and price > 0:
                avg_price = cost_basis / shares
                print(f"    Average price: ${avg_price:.2f}, Current price: ${price:.2f}")
                if abs(avg_price - price) < 0.01:
                    print(f"    ⚠️  Average price equals current price - position at break-even or data issue")

# Also search for CTRN and NUE case-insensitively
print(f"\n{'='*80}")
print("Searching for CTRN and NUE (case-insensitive):")
print(f"{'='*80}")

ctrn_matches = df[df['ticker'].str.upper() == 'CTRN']
nue_matches = df[df['ticker'].str.upper() == 'NUE']

if len(ctrn_matches) > 0:
    print(f"\nFound {len(ctrn_matches)} CTRN positions:")
    for row in ctrn_matches.to_dict('records'):
        print(f"  {row.get('ticker')} in {row.get('fund')}: P&L=${row.get('unrealized_pnl', 0):.2f}")
else:
    print("\nCTRN not found (case-insensitive search)")

if len(nue_matches) > 0:
    print(f"\nFound {len(nue_matches)} NUE positions:")
    for row in nue_matches.to_dict('records'):
        print(f"  {row.get('ticker')} in {row.get('fund')}: P&L=${row.get('unrealized_pnl', 0):.2f}")
else:
    print("\nNUE not found (case-insensitive search)")

# Show all funds and their ticker counts
print(f"\n{'='*80}")
print("All funds and position counts:")
print(f"{'='*80}")
for fund in sorted(df['fund'].unique()):
    fund_df = df[df['fund'] == fund]
    zero_count = len(fund_df[fund_df['unrealized_pnl'].abs() < 0.01])
    print(f"  {fund}: {len(fund_df)} positions, {zero_count} with zero P&L")

