#!/usr/bin/env python3
"""
Simple Data Migration Script
Migrate CSV data to Supabase without emojis
"""

import os
import sys
import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from decimal import Decimal

# Add the project root to the path
sys.path.append(str(Path(__file__).parent))

try:
    from web_dashboard.supabase_client import SupabaseClient
    print("OK: Supabase client imported successfully")
except ImportError as e:
    print(f"ERROR: Failed to import Supabase client: {e}")
    sys.exit(1)

def load_csv_data(data_directory: str):
    """Load CSV data from the specified directory."""
    print(f"Loading CSV data from: {data_directory}")
    
    data_dir = Path(data_directory)
    
    # Load portfolio data
    portfolio_file = data_dir / "llm_portfolio_update.csv"
    if not portfolio_file.exists():
        print(f"ERROR: Portfolio file not found: {portfolio_file}")
        return None, None, None
    
    try:
        portfolio_df = pd.read_csv(portfolio_file)
        print(f"OK: Loaded {len(portfolio_df)} portfolio records")
    except Exception as e:
        print(f"ERROR: Failed to load portfolio data: {e}")
        return None, None, None
    
    # Load trade log
    trade_log_file = data_dir / "llm_trade_log.csv"
    if not trade_log_file.exists():
        print(f"ERROR: Trade log file not found: {trade_log_file}")
        return None, None, None
    
    try:
        trade_log_df = pd.read_csv(trade_log_file)
        print(f"OK: Loaded {len(trade_log_df)} trade records")
    except Exception as e:
        print(f"ERROR: Failed to load trade log: {e}")
        return None, None, None
    
    # Load cash balances (if exists)
    cash_balances_file = data_dir / "cash_balances.json"
    cash_balances = {}
    if cash_balances_file.exists():
        try:
            with open(cash_balances_file, 'r') as f:
                cash_balances = json.load(f)
            print(f"OK: Loaded cash balances")
        except Exception as e:
            print(f"WARNING: Failed to load cash balances: {e}")
    else:
        print("WARNING: Cash balances file not found")
    
    return portfolio_df, trade_log_df, cash_balances

def migrate_portfolio_data(client, portfolio_df, fund_name="Project Chimera"):
    """Migrate portfolio data to Supabase."""
    print("Migrating portfolio data...")
    
    try:
        # Convert portfolio data to the expected format
        portfolio_records = []
        unique_tickers = set()
        ticker_currencies = {}
        
        for _, row in portfolio_df.iterrows():
            # Handle missing or NaN values
            ticker = str(row.get("Ticker", ""))
            currency = str(row.get("Currency", "USD"))

            # Skip records with missing essential data
            if not ticker or float(row.get("Shares", 0)) == 0:
                continue

            unique_tickers.add(ticker)
            if ticker not in ticker_currencies:
                ticker_currencies[ticker] = currency

            shares = float(row.get("Shares", 0))
            price = float(row.get("Current Price", 0))
            market_value = shares * price  # Calculate total_value
            record = {
                "fund": fund_name,
                "ticker": ticker,
                "company": str(row.get("Company", "")),
                "shares": shares,
                "price": price,
                "cost_basis": float(row.get("Cost Basis", 0)),
                "total_value": market_value,  # CRITICAL: Set total_value (was missing!)
                "pnl": float(row.get("PnL", 0)),
                "currency": currency,
                "date": datetime.now().isoformat(),
                "created_at": datetime.now().isoformat()
            }
            
            portfolio_records.append(record)
        
        # Ensure all tickers exist in securities table
        print(f"Verifying {len(unique_tickers)} tickers in securities table...")
        for ticker in unique_tickers:
            currency = ticker_currencies.get(ticker, "USD")
            try:
                client.ensure_ticker_in_securities(ticker, currency)
            except Exception as e:
                print(f"WARNING: Could not ensure ticker {ticker}: {e}")

        # Insert portfolio data
        if portfolio_records:
            result = client.supabase.table("portfolio_positions").upsert(portfolio_records).execute()
            print(f"OK: Inserted {len(portfolio_records)} portfolio records")
        else:
            print("WARNING: No valid portfolio records to insert")
            
    except Exception as e:
        print(f"ERROR: Failed to migrate portfolio data: {e}")
        return False
    
    return True

