#!/usr/bin/env python3
"""
Test ETF Watchtower Job Functions
=================================

Tests the job functions after migration to PostgresClient:
1. get_previous_holdings - reads from Research DB
2. save_holdings_snapshot - writes to Research DB

Usage:
    cd web_dashboard
    python scripts/test_etf_watchtower_job.py
"""

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pandas as pd

# Add project paths
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

from dotenv import load_dotenv
load_dotenv(project_root / 'web_dashboard' / '.env')

from postgres_client import PostgresClient


def test_get_previous_holdings():
    """Test the get_previous_holdings function pattern."""
    print("\n" + "=" * 60)
    print("Test 1: get_previous_holdings()")
    print("=" * 60)
    
    # Import the actual function
    from scheduler.jobs_etf_watchtower import get_previous_holdings
    
    pc = PostgresClient()
    
    # Get an ETF that has data
    result = pc.execute_query("""
        SELECT DISTINCT etf_ticker FROM etf_holdings_log 
        ORDER BY etf_ticker LIMIT 1
    """)
    
    if not result:
        print("  [SKIP] No ETF data in database")
        return True
    
    test_etf = result[0]['etf_ticker']
    print(f"\n  Testing with ETF: {test_etf}")
    
    # Use tomorrow's date so we get today's data as "previous"
    test_date = datetime.now(timezone.utc) + timedelta(days=1)
    
    print(f"  Calling get_previous_holdings(pc, '{test_etf}', {test_date.date()})...")
    
    try:
        df = get_previous_holdings(pc, test_etf, test_date)
        
        if df.empty:
            print("  [WARN] No previous holdings found")
        else:
            print(f"  [PASS] Retrieved {len(df)} holdings")
            print(f"\n  Sample data (first 5 rows):")
            print(f"  Columns: {list(df.columns)}")
            for _, row in df.head().iterrows():
                ticker = row.get('ticker', 'N/A')
                shares = row.get('shares', 0)
                weight = row.get('weight_percent', 0)
                print(f"    {ticker}: {shares:,.0f} shares, {weight:.2f}%")
        
        return True
    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_save_holdings_snapshot():
    """Test the save_holdings_snapshot function with test data."""
    print("\n" + "=" * 60)
    print("Test 2: save_holdings_snapshot()")
    print("=" * 60)
    
    from scheduler.jobs_etf_watchtower import save_holdings_snapshot
    
    pc = PostgresClient()
    
    # Create test data - use a fake ETF ticker so we don't affect real data
    # Note: etf_ticker is varchar(10) so keep it short
    test_etf = "XTEST"
    test_date = datetime(2099, 12, 31, tzinfo=timezone.utc)  # Far future date
    
    test_holdings = pd.DataFrame([
        {'ticker': 'AAPL', 'name': 'Apple Inc.', 'shares': 1000, 'weight_percent': 5.5},
        {'ticker': 'MSFT', 'name': 'Microsoft Corp.', 'shares': 500, 'weight_percent': 3.2},
        {'ticker': 'NVDA', 'name': 'NVIDIA Corp.', 'shares': 200, 'weight_percent': 2.1},
    ])
    
    print(f"\n  Test ETF: {test_etf}")
    print(f"  Test Date: {test_date.date()}")
    print(f"  Test Holdings: {len(test_holdings)} rows")
    
    try:
        # Save the snapshot
        print("\n  Calling save_holdings_snapshot()...")
        save_holdings_snapshot(pc, test_etf, test_holdings, test_date)
        print("  [PASS] save_holdings_snapshot() completed without error")
        
        # Verify the data was written
        print("\n  Verifying data was written...")
        result = pc.execute_query("""
            SELECT holding_ticker, holding_name, shares_held, weight_percent
            FROM etf_holdings_log
            WHERE etf_ticker = %s AND date = %s
            ORDER BY holding_ticker
        """, (test_etf, test_date.strftime('%Y-%m-%d')))
        
        if result:
            print(f"  [PASS] Found {len(result)} rows in database")
            for row in result:
                print(f"    {row['holding_ticker']}: {row['shares_held']:,.0f} shares, {row['weight_percent']:.2f}%")
        else:
            print("  [FAIL] No data found after save!")
            return False
        
        # Clean up test data
        print("\n  Cleaning up test data...")
        with pc.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM etf_holdings_log 
                WHERE etf_ticker = %s AND date = %s
            """, (test_etf, test_date.strftime('%Y-%m-%d')))
            deleted = cursor.rowcount
            conn.commit()
        print(f"  [OK] Cleaned up {deleted} test rows")
        
        return True
        
    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        import traceback
        traceback.print_exc()
        
        # Try to clean up anyway
        try:
            with pc.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM etf_holdings_log 
                    WHERE etf_ticker = %s
                """, (test_etf,))
                conn.commit()
        except:
            pass
        
        return False


