#!/usr/bin/env python3
"""
Audit Missing Tickers Script
=============================
Finds all tickers in dividend_log, trade_log, and portfolio_positions
that don't exist in the securities table.

This script helps identify data integrity issues before adding foreign keys.
"""

import sys
import logging
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from web_dashboard.supabase_client import SupabaseClient
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Load environment
load_dotenv("web_dashboard/.env")


def audit_missing_tickers() -> Dict[str, List[str]]:
    """Audit all tables for tickers missing from securities table.
    
    Returns:
        Dictionary mapping table names to lists of missing tickers
    """
    print("=" * 80)
    print("Ticker Audit - Finding Missing Tickers in Securities Table")
    print("=" * 80)
    
    client = SupabaseClient(use_service_role=True)
    
    # Get all tickers from securities table
    print("\n[1/4] Fetching all tickers from securities table...")
    try:
        securities_result = client.supabase.table("securities").select("ticker").execute()
        securities_tickers = {row['ticker'].upper() for row in securities_result.data}
        print(f"   Found {len(securities_tickers)} tickers in securities table")
    except Exception as e:
        logger.error(f"Error fetching securities: {e}")
        return {}
    
    missing_tickers = defaultdict(list)
    
    # Check dividend_log
    print("\n[2/4] Checking dividend_log...")
    try:
        dividend_result = client.supabase.table("dividend_log").select("ticker, fund, pay_date").execute()
        dividend_tickers = set()
        dividend_by_ticker = defaultdict(int)
        
        for row in dividend_result.data:
            ticker = row['ticker'].upper()
            dividend_tickers.add(ticker)
            dividend_by_ticker[ticker] += 1
        
        missing_dividend = dividend_tickers - securities_tickers
        if missing_dividend:
            missing_tickers['dividend_log'] = sorted(missing_dividend)
            print(f"   [WARN] Found {len(missing_dividend)} missing tickers in {len(dividend_result.data)} dividend records")
            print(f"   Missing tickers: {', '.join(sorted(missing_dividend)[:10])}{'...' if len(missing_dividend) > 10 else ''}")
            for ticker in sorted(missing_dividend)[:5]:
                print(f"      - {ticker}: {dividend_by_ticker[ticker]} records")
        else:
            print(f"   [OK] All {len(dividend_tickers)} tickers in dividend_log exist in securities")
    except Exception as e:
        logger.error(f"Error checking dividend_log: {e}")
    
    # Check trade_log
    print("\n[3/4] Checking trade_log...")
    try:
        trade_result = client.supabase.table("trade_log").select("ticker, fund, date").execute()
        trade_tickers = set()
        trade_by_ticker = defaultdict(int)
        
        for row in trade_result.data:
            ticker = row['ticker'].upper()
            trade_tickers.add(ticker)
            trade_by_ticker[ticker] += 1
        
        missing_trade = trade_tickers - securities_tickers
        if missing_trade:
            missing_tickers['trade_log'] = sorted(missing_trade)
            print(f"   [WARN] Found {len(missing_trade)} missing tickers in {len(trade_result.data)} trade records")
            print(f"   Missing tickers: {', '.join(sorted(missing_trade)[:10])}{'...' if len(missing_trade) > 10 else ''}")
            for ticker in sorted(missing_trade)[:5]:
                print(f"      - {ticker}: {trade_by_ticker[ticker]} records")
        else:
            print(f"   [OK] All {len(trade_tickers)} tickers in trade_log exist in securities")
    except Exception as e:
        logger.error(f"Error checking trade_log: {e}")
    
    # Check portfolio_positions
    print("\n[4/4] Checking portfolio_positions...")
    try:
        positions_result = client.supabase.table("portfolio_positions").select("ticker, fund").execute()
        positions_tickers = set()
        positions_by_ticker = defaultdict(int)
        
        for row in positions_result.data:
            ticker = row['ticker'].upper()
            positions_tickers.add(ticker)
            positions_by_ticker[ticker] += 1
        
        missing_positions = positions_tickers - securities_tickers
        if missing_positions:
            missing_tickers['portfolio_positions'] = sorted(missing_positions)
            print(f"   [WARN] Found {len(missing_positions)} missing tickers in {len(positions_result.data)} position records")
            print(f"   Missing tickers: {', '.join(sorted(missing_positions)[:10])}{'...' if len(missing_positions) > 10 else ''}")
            for ticker in sorted(missing_positions)[:5]:
                print(f"      - {ticker}: {positions_by_ticker[ticker]} records")
        else:
            print(f"   [OK] All {len(positions_tickers)} tickers in portfolio_positions exist in securities")
    except Exception as e:
        logger.error(f"Error checking portfolio_positions: {e}")
    
    # Summary
    print("\n" + "=" * 80)
    print("Audit Summary")
    print("=" * 80)
    
    all_missing = set()
    for table, tickers in missing_tickers.items():
        all_missing.update(tickers)
        print(f"{table}: {len(tickers)} missing tickers")
    
    if all_missing:
        print(f"\nTotal unique missing tickers: {len(all_missing)}")
        print(f"Missing tickers: {', '.join(sorted(all_missing))}")
    else:
        print("\n[OK] All tickers exist in securities table!")
        print("   Safe to add foreign key constraints.")
    
    print("=" * 80)
    
    return dict(missing_tickers)


if __name__ == "__main__":
    audit_missing_tickers()
