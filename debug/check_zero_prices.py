#!/usr/bin/env python3
"""
Check for zero or near-zero prices in portfolio_positions
"""

import sys
from pathlib import Path
from datetime import datetime, date
from decimal import Decimal

# Setup sys.path
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

from web_dashboard.supabase_client import SupabaseClient

def check_zero_prices(fund_name: str = "Project Chimera", days_back: int = 30):
    """Check for positions with zero or near-zero prices"""
    
    client = SupabaseClient(use_service_role=True)
    
    # Get recent dates
    from datetime import timedelta
    end_date = date.today()
    start_date = end_date - timedelta(days=days_back)
    
    print("Checking portfolio_positions for zero/near-zero prices")
    print(f"   Fund: {fund_name}")
    print(f"   Date range: {start_date} to {end_date}")
    print()
    
    # Query recent positions
    start_time = f"{start_date}T00:00:00"
    end_time = f"{end_date}T23:59:59"
    
    try:
        response = client.supabase.table("portfolio_positions")\
            .select("*")\
            .eq("fund", fund_name)\
            .gte("date", start_time)\
            .lte("date", end_time)\
            .order("date", desc=True)\
            .execute()
        
        positions = response.data
        print(f"Found {len(positions)} total positions")
        
        if not positions:
            print("   ERROR: NO DATA FOUND!")
            return
        
        # Group by ticker to see patterns
        ticker_stats = {}
        zero_price_positions = []
        near_zero_positions = []
        
        for p in positions:
            ticker = p.get('ticker')
            price = p.get('price')
            market_val = p.get('market_value')
            shares = p.get('shares')
            pos_date = p.get('date')
            currency = p.get('currency')
            
            # Convert price to Decimal for comparison
            try:
                price_decimal = Decimal(str(price)) if price is not None else Decimal('0')
            except:
                price_decimal = Decimal('0')
            
            # Track ticker stats
            if ticker not in ticker_stats:
                ticker_stats[ticker] = {
                    'count': 0,
                    'zero_count': 0,
                    'near_zero_count': 0,
                    'min_price': price_decimal,
                    'max_price': price_decimal,
                    'latest_date': pos_date,
                    'latest_price': price_decimal,
                    'currency': currency
                }
            
            ticker_stats[ticker]['count'] += 1
            if price_decimal > ticker_stats[ticker]['max_price']:
                ticker_stats[ticker]['max_price'] = price_decimal
                ticker_stats[ticker]['latest_date'] = pos_date
                ticker_stats[ticker]['latest_price'] = price_decimal
            if price_decimal < ticker_stats[ticker]['min_price']:
                ticker_stats[ticker]['min_price'] = price_decimal
            
            # Check for zero or near-zero
            if price is None or price_decimal == 0:
                zero_price_positions.append({
                    'ticker': ticker,
                    'date': pos_date,
                    'price': price,
                    'market_value': market_val,
                    'shares': shares,
                    'currency': currency
                })
                ticker_stats[ticker]['zero_count'] += 1
            elif price_decimal < Decimal('0.01'):  # Less than 1 cent
                near_zero_positions.append({
                    'ticker': ticker,
                    'date': pos_date,
                    'price': price_decimal,
                    'market_value': market_val,
                    'shares': shares,
                    'currency': currency
                })
                ticker_stats[ticker]['near_zero_count'] += 1
        
        # Report zero prices
        if zero_price_positions:
            print(f"\n*** FOUND {len(zero_price_positions)} positions with ZERO/NULL prices:")
            print()
            
            # Group by ticker
            zero_by_ticker = {}
            for pos in zero_price_positions:
                ticker = pos['ticker']
                if ticker not in zero_by_ticker:
                    zero_by_ticker[ticker] = []
                zero_by_ticker[ticker].append(pos)
            
            for ticker, positions_list in sorted(zero_by_ticker.items()):
                print(f"   {ticker} ({ticker_stats[ticker]['currency']}):")
                print(f"      Total positions: {ticker_stats[ticker]['count']}")
                print(f"      Zero prices: {ticker_stats[ticker]['zero_count']}")
                print(f"      Latest price: ${ticker_stats[ticker]['latest_price']} (on {ticker_stats[ticker]['latest_date']})")
                print(f"      Price range: ${ticker_stats[ticker]['min_price']} - ${ticker_stats[ticker]['max_price']}")
                
                # Show recent zero-price dates
                recent_zeros = sorted(positions_list, key=lambda x: x['date'], reverse=True)[:5]
                print(f"      Recent zero-price dates:")
                for pos in recent_zeros:
                    print(f"         {pos['date']}: price={pos['price']}, shares={pos['shares']}, market_val={pos['market_value']}")
                print()
        else:
            print("OK: No zero prices found")
        
        # Report near-zero prices
        if near_zero_positions:
            print(f"\nWARNING: FOUND {len(near_zero_positions)} positions with near-zero prices (< $0.01):")
            print()
            
            # Group by ticker
            near_zero_by_ticker = {}
            for pos in near_zero_positions:
                ticker = pos['ticker']
                if ticker not in near_zero_by_ticker:
                    near_zero_by_ticker[ticker] = []
                near_zero_by_ticker[ticker].append(pos)
            
            for ticker, positions_list in sorted(near_zero_by_ticker.items())[:10]:  # Show top 10
                print(f"   {ticker}: {len(positions_list)} positions with price < $0.01")
                latest = sorted(positions_list, key=lambda x: x['date'], reverse=True)[0]
                print(f"      Latest: {latest['date']} - price=${latest['price']}, shares={latest['shares']}")
        
        # Summary by ticker - show ALL tickers with their latest prices
        print(f"\nTicker Summary (all tickers with latest prices):")
        print()
        for ticker, stats in sorted(ticker_stats.items()):
            print(f"   {ticker} ({stats['currency']}):")
            print(f"      Latest price: ${stats['latest_price']} on {stats['latest_date']}")
            print(f"      Price range: ${stats['min_price']} - ${stats['max_price']}")
            print(f"      Total positions: {stats['count']}")
            if stats['zero_count'] > 0:
                print(f"      WARNING: {stats['zero_count']} positions with zero price")
            if stats['near_zero_count'] > 0:
                print(f"      WARNING: {stats['near_zero_count']} positions with near-zero price")
            print()
        
        # Also check for suspiciously low prices (not zero, but very low)
        print(f"\nChecking for suspiciously low prices (< $1.00):")
        print()
        low_price_positions = []
        for p in positions:
            price = p.get('price')
            try:
                price_decimal = Decimal(str(price)) if price is not None else Decimal('0')
                if price_decimal > 0 and price_decimal < Decimal('1.00'):
                    low_price_positions.append({
                        'ticker': p.get('ticker'),
                        'date': p.get('date'),
                        'price': price_decimal,
                        'market_value': p.get('market_value'),
                        'shares': p.get('shares'),
                        'currency': p.get('currency')
                    })
            except:
                pass
        
        if low_price_positions:
            print(f"   Found {len(low_price_positions)} positions with price < $1.00:")
            # Group by ticker
            low_by_ticker = {}
            for pos in low_price_positions:
                ticker = pos['ticker']
                if ticker not in low_by_ticker:
                    low_by_ticker[ticker] = []
                low_by_ticker[ticker].append(pos)
            
            for ticker, positions_list in sorted(low_by_ticker.items()):
                latest = sorted(positions_list, key=lambda x: x['date'], reverse=True)[0]
                print(f"      {ticker}: Latest price ${latest['price']} on {latest['date']} ({len(positions_list)} total)")
        else:
            print("   OK: No suspiciously low prices found")
        
        # Check for specific dates that might have issues
        print(f"\nChecking recent dates for patterns:")
        print()
        date_counts = {}
        for pos in positions:
            pos_date = pos.get('date', '')[:10]  # Just the date part
            if pos_date not in date_counts:
                date_counts[pos_date] = {'total': 0, 'zero': 0}
            date_counts[pos_date]['total'] += 1
            price = pos.get('price')
            if price is None or Decimal(str(price)) == 0:
                date_counts[pos_date]['zero'] += 1
        
        # Show last 10 dates
        for date_str in sorted(date_counts.keys(), reverse=True)[:10]:
            counts = date_counts[date_str]
            if counts['zero'] > 0:
                print(f"   {date_str}: {counts['zero']}/{counts['total']} positions with zero price WARNING")
            else:
                print(f"   {date_str}: {counts['total']} positions, all have prices OK")
        
    except Exception as e:
        print(f"   ERROR: Error querying database: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--fund", default="Project Chimera", help="Fund name to check")
    parser.add_argument("--days", type=int, default=30, help="Days back to check")
    args = parser.parse_args()
    
    check_zero_prices(args.fund, args.days)
