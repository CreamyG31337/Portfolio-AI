#!/usr/bin/env python3
"""
Debug script to compare web dashboard holdings data with console app output.

This script fetches holdings data from both sources and compares them side-by-side
to identify discrepancies in calculations, field mappings, or data freshness.
"""

import sys
import os
from pathlib import Path
from decimal import Decimal
from datetime import datetime
from typing import Dict, List, Any, Optional

# Add parent directory to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "web_dashboard"))

# Change to project root for imports
os.chdir(project_root)

from web_dashboard.streamlit_utils import get_current_positions, get_first_trade_dates, fetch_latest_rates_bulk
from portfolio.portfolio_manager import PortfolioManager
from data.repositories.supabase_repository import SupabaseRepository

def format_money(value: float, currency: str = "CAD") -> str:
    """Format money value"""
    if value is None:
        return "N/A"
    return f"${value:,.2f}"

def format_percent(value: float) -> str:
    """Format percentage value"""
    if value is None:
        return "N/A"
    return f"{value:.2f}%"

def get_web_dashboard_data(fund: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get holdings data as returned by web dashboard API"""
    display_currency = 'CAD'
    
    positions_df = get_current_positions(fund)
    
    if positions_df.empty:
        return []
    
    # Get first trade dates for "Opened" column
    first_trade_dates = get_first_trade_dates(fund)
    
    # Get rates
    all_currencies = positions_df['currency'].fillna('CAD').astype(str).str.upper().unique().tolist()
    rate_map = fetch_latest_rates_bulk(all_currencies, display_currency)
    def get_rate(curr): return rate_map.get(str(curr).upper(), 1.0)
    
    # Process data and calculate converted values first
    converted_data = []
    for row in positions_df.to_dict('records'):
        rate = get_rate(row.get('currency', 'CAD'))
        market_val = (row.get('market_value', 0) or 0) * rate
        converted_data.append(market_val)
    
    # Calculate total portfolio value in display currency for weight calculation
    total_portfolio_value = sum(converted_data) if converted_data else 0
    
    # Process data
    data = []
    for row in positions_df.to_dict('records'):
        ticker = row.get('ticker')
        
        # Handle nested securities data
        company_name = ticker # Default
        sector = ""
        if isinstance(row.get('securities'), dict):
            company_name = row['securities'].get('company_name') or ticker
            sector = row['securities'].get('sector') or ""
        
        # Use 'shares' from latest_positions view (not 'quantity')
        shares = row.get('shares', 0) or 0
        cost_basis = row.get('cost_basis', 0) or 0
        current_price = row.get('current_price', 0) or 0
        
        # Calculate average price from cost_basis / shares
        avg_price = (cost_basis / shares) if shares > 0 else 0
        
        # Values in Display Currency
        rate = get_rate(row.get('currency', 'CAD'))
        market_val = (row.get('market_value', 0) or 0) * rate
        pnl = (row.get('unrealized_pnl', 0) or 0) * rate
        day_pnl = (row.get('daily_pnl', 0) or 0) * rate
        five_day_pnl = (row.get('five_day_pnl', 0) or 0) * rate
        
        # Use P&L percentages from view (already calculated correctly)
        pnl_pct = row.get('return_pct', 0) or 0
        day_pnl_pct = row.get('daily_pnl_pct', 0) or 0
        five_day_pnl_pct = row.get('five_day_pnl_pct', 0) or 0
        
        # Calculate weight as percentage of total portfolio (in display currency)
        weight = (market_val / total_portfolio_value * 100) if total_portfolio_value > 0 else 0
        
        # Get opened date
        opened_date = None
        if ticker in first_trade_dates:
            try:
                opened_date = first_trade_dates[ticker].strftime('%m-%d-%y')
            except:
                opened_date = None
        
        # Get stop loss if available (might not be in view)
        stop_loss = row.get('stop_loss', None)
        
        data.append({
            "ticker": ticker,
            "name": company_name,
            "sector": sector,
            "shares": shares,
            "opened": opened_date,
            "avg_price": avg_price * rate,  # Avg price in display currency
            "price": current_price * rate,  # Current price in display currency
            "value": market_val,
            "day_change": day_pnl,
            "day_change_pct": day_pnl_pct,
            "total_return": pnl,
            "total_return_pct": pnl_pct,
            "five_day_pnl": five_day_pnl,
            "five_day_pnl_pct": five_day_pnl_pct,
            "weight": weight,
            "stop_loss": stop_loss,
            "currency": row.get('currency', 'CAD') # Original currency
        })
    
    # Sort by weight desc (matching console app default)
    data.sort(key=lambda x: x.get('weight', 0), reverse=True)
    
    return data

def get_console_app_data(fund: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get holdings data as computed by console app"""
    try:
        # Try to import Settings - handle different import paths
        try:
            from utils.settings import Settings
        except ImportError:
            try:
                from settings import Settings
            except ImportError:
                print("Warning: Could not import Settings, using defaults", file=sys.stderr)
                class Settings:
                    def __init__(self):
                        self.default_fund = "Project Chimera"
        
        settings = Settings()
        repository = SupabaseRepository(settings, fund or getattr(settings, 'default_fund', 'Project Chimera'))
        portfolio_manager = PortfolioManager(repository)
        
        # Get latest snapshot
        latest_snapshot = portfolio_manager.get_latest_snapshot()
        if not latest_snapshot:
            return []
        
        # Get trade log for opened dates
        trade_log = repository.get_trade_log(limit=10000, fund=fund)
        
        # Build opened date lookup
        opened_dates = {}
        for trade in trade_log:
            if trade.action.upper() == 'BUY':
                ticker = trade.ticker
                if ticker not in opened_dates or trade.timestamp < opened_dates[ticker]:
                    opened_dates[ticker] = trade.timestamp
        
        # Calculate total portfolio value for weights
        total_portfolio_value = sum(float(pos.market_value or 0) for pos in latest_snapshot.positions)
        
        data = []
        for position in latest_snapshot.positions:
            # Get opened date
            opened_date = None
            if position.ticker in opened_dates:
                try:
                    opened_date = opened_dates[position.ticker].strftime('%m-%d-%y')
                except:
                    opened_date = None
            
            # Calculate weight
            weight = (float(position.market_value or 0) / total_portfolio_value * 100) if total_portfolio_value > 0 else 0
            
            data.append({
                "ticker": position.ticker,
                "name": position.company or position.ticker,
                "sector": "",  # Console app might not show this
                "shares": float(position.shares or 0),
                "opened": opened_date,
                "avg_price": float(position.avg_price or 0),
                "price": float(position.current_price or 0),
                "value": float(position.market_value or 0),
                "day_change": float(position.daily_pnl or 0) if hasattr(position, 'daily_pnl') else 0,
                "day_change_pct": float(position.daily_pnl_pct or 0) if hasattr(position, 'daily_pnl_pct') else 0,
                "total_return": float(position.unrealized_pnl or 0),
                "total_return_pct": float(position.unrealized_pnl_pct or 0) if hasattr(position, 'unrealized_pnl_pct') else 0,
                "five_day_pnl": float(position.five_day_pnl or 0) if hasattr(position, 'five_day_pnl') else 0,
                "five_day_pnl_pct": float(position.five_day_pnl_pct or 0) if hasattr(position, 'five_day_pnl_pct') else 0,
                "weight": weight,
                "stop_loss": float(position.stop_loss or 0) if hasattr(position, 'stop_loss') else None,
                "currency": position.currency or 'CAD'
            })
        
        # Sort by weight desc
        data.sort(key=lambda x: x.get('weight', 0), reverse=True)
        
        return data
    except Exception as e:
        print(f"Error getting console app data: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return []

def compare_data(web_data: List[Dict], console_data: List[Dict]) -> None:
    """Compare the two datasets and print discrepancies"""
    
    # Create lookup by ticker
    web_lookup = {item['ticker']: item for item in web_data}
    console_lookup = {item['ticker']: item for item in console_data}
    
    all_tickers = set(web_lookup.keys()) | set(console_lookup.keys())
    
    print("=" * 150)
    print("HOLDINGS DATA COMPARISON")
    print("=" * 150)
    print(f"Web Dashboard: {len(web_data)} positions")
    print(f"Console App: {len(console_data)} positions")
    print(f"Total unique tickers: {len(all_tickers)}")
    print()
    
    # Check for missing tickers
    web_only = set(web_lookup.keys()) - set(console_lookup.keys())
    console_only = set(console_lookup.keys()) - set(web_lookup.keys())
    
    if web_only:
        print(f"WARNING: Tickers only in Web Dashboard: {sorted(web_only)}")
    if console_only:
        print(f"WARNING: Tickers only in Console App: {sorted(console_only)}")
    if web_only or console_only:
        print()
    
    # Compare each ticker
    discrepancies = []
    for ticker in sorted(all_tickers):
        web_item = web_lookup.get(ticker)
        console_item = console_lookup.get(ticker)
        
        if not web_item or not console_item:
            continue
        
        # Compare key fields
        diffs = []
        
        # Helper to compare floats with tolerance
        def compare_float(field: str, web_val: Any, console_val: Any, tolerance: float = 0.01) -> bool:
            if web_val is None and console_val is None:
                return True
            if web_val is None or console_val is None:
                diffs.append(f"{field}: Web={web_val}, Console={console_val}")
                return False
            diff = abs(float(web_val) - float(console_val))
            if diff > tolerance:
                diffs.append(f"{field}: Web={web_val:.4f}, Console={console_val:.4f}, Diff={diff:.4f}")
                return False
            return True
        
        # Compare fields
        compare_float("shares", web_item['shares'], console_item['shares'], 0.0001)
        compare_float("avg_price", web_item['avg_price'], console_item['avg_price'], 0.01)
        compare_float("price", web_item['price'], console_item['price'], 0.01)
        compare_float("value", web_item['value'], console_item['value'], 0.01)
        compare_float("total_return", web_item['total_return'], console_item['total_return'], 0.01)
        compare_float("total_return_pct", web_item['total_return_pct'], console_item['total_return_pct'], 0.1)
        compare_float("day_change", web_item['day_change'], console_item['day_change'], 0.01)
        compare_float("day_change_pct", web_item['day_change_pct'], console_item['day_change_pct'], 0.1)
        compare_float("five_day_pnl", web_item['five_day_pnl'], console_item['five_day_pnl'], 0.01)
        compare_float("five_day_pnl_pct", web_item['five_day_pnl_pct'], console_item['five_day_pnl_pct'], 0.1)
        compare_float("weight", web_item['weight'], console_item['weight'], 0.1)
        
        if diffs:
            discrepancies.append((ticker, diffs))
    
    # Print summary
    if not discrepancies:
        print("SUCCESS: All data matches!")
    else:
        print(f"ERROR: Found {len(discrepancies)} tickers with discrepancies:\n")
        
        for ticker, diffs in discrepancies:
            print(f"\n{'='*150}")
            print(f"TICKER: {ticker}")
            print(f"{'='*150}")
            web_item = web_lookup[ticker]
            console_item = console_lookup[ticker]
            
            print(f"\nWeb Dashboard:")
            print(f"  Company: {web_item['name']}")
            print(f"  Sector: {web_item['sector']}")
            print(f"  Shares: {web_item['shares']:.4f}")
            print(f"  Opened: {web_item['opened']}")
            print(f"  Avg Price: {format_money(web_item['avg_price'])}")
            print(f"  Current Price: {format_money(web_item['price'])}")
            print(f"  Value: {format_money(web_item['value'])}")
            print(f"  Total P&L: {format_money(web_item['total_return'])} ({format_percent(web_item['total_return_pct'])})")
            print(f"  1-Day P&L: {format_money(web_item['day_change'])} ({format_percent(web_item['day_change_pct'])})")
            print(f"  5-Day P&L: {format_money(web_item['five_day_pnl'])} ({format_percent(web_item['five_day_pnl_pct'])})")
            print(f"  Weight: {format_percent(web_item['weight'])}")
            print(f"  Currency: {web_item['currency']}")
            
            print(f"\nConsole App:")
            print(f"  Company: {console_item['name']}")
            print(f"  Sector: {console_item['sector']}")
            print(f"  Shares: {console_item['shares']:.4f}")
            print(f"  Opened: {console_item['opened']}")
            print(f"  Avg Price: {format_money(console_item['avg_price'])}")
            print(f"  Current Price: {format_money(console_item['price'])}")
            print(f"  Value: {format_money(console_item['value'])}")
            print(f"  Total P&L: {format_money(console_item['total_return'])} ({format_percent(console_item['total_return_pct'])})")
            print(f"  1-Day P&L: {format_money(console_item['day_change'])} ({format_percent(console_item['day_change_pct'])})")
            print(f"  5-Day P&L: {format_money(console_item['five_day_pnl'])} ({format_percent(console_item['five_day_pnl_pct'])})")
            print(f"  Weight: {format_percent(console_item['weight'])}")
            print(f"  Currency: {console_item['currency']}")
            
            print(f"\nDISCREPANCIES:")
            for diff in diffs:
                print(f"  - {diff}")

def print_web_dashboard_data(data: List[Dict[str, Any]]) -> None:
    """Print web dashboard data in a readable format for manual comparison"""
    print("\n" + "=" * 150)
    print("WEB DASHBOARD HOLDINGS DATA")
    print("=" * 150)
    print(f"Total positions: {len(data)}")
    print()
    
    # Print header
    print(f"{'Ticker':<8} {'Company':<25} {'Opened':<10} {'Shares':>10} {'Avg Price':>12} {'Current':>12} {'Value':>14} {'Total P&L':>18} {'1-Day P&L':>18} {'5-Day P&L':>18} {'Weight':>8}")
    print("-" * 150)
    
    # Print each position
    for item in data:
        ticker = item['ticker'][:7]
        name = (item['name'] or '')[:24]
        opened = item['opened'] or 'N/A'
        shares = f"{item['shares']:.4f}"
        avg_price = format_money(item['avg_price'])
        current = format_money(item['price'])
        value = format_money(item['value'])
        total_pnl = f"{format_money(item['total_return'])} {item['total_return_pct']:+.1f}%"
        day_pnl = f"{format_money(item['day_change'])} {item['day_change_pct']:+.1f}%"
        five_day_pnl = f"{format_money(item['five_day_pnl'])} {item['five_day_pnl_pct']:+.1f}%"
        weight = f"{item['weight']:.1f}%"
        
        print(f"{ticker:<8} {name:<25} {opened:<10} {shares:>10} {avg_price:>12} {current:>12} {value:>14} {total_pnl:>18} {day_pnl:>18} {five_day_pnl:>18} {weight:>8}")

def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Compare web dashboard holdings with console app')
    parser.add_argument('--fund', type=str, help='Fund name (optional)')
    parser.add_argument('--web-only', action='store_true', help='Only print web dashboard data (for manual comparison)')
    args = parser.parse_args()
    
    print("Fetching web dashboard data...")
    web_data = get_web_dashboard_data(args.fund)
    
    if not web_data:
        print("ERROR: No web dashboard data found!")
        return
    
    if args.web_only:
        print_web_dashboard_data(web_data)
        print("\nUse this output to manually compare with console app output.")
        return
    
    print("Fetching console app data...")
    console_data = get_console_app_data(args.fund)
    
    if not console_data:
        print("ERROR: No console app data found!")
        print("\nTip: Use --web-only to just print web dashboard data for manual comparison")
        return
    
    compare_data(web_data, console_data)

if __name__ == '__main__':
    main()
