#!/usr/bin/env python3
"""
Price Debug Script for LLM Micro-Cap Trading Bot

This script helps debug price data issues by:
1. Fetching current and historical price data
2. Comparing with known values (Yahoo Finance)
3. Identifying discrepancies in price data
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import pytz

def debug_ticker_prices(ticker, days_back=5):
    """
    Debug price data for a specific ticker
    
    Args:
        ticker (str): Stock ticker symbol
        days_back (int): Number of days to look back
    """
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
            print(f"❌ No historical data found for {ticker}")
            return None
            
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
            'latest_open': hist['Open'].iloc[-1] if len(hist) > 0 else None
        }
        
    except Exception as e:
        print(f"❌ Error fetching data for {ticker}: {str(e)}")
        return None

def compare_with_portfolio_data(ticker, portfolio_file="my trading/llm_portfolio_update.csv"):
    """
    Compare yfinance data with what's in our portfolio CSV
    """
    print(f"🔄 Comparing {ticker} data with portfolio records")
    print("=" * 60)
    
    try:
        # Read portfolio data
        df = pd.read_csv(portfolio_file)
        ticker_data = df[df['Ticker'] == ticker].copy()
        
        if ticker_data.empty:
            print(f"❌ No portfolio data found for {ticker}")
            return
            
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
            
    except Exception as e:
        print(f"❌ Error reading portfolio data: {str(e)}")

def suggest_corrections(ticker, debug_data, portfolio_file="my trading/llm_portfolio_update.csv"):
    """
    Suggest corrections based on the debug data
    """
    print(f"💡 Correction Suggestions for {ticker}")
    print("=" * 60)
    
    if not debug_data:
        print("❌ No debug data available")
        return
        
    try:
        # Read portfolio data
        df = pd.read_csv(portfolio_file)
        ticker_data = df[df['Ticker'] == ticker].copy()
        
        if ticker_data.empty:
            print(f"❌ No portfolio data found for {ticker}")
            return
            
        # Get the most recent historical data
        hist = debug_data['historical']
        latest_date = hist.index[-1].date()
        
        print(f"📊 Based on Yahoo Finance data:")
        print(f"   Latest Close ({latest_date}): ${hist['Close'].iloc[-1]:.2f}")
        print(f"   Latest Open ({latest_date}): ${hist['Open'].iloc[-1]:.2f}")
        
        if len(hist) > 1:
            prev_close = hist['Close'].iloc[-2]
            print(f"   Previous Close: ${prev_close:.2f}")
        
        print()
        print("🔧 Suggested corrections for portfolio CSV:")
        print("-" * 60)
        
        for row in ticker_data.to_dict('records'):
            if pd.isna(row['Current Price']) or row['Current Price'] == 'NO DATA':
                print(f"❌ Row with missing data: {row['Date']}")
                print(f"   Suggested Current Price: ${hist['Close'].iloc[-1]:.2f}")
                print(f"   Suggested Total Value: ${row['Shares'] * hist['Close'].iloc[-1]:.2f}")
                print(f"   Suggested PnL: ${(hist['Close'].iloc[-1] - row['Price']) * row['Shares']:.2f}")
                print()
            else:
                print(f"✅ Row with data: {row['Date']} - Current Price: {row['Current Price']}")
                
    except Exception as e:
        print(f"❌ Error generating suggestions: {str(e)}")

def main():
    """
    Main debug function
    """
    print("🐛 LLM Micro-Cap Trading Bot - Price Debug Tool")
    print("=" * 60)
    
    # Debug VEE.TO specifically
    ticker = "VEE.TO"
    
    print(f"🎯 Debugging {ticker} price data...")
    print()
    
    # Get debug data
    debug_data = debug_ticker_prices(ticker, days_back=5)
    
    # Compare with portfolio
    compare_with_portfolio_data(ticker)
    
    # Suggest corrections
    suggest_corrections(ticker, debug_data)
    
    print("✅ Debug complete!")
    print()
    print("💡 Next steps:")
    print("   1. Review the suggested corrections above")
    print("   2. Update the portfolio CSV with correct historical prices")
    print("   3. Use previous close for yesterday's data, not current price")

if __name__ == "__main__":
    main()
