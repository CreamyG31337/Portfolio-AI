#!/usr/bin/env python3
"""Check Lance Colton's contributions for duplicates"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

from supabase_client import SupabaseClient
import pandas as pd

client = SupabaseClient(use_service_role=True)

# Get Lance's contributions
res = client.supabase.table('fund_contributions').select('*').eq('contributor', 'Lance Colton').order('timestamp').execute()
df = pd.DataFrame(res.data)

print(f'Total records: {len(df)}')
print(f'Total amount: ${df["amount"].sum():.2f}')

print('\nAll contributions:')
for row in df.to_dict('records'):
    print(f'{row["timestamp"]} | {row["contribution_type"]} | ${row["amount"]:.2f} | {row.get("notes", "")}')

# Check for duplicates
print('\n' + '='*80)
print('Checking for duplicates (same date + amount):')
df['date'] = pd.to_datetime(df['timestamp']).dt.date
duplicates = df[df.duplicated(subset=['date', 'amount', 'contribution_type'], keep=False)]
if len(duplicates) > 0:
    print(f'Found {len(duplicates)} duplicate records!')
    for row in duplicates.to_dict('records'):
        print(f'  {row["timestamp"]} | ${row["amount"]:.2f} | {row.get("notes", "")}')
else:
    print('No duplicates found')
