#!/usr/bin/env python3
"""
Check for positions with shares but near-zero market values
This might indicate a calculation or data issue
"""

import sys
from pathlib import Path
from datetime import datetime, date, timedelta
from decimal import Decimal

# Setup sys.path
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

from web_dashboard.supabase_client import SupabaseClient

def check_market_values(fund_name: str = "Project Chimera", days_back: int = 30):
    """Check for positions with shares but suspiciously low market values"""
    
    client = SupabaseClient(use_service_role=True)
    
    # Get recent dates
    end_date = date.today()
    start_date = end_date - timedelta(days=days_back)
    
    print(f"Checking portfolio_positions for suspicious market values")
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
        
        # Check for positions with shares but low market value
        suspicious_positions = []
        
        for p in positions:
            ticker = p.get('ticker')
            price = p.get('price')
            # Table has 'total_value', views have 'market_value' - check both
            market_val = p.get('total_value') or p.get('market_value')
            shares = p.get('shares')
            cost = p.get('cost_basis') or p.get('cost')  # Table has 'cost_basis'
            pos_date = p.get('date')
            currency = p.get('currency')
            
            # Convert to Decimal
            try:
                shares_decimal = Decimal(str(shares)) if shares is not None else Decimal('0')
                price_decimal = Decimal(str(price)) if price is not None else Decimal('0')
                market_val_decimal = Decimal(str(market_val)) if market_val is not None else Decimal('0')
                cost_decimal = Decimal(str(cost)) if cost is not None else Decimal('0')
            except:
                continue
            
            # Check if we have shares but market value is suspiciously low
            if shares_decimal > 0:
                # Calculate expected market value
                expected_mv = shares_decimal * price_decimal
                
                # Check for mismatches
                if market_val_decimal == 0 and price_decimal > 0:
                    suspicious_positions.append({
                        'ticker': ticker,
                        'date': pos_date,
                        'shares': shares_decimal,
                        'price': price_decimal,
                        'market_value': market_val_decimal,
                        'expected_mv': expected_mv,
                        'cost': cost_decimal,
                        'currency': currency,
                        'issue': 'market_value_is_zero_but_has_price'
                    })
                elif price_decimal > 0 and abs(market_val_decimal - expected_mv) > Decimal('0.01'):
                    # Market value doesn't match price * shares (more than 1 cent difference)
                    suspicious_positions.append({
                        'ticker': ticker,
                        'date': pos_date,
                        'shares': shares_decimal,
                        'price': price_decimal,
                        'market_value': market_val_decimal,
                        'expected_mv': expected_mv,
                        'cost': cost_decimal,
                        'currency': currency,
                        'issue': 'market_value_mismatch'
                    })
                elif shares_decimal > 0 and price_decimal == 0:
                    suspicious_positions.append({
                        'ticker': ticker,
                        'date': pos_date,
                        'shares': shares_decimal,
                        'price': price_decimal,
                        'market_value': market_val_decimal,
                        'expected_mv': expected_mv,
                        'cost': cost_decimal,
                        'currency': currency,
                        'issue': 'has_shares_but_zero_price'
                    })
                elif shares_decimal > 0 and market_val_decimal < Decimal('1.00') and cost_decimal > Decimal('10.00'):
                    # Has shares, cost > $10, but market value < $1 (suspicious)
                    suspicious_positions.append({
                        'ticker': ticker,
                        'date': pos_date,
                        'shares': shares_decimal,
                        'price': price_decimal,
                        'market_value': market_val_decimal,
                        'expected_mv': expected_mv,
                        'cost': cost_decimal,
                        'currency': currency,
                        'issue': 'low_market_value_relative_to_cost'
                    })
        
        if suspicious_positions:
            print(f"\n*** FOUND {len(suspicious_positions)} suspicious positions:")
            print()
            
            # Group by issue type
            by_issue = {}
            for pos in suspicious_positions:
                issue = pos['issue']
                if issue not in by_issue:
                    by_issue[issue] = []
                by_issue[issue].append(pos)
            
            for issue_type, positions_list in sorted(by_issue.items()):
                print(f"\n{issue_type}: {len(positions_list)} positions")
                print("-" * 80)
                
                # Group by ticker
                by_ticker = {}
                for pos in positions_list:
                    ticker = pos['ticker']
                    if ticker not in by_ticker:
                        by_ticker[ticker] = []
                    by_ticker[ticker].append(pos)
                
                for ticker, ticker_positions in sorted(by_ticker.items()):
                    latest = sorted(ticker_positions, key=lambda x: x['date'], reverse=True)[0]
                    print(f"\n   {ticker} ({latest['currency']}):")
                    print(f"      Latest issue on: {latest['date']}")
                    print(f"      Shares: {latest['shares']}")
                    print(f"      Price: ${latest['price']}")
                    print(f"      Market Value: ${latest['market_value']}")
                    print(f"      Expected MV (price * shares): ${latest['expected_mv']}")
                    print(f"      Cost: ${latest['cost']}")
                    print(f"      Difference: ${abs(latest['market_value'] - latest['expected_mv'])}")
                    print(f"      Total occurrences: {len(ticker_positions)}")
                    
                    # Show date range
                    dates = sorted([p['date'][:10] for p in ticker_positions])
                    if len(dates) <= 5:
                        print(f"      Dates: {', '.join(dates)}")
                    else:
                        print(f"      Dates: {dates[0]} to {dates[-1]} ({len(dates)} dates)")
        else:
            print("\nOK: No suspicious market values found")
        
        # Also show summary of latest positions
        print(f"\n\nLatest positions summary (most recent date):")
        print("-" * 80)
        
        # Get latest date
        latest_date = max([p.get('date', '')[:10] for p in positions])
        latest_positions = [p for p in positions if p.get('date', '')[:10] == latest_date]
        
        print(f"\nDate: {latest_date}")
        print(f"Total positions: {len(latest_positions)}")
        print()
        
        for p in sorted(latest_positions, key=lambda x: x.get('ticker', '')):
            ticker = p.get('ticker')
            price = p.get('price')
            market_val = p.get('market_value')
            shares = p.get('shares')
            cost = p.get('cost')
            currency = p.get('currency')
            
            try:
                shares_decimal = Decimal(str(shares)) if shares is not None else Decimal('0')
                price_decimal = Decimal(str(price)) if price is not None else Decimal('0')
                market_val_decimal = Decimal(str(market_val)) if market_val is not None else Decimal('0')
                cost_decimal = Decimal(str(cost)) if cost is not None else Decimal('0')
            except:
                continue
            
            if shares_decimal > 0:
                expected_mv = shares_decimal * price_decimal
                print(f"   {ticker:10} ({currency:3}): {shares_decimal:>10.4f} shares @ ${price_decimal:>10.2f} = ${market_val_decimal:>12.2f} (expected: ${expected_mv:>12.2f}, cost: ${cost_decimal:>12.2f})")
        
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
    
    check_market_values(args.fund, args.days)
