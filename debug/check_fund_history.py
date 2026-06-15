#!/usr/bin/env python3
"""Check fund history to understand ownership discrepancy"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

from supabase_client import SupabaseClient
import pandas as pd

client = SupabaseClient(use_service_role=True)

print("="*80)
print("CHECKING FUND HISTORY")
print("="*80)

# Get first 20 contributions by date
print("\nFirst 20 contributions to Project Chimera:")
res = client.supabase.table('fund_contributions').select('*').eq('fund', 'Project Chimera').order('timestamp').limit(20).execute()
df = pd.DataFrame(res.data)

for row in df.to_dict('records'):
    print(f"{row['timestamp'][:10]} | {row['contributor']:20s} | ${row['amount']:8,.2f} | {row['contribution_type']}")

# Get first portfolio position date
print("\n" + "="*80)
print("First portfolio position date:")
pos_res = client.supabase.table('portfolio_positions').select('date').eq('fund', 'Project Chimera').order('date').limit(1).execute()
if pos_res.data:
    print(f"Fund started: {pos_res.data[0]['date'][:10]}")

# Check current contributor summary
print("\n" + "="*80)
print("Current contributor summary:")
contrib_res = client.supabase.table('fund_contributions').select('*').eq('fund', 'Project Chimera').execute()
contrib_df = pd.DataFrame(contrib_res.data)

summary = contrib_df.groupby('contributor')['amount'].sum().sort_values(ascending=False)
total = summary.sum()

for contributor, amount in summary.items():
    pct = (amount / total) * 100
    print(f"{contributor:20s} | ${amount:8,.2f} | {pct:5.2f}%")

print(f"{'TOTAL':20s} | ${total:8,.2f} | 100.00%")
