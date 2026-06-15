#!/usr/bin/env python3
"""
Comprehensive Price Debug Script for LLM Micro-Cap Trading Bot

This script provides comprehensive debugging capabilities for price data issues:
1. Fetches current and historical price data for any ticker
2. Compares with portfolio data
3. Identifies discrepancies and suggests corrections
4. Can be used to verify data accuracy before making trades
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import pytz
import argparse
import sys
import os

# Add parent directory to path to import from main project
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def debug_ticker_prices(ticker, days_back=5, verbose=True):
    """
    Debug price data for a specific ticker
    
    Args:
        ticker (str): Stock ticker symbol
        days_back (int): Number of days to look back
        verbose (bool): Whether to print detailed output
    """
    if verbose:
        print(f"🔍 Debugging price data for {ticker}")
        print("=" * 60)
    
    try:
        # Create ticker object
        stock = yf.Ticker(ticker)
        
        # Get historical data for the last few days
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        
        hist = stock.history(start=start_date, end=end_date)
        
        if hist.empty:
            if verbose:
                print(f"❌ No historical data found for {ticker}")
            return None
            
        if verbose:
            print(f"📊 Historical Data for {ticker} ({start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')})")
            print("-" * 60)
            
            # Display recent data
            for row in hist.tail(3).itertuples():
                print(f"📅 {row.Index.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"   Open:  ${row.Open:.2f}")
                print(f"   High:  ${row.High:.2f}")
                print(f"   Low:   ${row.Low:.2f}")
                print(f"   Close: ${row.Close:.2f}")
                print(f"   Volume: {row.Volume:,}")
                print()
        
        # Get current info
        info = stock.info
        if verbose:
            print(f"📈 Current Info for {ticker}")
            print("-" * 60)
            print(f"Current Price: ${info.get('currentPrice', 'N/A')}")
            print(f"Previous Close: ${info.get('previousClose', 'N/A')}")
            print(f"Open: ${info.get('open', 'N/A')}")
            print(f"Day High: ${info.get('dayHigh', 'N/A')}")
            print(f"Day Low: ${info.get('dayLow', 'N/A')}")
            print(f"52 Week High: ${info.get('fiftyTwoWeekHigh', 'N/A')}")
            print(f"52 Week Low: ${info.get('fiftyTwoWeekLow', 'N/A')}")
            print()
        
        return {
            'historical': hist,
            'info': info,
            'latest_close': hist['Close'].iloc[-1],
            'latest_open': hist['Open'].iloc[-1] if len(hist) > 0 else None,
            'previous_close': hist['Close'].iloc[-2] if len(hist) > 1 else None
        }
        
    except Exception as e:
        if verbose:
            print(f"❌ Error fetching data for {ticker}: {str(e)}")
        return None

def compare_with_portfolio_data(ticker, portfolio_file="my trading/llm_portfolio_update.csv", verbose=True):
    """
    Compare yfinance data with what's in our portfolio CSV
    """
    if verbose:
        print(f"🔄 Comparing {ticker} data with portfolio records")
        print("=" * 60)
    
    try:
        # Read portfolio data
        df = pd.read_csv(portfolio_file)
        ticker_data = df[df['Ticker'] == ticker].copy()
        
        if ticker_data.empty:
            if verbose:
                print(f"❌ No portfolio data found for {ticker}")
            return None
            
        if verbose:
            print(f"📋 Portfolio Records for {ticker}")
            print("-" * 60)
            for row in ticker_data.to_dict('records'):
                print(f"Date: {row['Date']}")
                print(f"Shares: {row['Shares']}")
                print(f"Price: ${row['Price']}")
                print(f"Current Price: {row['Current Price']}")
                print(f"Total Value: {row['Total Value']}")
                print(f"PnL: {row['PnL']}")
                print(f"Action: {row['Action']}")
                print(f"Company: {row['Company']}")
                print()
        
        return ticker_data
                
    except Exception as e:
        if verbose:
            print(f"❌ Error reading portfolio data: {str(e)}")
        return None

def suggest_corrections(ticker, debug_data, portfolio_file="my trading/llm_portfolio_update.csv", verbose=True):
    """
    Suggest corrections based on the debug data
    """
    if verbose:
        print(f"💡 Correction Suggestions for {ticker}")
        print("=" * 60)
    
    if not debug_data:
        if verbose:
            print("❌ No debug data available")
        return None
        
    try:
        # Read portfolio data
        df = pd.read_csv(portfolio_file)
        ticker_data = df[df['Ticker'] == ticker].copy()
        
        if ticker_data.empty:
            if verbose:
                print(f"❌ No portfolio data found for {ticker}")
            return None
            
        # Get the most recent historical data
        hist = debug_data['historical']
        latest_date = hist.index[-1].date()
        
        if verbose:
            print(f"📊 Based on Yahoo Finance data:")
            print(f"   Latest Close ({latest_date}): ${hist['Close'].iloc[-1]:.2f}")
            print(f"   Latest Open ({latest_date}): ${hist['Open'].iloc[-1]:.2f}")
            
            if len(hist) > 1:
                prev_close = hist['Close'].iloc[-2]
                print(f"   Previous Close: ${prev_close:.2f}")
            
            print()
            print("🔧 Suggested corrections for portfolio CSV:")
            print("-" * 60)
        
        corrections = []
        
        for row in ticker_data.to_dict('records'):
            if pd.isna(row['Current Price']) or row['Current Price'] == 'NO DATA':
                # Use latest close as current price
                suggested_price = hist['Close'].iloc[-1]
                suggested_value = row['Shares'] * suggested_price
                suggested_pnl = (suggested_price - row['Price']) * row['Shares']
                
                correction = {
                    'date': row['Date'],
                    'suggested_price': suggested_price,
                    'suggested_value': suggested_value,
                    'suggested_pnl': suggested_pnl
                }
                corrections.append(correction)
                
                if verbose:
                    print(f"❌ Row with missing data: {row['Date']}")
                    print(f"   Suggested Current Price: ${suggested_price:.2f}")
                    print(f"   Suggested Total Value: ${suggested_value:.2f}")
                    print(f"   Suggested PnL: ${suggested_pnl:.2f}")
                    print()
            else:
                if verbose:
                    print(f"✅ Row with data: {row['Date']} - Current Price: {row['Current Price']}")
        
        return corrections
                
    except Exception as e:
        if verbose:
            print(f"❌ Error generating suggestions: {str(e)}")
        return None

def debug_multiple_tickers(tickers, portfolio_file="my trading/llm_portfolio_update.csv"):
    """
    Debug multiple tickers at once
    """
    print("🐛 Multi-Ticker Debug Report")
    print("=" * 60)
    
    results = {}
    
    for ticker in tickers:
        print(f"\n🎯 Debugging {ticker}...")
        print("-" * 40)
        
        debug_data = debug_ticker_prices(ticker, verbose=False)
        portfolio_data = compare_with_portfolio_data(ticker, portfolio_file, verbose=False)
        corrections = suggest_corrections(ticker, debug_data, portfolio_file, verbose=False)
        
        results[ticker] = {
            'debug_data': debug_data,
            'portfolio_data': portfolio_data,
            'corrections': corrections
        }
        
        if debug_data:
            print(f"✅ {ticker}: Data available")
            if corrections:
                print(f"   🔧 {len(corrections)} corrections needed")
            else:
                print(f"   ✅ No corrections needed")
        else:
            print(f"❌ {ticker}: No data available")
    
    return results

def main():
    """
    Main debug function with command line interface
    """
    parser = argparse.ArgumentParser(description='Debug price data for trading bot')
    parser.add_argument('ticker', nargs='?', help='Ticker symbol to debug (e.g., VEE.TO)')
    parser.add_argument('--portfolio-file', default='my trading/llm_portfolio_update.csv', 
                       help='Path to portfolio CSV file')
    parser.add_argument('--days-back', type=int, default=5, 
                       help='Number of days to look back for historical data')
    parser.add_argument('--multi', nargs='+', help='Debug multiple tickers (e.g., --multi VEE.TO GMIN.TO)')
    parser.add_argument('--quiet', action='store_true', help='Quiet mode - minimal output')
    
    args = parser.parse_args()
    
    if not args.quiet:
        print("🐛 LLM Micro-Cap Trading Bot - Price Debug Tool")
        print("=" * 60)
    
    if args.multi:
        # Debug multiple tickers
        results = debug_multiple_tickers(args.multi, args.portfolio_file)
        
        if not args.quiet:
            print("\n📊 Summary:")
            for ticker, result in results.items():
                if result['debug_data']:
                    corrections_count = len(result['corrections']) if result['corrections'] else 0
                    print(f"   {ticker}: ✅ Data available, {corrections_count} corrections needed")
                else:
                    print(f"   {ticker}: ❌ No data available")
    
    elif args.ticker:
        # Debug single ticker
        if not args.quiet:
            print(f"🎯 Debugging {args.ticker} price data...")
            print()
        
        # Get debug data
        debug_data = debug_ticker_prices(args.ticker, args.days_back, not args.quiet)
        
        # Compare with portfolio
        portfolio_data = compare_with_portfolio_data(args.ticker, args.portfolio_file, not args.quiet)
        
        # Suggest corrections
        corrections = suggest_corrections(args.ticker, debug_data, args.portfolio_file, not args.quiet)
        
        if not args.quiet:
            print("✅ Debug complete!")
            print()
            print("💡 Next steps:")
            print("   1. Review the suggested corrections above")
            print("   2. Update the portfolio CSV with correct historical prices")
            print("   3. Use previous close for yesterday's data, not current price")
    
    else:
        # No ticker specified, show help
        parser.print_help()
        print("\n💡 Examples:")
        print("   python debug/comprehensive_price_debug.py VEE.TO")
        print("   python debug/comprehensive_price_debug.py --multi VEE.TO GMIN.TO")
        print("   python debug/comprehensive_price_debug.py VEE.TO --quiet")

if __name__ == "__main__":
    main()
