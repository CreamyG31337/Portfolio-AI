#!/usr/bin/env python3
"""Analyze CTRN and NUE trades to see what positions should exist"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

from supabase_client import SupabaseClient
import pandas as pd
from decimal import Decimal
from collections import defaultdict

client = SupabaseClient(use_service_role=True)

print("="*80)
print("Analyzing CTRN and NUE trades to determine expected positions")
print("="*80)

def analyze_trades_for_ticker(ticker, fund_name):
    """Calculate what positions should exist based on trades"""
    print(f"\n{'='*80}")
    print(f"Analyzing {ticker} in {fund_name}")
    print(f"{'='*80}")
    
    # Get all trades for this ticker in this fund
    trades = client.supabase.table('trade_log')\
        .select('*')\
        .eq('ticker', ticker)\
        .eq('fund', fund_name)\
        .order('date')\
        .execute()
    
    if not trades.data:
        print(f"  No trades found")
        return
    
    df = pd.DataFrame(trades.data)
    print(f"  Found {len(df)} trades")
    
    # Calculate running position
    running_shares = Decimal('0')
    running_cost = Decimal('0')
    currency = 'USD'
    
    for trade in df.to_dict('records'):
        date = trade.get('date', 'UNKNOWN')
        reason = str(trade.get('reason', '')).upper()
        shares = Decimal(str(trade.get('shares', 0)))
        price = Decimal(str(trade.get('price', 0)))
        cost = shares * price
        
        is_sell = 'SELL' in reason
        
        print(f"\n  {date}: {reason}")
        print(f"    Shares: {shares}, Price: ${price:.2f}, Cost: ${cost:.2f}")
        print(f"    Before: Shares={running_shares}, Cost=${running_cost:.2f}")
        
        if is_sell:
            if running_shares > 0:
                cost_per_share = running_cost / running_shares
                running_shares -= shares
                running_cost -= shares * cost_per_share
                if running_shares < 0:
                    running_shares = Decimal('0')
                if running_cost < 0:
                    running_cost = Decimal('0')
            else:
                print(f"    ⚠️  WARNING: Selling {shares} shares but only have {running_shares} shares!")
        else:
            running_shares += shares
            running_cost += cost
            currency = trade.get('currency', 'USD')
        
        print(f"    After: Shares={running_shares}, Cost=${running_cost:.2f}")
    
    print(f"\n  Final Position:")
    print(f"    Shares: {running_shares}")
    print(f"    Cost Basis: ${running_cost:.2f}")
    print(f"    Currency: {currency}")
    
    if running_shares > 0:
        avg_price = running_cost / running_shares
        print(f"    Average Price: ${avg_price:.2f}")
        print(f"    [OK] Should appear in latest_positions")
    else:
        print(f"    [CLOSED] Position closed - should NOT appear in latest_positions")

# Analyze CTRN for each fund
for fund in ['TEST', 'Project Chimera', 'TFSA']:
    analyze_trades_for_ticker('CTRN', fund)

# Analyze NUE
analyze_trades_for_ticker('NUE', 'RRSP Lance Webull')

