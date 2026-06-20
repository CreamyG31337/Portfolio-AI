#!/usr/bin/env python3
"""Check trade_log for CTRN and NUE to see why they're not in latest_positions"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

from supabase_client import SupabaseClient
import pandas as pd

client = SupabaseClient(use_service_role=True)

print("="*80)
print("Checking trade_log for CTRN and NUE")
print("="*80)

# Check trade_log for CTRN
print("\nSearching trade_log for CTRN:")
ctrn_trades = client.supabase.table('trade_log')\
    .select('*')\
    .eq('ticker', 'CTRN')\
    .order('date', desc=False)\
    .execute()

if ctrn_trades.data:
    print(f"Found {len(ctrn_trades.data)} CTRN trades:")
    df_ctrn = pd.DataFrame(ctrn_trades.data)
    for trade in df_ctrn.to_dict('records'):
        print(f"  Date: {trade.get('date', 'UNKNOWN')}")
        print(f"  Action: {trade.get('action', 'UNKNOWN')}")
        print(f"  Reason: {trade.get('reason', 'UNKNOWN')}")
        print(f"  Shares: {trade.get('shares', 0)}")
        print(f"  Price: ${trade.get('price', 0):.2f}")
        print(f"  Fund: {trade.get('fund', 'UNKNOWN')}")
        print(f"  Currency: {trade.get('currency', 'UNKNOWN')}")
        print()
else:
    print("  CTRN not found in trade_log")

# Check trade_log for NUE
print("\nSearching trade_log for NUE:")
nue_trades = client.supabase.table('trade_log')\
    .select('*')\
    .eq('ticker', 'NUE')\
    .order('date', desc=False)\
    .execute()

if nue_trades.data:
    print(f"Found {len(nue_trades.data)} NUE trades:")
    df_nue = pd.DataFrame(nue_trades.data)
    for trade in df_nue.to_dict('records'):
        print(f"  Date: {trade.get('date', 'UNKNOWN')}")
        print(f"  Action: {trade.get('action', 'UNKNOWN')}")
        print(f"  Reason: {trade.get('reason', 'UNKNOWN')}")
        print(f"  Shares: {trade.get('shares', 0)}")
        print(f"  Price: ${trade.get('price', 0):.2f}")
        print(f"  Fund: {trade.get('fund', 'UNKNOWN')}")
        print(f"  Currency: {trade.get('currency', 'UNKNOWN')}")
        print()
else:
    print("  NUE not found in trade_log")

# Check portfolio_positions for these tickers
print(f"\n{'='*80}")
print("Checking portfolio_positions for CTRN and NUE:")
print(f"{'='*80}")

ctrn_pos = client.supabase.table('portfolio_positions')\
    .select('*')\
    .eq('ticker', 'CTRN')\
    .order('date', desc=True)\
    .limit(10)\
    .execute()

if ctrn_pos.data:
    print(f"\nFound {len(ctrn_pos.data)} CTRN records in portfolio_positions:")
    for pos in ctrn_pos.data:
        print(f"  Date: {pos.get('date', 'UNKNOWN')}, Fund: {pos.get('fund', 'UNKNOWN')}, Shares: {pos.get('shares', 0)}")
else:
    print("\nCTRN NOT in portfolio_positions - this is the problem!")

nue_pos = client.supabase.table('portfolio_positions')\
    .select('*')\
    .eq('ticker', 'NUE')\
    .order('date', desc=True)\
    .limit(10)\
    .execute()

if nue_pos.data:
    print(f"\nFound {len(nue_pos.data)} NUE records in portfolio_positions:")
    for pos in nue_pos.data:
        print(f"  Date: {pos.get('date', 'UNKNOWN')}, Fund: {pos.get('fund', 'UNKNOWN')}, Shares: {pos.get('shares', 0)}")
else:
    print("\nNUE NOT in portfolio_positions - this is the problem!")

