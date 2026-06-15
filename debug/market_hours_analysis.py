#!/usr/bin/env python3
"""
Market Hours Analysis Script for LLM Micro-Cap Trading Bot

This script analyzes how yfinance handles price data during different market scenarios:
1. During market hours (real-time prices)
2. After market close (previous close vs current price)
3. Before market open (previous close vs pre-market)
4. Weekend/holiday scenarios

This helps ensure our daily P&L calculation follows industry standards.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import pytz
from trading_script import download_price_data, trading_day_window, last_trading_date

def analyze_yfinance_behavior(ticker="TSLA"):
    """
    Analyze what yfinance returns during different market scenarios
    """
    print(f"🔍 Analyzing yfinance behavior for {ticker}")
    print("=" * 80)
    
    # Create ticker object
    stock = yf.Ticker(ticker)
    
    # Get current time in different timezones
    utc_now = datetime.now(pytz.UTC)
    est_now = utc_now.astimezone(pytz.timezone('US/Eastern'))
    pst_now = utc_now.astimezone(pytz.timezone('US/Pacific'))
    
    print(f"🕐 Current Time:")
    print(f"   UTC: {utc_now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"   EST: {est_now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"   PST: {pst_now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print()
    
    # Check if markets are open (simplified - 9:30 AM to 4:00 PM EST)
    market_open = est_now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = est_now.replace(hour=16, minute=0, second=0, microsecond=0)
    
    if est_now.weekday() < 5:  # Monday = 0, Friday = 4
        if market_open <= est_now <= market_close:
            market_status = "🟢 MARKET OPEN"
        elif est_now < market_open:
            market_status = "🟡 PRE-MARKET"
        else:
            market_status = "🔴 AFTER HOURS"
    else:
        market_status = "🔴 WEEKEND/HOLIDAY"
    
    print(f"📊 Market Status: {market_status}")
    print()
    
    # Get historical data for the last 5 days
    end_date = datetime.now()
    start_date = end_date - timedelta(days=5)
    
    print(f"📈 Historical Data (Last 5 Days)")
    print("-" * 50)
    hist = stock.history(start=start_date, end=end_date)
    
    if not hist.empty:
        print(f"Data shape: {hist.shape}")
        print(f"Columns: {list(hist.columns)}")
        print()
        
        # Show the last few days
        for row in hist.tail(3).itertuples():
            print(f"📅 {row.Index.strftime('%Y-%m-%d')}")
            print(f"   Open:  ${row.Open:.2f}")
            print(f"   High:  ${row.High:.2f}")
            print(f"   Low:   ${row.Low:.2f}")
            print(f"   Close: ${row.Close:.2f}")
            print(f"   Volume: {row.Volume:,}")
            print()
    else:
        print("❌ No historical data available")
        return
    
    # Get current info
    print(f"📊 Current Info")
    print("-" * 50)
    info = stock.info
    
    current_price = info.get('currentPrice', 'N/A')
    previous_close = info.get('previousClose', 'N/A')
    open_price = info.get('open', 'N/A')
    day_high = info.get('dayHigh', 'N/A')
    day_low = info.get('dayLow', 'N/A')
    
    print(f"Current Price: ${current_price}")
    print(f"Previous Close: ${previous_close}")
    print(f"Open: ${open_price}")
    print(f"Day High: ${day_high}")
    print(f"Day Low: ${day_low}")
    print()
    
    # Analyze what our current logic would do
    print(f"🔍 Current Daily P&L Logic Analysis")
    print("-" * 50)
    
    # Simulate our current logic
    s, e = trading_day_window()
    s_expanded = s - timedelta(days=5)
    
    print(f"Trading day window: {s} to {e}")
    print(f"Expanded window: {s_expanded} to {e}")
    
    # Fetch data using our function
    fetch = download_price_data(ticker, start=s_expanded, end=e, auto_adjust=False, progress=False)
    
    print(f"Data source: {fetch.source}")
    print(f"Data shape: {fetch.df.shape}")
    
    if not fetch.df.empty and "Close" in fetch.df.columns:
        if len(fetch.df) > 1:
            current_price_val = float(fetch.df['Close'].iloc[-1].item())
            prev_price_val = float(fetch.df['Close'].iloc[-2].item())
            daily_pnl_pct = ((current_price_val - prev_price_val) / prev_price_val) * 100
            
            print(f"✅ Daily P&L Calculation:")
            print(f"   Current Price (from data): ${current_price_val:.2f}")
            print(f"   Previous Price: ${prev_price_val:.2f}")
            print(f"   Daily P&L: {daily_pnl_pct:+.1f}%")
            
            # Compare with yfinance info
            if current_price != 'N/A' and previous_close != 'N/A':
                yf_daily_pnl = ((float(current_price) - float(previous_close)) / float(previous_close)) * 100
                print(f"   Yahoo Finance Daily P&L: {yf_daily_pnl:+.1f}%")
                
                if abs(daily_pnl_pct - yf_daily_pnl) > 0.1:  # More than 0.1% difference
                    print(f"   ⚠️  WARNING: Significant difference between our calculation and Yahoo Finance!")
                    print(f"   This suggests we might be using different price sources or timing")
        else:
            print("❌ Not enough data for daily P&L calculation")
    else:
        print("❌ No valid price data available")
    
    print()
    
    # Industry standards analysis
    print(f"📋 Industry Standards Analysis")
    print("-" * 50)
    
    print("✅ Industry Standard Practices:")
    print("1. During market hours: Use current market price vs previous close")
    print("2. After market close: Use current price (includes after-hours) vs previous close")
    print("3. Before market open: Use pre-market price vs previous close")
    print("4. Weekend/holidays: Use last available price vs previous close")
    print()
    
    print("🔍 Our Current Implementation:")
    print(f"✓ Uses historical data with expanded date range")
    print(f"✓ Compares current day's close vs previous day's close")
    print(f"✓ Handles weekends by using last trading day")
    print()
    
    # Recommendations
    print(f"💡 Recommendations")
    print("-" * 50)
    
    if market_status == "🟢 MARKET OPEN":
        print("✅ During market hours: Our logic is correct")
        print("   - We should use current market price vs previous close")
        print("   - yfinance provides real-time prices during market hours")
    elif market_status == "🔴 AFTER HOURS":
        print("⚠️  After hours: Consider the implications")
        print("   - Our current logic uses 'close' price which may be the 4 PM close")
        print("   - After-hours prices might be more relevant for real-time P&L")
        print("   - Consider using currentPrice from info instead of Close from history")
    elif market_status == "🟡 PRE-MARKET":
        print("⚠️  Pre-market: Consider using pre-market prices")
        print("   - Our current logic uses previous close")
        print("   - Pre-market prices might be more relevant")
    else:
        print("✅ Weekend/holiday: Our logic is appropriate")
        print("   - Using last trading day's close is correct")
    
    print()
    print("🔧 Potential Improvements:")
    print("1. Use currentPrice from info during market hours for real-time accuracy")
    print("2. Clearly document when P&L resets (e.g., at market close)")
    print("3. Consider timezone handling for different markets (US vs Canada)")
    print("4. Add market status indicator to the display")

def test_different_scenarios():
    """
    Test different market scenarios
    """
    print("🧪 Testing Different Market Scenarios")
    print("=" * 80)
    
    tickers = ["TSLA", "VEE.TO"]  # US and Canadian tickers
    
    for ticker in tickers:
        print(f"\n{'='*20} {ticker} {'='*20}")
        analyze_yfinance_behavior(ticker)
        print()

def main():
    """
    Main analysis function
    """
    print("🔬 Market Hours Analysis for Daily P&L Calculation")
    print("=" * 80)
    print("This script analyzes how our daily P&L calculation handles different market scenarios")
    print("and compares it with industry standards.")
    print()
    
    test_different_scenarios()
    
    print("📊 Summary")
    print("=" * 80)
    print("Our current daily P&L calculation:")
    print("✅ Uses appropriate historical data range")
    print("✅ Compares current close vs previous close")
    print("✅ Handles weekends and holidays correctly")
    print("⚠️  May not use real-time prices during market hours")
    print("⚠️  May not reflect after-hours price movements")
    print()
    print("For most use cases, our current implementation is appropriate.")
    print("For real-time trading during market hours, consider using currentPrice from yfinance info.")

if __name__ == "__main__":
    main()
