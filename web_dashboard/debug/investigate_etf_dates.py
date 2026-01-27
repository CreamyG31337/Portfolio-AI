#!/usr/bin/env python3
"""
Investigate ETF date filtering issue
Check what dates exist and why the filter isn't working
"""

import sys
from pathlib import Path
from datetime import date, datetime, timedelta

sys.path.append(str(Path(__file__).resolve().parent.parent))

from postgres_client import PostgresClient

def main():
    print("=" * 80)
    print("ETF Date Filter Investigation")
    print("=" * 80)
    print()
    
    pc = PostgresClient()
    
    # 1. Check all available dates
    print("1. All dates in database (last 10):")
    print("-" * 80)
    dates_result = pc.execute_query("""
        SELECT DISTINCT date 
        FROM etf_holdings_log 
        ORDER BY date DESC 
        LIMIT 10
    """)
    
    if dates_result:
        for row in dates_result:
            print(f"  {row['date']}")
    print()
    
    # 2. Check what date get_as_of_date would return for today
    print("2. What get_as_of_date logic would return:")
    print("-" * 80)
    today = date.today()
    print(f"  Today: {today}")
    
    # Simulate get_as_of_date logic
    latest_result = pc.execute_query("""
        SELECT date FROM etf_holdings_log
        WHERE date <= %s
        ORDER BY date DESC
        LIMIT 1
    """, (today.isoformat(),))
    
    if latest_result:
        as_of_date = latest_result[0]['date']
        print(f"  get_as_of_date({today}) would return: {as_of_date}")
    print()
    
    # 3. Check ETFs by date - see what's on each recent date
    print("3. ETF counts by date (last 5 days):")
    print("-" * 80)
    recent_dates_result = pc.execute_query("""
        SELECT DISTINCT date 
        FROM etf_holdings_log 
        ORDER BY date DESC 
        LIMIT 5
    """)
    
    if recent_dates_result:
        for row in recent_dates_result:
            check_date = row['date']
            etf_count_result = pc.execute_query("""
                SELECT COUNT(DISTINCT etf_ticker) as count
                FROM etf_holdings_log
                WHERE date = %s
            """, (check_date.isoformat() if hasattr(check_date, 'isoformat') else str(check_date),))
            
            count = etf_count_result[0]['count'] if etf_count_result else 0
            print(f"  {check_date}: {count} ETFs")
    print()
    
    # 4. Check specific new ETFs - what dates do they have?
    print("4. New ETF dates (sample):")
    print("-" * 80)
    new_etfs = ['SMH', 'BUG', 'SOXX', 'IBB']
    for etf in new_etfs:
        dates_result = pc.execute_query("""
            SELECT DISTINCT date 
            FROM etf_holdings_log 
            WHERE etf_ticker = %s
            ORDER BY date DESC
        """, (etf,))
        
        if dates_result:
            dates = [str(row['date']) for row in dates_result]
            print(f"  {etf}: {', '.join(dates)}")
    print()
    
    # 5. Check if job ran - look for recent data
    print("5. Most recent data per ETF:")
    print("-" * 80)
    recent_result = pc.execute_query("""
        SELECT etf_ticker, MAX(date) as latest_date
        FROM etf_holdings_log
        GROUP BY etf_ticker
        ORDER BY latest_date DESC, etf_ticker
    """)
    
    if recent_result:
        # Group by date
        by_date = {}
        for row in recent_result:
            etf = row['etf_ticker']
            latest = row['latest_date']
            if latest not in by_date:
                by_date[latest] = []
            by_date[latest].append(etf)
        
        for check_date in sorted(by_date.keys(), reverse=True)[:5]:
            etfs = by_date[check_date]
            print(f"  {check_date}: {len(etfs)} ETFs - {', '.join(sorted(etfs))}")
    print()
    
    # 6. The problem: what happens when querying for latest date
    print("6. The Problem:")
    print("-" * 80)
    latest_result = pc.execute_query("""
        SELECT MAX(date) as latest_date
        FROM etf_holdings_log
    """)
    
    if latest_result:
        global_latest = latest_result[0]['latest_date']
        print(f"  Global latest date: {global_latest}")
        print(f"  Query: WHERE date = '{global_latest}'")
        print()
        print(f"  This query will ONLY return ETFs with data on {global_latest}")
        print(f"  ETFs with data on earlier dates will be EXCLUDED")
        print()
        print(f"  Solution: Query should use each ETF's own latest date, not global latest")

if __name__ == "__main__":
    main()
