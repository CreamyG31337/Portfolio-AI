#!/usr/bin/env python3
"""Simulate what the dashboard sees - check all positions with zero P&L"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

# Mock streamlit for testing
import sys
sys.modules['streamlit'] = type(sys)('streamlit')
sys.modules['streamlit'].cache_data = lambda *args, **kwargs: lambda f: f

from streamlit_utils import get_current_positions
import pandas as pd

print("="*80)
print("Checking what get_current_positions returns (simulating dashboard)")
print("="*80)

# Check all funds
funds = ['Project Chimera', 'RRSP Lance Webull', 'TEST']

for fund in funds:
    print(f"\n{'='*80}")
    print(f"Fund: {fund}")
    print(f"{'='*80}")
    
    try:
        positions_df = get_current_positions(fund)
        
        if positions_df.empty:
            print(f"  No positions found")
            continue
        
        print(f"  Found {len(positions_df)} positions")
        
        # Check for CTRN and NUE (case-insensitive)
        ctrn = positions_df[positions_df['ticker'].str.upper() == 'CTRN']
        nue = positions_df[positions_df['ticker'].str.upper() == 'NUE']
        
        if len(ctrn) > 0:
            print(f"\n  ✓ Found CTRN:")
            for row in ctrn.to_dict('records'):
                print(f"    Shares: {row.get('shares', 0)}")
                print(f"    Price: ${row.get('current_price', 0) or row.get('price', 0):.2f}")
                print(f"    Cost Basis: ${row.get('cost_basis', 0):.2f}")
                print(f"    Market Value: ${row.get('market_value', 0):.2f}")
                print(f"    Unrealized P&L: ${row.get('unrealized_pnl', 0):.2f}")
                print(f"    Currency: {row.get('currency', 'UNKNOWN')}")
        
        if len(nue) > 0:
            print(f"\n  ✓ Found NUE:")
            for row in nue.to_dict('records'):
                print(f"    Shares: {row.get('shares', 0)}")
                print(f"    Price: ${row.get('current_price', 0) or row.get('price', 0):.2f}")
                print(f"    Cost Basis: ${row.get('cost_basis', 0):.2f}")
                print(f"    Market Value: ${row.get('market_value', 0):.2f}")
                print(f"    Unrealized P&L: ${row.get('unrealized_pnl', 0):.2f}")
                print(f"    Currency: {row.get('currency', 'UNKNOWN')}")
        
        # Find all positions with zero P&L
        zero_pnl = positions_df[positions_df['unrealized_pnl'].abs() < 0.01]
        if len(zero_pnl) > 0:
            print(f"\n  ⚠️  Found {len(zero_pnl)} positions with P&L = 0:")
            for row in zero_pnl.to_dict('records'):
                ticker = row.get('ticker', 'UNKNOWN')
                shares = row.get('shares', 0)
                cost_basis = row.get('cost_basis', 0)
                market_value = row.get('market_value', 0)
                pnl = row.get('unrealized_pnl', 0)
                print(f"    {ticker}: Shares={shares}, Cost=${cost_basis:.2f}, Value=${market_value:.2f}, P&L=${pnl:.2f}")
        
        # Show all tickers for this fund
        print(f"\n  All tickers in {fund}:")
        tickers = sorted(positions_df['ticker'].unique())
        for ticker in tickers:
            pos = positions_df[positions_df['ticker'] == ticker].iloc[0]
            pnl = pos.get('unrealized_pnl', 0)
            if abs(pnl) < 0.01:
                print(f"    {ticker}: P&L=${pnl:.2f} ⚠️")
            else:
                print(f"    {ticker}: P&L=${pnl:.2f}")
                
    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()

