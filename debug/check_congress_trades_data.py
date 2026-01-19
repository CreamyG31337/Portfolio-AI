#!/usr/bin/env python3
"""
Check Congress Trades Data
==========================
"""

import sys
import io
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

from supabase_client import SupabaseClient

def check_trades_data():
    """Check recent congress trades data."""
    client = SupabaseClient(use_service_role=True)
    
    today = datetime.now(timezone.utc).date()
    week_ago = today - timedelta(days=7)
    
    print("\n" + "=" * 80)
    print("CONGRESS TRADES DATA ANALYSIS")
    print("=" * 80)
    print()
    
    # Get trades from last 7 days
    result = client.supabase.table('congress_trades')\
        .select('id, ticker, transaction_date, created_at, politician_id')\
        .gte('created_at', week_ago.isoformat())\
        .order('created_at', desc=True)\
        .limit(100)\
        .execute()
    
    if not result.data:
        print("❌ No trades found in the last 7 days")
        return
    
    print(f"Total trades created in last 7 days: {len(result.data)}\n")
    
    # Group by date
    by_date = {}
    for trade in result.data:
        created = trade.get('created_at', '')
        if created:
            date_key = created[:10]
            if date_key not in by_date:
                by_date[date_key] = []
            by_date[date_key].append(trade)
    
    print("Trades by creation date:")
    for date_key in sorted(by_date.keys(), reverse=True):
        count = len(by_date[date_key])
        print(f"  {date_key}: {count} trades")
    
    print()
    print("Most recent 15 trades:")
    print("-" * 80)
    for i, trade in enumerate(result.data[:15], 1):
        ticker = trade.get('ticker', 'N/A')
        tx_date = trade.get('transaction_date', 'N/A')
        created = trade.get('created_at', 'N/A')[:19] if trade.get('created_at') else 'N/A'
        pol_id = trade.get('politician_id', 'N/A')
        print(f"{i:2}. {ticker:6} | TX: {tx_date} | Created: {created} | Pol ID: {pol_id}")
    
    # Check for issues
    print("\n" + "=" * 80)
    print("POTENTIAL ISSUES:")
    print("=" * 80)
    
    # Check for missing politician_id
    missing_pol = [t for t in result.data if not t.get('politician_id')]
    if missing_pol:
        print(f"⚠️  {len(missing_pol)} trades missing politician_id")
    
    # Check for duplicates (same ticker, date, politician)
    seen = set()
    duplicates = []
    for trade in result.data:
        key = (trade.get('ticker'), trade.get('transaction_date'), trade.get('politician_id'))
        if key in seen:
            duplicates.append(trade)
        seen.add(key)
    
    if duplicates:
        print(f"⚠️  {len(duplicates)} potential duplicates found")
    
    # Check job execution message details
    print("\n" + "=" * 80)
    print("JOB EXECUTION DETAILS:")
    print("=" * 80)
    
    exec_result = client.supabase.table('job_executions')\
        .select('*')\
        .eq('job_name', 'congress_trades')\
        .gte('started_at', week_ago.isoformat())\
        .order('started_at', desc=True)\
        .limit(5)\
        .execute()
    
    for exec_record in exec_result.data:
        started = exec_record.get('started_at', 'N/A')[:19] if exec_record.get('started_at') else 'N/A'
        status = exec_record.get('status', 'N/A')
        duration = exec_record.get('duration_ms', 0)
        message = exec_record.get('message') or exec_record.get('error_message', 'N/A')
        
        print(f"\n[{started}] {status} ({duration}ms)")
        if message and message != 'N/A':
            print(f"  Message: {message}")
        else:
            print(f"  (No detailed message)")

if __name__ == "__main__":
    check_trades_data()
