#!/usr/bin/env python3
"""Check CTRN position specifically"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

from supabase_client import SupabaseClient
import pandas as pd

client = SupabaseClient(use_service_role=True)

print("="*80)
print("Checking CTRN in portfolio_positions and latest_positions")
print("="*80)

# Check latest_positions view
lp_result = client.supabase.table('latest_positions')\
    .select('*')\
    .eq('ticker', 'CTRN')\
    .execute()

if lp_result.data:
    print(f"\nFound {len(lp_result.data)} CTRN records in latest_positions view:")
    for row in lp_result.data:
        fund = row.get('fund', 'UNKNOWN')
        shares = row.get('shares', 0)
        price = row.get('current_price', 0) or row.get('price', 0)
        cost_basis = row.get('cost_basis', 0)
        market_value = row.get('market_value', 0)
        unrealized_pnl = row.get('unrealized_pnl', 0)
        currency = row.get('currency', 'UNKNOWN')
        return_pct = row.get('return_pct', 0)
        
        print(f"\n  Fund: {fund}")
        print(f"  Shares: {shares}")
        print(f"  Price: ${price:.2f} ({currency})")
        print(f"  Cost Basis: ${cost_basis:.2f}")
        print(f"  Market Value: ${market_value:.2f}")
        print(f"  Unrealized P&L (from view): ${unrealized_pnl:.2f}")
        print(f"  Return %: {return_pct:.2f}%")
        print(f"  Calculated P&L (market_value - cost_basis): ${market_value - cost_basis:.2f}")
        
        if abs(unrealized_pnl) < 0.01 and abs(market_value - cost_basis) > 0.01:
            print(f"  ⚠️  ISSUE: View shows P&L=0 but calculated P&L is ${market_value - cost_basis:.2f}!")
        elif abs(market_value - cost_basis) < 0.01:
            print(f"  ⚠️  ISSUE: Cost basis equals market value (position at break-even or data issue)")
else:
    print("CTRN not found in latest_positions view")

# Check portfolio_positions table
print(f"\n{'='*80}")
print("Checking portfolio_positions table:")
print(f"{'='*80}")

pp_result = client.supabase.table('portfolio_positions')\
    .select('*')\
    .eq('ticker', 'CTRN')\
    .order('date', desc=True)\
    .limit(10)\
    .execute()

if pp_result.data:
    print(f"\nFound {len(pp_result.data)} CTRN records in portfolio_positions:")
    df = pd.DataFrame(pp_result.data)
    
    for fund in df['fund'].unique():
        fund_df = df[df['fund'] == fund].sort_values('date', ascending=False)
        latest = fund_df.iloc[0]
        
        print(f"\n  Fund: {fund}")
        print(f"  Latest record (date: {latest.get('date', 'UNKNOWN')}):")
        print(f"    Shares: {latest.get('shares', 0)}")
        print(f"    Price: ${latest.get('price', 0):.2f}")
        print(f"    Cost Basis: ${latest.get('cost_basis', 0):.2f}")
        print(f"    Currency: {latest.get('currency', 'UNKNOWN')}")
        
        shares = float(latest.get('shares', 0))
        price = float(latest.get('price', 0))
        cost_basis = float(latest.get('cost_basis', 0))
        market_value = shares * price
        pnl = market_value - cost_basis
        
        print(f"    Market Value (shares * price): ${market_value:.2f}")
        print(f"    Calculated P&L: ${pnl:.2f}")
        
        if abs(pnl) < 0.01:
            print(f"    ⚠️  P&L is essentially 0 - cost_basis matches market_value")
            print(f"    This could mean:")
            print(f"      1. Position was just opened at current price")
            print(f"      2. Cost basis was incorrectly set to current market value")
            print(f"      3. Price hasn't moved since purchase")
        
        # Show history
        print(f"\n    Recent history (last 5 records):")
        for row in fund_df.head(5).to_dict('records'):
            date = row.get('date', 'UNKNOWN')
            r_shares = row.get('shares', 0)
            r_price = row.get('price', 0)
            r_cost = row.get('cost_basis', 0)
            r_value = float(r_shares) * float(r_price) if r_shares and r_price else 0
            r_pnl = r_value - float(r_cost) if r_cost else 0
            print(f"      {date}: Shares={r_shares}, Price=${r_price:.2f}, Cost=${r_cost:.2f}, Value=${r_value:.2f}, P&L=${r_pnl:.2f}")
else:
    print("CTRN not found in portfolio_positions table")

