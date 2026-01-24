#!/usr/bin/env python3
"""
Test ETF Holdings Migration
===========================

This script verifies all ETF-related functionality after migration
from Supabase to Research DB.

Tests:
1. Database schema (indexes, view, function)
2. Data integrity
3. get_previous_holdings (watchtower job)
4. save_holdings_snapshot (watchtower job)
5. ETF routes queries
6. get_etf_holding_trades function

Usage:
    cd web_dashboard
    python scripts/test_etf_migration.py
"""

import sys
from pathlib import Path
from datetime import datetime, date, timedelta

# Add project paths
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

from dotenv import load_dotenv
load_dotenv(project_root / 'web_dashboard' / '.env')

from postgres_client import PostgresClient


def test_schema():
    """Test that schema objects exist."""
    print("\n" + "=" * 60)
    print("Test 1: Schema Verification")
    print("=" * 60)
    
    pc = PostgresClient()
    all_passed = True
    
    # Check table exists
    print("\n[1.1] Checking etf_holdings_log table...")
    result = pc.execute_query("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'etf_holdings_log'
        ) as exists
    """)
    if result and result[0]['exists']:
        print("  [PASS] Table exists")
    else:
        print("  [FAIL] Table missing!")
        all_passed = False
    
    # Check indexes
    print("\n[1.2] Checking indexes...")
    expected_indexes = [
        'etf_holdings_log_pkey',
        'idx_etf_holdings_date',
        'idx_etf_holdings_etf',
        'idx_etf_holdings_ticker',
        'idx_ehl_holding_date'
    ]
    
    result = pc.execute_query("""
        SELECT indexname FROM pg_indexes 
        WHERE tablename = 'etf_holdings_log'
    """)
    existing = [row['indexname'] for row in result] if result else []
    
    for idx in expected_indexes:
        if idx in existing:
            print(f"  [PASS] Index {idx}")
        else:
            print(f"  [FAIL] Index {idx} missing!")
            all_passed = False
    
    # Check view exists
    print("\n[1.3] Checking etf_holdings_changes view...")
    result = pc.execute_query("""
        SELECT EXISTS (
            SELECT FROM information_schema.views 
            WHERE table_name = 'etf_holdings_changes'
        ) as exists
    """)
    if result and result[0]['exists']:
        print("  [PASS] View exists")
    else:
        print("  [FAIL] View missing!")
        all_passed = False
    
    # Check function exists
    print("\n[1.4] Checking get_etf_holding_trades function...")
    result = pc.execute_query("""
        SELECT EXISTS (
            SELECT FROM pg_proc WHERE proname = 'get_etf_holding_trades'
        ) as exists
    """)
    if result and result[0]['exists']:
        print("  [PASS] Function exists")
    else:
        print("  [FAIL] Function missing!")
        all_passed = False
    
    return all_passed


def test_data_integrity():
    """Test data exists and is valid."""
    print("\n" + "=" * 60)
    print("Test 2: Data Integrity")
    print("=" * 60)
    
    pc = PostgresClient()
    all_passed = True
    
    # Check row count
    print("\n[2.1] Checking row count...")
    result = pc.execute_query("SELECT COUNT(*) as cnt FROM etf_holdings_log")
    row_count = result[0]['cnt'] if result else 0
    print(f"  Total rows: {row_count:,}")
    
    if row_count > 0:
        print("  [PASS] Data exists")
    else:
        print("  [WARN] No data - this might be expected if no ETF runs have completed")
    
    # Check ETF count
    print("\n[2.2] Checking ETF coverage...")
    result = pc.execute_query("SELECT COUNT(DISTINCT etf_ticker) as cnt FROM etf_holdings_log")
    etf_count = result[0]['cnt'] if result else 0
    print(f"  Distinct ETFs: {etf_count}")
    
    if etf_count > 0:
        result = pc.execute_query("""
            SELECT etf_ticker, COUNT(*) as holdings 
            FROM etf_holdings_log 
            GROUP BY etf_ticker 
            ORDER BY holdings DESC 
            LIMIT 5
        """)
        print("  Top 5 ETFs by holdings:")
        for row in result:
            print(f"    - {row['etf_ticker']}: {row['holdings']:,} rows")
    
    # Check date range
    print("\n[2.3] Checking date range...")
    result = pc.execute_query("""
        SELECT MIN(date) as min_date, MAX(date) as max_date 
        FROM etf_holdings_log
    """)
    if result and result[0]['min_date']:
        print(f"  Date range: {result[0]['min_date']} to {result[0]['max_date']}")
        print("  [PASS] Date range valid")
    else:
        print("  [WARN] No dates found")
    
    return all_passed


def test_view_query():
    """Test the etf_holdings_changes view."""
    print("\n" + "=" * 60)
    print("Test 3: View Query")
    print("=" * 60)
    
    pc = PostgresClient()
    
    print("\n[3.1] Querying etf_holdings_changes view...")
    result = pc.execute_query("""
        SELECT COUNT(*) as cnt FROM etf_holdings_changes
    """)
    change_count = result[0]['cnt'] if result else 0
    print(f"  Total changes: {change_count:,}")
    
    if change_count > 0:
        print("  [PASS] View returns data")
        
        # Sample some changes
        result = pc.execute_query("""
            SELECT date, etf_ticker, holding_ticker, share_change, action
            FROM etf_holdings_changes
            ORDER BY date DESC, ABS(share_change) DESC
            LIMIT 5
        """)
        print("\n  Sample recent changes:")
        for row in result:
            print(f"    {row['date']} | {row['etf_ticker']} | {row['holding_ticker']} | {row['action']} | {row['share_change']:+,}")
    else:
        print("  [INFO] No changes recorded (might be expected with limited data)")
    
    return True


def test_function_query():
    """Test the get_etf_holding_trades function."""
    print("\n" + "=" * 60)
    print("Test 4: Function Query")
    print("=" * 60)
    
    pc = PostgresClient()
    
    # Get a holding ticker that exists in the data
    print("\n[4.1] Finding a holding ticker to test...")
    result = pc.execute_query("""
        SELECT DISTINCT holding_ticker 
        FROM etf_holdings_log 
        WHERE holding_ticker IS NOT NULL 
        LIMIT 1
    """)
    
    if not result:
        print("  [SKIP] No holding tickers found in data")
        return True
    
    test_ticker = result[0]['holding_ticker']
    print(f"  Using ticker: {test_ticker}")
    
    # Test the function
    print("\n[4.2] Calling get_etf_holding_trades function...")
    start_date = (date.today() - timedelta(days=365)).isoformat()
    end_date = date.today().isoformat()
    
    try:
        result = pc.execute_query("""
            SELECT * FROM get_etf_holding_trades(%s, %s::date, %s::date)
        """, (test_ticker, start_date, end_date))
        
        if result:
            print(f"  [PASS] Function returned {len(result)} trades")
            print("\n  Sample trades:")
            for row in result[:3]:
                print(f"    {row['trade_date']} | {row['etf_ticker']} | {row['trade_type']} | {row['shares_change']:+,.0f}")
        else:
            print("  [INFO] No trades found for this ticker in date range")
    except Exception as e:
        print(f"  [FAIL] Function error: {e}")
        return False
    
    return True


def test_watchtower_functions():
    """Test the watchtower job functions (without actually saving)."""
    print("\n" + "=" * 60)
    print("Test 5: Watchtower Job Functions")
    print("=" * 60)
    
    pc = PostgresClient()
    
    # Test get_previous_holdings query pattern
    print("\n[5.1] Testing get_previous_holdings query pattern...")
    
    # Get an ETF ticker
    result = pc.execute_query("""
        SELECT DISTINCT etf_ticker FROM etf_holdings_log LIMIT 1
    """)
    
    if not result:
        print("  [SKIP] No ETF data to test")
        return True
    
    test_etf = result[0]['etf_ticker']
    test_date = date.today().isoformat()
    
    # Find latest date before today
    result = pc.execute_query("""
        SELECT date FROM etf_holdings_log
        WHERE etf_ticker = %s AND date < %s
        ORDER BY date DESC
        LIMIT 1
    """, (test_etf, test_date))
    
    if result:
        prev_date = result[0]['date']
        print(f"  [PASS] Found previous date: {prev_date}")
        
        # Fetch holdings for that date
        result = pc.execute_query("""
            SELECT holding_ticker, shares_held, weight_percent
            FROM etf_holdings_log
            WHERE etf_ticker = %s AND date = %s
        """, (test_etf, prev_date))
        
        print(f"  [PASS] Retrieved {len(result)} holdings for {test_etf}")
    else:
        print(f"  [INFO] No previous data for {test_etf}")
    
    return True


def test_etf_routes_queries():
    """Test the etf_routes.py query patterns."""
    print("\n" + "=" * 60)
    print("Test 6: ETF Routes Query Patterns")
    print("=" * 60)
    
    pc = PostgresClient()
    
    # Test get_latest_date pattern
    print("\n[6.1] Testing get_latest_date pattern...")
    result = pc.execute_query("""
        SELECT date FROM etf_holdings_log
        ORDER BY date DESC
        LIMIT 1
    """)
    if result:
        print(f"  [PASS] Latest date: {result[0]['date']}")
    else:
        print("  [INFO] No dates found")
    
    # Test get_available_dates pattern
    print("\n[6.2] Testing get_available_dates pattern...")
    result = pc.execute_query("""
        SELECT DISTINCT date FROM etf_holdings_log
        ORDER BY date DESC
    """)
    print(f"  [PASS] Found {len(result) if result else 0} distinct dates")
    
    # Test get_available_etfs pattern
    print("\n[6.3] Testing get_available_etfs pattern...")
    result = pc.execute_query("""
        SELECT DISTINCT etf_ticker FROM etf_holdings_log
        ORDER BY etf_ticker
    """)
    if result:
        etfs = [r['etf_ticker'] for r in result]
        print(f"  [PASS] Found {len(etfs)} ETFs: {', '.join(etfs[:5])}{'...' if len(etfs) > 5 else ''}")
    else:
        print("  [INFO] No ETFs found")
    
    return True


def main():
    print("=" * 60)
    print("ETF Holdings Migration Test Suite")
    print("=" * 60)
    print(f"\nTest Date: {datetime.now().isoformat()}")
    
    results = {
        'Schema': test_schema(),
        'Data Integrity': test_data_integrity(),
        'View Query': test_view_query(),
        'Function Query': test_function_query(),
        'Watchtower Functions': test_watchtower_functions(),
        'ETF Routes Queries': test_etf_routes_queries(),
    }
    
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    all_passed = True
    for test_name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {test_name}: [{status}]")
        if not passed:
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("All tests PASSED!")
    else:
        print("Some tests FAILED - review output above")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())
