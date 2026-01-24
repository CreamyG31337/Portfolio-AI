#!/usr/bin/env python3
"""Verify ETF snapshots using service role (production DB)"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from supabase_client import SupabaseClient

# Use service role like the job does
db = SupabaseClient(use_service_role=True)

print("\n" + "="*60)
print("Checking NEW ETF snapshots (XBI, BOTZ, LIT)")
print("="*60)

for ticker in ['XBI', 'BOTZ', 'LIT']:
    result = db.supabase.table('etf_holdings_log').select('date', count='exact').eq('etf_ticker', ticker).execute()
    
    if result.count > 0:
        print(f"\n✅ {ticker}: {result.count} total holdings across all dates")
        
        # Get unique dates
        dates_result = db.supabase.rpc('get_distinct_dates_for_etf', {'etf': ticker}).execute() if hasattr(db.supabase, 'rpc') else None
        
        # Fallback: just show latest date
        latest = db.supabase.table('etf_holdings_log').select('date').eq('etf_ticker', ticker).order('date', desc=True).limit(1).execute()
        if latest.data:
            latest_date = latest.data[0]['date']
            count_for_date = db.supabase.table('etf_holdings_log').select('*', count='exact').eq('etf_ticker', ticker).eq('date', latest_date).execute()
            print(f"   Latest: {latest_date} with {count_for_date.count} holdings")
    else:
        print(f"\n❌ {ticker}: No data found")

print("\n" + "="*60)
print("Verifying EXISTING ETFs still intact (spot check)")
print("="*60)

for ticker in ['ARKK', 'ARKQ', 'IWM', 'IVV']:
    latest = db.supabase.table('etf_holdings_log').select('date').eq('etf_ticker', ticker).order('date', desc=True).limit(1).execute()
    
    if latest.data:
        latest_date = latest.data[0]['date']
        count_for_date = db.supabase.table('etf_holdings_log').select('*', count='exact').eq('etf_ticker', ticker).eq('date', latest_date).execute()
        print(f"✅ {ticker}: {latest_date} ({count_for_date.count} holdings)")
    else:
        print(f"❌ {ticker}: No data!")

print("\n" + "="*60)
print("Summary")
print("="*60)
total = db.supabase.table('etf_holdings_log').select('*', count='exact').execute()
print(f"Total rows in database: {total.count:,}")
