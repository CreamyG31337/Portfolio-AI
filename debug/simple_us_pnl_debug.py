#!/usr/bin/env python3
"""
Simple debug script to check US stock P&L issues by examining the CSV data directly
"""

import pandas as pd
from datetime import datetime

def main():
    print("=== Simple US Stock P&L Debug ===")
    
    # Load portfolio data
    df = pd.read_csv("trading_data/funds/TEST/llm_portfolio_update.csv")
    print(f"Portfolio data loaded: {len(df)} rows")
    
    # Convert Date column to datetime
    df['Date'] = pd.to_datetime(df['Date'])
    df['Date_Only'] = df['Date'].dt.date
    
    # Get unique tickers
    tickers = df['Ticker'].unique()
    print(f"Found {len(tickers)} unique tickers: {sorted(tickers)}")
    
    # Identify US stocks (those without .TO, .V, or .CN suffixes)
    us_stocks = [t for t in tickers if not t.endswith(('.TO', '.V', '.CN'))]
    print(f"US stocks: {us_stocks}")
    
    # Check data for each US stock
    for ticker in us_stocks:
        print(f"\n--- {ticker} ---")
        ticker_data = df[df['Ticker'] == ticker].sort_values('Date')
        print(f"  Rows: {len(ticker_data)}")
        
        if len(ticker_data) > 0:
            print(f"  Date range: {ticker_data['Date_Only'].min()} to {ticker_data['Date_Only'].max()}")
            print(f"  Latest price: ${ticker_data.iloc[-1]['Current Price']}")
            print(f"  Latest shares: {ticker_data.iloc[-1]['Shares']}")
            
            # Check if there are multiple days of data
            unique_dates = ticker_data['Date_Only'].nunique()
            print(f"  Unique dates: {unique_dates}")
            
            if unique_dates > 1:
                # Show last 3 entries
                print("  Last 3 entries:")
                for _, row in ticker_data.tail(3).iterrows():
                    print(f"    {row['Date_Only']}: ${row['Current Price']} (shares: {row['Shares']})")
            else:
                print("  Only one day of data - this explains why P&L is $0.00")

if __name__ == "__main__":
    main()
