import sys
import os
from pathlib import Path
from datetime import datetime
import json

# Setup sys.path
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

from web_dashboard.supabase_client import SupabaseClient

def verify_holiday_data():
    print("🔍 Verifying Database Data for Market Holidays...")
    
    client = SupabaseClient(use_service_role=True)
    fund_name = "Project Chimera"
    
    # Dates to check
    # 1. Nov 27, 2025 - US Thanksgiving (US Closed, Canada Open)
    #    Expect: US stocks to have prices (forward-filled), Canadian stocks to have fresh prices
    check_dates = [
        ('2025-11-27', 'US Thanksgiving (US Closed)'),
        ('2025-12-25', 'Christmas (Both Closed)'), 
        ('2025-12-26', 'Boxing Day (Canada Closed, US Open?)') # Check status
    ]
    
    for date_str, desc in check_dates:
        print(f"\n📅 Checking {date_str} ({desc})...")
        
        # Query positions for this date (full day range)
        start_time = f"{date_str}T00:00:00"
        end_time = f"{date_str}T23:59:59"
        
        try:
            response = client.supabase.table("portfolio_positions")\
                .select("*")\
                .eq("fund", fund_name)\
                .gte("date", start_time)\
                .lte("date", end_time)\
                .execute()
            
            positions = response.data
            print(f"   Found {len(positions)} positions")
            
            if not positions:
                print("   ❌ NO DATA FOUND!")
                continue
                
            # Inspect US vs Canadian tickers
            us_tickers = []
            ca_tickers = []
            
            for p in positions:
                price = p.get('price')
                ticker = p.get('ticker')
                currency = p.get('currency')
                market_val = p.get('market_value')
                
                info = f"{ticker} ({currency}): Price=${price}, Val=${market_val}"
                
                if ticker.endswith(('.TO', '.V', '.CN')) or currency == 'CAD':
                    ca_tickers.append(info)
                else:
                    us_tickers.append(info)
            
            print("   🇺🇸 US Stocks (Should be preserved/forward-filled):")
            for info in us_tickers[:5]:
                print(f"      - {info}")
            if len(us_tickers) > 5: print(f"      ... {len(us_tickers)-5} more")
            
            print("   🇨🇦 Canadian Stocks:")
            for info in ca_tickers[:5]:
                print(f"      - {info}")
            if len(ca_tickers) > 5: print(f"      ... {len(ca_tickers)-5} more")
            
            # Validation Logic
            zero_price_us = [p for p in positions if p.get('currency') == 'USD' and (p.get('price') == 0 or p.get('price') is None)]
            if zero_price_us:
                 print(f"   ❌ WARNING: {len(zero_price_us)} US stocks have ZERO/NULL price!")
                 for p in zero_price_us:
                     print(f"      !! {p.get('ticker')}")
            else:
                 print("   ✅ All US stocks have valid prices (Success!)")

        except Exception as e:
            print(f"   ❌ Error querying database: {e}")

if __name__ == "__main__":
    verify_holiday_data()
