#!/usr/bin/env python3
"""
Create Masked Test Data
Copies real portfolio data from a source fund to a target test fund,
scaling purely by amount to hide actual net worth while preserving
realistic portfolio structure, tickers, and prices.
"""

import os
import sys
import random
from decimal import Decimal
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to path to import utils
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import admin_utils manually or just use supabase-py directly if import fails
try:
    from admin_utils import get_admin_supabase_client
except ImportError:
    # If specific utility is not available, we can rely on manual client creation 
    # but based on previous file reads, admin_utils should exist.
    pass

from supabase import create_client

load_dotenv()

SOURCE_FUND = "RRSP Lance Webull"
TARGET_FUND = "TFSA"
TARGET_PORTFOLIO_VALUE = 100000.0  # Target ~$100k for the test portfolio

def main():
    print("=" * 60)
    print(f"[TEST DATA] Creating Masked Data")
    print(f"Source: {SOURCE_FUND}")
    print(f"Target: {TARGET_FUND}")
    print("=" * 60)

    # 1. Connect to Supabase
    supabase_url = os.getenv("SUPABASE_URL")
    service_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    
    if not supabase_url or not service_key:
        print("[ERROR] SUPABASE_URL and SUPABASE_SECRET_KEY must be set")
        sys.exit(1)

    supabase = create_client(supabase_url, service_key)

    # 2. Calculate Scaling Factor
    print("\n[1/5] Calculating Scaling Factor...")
    
    # Get total value of source fund positions
    try:
        response = supabase.table("portfolio_positions") \
            .select("shares, price, currency") \
            .eq("fund", SOURCE_FUND) \
            .gt("shares", 0) \
            .execute()
    except Exception as e:
        print(f"[ERROR] Failed to fetch source positions: {e}")
        sys.exit(1)
    
    if not response.data:
        print(f"[ERROR] No positions found for source fund: {SOURCE_FUND}")
        sys.exit(1)
        
    source_total_value = 0.0
    for row in response.data:
        # Simple approximation: sum(shares * price). ignoring currency conversion for scaling factor estimation
        # This is rough but sufficient for "masking" purposes to get order of magnitude right
        val = float(row['shares']) * float(row['price'])
        source_total_value += val
    
    if source_total_value == 0:
        print("[ERROR] Source fund has 0 total value")
        sys.exit(1)
        
    scaling_factor = TARGET_PORTFOLIO_VALUE / source_total_value
    
    print(f"   Source Value (approx): ${source_total_value:,.2f}")
    print(f"   Target Value: ${TARGET_PORTFOLIO_VALUE:,.2f}")
    print(f"   Scaling Factor: {scaling_factor:.6f}")

    # 3. Clear Target Fund Data
    print(f"\n[2/5] Clearing Target Fund: {TARGET_FUND}...")
    
    tables_to_clear = [
        "portfolio_positions",
        "trade_log",
        "cash_balances",
        "performance_metrics"
    ]
    
    for table in tables_to_clear:
        try:
            # Check if table exists/errors first? No, just delete
            supabase.table(table).delete().eq("fund", TARGET_FUND).execute()
            print(f"   Cleared {table}")
        except Exception as e:
            print(f"   [WARNING] Failed to clear {table}: {e}")

    # 4. Copy & Scale Portfolio Positions
    print(f"\n[3/5] Copying & Scaling Positions...")
    
    try:
        response = supabase.table("portfolio_positions") \
            .select("*") \
            .eq("fund", SOURCE_FUND) \
            .execute()
            
        positions = response.data
        new_positions = []
        
        for pos in positions:
            # Create new dict to avoid modifying original
            new_pos = pos.copy()
            
            # Remove ID and generated columns
            if 'id' in new_pos: del new_pos['id']
            if 'total_value' in new_pos: del new_pos['total_value']
            if 'avg_price' in new_pos: del new_pos['avg_price']
            
            new_pos['fund'] = TARGET_FUND
            
            # Scale
            new_pos['shares'] = float(new_pos['shares']) * scaling_factor
            new_pos['cost_basis'] = float(new_pos['cost_basis']) * scaling_factor
            if new_pos.get('pnl'):
                new_pos['pnl'] = float(new_pos['pnl']) * scaling_factor
            if new_pos.get('unrealized_pnl'):
                new_pos['unrealized_pnl'] = float(new_pos['unrealized_pnl']) * scaling_factor
            if new_pos.get('stop_loss'):
                 # Stop loss is a price level, DO NOT SCALE price levels
                 pass 
            
            new_positions.append(new_pos)
            
        if new_positions:
            chunk_size = 50
            for i in range(0, len(new_positions), chunk_size):
                chunk = new_positions[i:i + chunk_size]
                supabase.table("portfolio_positions").insert(chunk).execute()
            print(f"   Inserted {len(new_positions)} positions.")
        else:
            print("   No positions to copy.")
            
    except Exception as e:
        print(f"[ERROR] Failed to copy positions: {e}")

    # 5. Copy & Scale Cash Balances
    print(f"\n[4/5] Copying & Scaling Cash...")
    try:
        response = supabase.table("cash_balances") \
            .select("*") \
            .eq("fund", SOURCE_FUND) \
            .execute()
            
        cash = response.data
        new_cash = []
        
        for c in cash:
            new_c = c.copy()
            if 'id' in new_c: del new_c['id']
            new_c['fund'] = TARGET_FUND
            new_c['amount'] = float(new_c['amount']) * scaling_factor
            new_cash.append(new_c)
            
        if new_cash:
            supabase.table("cash_balances").insert(new_cash).execute()
            print(f"   Inserted {len(new_cash)} cash records.")
    except Exception as e:
        print(f"[ERROR] Failed to copy cash: {e}")

    # 6. Copy & Scale Trade Log
    print(f"\n[5/5] Copying & Scaling Trade Log...")
    try:
        response = supabase.table("trade_log") \
            .select("*") \
            .eq("fund", SOURCE_FUND) \
            .order("date", desc=True) \
            .limit(200) \
            .execute() # Only recent trades
            
        trades = response.data
        new_trades = []
        
        for t in trades:
            new_t = t.copy()
            if 'id' in new_t: del new_t['id']
            new_t['fund'] = TARGET_FUND
            new_t['shares'] = float(new_t['shares']) * scaling_factor
            new_t['cost_basis'] = float(new_t['cost_basis']) * scaling_factor
            if new_t.get('pnl'):
                new_t['pnl'] = float(new_t['pnl']) * scaling_factor
            # Price stays same
            new_trades.append(new_t)
            
        if new_trades:
            chunk_size = 50
            for i in range(0, len(new_trades), chunk_size):
                chunk = new_trades[i:i + chunk_size]
                supabase.table("trade_log").insert(chunk).execute()
            print(f"   Inserted {len(new_trades)} trades...")
            
    except Exception as e:
        print(f"[ERROR] Failed to copy trade log: {e}")

    print("\n" + "=" * 60)
    print("[SUCCESS] Data Masking Complete!")
    print(f"Check 'TFSA' fund in the dashboard.")
    print("=" * 60)

if __name__ == "__main__":
    main()
