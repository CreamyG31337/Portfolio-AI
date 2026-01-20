#!/usr/bin/env python3
"""
Find dates with suspiciously low prices for US tickers (likely from Canadian fallback bug).

This script identifies dates where US tickers have prices that are suspiciously low,
which likely indicates the Canadian fallback bug occurred on a market holiday.
"""

import sys
from pathlib import Path
from datetime import datetime, date, timedelta
from decimal import Decimal
from collections import defaultdict

# Setup sys.path
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

from web_dashboard.supabase_client import SupabaseClient

# Import MarketHolidays using importlib to avoid path issues
import importlib.util
market_holidays_path = project_root / 'utils' / 'market_holidays.py'
spec = importlib.util.spec_from_file_location("market_holidays", market_holidays_path)
market_holidays_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(market_holidays_module)
MarketHolidays = market_holidays_module.MarketHolidays

def find_suspicious_dates(fund_name: str = "Project Chimera", days_back: int = 180):
    """Find dates with suspiciously low prices for US tickers."""
    
    client = SupabaseClient(use_service_role=True)
    market_holidays = MarketHolidays()
    
    # Get date range
    end_date = date.today()
    start_date = end_date - timedelta(days=days_back)
    
    print("=" * 70)
    print("Finding Suspicious Holiday Prices (Canadian Fallback Bug)")
    print("=" * 70)
    print(f"Fund: {fund_name}")
    print(f"Date range: {start_date} to {end_date}")
    print()
    
    # Query all positions in date range
    start_time = f"{start_date}T00:00:00"
    end_time = f"{end_date}T23:59:59"
    
    try:
        response = client.supabase.table("portfolio_positions")\
            .select("ticker, price, currency, date, fund")\
            .eq("fund", fund_name)\
            .gte("date", start_time)\
            .lte("date", end_time)\
            .order("date", desc=False)\
            .execute()
        
        positions = response.data
        print(f"Found {len(positions)} total positions")
        
        if not positions:
            print("   ERROR: NO DATA FOUND!")
            return
        
        # Group by date and ticker
        date_ticker_prices = defaultdict(dict)  # {date: {ticker: price}}
        ticker_info = {}  # {ticker: {currency, is_us}}
        
        for p in positions:
            ticker = p.get('ticker', '').upper()
            price = p.get('price')
            currency = p.get('currency', 'USD')
            pos_date_str = p.get('date', '')
            
            # Parse date
            try:
                if 'T' in pos_date_str:
                    pos_date = datetime.fromisoformat(pos_date_str.replace('Z', '+00:00')).date()
                else:
                    pos_date = datetime.fromisoformat(pos_date_str).date()
            except:
                continue
            
            # Store ticker info
            if ticker not in ticker_info:
                is_us = not ticker.endswith(('.TO', '.V', '.CN'))
                ticker_info[ticker] = {
                    'currency': currency,
                    'is_us': is_us
                }
            
            # Convert price to Decimal
            try:
                price_decimal = Decimal(str(price)) if price is not None else Decimal('0')
            except:
                price_decimal = Decimal('0')
            
            # Store price for this date/ticker
            if ticker not in date_ticker_prices[pos_date]:
                date_ticker_prices[pos_date][ticker] = price_decimal
            else:
                # Keep the higher price if multiple entries (likely the correct one)
                if price_decimal > date_ticker_prices[pos_date][ticker]:
                    date_ticker_prices[pos_date][ticker] = price_decimal
        
        # Find suspicious dates
        # Bug only occurs when: US market closed + Canadian market OPEN + US ticker fetch fails
        suspicious_dates = []
        threshold = Decimal('0.10')  # Prices below $0.10 are suspicious for US stocks
        
        for check_date in sorted(date_ticker_prices.keys()):
            is_us_holiday = market_holidays.is_us_market_closed(check_date)
            is_canadian_holiday = market_holidays.is_canadian_market_closed(check_date)
            
            # CRITICAL: Bug only happens when US is closed BUT Canada is OPEN
            # This allows the code to successfully fetch Canadian variants (wrong stocks)
            if not (is_us_holiday and not is_canadian_holiday):
                continue  # Skip if not the right conditions for the bug
            
            suspicious_tickers = []
            for ticker, price in date_ticker_prices[check_date].items():
                ticker_data = ticker_info.get(ticker, {})
                is_us = ticker_data.get('is_us', False)
                
                # Check if US ticker has suspiciously low price
                if is_us and price < threshold and price > Decimal('0'):
                    suspicious_tickers.append({
                        'ticker': ticker,
                        'price': price,
                        'currency': ticker_data.get('currency', 'USD')
                    })
            
            if suspicious_tickers:
                suspicious_dates.append({
                    'date': check_date,
                    'is_us_holiday': is_us_holiday,
                    'is_canadian_holiday': is_canadian_holiday,
                    'suspicious_tickers': suspicious_tickers
                })
        
        # Report findings
        print()
        print("=" * 70)
        print("SUSPICIOUS DATES FOUND (US Closed + Canada Open + Low US Prices)")
        print("=" * 70)
        
        if not suspicious_dates:
            print("No suspicious dates found!")
            print("   All US ticker prices look normal.")
        else:
            print(f"[WARNING] Found {len(suspicious_dates)} suspicious dates:")
            print()
            
            for item in suspicious_dates:
                check_date = item['date']
                holiday_type = []
                if item['is_us_holiday']:
                    holiday_type.append("US Holiday")
                if item['is_canadian_holiday']:
                    holiday_type.append("Canadian Holiday")
                
                # Show market status
                market_status = []
                if item['is_us_holiday']:
                    market_status.append("US: CLOSED")
                else:
                    market_status.append("US: OPEN")
                if item['is_canadian_holiday']:
                    market_status.append("Canada: CLOSED")
                else:
                    market_status.append("Canada: OPEN")
                
                print(f"[DATE] {check_date} ({', '.join(market_status)})")
                for ticker_info in item['suspicious_tickers']:
                    print(f"   [WARNING] {ticker_info['ticker']}: ${ticker_info['price']:.4f} ({ticker_info['currency']})")
                print()
        
        # Summary
        print("=" * 70)
        print("RECOMMENDATION")
        print("=" * 70)
        if suspicious_dates:
            dates_to_fix = [item['date'].isoformat() for item in suspicious_dates]
            print(f"Re-run rebuild_portfolio_complete.py for these dates:")
            print(f"  Dates: {', '.join(dates_to_fix)}")
            print()
            print("Or re-run for all dates since late August to be safe:")
            print(f"  Date range: {start_date} to {end_date}")
        else:
            print("No action needed - no suspicious dates found!")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Find suspicious holiday prices")
    parser.add_argument("--fund", default="Project Chimera", help="Fund name")
    parser.add_argument("--days", type=int, default=180, help="Days to look back")
    args = parser.parse_args()
    
    find_suspicious_dates(args.fund, args.days)
