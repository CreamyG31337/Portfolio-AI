#!/usr/bin/env python3
"""Check all positions with zero or near-zero P&L to identify the issue"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

from supabase_client import SupabaseClient
import pandas as pd

client = SupabaseClient(use_service_role=True)

print("="*80)
print("Checking all positions for zero P&L issues")
print("="*80)

# Get all positions from latest_positions
result = client.supabase.table('latest_positions').select('*').execute()

if not result.data:
    print("No positions found!")
    sys.exit(1)

df = pd.DataFrame(result.data)

print(f"\nTotal positions: {len(df)}")

# Find positions where unrealized_pnl is 0 or very close to 0
zero_pnl = df[df['unrealized_pnl'].abs() < 0.01].copy()

if len(zero_pnl) > 0:
    print(f"\n{'='*80}")
    print(f"Found {len(zero_pnl)} positions with P&L = 0 (or very close):")
    print(f"{'='*80}")
    
    for row in zero_pnl.to_dict('records'):
        ticker = row.get('ticker', 'UNKNOWN')
        fund = row.get('fund', 'UNKNOWN')
        shares = float(row.get('shares', 0))
        price = float(row.get('current_price', 0) or row.get('price', 0))
        cost_basis = float(row.get('cost_basis', 0))
        market_value = float(row.get('market_value', 0))
        unrealized_pnl = float(row.get('unrealized_pnl', 0))
        currency = row.get('currency', 'UNKNOWN')
        return_pct = row.get('return_pct', 0)
        
        calculated_pnl = market_value - cost_basis
        calculated_market_value = shares * price
        
        print(f"\n  {ticker} ({fund}):")
        print(f"    Shares: {shares}")
        print(f"    Price: ${price:.2f} ({currency})")
        print(f"    Cost Basis: ${cost_basis:.2f}")
        print(f"    Market Value (from view): ${market_value:.2f}")
        print(f"    Market Value (calculated): ${calculated_market_value:.2f}")
        print(f"    Unrealized P&L (from view): ${unrealized_pnl:.2f}")
        print(f"    P&L (calculated): ${calculated_pnl:.2f}")
        print(f"    Return %: {return_pct:.2f}%")
        
        # Check for issues
        issues = []
        if abs(market_value - calculated_market_value) > 0.01:
            issues.append(f"Market value mismatch: view={market_value:.2f} vs calculated={calculated_market_value:.2f}")
        
        if abs(unrealized_pnl - calculated_pnl) > 0.01:
            issues.append(f"P&L mismatch: view={unrealized_pnl:.2f} vs calculated={calculated_pnl:.2f}")
        
        if abs(cost_basis - market_value) < 0.01 and shares > 0 and price > 0:
            issues.append(f"Cost basis equals market value - position at break-even or data issue")
            if cost_basis > 0:
                avg_price = cost_basis / shares
                if abs(avg_price - price) < 0.01:
                    issues.append(f"Average price ({avg_price:.2f}) equals current price ({price:.2f}) - position just opened?")
        
        if cost_basis == 0 and shares > 0:
            issues.append(f"Cost basis is 0 but position has shares!")
        
        if issues:
            print(f"    ⚠️  ISSUES FOUND:")
            for issue in issues:
                print(f"       - {issue}")
        else:
            print(f"    ✓ No obvious issues (position may be at break-even)")
else:
    print("\nNo positions with zero P&L found")

# Summary
print(f"\n{'='*80}")
print("Summary Statistics:")
print(f"{'='*80}")
print(f"Total positions: {len(df)}")
print(f"Positions with P&L = 0: {len(zero_pnl)}")
print(f"Positions with NULL cost_basis: {df['cost_basis'].isna().sum()}")
print(f"Positions with cost_basis = 0: {(df['cost_basis'] == 0).sum()}")
print(f"Positions where cost_basis = market_value: {((df['market_value'] - df['cost_basis']).abs() < 0.01).sum()}")

# Check if there are positions where cost_basis equals market_value but P&L is not 0
mismatch = df[((df['market_value'] - df['cost_basis']).abs() < 0.01) & (df['unrealized_pnl'].abs() >= 0.01)]
if len(mismatch) > 0:
    print(f"\n⚠️  Found {len(mismatch)} positions where cost_basis = market_value but P&L != 0 (SQL view calculation issue?)")
    for row in mismatch.head(5).to_dict('records'):
        print(f"  {row.get('ticker', 'UNKNOWN')} ({row.get('fund', 'UNKNOWN')}): P&L=${row.get('unrealized_pnl', 0):.2f}, Cost=${row.get('cost_basis', 0):.2f}, Value=${row.get('market_value', 0):.2f}")

