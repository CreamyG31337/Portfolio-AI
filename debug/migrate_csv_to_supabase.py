#!/usr/bin/env python3
"""Migrate CSV data to Supabase with proper deduplication."""

import sys
import os
import pandas as pd
from datetime import datetime
from decimal import Decimal

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set environment variables
os.environ["SUPABASE_URL"] = "https://injqbxdqyxfvannygadt.supabase.co"
# Use environment variable instead of hardcoded key
    # # Use environment variable instead of hardcoded key
    # os.environ["SUPABASE_ANON_KEY"] = "your-key-here"  # REMOVED FOR SECURITY  # REMOVED FOR SECURITY

from supabase import create_client

def migrate_csv_to_supabase(fund_name="TEST", data_dir="trading_data/funds/TEST"):
    """Migrate CSV data to Supabase with proper structure."""
    print(f"🔄 Migrating {fund_name} data from CSV to Supabase...")
    
    # Initialize Supabase client
    supabase = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_ANON_KEY"]
    )
    
    # Clear existing data for this fund
    print("🧹 Clearing existing data...")
    result = supabase.table('portfolio_positions').delete().eq('fund', fund_name).execute()
    print(f"   Deleted {len(result.data)} existing portfolio positions")
    
    result = supabase.table('trade_log').delete().eq('fund', fund_name).execute()
    print(f"   Deleted {len(result.data)} existing trade log entries")
    
    # Load CSV data
    print("📊 Loading CSV data...")
    portfolio_file = os.path.join(data_dir, "llm_portfolio_update.csv")
    trade_file = os.path.join(data_dir, "llm_trade_log.csv")
    
    if not os.path.exists(portfolio_file):
        print(f"❌ Portfolio file not found: {portfolio_file}")
        return False
    
    if not os.path.exists(trade_file):
        print(f"❌ Trade log file not found: {trade_file}")
        return False
    
    # Load portfolio data
    portfolio_df = pd.read_csv(portfolio_file)
    print(f"   Loaded {len(portfolio_df)} portfolio records")
    
    # Load trade data
    trade_df = pd.read_csv(trade_file)
    print(f"   Loaded {len(trade_df)} trade records")
    
    # Migrate portfolio positions (only latest snapshot)
    print("📈 Migrating portfolio positions...")
    
    # Get the latest date for each ticker
    portfolio_df['Date'] = pd.to_datetime(portfolio_df['Date'])
    latest_positions = portfolio_df.loc[portfolio_df.groupby('Ticker')['Date'].idxmax()]
    
    print(f"   Found {len(latest_positions)} unique positions")
    
    # Convert to Supabase format
    portfolio_entries = []
    for _, row in latest_positions.iterrows():
        shares = float(row['Shares'])
        price = float(row['Current Price'])
        market_value = shares * price  # Calculate total_value
        entry = {
            'fund': fund_name,
            'ticker': row['Ticker'],
            'company': row.get('Company', ''),
            'shares': shares,
            'price': price,
            'cost_basis': float(row['Cost Basis']),
            'total_value': market_value,  # CRITICAL: Set total_value (was missing!)
            'pnl': float(row.get('PnL', 0)),
            'currency': row.get('Currency', 'USD'),
            'date': row['Date'].isoformat()
        }
        portfolio_entries.append(entry)
    
    # Insert portfolio positions
    if portfolio_entries:
        result = supabase.table('portfolio_positions').insert(portfolio_entries).execute()
        print(f"   ✅ Inserted {len(result.data)} portfolio positions")
    
    # Migrate trade log
    print("📝 Migrating trade log...")
    
    trade_entries = []
    for _, row in trade_df.iterrows():
        # Handle NaN values
        def safe_float(value, default=0):
            try:
                if pd.isna(value):
                    return default
                return float(value)
            except (ValueError, TypeError):
                return default
        
        entry = {
            'fund': fund_name,
            'date': pd.to_datetime(row['Date']).isoformat(),
            'ticker': row['Ticker'],
            'shares': safe_float(row['Shares']),
            'price': safe_float(row['Price']),
            'cost_basis': safe_float(row['Cost Basis']),
            'pnl': safe_float(row.get('PnL', 0)),
            'reason': str(row.get('Reason', '')),
            'currency': str(row.get('Currency', 'USD'))
        }
        trade_entries.append(entry)
    
    # Insert trade log
    if trade_entries:
        result = supabase.table('trade_log').insert(trade_entries).execute()
        print(f"   ✅ Inserted {len(result.data)} trade log entries")
    
    print(f"🎉 Migration completed for {fund_name}!")
    print(f"   Portfolio positions: {len(portfolio_entries)}")
    print(f"   Trade log entries: {len(trade_entries)}")
    
    return True

if __name__ == "__main__":
    migrate_csv_to_supabase()
