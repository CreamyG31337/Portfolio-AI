#!/usr/bin/env python3
"""
Simple Migration Script
Works with the single supabase_setup.sql file
"""

import os
import sys
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from supabase_client import SupabaseClient
from typing import Dict, List, Any

def discover_funds(base_dir: str = "../trading_data/funds") -> List[str]:
    """Discover all available fund directories."""
    funds_path = Path(base_dir)
    if not funds_path.exists():
        print(f"❌ Funds directory not found: {base_dir}")
        return []

    funds = []
    for fund_dir in funds_path.iterdir():
        if fund_dir.is_dir() and not fund_dir.name.startswith('.'):
            portfolio_file = fund_dir / "llm_portfolio_update.csv"
            if portfolio_file.exists():
                funds.append(fund_dir.name)
                print(f"  ✅ {fund_dir.name}")
            else:
                print(f"  ⚠️  {fund_dir.name} (no portfolio data)")

    return funds

def load_fund_data(fund_name: str, base_dir: str = "../trading_data/funds") -> Dict[str, pd.DataFrame]:
    """Load CSV data for a specific fund."""
    fund_path = Path(base_dir) / fund_name
    data = {}

    # Load portfolio data
    portfolio_file = fund_path / "llm_portfolio_update.csv"
    if portfolio_file.exists():
        df = pd.read_csv(portfolio_file)
        if not df.empty:
            df['Date'] = pd.to_datetime(df['Date'], format='mixed', utc=True)
            data['portfolio'] = df

    # Load trade log
    trades_file = fund_path / "llm_trade_log.csv"
    if trades_file.exists():
        df = pd.read_csv(trades_file)
        if not df.empty:
            df['Date'] = pd.to_datetime(df['Date'], format='mixed', utc=True)
            data['trades'] = df

    # Load cash balances
    cash_file = fund_path / "llm_cash_balances.csv"
    if cash_file.exists():
        df = pd.read_csv(cash_file)
        if not df.empty:
            data['cash'] = df

    return data

def infer_currency_from_ticker(ticker: str) -> str:
    """Infer currency from ticker symbol.
    
    Common patterns:
    - Tickers ending in .TO are Canadian (CAD)
    - Otherwise default to USD
    """
    if ticker.endswith('.TO'):
        return 'CAD'
    return 'USD'

def migrate_fund(client: SupabaseClient, fund_name: str, fund_data: Dict[str, pd.DataFrame]) -> bool:
    """Migrate a single fund's data."""
    print(f"\n📊 Migrating {fund_name}...")
    success = True

    # Migrate portfolio positions
    if 'portfolio' in fund_data:
        df = fund_data['portfolio']
        print(f"  📈 Portfolio: {len(df)} positions")

        positions = []
        for _, row in df.iterrows():
            positions.append({
                "fund": fund_name,  # Add fund name!
                "ticker": str(row["Ticker"]),  # Clean ticker name!
                "company": str(row["Company"]),
                "shares": float(row["Shares"]),
                "price": float(row["Current Price"]),
                "cost_basis": float(row["Cost Basis"]),
                "pnl": float(row["PnL"]),
                "date": row["Date"].isoformat()
            })

        try:
            # Ensure all tickers exist in securities table before inserting
            unique_tickers = set(pos['ticker'] for pos in positions)
            for ticker in unique_tickers:
                currency = infer_currency_from_ticker(ticker)
                try:
                    client.ensure_ticker_in_securities(ticker, currency)
                except Exception as e:
                    print(f"    ⚠️  Warning: Could not ensure ticker {ticker} in securities: {e}")
            
            result = client.supabase.table("portfolio_positions").upsert(positions).execute()
            print(f"    ✅ {len(positions)} positions uploaded")
        except Exception as e:
            print(f"    ❌ Portfolio error: {e}")
            success = False

    # Migrate trades
    if 'trades' in fund_data:
        df = fund_data['trades']
        print(f"  📊 Trades: {len(df)} entries")

        trades = []
        for _, row in df.iterrows():
            trades.append({
                "fund": fund_name,  # Add fund name!
                "date": row["Date"].isoformat(),
                "ticker": str(row["Ticker"]),  # Clean ticker name!
                "shares": float(row["Shares"]),
                "price": float(row["Price"]),
                "cost_basis": float(row["Cost Basis"]),
                "pnl": float(row["PnL"]),
                "reason": str(row["Reason"])
            })

        try:
            # Ensure all tickers exist in securities table before inserting
            unique_tickers = set(trade['ticker'] for trade in trades)
            for ticker in unique_tickers:
                currency = infer_currency_from_ticker(ticker)
                try:
                    client.ensure_ticker_in_securities(ticker, currency)
                except Exception as e:
                    print(f"    ⚠️  Warning: Could not ensure ticker {ticker} in securities: {e}")
            
            result = client.supabase.table("trade_log").upsert(trades).execute()
            print(f"    ✅ {len(trades)} trades uploaded")
        except Exception as e:
            print(f"    ❌ Trades error: {e}")
            success = False

    # Migrate cash balances
    if 'cash' in fund_data:
        df = fund_data['cash']
        print(f"  💰 Cash: {len(df)} balances")

        for _, row in df.iterrows():
            try:
                result = client.supabase.table("cash_balances").upsert({
                    "fund": fund_name,  # Add fund name!
                    "currency": str(row["Currency"]),
                    "amount": float(row["Amount"])
                }).execute()
                print(f"    ✅ {fund_name} {row['Currency']}: ${row['Amount']}")
            except Exception as e:
                print(f"    ❌ Cash error for {fund_name} {row['Currency']}: {e}")
                success = False

    return success

