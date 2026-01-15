#!/usr/bin/env python3
"""
Comprehensive Fund Migration Script
===================================

Migrates all CSV fund data to Supabase database.
This will enable full Supabase mode for the web dashboard.

Usage:
    python migrate_all_funds.py [--dry-run] [--fund FUND_NAME]
"""

import os
import sys
import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import argparse
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from supabase_client import SupabaseClient

class FundMigrator:
    """Handles migration of fund data from CSV to Supabase"""
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.client = None
        self.migration_stats = {
            'funds_processed': 0,
            'funds_successful': 0,
            'funds_failed': 0,
            'total_positions': 0,
            'total_trades': 0,
            'errors': []
        }
        
    def initialize_client(self) -> bool:
        """Initialize Supabase client"""
        try:
            self.client = SupabaseClient()
            if self.client.test_connection():
                print("✅ Supabase connection successful")
                return True
            else:
                print("❌ Supabase connection failed")
                return False
        except Exception as e:
            print(f"❌ Failed to initialize Supabase client: {e}")
            return False
    
    def get_available_csv_funds(self) -> List[str]:
        """Get list of available CSV fund directories"""
        funds_dir = Path("../trading_data/funds")
        if not funds_dir.exists():
            return []
        
        funds = []
        for fund_dir in funds_dir.iterdir():
            if fund_dir.is_dir():
                # Check if required files exist
                portfolio_file = fund_dir / "llm_portfolio_update.csv"
                trade_file = fund_dir / "llm_trade_log.csv"
                if portfolio_file.exists() and trade_file.exists():
                    funds.append(fund_dir.name)
                    
        return sorted(funds)
    
    def load_fund_data(self, fund_name: str) -> Dict:
        """Load CSV data for a specific fund"""
        fund_dir = Path(f"../trading_data/funds/{fund_name}")
        
        print(f"📁 Loading data from: {fund_dir}")
        
        data = {
            'portfolio': pd.DataFrame(),
            'trades': pd.DataFrame(),
            'cash_balances': {}
        }
        
        # Load portfolio data
        portfolio_file = fund_dir / "llm_portfolio_update.csv"
        if portfolio_file.exists():
            try:
                data['portfolio'] = pd.read_csv(portfolio_file)
                # Get only current positions (shares > 0)
                data['portfolio'] = data['portfolio'][data['portfolio']['Shares'] > 0]
                print(f"  📊 Portfolio: {len(data['portfolio'])} current positions")
            except Exception as e:
                print(f"  ❌ Error loading portfolio: {e}")
                self.migration_stats['errors'].append(f"{fund_name}: Portfolio load error - {e}")
        
        # Load trade log
        trade_file = fund_dir / "llm_trade_log.csv"
        if trade_file.exists():
            try:
                data['trades'] = pd.read_csv(trade_file)
                print(f"  📈 Trades: {len(data['trades'])} records")
            except Exception as e:
                print(f"  ❌ Error loading trades: {e}")
                self.migration_stats['errors'].append(f"{fund_name}: Trade log load error - {e}")
        
        # Load cash balances
        cash_file = fund_dir / "cash_balances.json"
        if cash_file.exists():
            try:
                with open(cash_file, 'r') as f:
                    data['cash_balances'] = json.load(f)
                print(f"  💰 Cash balances: {len(data['cash_balances'])} currencies")
            except Exception as e:
                print(f"  ❌ Error loading cash balances: {e}")
                self.migration_stats['errors'].append(f"{fund_name}: Cash balances load error - {e}")
        
        return data
    
    def migrate_portfolio_positions(self, fund_name: str, portfolio_df: pd.DataFrame) -> bool:
        """Migrate portfolio positions to Supabase"""
        if portfolio_df.empty:
            print("  ⚠️  No portfolio positions to migrate")
            return True
            
        try:
            # Convert DataFrame to Supabase format
            positions = []
            for _, row in portfolio_df.iterrows():
                position = {
                    "fund": fund_name,
                    "ticker": str(row.get("Ticker", "")),
                    "company": str(row.get("Company", "")),
                    "shares": float(row.get("Shares", 0)),
                    "price": float(row.get("Price", row.get("Current Price", 0))),
                    "cost_basis": float(row.get("Cost Basis", 0)),
                    "pnl": float(row.get("PnL", 0)),
                    "currency": str(row.get("Currency", "USD")),
                    "date": datetime.now().isoformat(),
                    "created_at": datetime.now().isoformat()
                }
                
                # Skip invalid positions
                if not position["ticker"] or position["shares"] <= 0:
                    continue
                    
                positions.append(position)
            
            if not positions:
                print("  ⚠️  No valid portfolio positions to migrate")
                return True
            
            if not self.dry_run:
                # Ensure all tickers exist in securities table before inserting
                unique_tickers = set(pos['ticker'] for pos in positions)
                for ticker in unique_tickers:
                    # Get currency for this ticker from positions
                    ticker_positions = [p for p in positions if p['ticker'] == ticker]
                    currency = ticker_positions[0].get('currency', 'USD') if ticker_positions else 'USD'
                    try:
                        self.client.ensure_ticker_in_securities(ticker, currency)
                    except Exception as e:
                        print(f"  ⚠️  Warning: Could not ensure ticker {ticker} in securities: {e}")
                
                # Delete existing positions for this fund first
                delete_result = self.client.supabase.table("portfolio_positions").delete().eq("fund", fund_name).execute()
                print(f"  🗑️  Deleted {len(delete_result.data) if delete_result.data else 0} existing positions")
                
                # Insert new positions
                result = self.client.supabase.table("portfolio_positions").insert(positions).execute()
                print(f"  ✅ Migrated {len(positions)} portfolio positions")
            else:
                print(f"  🔍 [DRY RUN] Would migrate {len(positions)} portfolio positions")
            
            self.migration_stats['total_positions'] += len(positions)
            return True
            
        except Exception as e:
            print(f"  ❌ Error migrating portfolio positions: {e}")
            self.migration_stats['errors'].append(f"{fund_name}: Portfolio migration error - {e}")
            return False
    
    def migrate_trade_log(self, fund_name: str, trades_df: pd.DataFrame) -> bool:
        """Migrate trade log to Supabase"""
        if trades_df.empty:
            print("  ⚠️  No trades to migrate")
            return True
            
        try:
            # Convert DataFrame to Supabase format
            trades = []
            for _, row in trades_df.iterrows():
                trade = {
                    "fund": fund_name,
                    "ticker": str(row.get("Ticker", "")),
                    "reason": str(row.get("Action", row.get("Reason", ""))),
                    "shares": float(row.get("Shares", 0)),
                    "price": float(row.get("Price", 0)),
                    "cost_basis": float(row.get("Cost Basis", 0)),
                    "pnl": float(row.get("PnL", row.get("P&L", 0))),
                    "currency": str(row.get("Currency", "USD")),
                    "date": str(row.get("Date", datetime.now().isoformat())),
                    "created_at": datetime.now().isoformat()
                }
                
                # Skip invalid trades
                if not trade["ticker"]:
                    continue
                    
                trades.append(trade)
            
            if not trades:
                print("  ⚠️  No valid trades to migrate")
                return True
            
            if not self.dry_run:
                # Ensure all tickers exist in securities table before inserting
                unique_tickers = set(trade['ticker'] for trade in trades)
                for ticker in unique_tickers:
                    # Get currency for this ticker from trades
                    ticker_trades = [t for t in trades if t['ticker'] == ticker]
                    currency = ticker_trades[0].get('currency', 'USD') if ticker_trades else 'USD'
                    try:
                        self.client.ensure_ticker_in_securities(ticker, currency)
                    except Exception as e:
                        print(f"  ⚠️  Warning: Could not ensure ticker {ticker} in securities: {e}")
                
                # Delete existing trades for this fund first
                delete_result = self.client.supabase.table("trade_log").delete().eq("fund", fund_name).execute()
                print(f"  🗑️  Deleted {len(delete_result.data) if delete_result.data else 0} existing trades")
                
                # Insert new trades
                result = self.client.supabase.table("trade_log").insert(trades).execute()
                print(f"  ✅ Migrated {len(trades)} trade records")
            else:
                print(f"  🔍 [DRY RUN] Would migrate {len(trades)} trade records")
            
            self.migration_stats['total_trades'] += len(trades)
            return True
            
        except Exception as e:
            print(f"  ❌ Error migrating trade log: {e}")
            self.migration_stats['errors'].append(f"{fund_name}: Trade log migration error - {e}")
            return False
    
    def migrate_cash_balances(self, fund_name: str, cash_balances: Dict) -> bool:
        """Migrate cash balances to Supabase"""
        if not cash_balances:
            print("  ⚠️  No cash balances to migrate")
            return True
            
        try:
            # Convert to Supabase format
            balances = []
            for currency, amount in cash_balances.items():
                balance = {
                    "fund": fund_name,
                    "currency": currency,
                    "amount": float(amount),
                    "updated_at": datetime.now().isoformat()
                }
                balances.append(balance)
            
            if not self.dry_run:
                # Delete existing balances for this fund first
                delete_result = self.client.supabase.table("cash_balances").delete().eq("fund", fund_name).execute()
                print(f"  🗑️  Deleted {len(delete_result.data) if delete_result.data else 0} existing cash balances")
                
                # Insert new balances
                result = self.client.supabase.table("cash_balances").insert(balances).execute()
                print(f"  ✅ Migrated {len(balances)} cash balance records")
            else:
                print(f"  🔍 [DRY RUN] Would migrate {len(balances)} cash balance records")
            
            return True
            
        except Exception as e:
            print(f"  ❌ Error migrating cash balances: {e}")
            self.migration_stats['errors'].append(f"{fund_name}: Cash balances migration error - {e}")
            return False
    
    def migrate_fund(self, fund_name: str) -> bool:
        """Migrate a single fund to Supabase"""
        print(f"\n🏦 Migrating Fund: {fund_name}")
        print("=" * 50)
        
        self.migration_stats['funds_processed'] += 1
        
        # Load fund data
        data = self.load_fund_data(fund_name)
        
        if data['portfolio'].empty and data['trades'].empty:
            print(f"  ⚠️  No data found for {fund_name}")
            return False
        
        # Migrate each component
        success = True
        
        # Portfolio positions
        if not self.migrate_portfolio_positions(fund_name, data['portfolio']):
            success = False
        
        # Trade log
        if not self.migrate_trade_log(fund_name, data['trades']):
            success = False
        
        # Cash balances
        if not self.migrate_cash_balances(fund_name, data['cash_balances']):
            success = False
        
        if success:
            print(f"  🎉 Successfully migrated {fund_name}")
            self.migration_stats['funds_successful'] += 1
        else:
            print(f"  ❌ Migration failed for {fund_name}")
            self.migration_stats['funds_failed'] += 1
        
        return success
    
    def print_migration_summary(self):
        """Print migration summary"""
        print("\n" + "=" * 60)
        print("📊 MIGRATION SUMMARY")
        print("=" * 60)
        
        stats = self.migration_stats
        print(f"Funds processed: {stats['funds_processed']}")
        print(f"Funds successful: {stats['funds_successful']} ✅")
        print(f"Funds failed: {stats['funds_failed']} ❌")
        print(f"Total positions migrated: {stats['total_positions']}")
        print(f"Total trades migrated: {stats['total_trades']}")
        
        if stats['errors']:
            print(f"\nErrors ({len(stats['errors'])}):")
            for error in stats['errors'][:10]:  # Show first 10 errors
                print(f"  • {error}")
            if len(stats['errors']) > 10:
                print(f"  ... and {len(stats['errors']) - 10} more errors")
        
        success_rate = (stats['funds_successful'] / stats['funds_processed'] * 100) if stats['funds_processed'] > 0 else 0
        print(f"\nSuccess Rate: {success_rate:.1f}%")
        
        if stats['funds_successful'] == stats['funds_processed']:
            print("🎉 ALL FUNDS MIGRATED SUCCESSFULLY!")
        elif stats['funds_successful'] > 0:
            print("⚠️  PARTIAL SUCCESS - Some funds migrated")
        else:
            print("❌ MIGRATION FAILED - No funds migrated")

