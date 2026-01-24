#!/usr/bin/env python3
"""Simple database check with debugging"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from supabase_client import SupabaseClient

db = SupabaseClient()

print("Testing database connection...")
print(f"Client initialized: {db is not None}")
print(f"Supabase client: {db.supabase is not None}")

# Try a simpler query first
print("\nTrying simple count query...")
try:
    result = db.supabase.table('etf_holdings_log').select('*', count='exact').limit(0).execute()
    print(f"✅ Total rows in etf_holdings_log: {result.count}")
except Exception as e:
    print(f"❌ Error: {e}")

# Try to get ANY etf_ticker
print("\nTrying to get distinct ETF tickers...")
try:
    result = db.supabase.table('etf_holdings_log').select('etf_ticker').limit(20).execute()
    if result.data:
        tickers = set(row['etf_ticker'] for row in result.data)
        print(f"✅ Found tickers: {sorted(tickers)}")
    else:
        print("❌ No data returned")
except Exception as e:
    print(f"❌ Error: {e}")

# Check specifically for new tickers
print("\nChecking for today's snapshots (2026-01-23)...")
try:
    result = db.supabase.table('et f_holdings_log').select('etf_ticker', count='exact').eq('date', '2026-01-23').execute()
    print(f"✅ Found {result.count} records for 2026-01-23")
    if result.data:
        tickers = set(row['etf_ticker'] for row in result.data)
        print(f"   Tickers: {sorted(tickers)}")
except Exception as e:
    print(f"❌ Error: {e}")