def migrate_trade_data(client, trade_log_df, fund_name="Project Chimera"):
    """Migrate trade log data to Supabase."""
    print("Migrating trade log data...")
    
    try:
        # Convert trade log data to the expected format
        trade_records = []
        unique_tickers = set()
        ticker_currencies = {}
        
        for _, row in trade_log_df.iterrows():
            # Handle missing or NaN values
            ticker = str(row.get("Ticker", ""))
            currency = str(row.get("Currency", "USD"))

            # Skip records with missing essential data
            if not ticker:
                continue

            unique_tickers.add(ticker)
            if ticker not in ticker_currencies:
                ticker_currencies[ticker] = currency

            record = {
                "fund": fund_name,
                "ticker": ticker,
                "reason": str(row.get("Action", "")),
                "shares": float(row.get("Shares", 0)),
                "price": float(row.get("Price", 0)),
                "cost_basis": float(row.get("Cost Basis", 0)),
                "pnl": float(row.get("P&L", 0)),
                "currency": currency,
                "date": str(row.get("Date", datetime.now().isoformat())),
                "created_at": datetime.now().isoformat()
            }
            
            trade_records.append(record)
        
        # Ensure all tickers exist in securities table
        print(f"Verifying {len(unique_tickers)} tickers in securities table...")
        for ticker in unique_tickers:
            currency = ticker_currencies.get(ticker, "USD")
            try:
                client.ensure_ticker_in_securities(ticker, currency)
            except Exception as e:
                print(f"WARNING: Could not ensure ticker {ticker}: {e}")

        # Insert trade data
        if trade_records:
            result = client.supabase.table("trade_log").upsert(trade_records).execute()
            print(f"OK: Inserted {len(trade_records)} trade records")
        else:
            print("WARNING: No valid trade records to insert")
            
    except Exception as e:
        print(f"ERROR: Failed to migrate trade data: {e}")
        return False
    
    return True

def migrate_cash_balances(client, cash_balances, fund_name="Project Chimera"):
    """Migrate cash balance data to Supabase."""
    print("Migrating cash balance data...")
    
    try:
        if not cash_balances:
            print("WARNING: No cash balance data to migrate")
            return True
        
        # Convert cash balances to the expected format
        cash_records = []
        
        for currency, balance in cash_balances.items():
            record = {
                "fund": fund_name,
                "currency": currency,
                "amount": float(balance),
                "updated_at": datetime.now().isoformat()
            }
            cash_records.append(record)
        
        # Insert cash balance data
        if cash_records:
            result = client.supabase.table("cash_balances").upsert(cash_records).execute()
            print(f"OK: Inserted {len(cash_records)} cash balance records")
        else:
            print("WARNING: No valid cash balance records to insert")
            
    except Exception as e:
        print(f"ERROR: Failed to migrate cash balance data: {e}")
        return False
    
    return True

def main():
    """Main migration function."""
    print("DATA MIGRATION SCRIPT")
    print("=" * 40)
    
    # Check environment variables
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_ANON_KEY")
    
    if not supabase_url or not supabase_key:
        print("ERROR: Supabase credentials not found")
        print("Please set SUPABASE_URL and SUPABASE_ANON_KEY environment variables")
        return False
    
    # Initialize Supabase client
    try:
        client = SupabaseClient()
        print("OK: Supabase client initialized")
    except Exception as e:
        print(f"ERROR: Failed to initialize Supabase client: {e}")
        return False
    
    # Load CSV data
    data_directory = "trading_data/funds/Project Chimera"
    portfolio_df, trade_log_df, cash_balances = load_csv_data(data_directory)
    
    if portfolio_df is None or trade_log_df is None:
        print("ERROR: Failed to load CSV data")
        return False
    
    # Migrate data
    success = True
    
    # Migrate portfolio data
    if not migrate_portfolio_data(client, portfolio_df):
        success = False
    
    # Migrate trade data
    if not migrate_trade_data(client, trade_log_df):
        success = False
    
    # Migrate cash balances
    if not migrate_cash_balances(client, cash_balances):
        success = False
    
    if success:
        print("=" * 40)
        print("MIGRATION COMPLETED SUCCESSFULLY")
        print("=" * 40)
    else:
        print("=" * 40)
        print("MIGRATION COMPLETED WITH ERRORS")
        print("=" * 40)
    
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