def main():
    print("🧹 MIGRATION SCRIPT")
    print("=" * 50)
    print("This script works with the single supabase_setup.sql file")
    print("1. Make sure you've run supabase_setup.sql in Supabase SQL Editor")
    print("2. Then run this script to migrate your data")
    print("=" * 50)

    # Initialize Supabase client
    try:
        client = SupabaseClient()
        print("✅ Connected to Supabase")
    except Exception as e:
        print(f"❌ Failed to connect to Supabase: {e}")
        return 1

    # Discover funds
    print("\n🔍 Discovering funds...")
    funds = discover_funds()
    print(f"📊 Found {len(funds)} funds with data")

    if not funds:
        print("❌ No funds found!")
        return 1

    # Migrate each fund
    print("\n📦 Migrating funds with clean ticker names...")
    all_success = True

    for fund_name in funds:
        fund_data = load_fund_data(fund_name)
        if fund_data:
            success = migrate_fund(client, fund_name, fund_data)
            all_success = all_success and success
        else:
            print(f"⚠️  No data found for {fund_name}")

    # Test the migration
    print("\n🧪 Testing migration...")
    try:
        # Test portfolio data
        portfolio_result = client.supabase.table("portfolio_positions").select("ticker, shares, price").limit(10).execute()
        portfolio_data = portfolio_result.data
        print(f"✅ Portfolio data: {len(portfolio_data)} entries")

        if portfolio_data:
            for pos in portfolio_data[:5]:  # Show first 5
                print(f"  - {pos['ticker']}: {pos['shares']} shares @ ${pos['price']}")

        # Test trade data
        trades_result = client.supabase.table("trade_log").select("ticker, shares").limit(10).execute()
        trades_data = trades_result.data
        print(f"✅ Trade data: {len(trades_data)} entries")

        # Test cash data
        cash_result = client.supabase.table("cash_balances").select("currency, amount").execute()
        cash_data = cash_result.data
        print(f"✅ Cash data: {len(cash_data)} entries")

        if cash_data:
            for cash in cash_data:
                print(f"  - {cash['currency']}: ${cash['amount']}")

    except Exception as e:
        print(f"❌ Test error: {e}")
        all_success = False

    if all_success:
        print("\n✅ MIGRATION SUCCESSFUL!")
        print("🎉 Ticker names are now clean (no more abbreviations)!")
        print("\n🔗 Your dashboard URL:")
        print("https://webdashboard-1xib588tm-creamyg31337s-projects.vercel.app")
        return 0
    else:
        print("\n❌ Migration completed with errors")
        return 1

if __name__ == "__main__":
    sys.exit(main())
