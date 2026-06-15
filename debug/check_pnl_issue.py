#!/usr/bin/env python3
"""Debug script to check why P&L shows $0 for some positions"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

from supabase_client import SupabaseClient
import pandas as pd

# Initialize client
client = SupabaseClient(use_service_role=True)

print("="*80)
print("Checking P&L calculation issues in latest_positions")
print("="*80)

# Query latest_positions for all funds
result = client.supabase.table('latest_positions').select('*').execute()

if not result.data:
    print("No positions found!")
    sys.exit(1)

df = pd.DataFrame(result.data)

print(f"\nFound {len(df)} positions across all funds")
print("\n" + "="*80)
print("Positions with unrealized_pnl = 0 (or very close to 0):")
print("="*80)

# Check positions with zero or near-zero P&L
zero_pnl = df[df['unrealized_pnl'].abs() < 0.01]
if len(zero_pnl) > 0:
    print(f"\nFound {len(zero_pnl)} positions with P&L = 0:")
    for row in zero_pnl.to_dict('records'):
        ticker = row.get('ticker', 'UNKNOWN')
        fund = row.get('fund', 'UNKNOWN')
        shares = row.get('shares', 0)
        price = row.get('current_price', 0) or row.get('price', 0)
        cost_basis = row.get('cost_basis', 0)
        market_value = row.get('market_value', 0)
        unrealized_pnl = row.get('unrealized_pnl', 0)
        currency = row.get('currency', 'UNKNOWN')
        
        print(f"\n  {ticker} ({fund}):")
        print(f"    Shares: {shares}")
        print(f"    Price: ${price:.2f} ({currency})")
        print(f"    Market Value: ${market_value:.2f}")
        print(f"    Cost Basis: ${cost_basis:.2f}")
        print(f"    Unrealized P&L: ${unrealized_pnl:.2f}")
        print(f"    Calculated P&L: ${market_value - cost_basis:.2f}")
        
        # Check if cost_basis equals market_value (which would cause 0 P&L)
        if abs(market_value - cost_basis) < 0.01:
            print(f"    ⚠️  ISSUE: cost_basis equals market_value!")
        elif cost_basis == 0:
            print(f"    ⚠️  ISSUE: cost_basis is 0!")
        elif market_value == 0:
            print(f"    ⚠️  ISSUE: market_value is 0!")
else:
    print("No positions with zero P&L found")

# Specifically check NUE
print("\n" + "="*80)
print("Checking NUE specifically:")
print("="*80)

nue_positions = df[df['ticker'] == 'NUE']
if len(nue_positions) > 0:
    for row in nue_positions.to_dict('records'):
        ticker = row.get('ticker', 'UNKNOWN')
        fund = row.get('fund', 'UNKNOWN')
        shares = row.get('shares', 0)
        price = row.get('current_price', 0) or row.get('price', 0)
        cost_basis = row.get('cost_basis', 0)
        market_value = row.get('market_value', 0)
        unrealized_pnl = row.get('unrealized_pnl', 0)
        currency = row.get('currency', 'UNKNOWN')
        date = row.get('date', 'UNKNOWN')
        
        print(f"\n  {ticker} ({fund}):")
        print(f"    Date: {date}")
        print(f"    Shares: {shares}")
        print(f"    Price: ${price:.2f} ({currency})")
        print(f"    Market Value: ${market_value:.2f}")
        print(f"    Cost Basis: ${cost_basis:.2f}")
        print(f"    Unrealized P&L (from view): ${unrealized_pnl:.2f}")
        print(f"    Calculated P&L (market_value - cost_basis): ${market_value - cost_basis:.2f}")
        
        # Check underlying portfolio_positions data
        print(f"\n    Checking underlying portfolio_positions data...")
        pp_result = client.supabase.table('portfolio_positions')\
            .select('*')\
            .eq('fund', fund)\
            .eq('ticker', ticker)\
            .order('date', desc=True)\
            .limit(5)\
            .execute()
        
        if pp_result.data:
            print(f"    Found {len(pp_result.data)} recent portfolio_positions records:")
            for i, pp_row in enumerate(pp_result.data[:3]):  # Show first 3
                pp_date = pp_row.get('date', 'UNKNOWN')
                pp_shares = pp_row.get('shares', 0)
                pp_price = pp_row.get('price', 0)
                pp_cost_basis = pp_row.get('cost_basis', 0)
                pp_market_value = pp_shares * pp_price if pp_shares and pp_price else 0
                pp_pnl = pp_market_value - pp_cost_basis
                
                print(f"      [{i+1}] Date: {pp_date}")
                print(f"          Shares: {pp_shares}, Price: ${pp_price:.2f}")
                print(f"          Cost Basis: ${pp_cost_basis:.2f}")
                print(f"          Market Value: ${pp_market_value:.2f}")
                print(f"          P&L: ${pp_pnl:.2f}")
else:
    print("  NUE not found in latest_positions!")

# Summary statistics
print("\n" + "="*80)
print("Summary Statistics:")
print("="*80)
print(f"Total positions: {len(df)}")
print(f"Positions with P&L = 0: {len(df[df['unrealized_pnl'].abs() < 0.01])}")
print(f"Positions with NULL cost_basis: {df['cost_basis'].isna().sum()}")
print(f"Positions with cost_basis = 0: {(df['cost_basis'] == 0).sum()}")
print(f"Positions where cost_basis = market_value: {((df['market_value'] - df['cost_basis']).abs() < 0.01).sum()}")

# Show sample of positions with good P&L for comparison
print("\n" + "="*80)
print("Sample positions with non-zero P&L (for comparison):")
print("="*80)
non_zero_pnl = df[df['unrealized_pnl'].abs() >= 0.01].head(5)
for row in non_zero_pnl.to_dict('records'):
    ticker = row.get('ticker', 'UNKNOWN')
    fund = row.get('fund', 'UNKNOWN')
    shares = row.get('shares', 0)
    price = row.get('current_price', 0) or row.get('price', 0)
    cost_basis = row.get('cost_basis', 0)
    market_value = row.get('market_value', 0)
    unrealized_pnl = row.get('unrealized_pnl', 0)
    
    print(f"  {ticker} ({fund}): Shares={shares}, Price=${price:.2f}, Cost=${cost_basis:.2f}, Value=${market_value:.2f}, P&L=${unrealized_pnl:.2f}")

