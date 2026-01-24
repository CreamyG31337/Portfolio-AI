#!/usr/bin/env python3
"""Final verification for all 3 new ETFs"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from supabase_client import SupabaseClient

db = SupabaseClient(use_service_role=True)

print("="*60)
print("FINAL VERIFICATION - NEW ETFs")
print("="*60)

for ticker in ['XBI', 'BOTZ', 'LIT']:
    result = db.supabase.table('etf_holdings_log').select('date', count='exact').eq('etf_ticker', ticker).execute()
    
    if result.count > 0:
        # Get latest date
        latest = db.supabase.table('etf_holdings_log').select('date').eq('etf_ticker', ticker).order('date', desc=True).limit(1).execute()
        latest_date = latest.data[0]['date']
        count_for_date = db.supabase.table('etf_holdings_log').select('*', count='exact').eq('etf_ticker', ticker).eq('date', latest_date).execute()
        print(f"✅ {ticker}: {count_for_date.count} holdings on {latest_date}")
    else:
        print(f"❌ {ticker}: NO DATA")

print("\n" + "="*60)
print("SUMMARY")
print("="*60)
total = db.supabase.table('etf_holdings_log').select('*', count='exact').execute()
print(f"Total database rows: {total.count:,}")

# Count distinct ETF tickers
distinct = db.supabase.table('etf_holdings_log').select('etf_ticker').execute()
tickers = set(row['etf_ticker'] for row in distinct.data[:100])  # Sample first 100
print(f"Sample tickers: {sorted(tickers)}")