def main():
    """Main migration function"""
    parser = argparse.ArgumentParser(description="Migrate CSV funds to Supabase")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be migrated without actually doing it")
    parser.add_argument("--fund", type=str, help="Migrate only a specific fund")
    
    args = parser.parse_args()
    
    print("🚀 Fund Migration to Supabase")
    print("=" * 40)
    
    if args.dry_run:
        print("🔍 DRY RUN MODE - No actual changes will be made")
    
    # Initialize migrator
    migrator = FundMigrator(dry_run=args.dry_run)
    
    # Initialize Supabase connection
    if not migrator.initialize_client():
        print("❌ Cannot proceed without Supabase connection")
        return 1
    
    # Get available funds
    available_funds = migrator.get_available_csv_funds()
    if not available_funds:
        print("❌ No CSV funds found to migrate")
        return 1
    
    print(f"📂 Found {len(available_funds)} CSV funds: {', '.join(available_funds)}")
    
    # Filter to specific fund if requested
    if args.fund:
        if args.fund not in available_funds:
            print(f"❌ Fund '{args.fund}' not found")
            return 1
        available_funds = [args.fund]
        print(f"🎯 Migrating only: {args.fund}")
    
    # Confirm migration
    if not args.dry_run:
        print(f"\n⚠️  This will REPLACE existing data in Supabase for {len(available_funds)} fund(s)")
        confirmation = input("Continue? (yes/no): ").strip().lower()
        if confirmation not in ['yes', 'y']:
            print("Migration cancelled")
            return 0
    
    # Migrate each fund
    for fund_name in available_funds:
        migrator.migrate_fund(fund_name)
    
    # Print summary
    migrator.print_migration_summary()
    
    return 0 if migrator.migration_stats['funds_failed'] == 0 else 1

if __name__ == "__main__":
    sys.exit(main())