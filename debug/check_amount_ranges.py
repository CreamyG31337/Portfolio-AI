#!/usr/bin/env python3
"""
Check Amount Ranges
===================
Checks the actual amount ranges in congress trades data to determine correct emoji thresholds
"""

import sys
import io
from pathlib import Path
from collections import Counter

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

from supabase_client import SupabaseClient

def check_amount_ranges():
    """Check actual amount ranges in the data."""
    supabase = SupabaseClient(use_service_role=True)
    
    print("\n" + "=" * 80)
    print("CHECKING CONGRESS TRADES AMOUNT RANGES")
    print("=" * 80)
    print()
    
    # Get all trades with amounts
    print("1. Fetching trades with amount data...")
    all_trades = []
    batch_size = 1000
    offset = 0
    
    while True:
        result = supabase.supabase.table('congress_trades')\
            .select('id, amount')\
            .not_.is_('amount', 'null')\
            .range(offset, offset + batch_size - 1)\
            .execute()
        
        if not result.data:
            break
        
        all_trades.extend(result.data)
        
        if len(result.data) < batch_size:
            break
        
        offset += batch_size
    
    print(f"   Found {len(all_trades)} trades with amount data")
    
    if not all_trades:
        print("   ⚠️  No trades found with amount data")
        return
    
    # Parse amounts and categorize
    print("\n2. Analyzing amount ranges...")
    
    amount_counter = Counter()
    max_values = []
    
    for trade in all_trades:
        amount = trade.get('amount', '')
        if not amount or amount == 'N/A':
            continue
        
        # Extract numeric values from amount string
        # Format is usually "$1,001 - $15,000" or "$15,001 - $50,000" etc.
        import re
        matches = re.findall(r'\$?([\d,]+)', amount)
        if matches:
            # Get the last (highest) number
            max_value_str = matches[-1].replace(',', '')
            try:
                max_value = int(max_value_str)
                max_values.append(max_value)
                
                # Categorize
                if max_value <= 15000:
                    amount_counter['$1k-$15k'] += 1
                elif max_value <= 50000:
                    amount_counter['$15k-$50k'] += 1
                elif max_value <= 100000:
                    amount_counter['$50k-$100k'] += 1
                elif max_value <= 250000:
                    amount_counter['$100k-$250k'] += 1
                elif max_value <= 500000:
                    amount_counter['$250k-$500k'] += 1
                elif max_value <= 1000000:
                    amount_counter['$500k-$1M'] += 1
                else:
                    amount_counter['$1M+'] += 1
            except ValueError:
                pass
    
    print(f"\n   Total valid amounts parsed: {len(max_values)}")
    
    if max_values:
        print(f"   Min value: ${min(max_values):,}")
        print(f"   Max value: ${max(max_values):,}")
        print(f"   Average: ${sum(max_values) / len(max_values):,.0f}")
    
    print("\n3. Amount Range Distribution:")
    print("-" * 80)
    for range_name, count in sorted(amount_counter.items(), key=lambda x: x[1], reverse=True):
        percentage = (count / len(max_values) * 100) if max_values else 0
        print(f"   {range_name:15} : {count:5} trades ({percentage:5.1f}%)")
    
    print("\n4. Sample amounts by range:")
    print("-" * 80)
    
    # Show samples
    samples_by_range = {
        '$1k-$15k': [],
        '$15k-$50k': [],
        '$50k-$100k': [],
        '$100k-$250k': [],
        '$250k-$500k': [],
        '$500k-$1M': [],
        '$1M+': []
    }
    
    for trade in all_trades[:500]:  # Check first 500 for samples
        amount = trade.get('amount', '')
        if not amount or amount == 'N/A':
            continue
        
        import re
        matches = re.findall(r'\$?([\d,]+)', amount)
        if matches:
            max_value_str = matches[-1].replace(',', '')
            try:
                max_value = int(max_value_str)
                
                if max_value <= 15000 and len(samples_by_range['$1k-$15k']) < 3:
                    samples_by_range['$1k-$15k'].append(amount)
                elif max_value <= 50000 and len(samples_by_range['$15k-$50k']) < 3:
                    samples_by_range['$15k-$50k'].append(amount)
                elif max_value <= 100000 and len(samples_by_range['$50k-$100k']) < 3:
                    samples_by_range['$50k-$100k'].append(amount)
                elif max_value <= 250000 and len(samples_by_range['$100k-$250k']) < 3:
                    samples_by_range['$100k-$250k'].append(amount)
                elif max_value <= 500000 and len(samples_by_range['$250k-$500k']) < 3:
                    samples_by_range['$250k-$500k'].append(amount)
                elif max_value <= 1000000 and len(samples_by_range['$500k-$1M']) < 3:
                    samples_by_range['$500k-$1M'].append(amount)
                elif len(samples_by_range['$1M+']) < 3:
                    samples_by_range['$1M+'].append(amount)
            except ValueError:
                pass
    
    for range_name, samples in samples_by_range.items():
        if samples:
            print(f"\n   {range_name}:")
            for sample in samples:
                print(f"      - {sample}")
    
    print("\n" + "=" * 80)
    print("RECOMMENDED EMOJI MAPPING")
    print("=" * 80)
    print()
    print("Based on the data, here's a suggested emoji mapping:")
    print()
    print("   💰      = $1k - $15k (1 moneybag)")
    print("   💰💰    = $15k - $50k (2 moneybags)")
    print("   💰💰💰  = $50k - $100k (3 moneybags)")
    print("   💎      = $100k - $250k (1 diamond)")
    print("   💎💎    = $250k - $500k (2 diamonds)")
    print("   💎💎💎  = $500k - $1M (3 diamonds)")
    print("   💎💎💎💎 = $1M+ (4 diamonds)")
    print()
    print("Or alternative:")
    print("   💰      = $1k - $15k")
    print("   💰💰    = $15k - $50k")
    print("   💰💰💰  = $50k - $100k")
    print("   💎      = $100k - $250k")
    print("   💎💎    = $250k - $500k")
    print("   💎💎💎  = $500k - $1M")
    print("   💎💎💎💎 = $1M - $5M")
    print("   💎💎💎💎💎 = $5M+")

if __name__ == "__main__":
    check_amount_ranges()
