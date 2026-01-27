#!/usr/bin/env python3
"""
Diagnostic script to check ETF holdings data in Research DB
Helps diagnose why new ETFs aren't showing up in Latest Changes
"""

import sys
from pathlib import Path
from datetime import date, datetime
from collections import defaultdict

# Add parent directory to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from postgres_client import PostgresClient
import pandas as pd

def main():
    print("=" * 80)
    print("ETF Holdings Data Diagnostic")
    print("=" * 80)
    print()
    
    try:
        pc = PostgresClient()
        
        # 1. Get all unique ETFs
        print("1. All ETFs in database:")
        print("-" * 80)
        etfs_result = pc.execute_query("""
            SELECT DISTINCT etf_ticker 
            FROM etf_holdings_log 
            ORDER BY etf_ticker
        """)
        
        if not etfs_result:
            print("ERROR: No ETFs found in database!")
            return
        
        all_etfs = [row['etf_ticker'] for row in etfs_result]
        print(f"Found {len(all_etfs)} ETFs: {', '.join(all_etfs)}")
        print()
        
        # 2. Get date range for each ETF
        print("2. Date coverage per ETF:")
        print("-" * 80)
        etf_dates = {}
        for etf in all_etfs:
            dates_result = pc.execute_query("""
                SELECT 
                    MIN(date) as first_date,
                    MAX(date) as last_date,
                    COUNT(DISTINCT date) as date_count
                FROM etf_holdings_log
                WHERE etf_ticker = %s
            """, (etf,))
            
            if dates_result and dates_result[0]:
                row = dates_result[0]
                etf_dates[etf] = {
                    'first': row.get('first_date'),
                    'last': row.get('last_date'),
                    'count': row.get('date_count', 0)
                }
                print(f"  {etf:6s}: {row.get('first_date')} to {row.get('last_date')} ({row.get('date_count', 0)} dates)")
        
        print()
        
        # 3. Find the global latest date
        print("3. Global latest date:")
        print("-" * 80)
        latest_result = pc.execute_query("""
            SELECT MAX(date) as latest_date
            FROM etf_holdings_log
        """)
        
        if latest_result and latest_result[0]:
            global_latest = latest_result[0].get('latest_date')
            print(f"  Latest date across all ETFs: {global_latest}")
        else:
            print("  ERROR: Could not determine latest date")
            return
        
        print()
        
        # 4. Check which ETFs have data on the latest date
        print("4. ETFs with data on latest date:")
        print("-" * 80)
        latest_date_str = global_latest.isoformat() if hasattr(global_latest, 'isoformat') else str(global_latest)
        
        on_latest_result = pc.execute_query("""
            SELECT DISTINCT etf_ticker
            FROM etf_holdings_log
            WHERE date = %s
            ORDER BY etf_ticker
        """, (latest_date_str,))
        
        etfs_on_latest = [row['etf_ticker'] for row in on_latest_result] if on_latest_result else []
        print(f"  ETFs with data on {latest_date_str}: {len(etfs_on_latest)}")
        print(f"  {', '.join(etfs_on_latest)}")
        print()
        
        # 5. Find ETFs missing from latest date
        print("5. ETFs missing from latest date:")
        print("-" * 80)
        missing_etfs = [etf for etf in all_etfs if etf not in etfs_on_latest]
        if missing_etfs:
            print(f"  WARNING: {len(missing_etfs)} ETFs missing: {', '.join(missing_etfs)}")
            for etf in missing_etfs:
                if etf in etf_dates:
                    info = etf_dates[etf]
                    print(f"     {etf}: last data on {info['last']} ({info['count']} total dates)")
        else:
            print("  ✅ All ETFs have data on latest date")
        print()
        
        # 6. Check for ETFs with only 1 date (new ETFs)
        print("6. ETFs with only 1 date (newly added):")
        print("-" * 80)
        single_date_etfs = [etf for etf, info in etf_dates.items() if info['count'] == 1]
        if single_date_etfs:
            print(f"  Found {len(single_date_etfs)} ETFs with only 1 date:")
            for etf in single_date_etfs:
                info = etf_dates[etf]
                print(f"     {etf}: only has data on {info['first']}")
        else:
            print("  OK: All ETFs have multiple dates")
        print()
        
        # 7. Check holdings counts
        print("7. Holdings count per ETF (on latest date):")
        print("-" * 80)
        for etf in etfs_on_latest:
            count_result = pc.execute_query("""
                SELECT COUNT(*) as count
                FROM etf_holdings_log
                WHERE etf_ticker = %s AND date = %s
            """, (etf, latest_date_str))
            
            if count_result and count_result[0]:
                count = count_result[0].get('count', 0)
                print(f"  {etf:6s}: {count:4d} holdings")
        
        print()
        print("=" * 80)
        print("Diagnostic complete!")
        print("=" * 80)
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
