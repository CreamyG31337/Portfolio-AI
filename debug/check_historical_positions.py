#!/usr/bin/env python3
"""Check if historical portfolio_positions exist for CTRN and NUE"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

from supabase_client import SupabaseClient
import pandas as pd

client = SupabaseClient(use_service_role=True)

print("="*80)
print("Checking historical portfolio_positions for CTRN and NUE")
print("="*80)

# Check CTRN
print("\nChecking CTRN in portfolio_positions:")
ctrn_pos = client.supabase.table('portfolio_positions')\
    .select('*')\
    .eq('ticker', 'CTRN')\
    .order('date')\
    .execute()

if ctrn_pos.data:
    df = pd.DataFrame(ctrn_pos.data)
    print(f"Found {len(df)} CTRN records")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")
    print(f"Funds: {df['fund'].unique()}")
    print("\nSample records:")
    for row in df.head(10).to_dict('records'):
        print(f"  {row.get('date', 'UNKNOWN')[:10]}: {row.get('fund', 'UNKNOWN')} - Shares={row.get('shares', 0)}, Cost=${row.get('cost_basis', 0):.2f}")
else:
    print("NO CTRN records found in portfolio_positions!")

# Check NUE
print("\n" + "="*80)
print("Checking NUE in portfolio_positions:")
nue_pos = client.supabase.table('portfolio_positions')\
    .select('*')\
    .eq('ticker', 'NUE')\
    .order('date')\
    .execute()

if nue_pos.data:
    df = pd.DataFrame(nue_pos.data)
    print(f"Found {len(df)} NUE records")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")
    print(f"Funds: {df['fund'].unique()}")
    print("\nSample records:")
    for row in df.head(10).to_dict('records'):
        print(f"  {row.get('date', 'UNKNOWN')[:10]}: {row.get('fund', 'UNKNOWN')} - Shares={row.get('shares', 0)}, Cost=${row.get('cost_basis', 0):.2f}")
else:
    print("NO NUE records found in portfolio_positions!")

# Compare with trade dates
print("\n" + "="*80)
print("Comparing with trade_log dates:")
print("="*80)

# Get CTRN trades
ctrn_trades = client.supabase.table('trade_log')\
    .select('date, fund')\
    .eq('ticker', 'CTRN')\
    .order('date')\
    .execute()

if ctrn_trades.data:
    trade_df = pd.DataFrame(ctrn_trades.data)
    print(f"\nCTRN trades: {len(trade_df)} trades")
    print(f"Trade date range: {trade_df['date'].min()} to {trade_df['date'].max()}")
    print(f"Funds with trades: {trade_df['fund'].unique()}")
    
    if ctrn_pos.data:
        pos_df = pd.DataFrame(ctrn_pos.data)
        print(f"\nCTRN positions: {len(pos_df)} records")
        print(f"Position date range: {pos_df['date'].min()} to {pos_df['date'].max()}")
        print(f"Funds with positions: {pos_df['fund'].unique()}")
        
        # Check if all trade dates have corresponding positions
        trade_dates = set(pd.to_datetime(trade_df['date']).dt.date)
        pos_dates = set(pd.to_datetime(pos_df['date']).dt.date)
        missing_dates = trade_dates - pos_dates
        if missing_dates:
            print(f"\n⚠️  MISSING: {len(missing_dates)} trade dates have no portfolio_positions entries:")
            for date in sorted(missing_dates)[:10]:
                print(f"  {date}")
        else:
            print("\n✓ All trade dates have portfolio_positions entries")
    else:
        print("\n[WARNING] NO portfolio_positions found for CTRN trades!")

# Get NUE trades
nue_trades = client.supabase.table('trade_log')\
    .select('date, fund')\
    .eq('ticker', 'NUE')\
    .order('date')\
    .execute()

if nue_trades.data:
    trade_df = pd.DataFrame(nue_trades.data)
    print(f"\nNUE trades: {len(trade_df)} trades")
    print(f"Trade date range: {trade_df['date'].min()} to {trade_df['date'].max()}")
    print(f"Funds with trades: {trade_df['fund'].unique()}")
    
    if nue_pos.data:
        pos_df = pd.DataFrame(nue_pos.data)
        print(f"\nNUE positions: {len(pos_df)} records")
        print(f"Position date range: {pos_df['date'].min()} to {pos_df['date'].max()}")
        print(f"Funds with positions: {pos_df['fund'].unique()}")
        
        # Check if all trade dates have corresponding positions
        trade_dates = set(pd.to_datetime(trade_df['date']).dt.date)
        pos_dates = set(pd.to_datetime(pos_df['date']).dt.date)
        missing_dates = trade_dates - pos_dates
        if missing_dates:
            print(f"\n⚠️  MISSING: {len(missing_dates)} trade dates have no portfolio_positions entries:")
            for date in sorted(missing_dates)[:10]:
                print(f"  {date}")
        else:
            print("\n✓ All trade dates have portfolio_positions entries")
    else:
        print("\n[WARNING] NO portfolio_positions found for NUE trades!")

