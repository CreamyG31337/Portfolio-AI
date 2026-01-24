#!/usr/bin/env python3
"""Check database for new ETF snapshots"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from supabase_client import SupabaseClient

db = SupabaseClient()

# Check for new ETFs
print("\n" + "="*60)
print("Checking for NEW ETF snapshots (XBI, BOTZ, LIT)")
print("="*60)

for ticker in ['XBI', 'BOTZ', 'LIT']:
    result = db.supabase.table('etf_holdings_log').select('date, etf_ticker').eq('etf_ticker', ticker).limit(5).execute()
    if result.data:
        print(f"\n✅ {ticker}: Found {len(result.data)} snapshots")
        for row in result.data:
            # Count holdings for this snapshot
            count_result = db.supabase.table('etf_holdings_log').select('*', count='exact').eq('etf_ticker', ticker).eq('date', row['date']).execute()
            print(f"   - {row['date']}: {count_result.count} holdings")
    else:
        print(f"\n❌ {ticker}: No snapshots found")

# Verify existing ETFs weren't affected
print("\n" + "="*60)
print("Verifying EXISTING ETFs still intact")
print("="*60)

for ticker in ['ARKK', 'IWM']:
    result = db.supabase.table('etf_holdings_log').select('date').eq('etf_ticker', ticker).order('date', desc=True).limit(1).execute()
    if result.data:
        latest_date = result.data[0]['date']
        count_result = db.supabase.table('etf_holdings_log').select('*', count='exact').eq('etf_ticker', ticker).eq('date', latest_date).execute()
        print(f"✅ {ticker}: Latest snapshot {latest_date} has {count_result.count} holdings")
    else:
        print(f"❌ {ticker}: No data found!")