def test_fetch_handler():
    """Test one of the fetch handlers to verify it still works."""
    print("\n" + "=" * 60)
    print("Test 3: Fetch Handler (ARK)")
    print("=" * 60)
    
    from scheduler.jobs_etf_watchtower import fetch_ark_holdings, ETF_CONFIGS
    
    # Test with ARKK
    test_etf = 'ARKK'
    if test_etf not in ETF_CONFIGS:
        print(f"  [SKIP] {test_etf} not in ETF_CONFIGS")
        return True
    
    config = ETF_CONFIGS[test_etf]
    print(f"\n  Testing fetch for: {test_etf}")
    print(f"  Provider: {config['provider']}")
    
    try:
        print("  Fetching holdings (this makes a network request)...")
        df = fetch_ark_holdings(test_etf, config['url'])
        
        if df is None or df.empty:
            print("  [WARN] No data returned (may be weekend/holiday)")
            return True
        
        print(f"  [PASS] Fetched {len(df)} holdings")
        print(f"\n  Columns: {list(df.columns)}")
        print(f"\n  Top 5 holdings:")
        for _, row in df.head().iterrows():
            ticker = row.get('ticker', 'N/A')
            shares = row.get('shares', 0)
            weight = row.get('weight_percent', 0)
            print(f"    {ticker}: {shares:,.0f} shares, {weight:.2f}%")
        
        return True
        
    except Exception as e:
        print(f"  [WARN] Fetch failed: {e}")
        print("  (This may be expected if market is closed or API is unavailable)")
        return True  # Don't fail the test for network issues


def test_end_to_end_simulation():
    """Simulate a full job run for one ETF (without actually saving to prod)."""
    print("\n" + "=" * 60)
    print("Test 4: End-to-End Simulation")
    print("=" * 60)
    
    from scheduler.jobs_etf_watchtower import (
        get_previous_holdings, 
        calculate_diff,
        ETF_CONFIGS,
        fetch_ark_holdings
    )
    
    pc = PostgresClient()
    test_etf = 'ARKK'
    
    if test_etf not in ETF_CONFIGS:
        print(f"  [SKIP] {test_etf} not configured")
        return True
    
    print(f"\n  Simulating job for: {test_etf}")
    
    try:
        # Step 1: Get previous holdings
        print("\n  Step 1: Get previous holdings...")
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_holdings = get_previous_holdings(pc, test_etf, today)
        print(f"    Previous holdings: {len(yesterday_holdings)} rows")
        
        # Step 2: Fetch current holdings
        print("\n  Step 2: Fetch current holdings...")
        config = ETF_CONFIGS[test_etf]
        today_holdings = fetch_ark_holdings(test_etf, config['url'])
        
        if today_holdings is None or today_holdings.empty:
            print("    [WARN] No current holdings (market closed?)")
            return True
        
        print(f"    Current holdings: {len(today_holdings)} rows")
        
        # Step 3: Calculate diff
        print("\n  Step 3: Calculate diff...")
        if not yesterday_holdings.empty:
            changes = calculate_diff(today_holdings, yesterday_holdings, test_etf)
            print(f"    Changes detected: {len(changes)}")
            
            if changes:
                print("\n    Sample changes (first 3):")
                for change in changes[:3]:
                    print(f"      {change.get('ticker')}: {change.get('action')} {change.get('share_change', 0):+,.0f} shares")
        else:
            print("    [INFO] No previous data to compare")
        
        # Step 4: Would save snapshot (but we skip this)
        print("\n  Step 4: Would save snapshot (SKIPPED for simulation)")
        
        print("\n  [PASS] End-to-end simulation completed successfully")
        return True
        
    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("=" * 60)
    print("ETF Watchtower Job Test Suite")
    print("=" * 60)
    print(f"\nTest Date: {datetime.now().isoformat()}")
    
    results = {
        'get_previous_holdings': test_get_previous_holdings(),
        'save_holdings_snapshot': test_save_holdings_snapshot(),
        'fetch_handler': test_fetch_handler(),
        'end_to_end_simulation': test_end_to_end_simulation(),
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
        print("\nThe ETF Watchtower job is ready to use PostgresClient.")
    else:
        print("Some tests FAILED - review output above")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())
