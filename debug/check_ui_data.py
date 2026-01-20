#!/usr/bin/env python3
"""Check what the UI would actually see"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'web_dashboard'))

from web_dashboard.flask_data_utils import get_current_positions_flask
import pandas as pd

df = get_current_positions_flask('Project Chimera')
print(f"Positions: {len(df)}")
print(f"\nColumns: {list(df.columns)}")

if 'market_value' in df.columns:
    print(f"\nMarket Value Column:")
    print(f"  Sample values: {df['market_value'].head(5).tolist()}")
    print(f"  Total: ${df['market_value'].sum():,.2f}")
    print(f"  Null count: {df['market_value'].isna().sum()}")
    print(f"  Zero count: {(df['market_value'] == 0).sum()}")
    
    # Check if it matches shares * price
    if 'shares' in df.columns and 'current_price' in df.columns:
        calculated = df['shares'] * df['current_price']
        print(f"\nCalculated (shares * price):")
        print(f"  Sample: {calculated.head(5).tolist()}")
        print(f"  Total: ${calculated.sum():,.2f}")
        print(f"\nMatch check:")
        mismatches = abs(df['market_value'] - calculated) > 0.01
        print(f"  Mismatches: {mismatches.sum()}")
        if mismatches.sum() > 0:
            print(f"  Mismatched rows:")
            for idx in df[mismatches].index[:5]:
                row = df.loc[idx]
                print(f"    {row['ticker']}: market_value={row['market_value']}, calculated={calculated.loc[idx]}")
else:
    print("\nNO market_value COLUMN!")
    if 'shares' in df.columns and 'current_price' in df.columns:
        calculated = df['shares'] * df['current_price']
        print(f"Calculated total (shares * price): ${calculated.sum():,.2f}")
