#!/usr/bin/env python3
"""
Reload Trade Log from CSV Files to Supabase

This script reads all trade log CSV files from the trading_data/funds directory
and inserts them into the Supabase trade_log table.

Prerequisites:
1. Run 004_clean_trade_log_add_fk.sql first to:
   - Create the funds table
   - Add foreign key constraint
   - Clear the trade_log table
2. Ensure all fund names in CSVs match the funds table

Usage:
    python migrations/reload_trade_log.py
"""

import os
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / '.env')

import pandas as pd
from supabase import create_client


def get_fund_directories():
    """Get all fund directories with trade log files."""
    funds_dir = project_root / 'trading_data' / 'funds'
    fund_dirs = []
    
    if funds_dir.exists():
        for fund_dir in funds_dir.iterdir():
            if fund_dir.is_dir():
                trade_log = fund_dir / 'llm_trade_log.csv'
                if trade_log.exists():
                    fund_dirs.append({
                        'name': fund_dir.name,
                        'path': fund_dir,
                        'trade_log': trade_log
                    })
    
    return fund_dirs


def load_and_transform_trades(trade_log_path: Path, fund_name: str) -> list:
    """Load trades from CSV and transform to Supabase format."""
    df = pd.read_csv(trade_log_path)
    
    if df.empty:
        return []
    
    trades = []
    for row in df.to_dict('records'):
        try:
            # Handle NaN/empty/invalid currency values BEFORE building the dict
            raw_currency = row.get('Currency')
            if pd.isna(raw_currency) or raw_currency is None or str(raw_currency).strip().lower() in ('', 'nan', 'none'):
                # Fallback: detect currency from ticker suffix
                ticker = row['Ticker']
                if any(ticker.upper().endswith(suffix) for suffix in ['.TO', '.V', '.CN', '.NE']):
                    currency = 'CAD'
                else:
                    currency = 'USD'
                print(f"  [WARN] Trade {ticker} has missing currency, defaulting to {currency}")
            else:
                currency = str(raw_currency).strip().upper()
            
            trade = {
                'ticker': row['Ticker'],
                'shares': float(row['Shares']),
                'price': float(row['Price']),
                'cost_basis': float(row['Cost Basis']),
                'pnl': float(row.get('PnL', 0)) if pd.notna(row.get('PnL')) else 0,
                'reason': str(row.get('Reason', '')),
                'currency': currency,
                'fund': fund_name,  # Use the proper fund name
                'date': str(row['Date'])
            }
            trades.append(trade)
        except Exception as e:
            print(f"  [!] Error parsing trade: {e}")
            continue
    
    return trades


def main():
    """Reload trade_log table from CSV files."""
    
    # Get Supabase credentials
    supabase_url = os.environ.get('SUPABASE_URL')
    supabase_key = os.environ.get('SUPABASE_PUBLISHABLE_KEY') or os.environ.get('SUPABASE_SERVICE_KEY')
    
    if not supabase_url or not supabase_key:
        print("[ERROR] SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY environment variables required")
        return
    
    # Connect to Supabase
    supabase = create_client(supabase_url, supabase_key)
    print(f"[OK] Connected to Supabase")
    
    # Get valid fund names from the database
    result = supabase.table('funds').select('name').execute()
    valid_funds = {row['name'] for row in result.data}
    print(f"[INFO] Valid funds in database: {valid_funds}")
    
    # Check if trade_log is empty (should be after running the SQL migration)
    result = supabase.table('trade_log').select('id', count='exact').limit(1).execute()
    if result.count and result.count > 0:
        print(f"[WARNING] trade_log table has {result.count} rows - expected 0 after migration")
        confirm = input("Continue anyway? (y/N): ")
        if confirm.lower() != 'y':
            print("Aborted.")
            return
    
    # Get all fund directories
    fund_dirs = get_fund_directories()
    print(f"[INFO] Found {len(fund_dirs)} funds with trade logs")
    
    total_inserted = 0
    total_skipped = 0
    
    for fund_info in fund_dirs:
        fund_name = fund_info['name']
        trade_log_path = fund_info['trade_log']
        
        print(f"\n--- Processing: {fund_name} ---")
        
        # Check if fund exists in database
        if fund_name not in valid_funds:
            print(f"  [!] Fund '{fund_name}' not in database - skipping")
            print(f"      Add it to funds table first: INSERT INTO funds (name) VALUES ('{fund_name}');")
            total_skipped += 1
            continue
        
        # Load and transform trades
        trades = load_and_transform_trades(trade_log_path, fund_name)
        print(f"  [INFO] Loaded {len(trades)} trades from CSV")
        
        if not trades:
            print(f"  [INFO] No trades to insert")
            continue
        
        # Insert trades in batches
        batch_size = 100
        inserted = 0
        
        for i in range(0, len(trades), batch_size):
            batch = trades[i:i + batch_size]
            try:
                supabase.table('trade_log').insert(batch).execute()
                inserted += len(batch)
                print(f"  [+] Inserted batch {i // batch_size + 1} ({len(batch)} trades)")
            except Exception as e:
                print(f"  [!] Error inserting batch: {e}")
                # Try inserting one by one to find the problem
                for trade in batch:
                    try:
                        supabase.table('trade_log').insert(trade).execute()
                        inserted += 1
                    except Exception as e2:
                        print(f"      Failed: {trade['ticker']} on {trade['date']}: {e2}")
        
        print(f"  [OK] Inserted {inserted} trades for {fund_name}")
        total_inserted += inserted
    
    # Final summary
    print(f"\n=== Summary ===")
    print(f"  Total trades inserted: {total_inserted}")
    print(f"  Funds skipped: {total_skipped}")
    
    # Verify final count
    result = supabase.table('trade_log').select('id', count='exact').limit(1).execute()
    print(f"  Trade log now has: {result.count} rows")


if __name__ == '__main__':
    main()
