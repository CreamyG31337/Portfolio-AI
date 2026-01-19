#!/usr/bin/env python3
"""
Check Congress Trade Dates
==========================
Shows the relationship between transaction_date (when trade happened) 
and created_at (when it was added to database)
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

def check_trade_dates():
    """Check relationship between transaction_date and created_at."""
    client = SupabaseClient(use_service_role=True)
    
    print("\n" + "=" * 80)
    print("CONGRESS TRADES: Transaction Date vs Created At")
    print("=" * 80)
    print()
    print("transaction_date = When the trade actually happened (from disclosure)")
    print("created_at = When the trade was added to our database")
    print()
    
    # Get trades from January 7th
    jan_7 = datetime(2026, 1, 7).date()
    
    result = client.supabase.table('congress_trades')\
        .select('id, ticker, transaction_date, created_at, politician_id')\
        .eq('transaction_date', jan_7.isoformat())\
        .order('created_at', desc=True)\
        .limit(50)\
        .execute()
    
    if not result.data:
        print(f"❌ No trades found with transaction_date = {jan_7}")
        return
    
    print(f"Found {len(result.data)} trades with transaction_date = {jan_7}\n")
    print("Trade ID | Ticker | Transaction Date | Created At (when added to DB) | Days Difference")
    print("-" * 100)
    
    for trade in result.data:
        trade_id = trade.get('id', 'N/A')
        ticker = trade.get('ticker', 'N/A')
        tx_date = trade.get('transaction_date', 'N/A')
        created = trade.get('created_at', '')
        
        if created:
            try:
                created_dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                created_date = created_dt.date()
                
                # Calculate difference
                if isinstance(tx_date, str):
                    tx_date_obj = datetime.fromisoformat(tx_date).date()
                else:
                    tx_date_obj = tx_date
                
                days_diff = (created_date - tx_date_obj).days
                
                print(f"{trade_id:8} | {ticker:6} | {tx_date} | {created[:19]} | {days_diff:+4} days")
            except Exception as e:
                print(f"{trade_id:8} | {ticker:6} | {tx_date} | {created[:19]} | Error: {e}")
        else:
            print(f"{trade_id:8} | {ticker:6} | {tx_date} | N/A | N/A")
    
    print()
    print("=" * 80)
    print("EXPLANATION:")
    print("=" * 80)
    print()
    print("The API job fetches the 10 MOST RECENT DISCLOSURES (not trades by date).")
    print("If someone filed a disclosure on Jan 18 for a trade that happened on Jan 7,")
    print("the API will return it, and it gets added with transaction_date = Jan 7.")
    print()
    print("So you can have:")
    print("  - transaction_date = Jan 7 (when trade happened)")
    print("  - created_at = Jan 18 (when disclosure was filed and we added it)")
    print()
    
    # Also check recent additions
    print("=" * 80)
    print("RECENT ADDITIONS (Last 7 days)")
    print("=" * 80)
    print()
    
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    
    recent_result = client.supabase.table('congress_trades')\
        .select('id, ticker, transaction_date, created_at')\
        .gte('created_at', week_ago.isoformat())\
        .order('created_at', desc=True)\
        .limit(20)\
        .execute()
    
    if recent_result.data:
        print("Trade ID | Ticker | Transaction Date | Created At | Days Old")
        print("-" * 80)
        
        for trade in recent_result.data:
            trade_id = trade.get('id', 'N/A')
            ticker = trade.get('ticker', 'N/A')
            tx_date = trade.get('transaction_date', 'N/A')
            created = trade.get('created_at', '')
            
            if created and tx_date:
                try:
                    created_dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                    if isinstance(tx_date, str):
                        tx_date_obj = datetime.fromisoformat(tx_date).date()
                    else:
                        tx_date_obj = tx_date
                    
                    days_old = (created_dt.date() - tx_date_obj).days
                    print(f"{trade_id:8} | {ticker:6} | {tx_date} | {created[:19]} | {days_old:+3} days")
                except:
                    print(f"{trade_id:8} | {ticker:6} | {tx_date} | {created[:19]} | N/A")

if __name__ == "__main__":
    check_trade_dates()
