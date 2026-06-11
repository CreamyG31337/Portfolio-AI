#!/usr/bin/env python3
"""
Exchange Rates Migration Script
================================

Migrates exchange rates from CSV files to Supabase database.
Scans all fund directories for exchange_rates.csv files and loads them.

Usage:
    python migrate_exchange_rates.py [--dry-run] [--csv-path PATH]
"""

import os
import sys
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
from decimal import Decimal
import argparse
from dotenv import load_dotenv
import pytz

# Load environment variables
load_dotenv()

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from web_dashboard.supabase_client import SupabaseClient

class ExchangeRatesMigrator:
    """Handles migration of exchange rates from CSV to Supabase"""
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.client = None
        self.migration_stats = {
            'files_processed': 0,
            'files_successful': 0,
            'files_failed': 0,
            'total_rates': 0,
            'unique_rates': 0,
            'errors': []
        }
        self.seen_rates: Set[tuple] = set()  # Track (from_currency, to_currency, timestamp) tuples
        
    def initialize_client(self) -> bool:
        """Initialize Supabase client with service role for admin operations"""
        try:
            # Use service role for migration (bypasses RLS)
            self.client = SupabaseClient(use_service_role=True)
            if self.client.test_connection():
                print("[OK] Supabase connection successful")
                return True
            else:
                print("[ERROR] Supabase connection failed")
                return False
        except Exception as e:
            print(f"[ERROR] Failed to initialize Supabase client: {e}")
            return False
    
    def parse_csv_date(self, date_str: str) -> Optional[datetime]:
        """Parse CSV date string to datetime with timezone handling
        
        Handles formats like:
        - '2025-09-08 06:30:00 PDT'
        - '2025-09-08 06:30:00 PST'
        - ISO format timestamps
        """
        try:
            date_str = str(date_str).strip()
            
            # Handle PDT/PST timezone abbreviations
            if " PDT" in date_str:
                clean_timestamp = date_str.replace(" PDT", "")
                # Parse as naive datetime, then localize to PDT
                dt = datetime.strptime(clean_timestamp, "%Y-%m-%d %H:%M:%S")
                tz = pytz.timezone('America/Los_Angeles')
                # Check if DST applies (PDT = UTC-7, PST = UTC-8)
                # For simplicity, we'll use America/Los_Angeles which handles DST automatically
                dt = tz.localize(dt)
            elif " PST" in date_str:
                clean_timestamp = date_str.replace(" PST", "")
                dt = datetime.strptime(clean_timestamp, "%Y-%m-%d %H:%M:%S")
                tz = pytz.timezone('America/Los_Angeles')
                dt = tz.localize(dt)
            else:
                # Try parsing as ISO format or other standard formats
                dt = pd.to_datetime(date_str)
                if dt.tzinfo is None:
                    # Assume UTC if no timezone info
                    dt = dt.replace(tzinfo=timezone.utc)
            
            # Convert to UTC for storage
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc)
            else:
                dt = dt.replace(tzinfo=timezone.utc)
            
            return dt
        except Exception as e:
            print(f"  [WARNING] Could not parse date '{date_str}': {e}")
            return None
    
    def load_csv_file(self, csv_path: Path) -> Optional[pd.DataFrame]:
        """Load and parse exchange rates CSV file"""
        try:
            if not csv_path.exists():
                print(f"  [WARNING] File not found: {csv_path}")
                return None
            
            df = pd.read_csv(csv_path)
            
            # Validate required columns
            if 'Date' not in df.columns or 'USD_CAD_Rate' not in df.columns:
                print(f"  [ERROR] Invalid CSV format. Expected columns: Date, USD_CAD_Rate")
                return None
            
            # Parse dates
            df['parsed_date'] = df['Date'].apply(self.parse_csv_date)
            
            # Remove rows with invalid dates
            df = df[df['parsed_date'].notna()]
            
            # Convert rate to Decimal
            df['rate_decimal'] = df['USD_CAD_Rate'].apply(
                lambda x: Decimal(str(x)) if pd.notna(x) else None
            )
            
            # Remove rows with invalid rates
            df = df[df['rate_decimal'].notna()]
            
            print(f"  [INFO] Loaded {len(df)} valid exchange rate entries")
            return df
            
        except Exception as e:
            print(f"  [ERROR] Error loading CSV: {e}")
            self.migration_stats['errors'].append(f"{csv_path}: Load error - {e}")
            return None
    
    def prepare_rates_for_upsert(self, df: pd.DataFrame) -> List[Dict]:
        """Convert DataFrame to list of dictionaries for Supabase upsert"""
        rates = []
        
        # ⚡ Bolt: Replaced slow .iterrows() with .to_dict('records') for O(1) bulk conversion
        records = df.to_dict('records')
        for row in records:
            timestamp = row['parsed_date']
            rate = row['rate_decimal']
            
            # Create unique key for deduplication
            rate_key = ('USD', 'CAD', timestamp.isoformat())
            
            # Skip if we've already seen this rate in this migration run
            if rate_key in self.seen_rates:
                continue
            
            self.seen_rates.add(rate_key)
            
            rates.append({
                'from_currency': 'USD',
                'to_currency': 'CAD',
                'rate': float(rate),
                'timestamp': timestamp.isoformat()
            })
        
        return rates
    
    def migrate_csv_file(self, csv_path: Path) -> bool:
        """Migrate a single CSV file to Supabase"""
        print(f"\n[PROCESSING] {csv_path}")
        
        # Load CSV
        df = self.load_csv_file(csv_path)
        if df is None or df.empty:
            self.migration_stats['files_failed'] += 1
            return False
        
        # Prepare rates for upsert
        rates = self.prepare_rates_for_upsert(df)
        if not rates:
            print(f"  [WARNING] No new rates to migrate (all duplicates)")
            self.migration_stats['files_processed'] += 1
            return True
        
        print(f"  [INFO] Preparing to upsert {len(rates)} exchange rates...")
        
        if self.dry_run:
            print(f"  [DRY RUN] Would upsert {len(rates)} rates")
            for rate in rates[:5]:  # Show first 5 as sample
                print(f"     - {rate['timestamp']}: {rate['from_currency']}/{rate['to_currency']} = {rate['rate']}")
            if len(rates) > 5:
                print(f"     ... and {len(rates) - 5} more")
            self.migration_stats['total_rates'] += len(rates)
            self.migration_stats['unique_rates'] += len(rates)
            self.migration_stats['files_processed'] += 1
            self.migration_stats['files_successful'] += 1
            return True
        
        # Upsert to Supabase
        try:
            # Use bulk upsert - Supabase will handle duplicates via UNIQUE constraint
            result = self.client.supabase.table("exchange_rates").upsert(
                rates,
                on_conflict="from_currency,to_currency,timestamp"
            ).execute()
            
            print(f"  [OK] Successfully upserted {len(rates)} exchange rates")
            self.migration_stats['total_rates'] += len(rates)
            self.migration_stats['unique_rates'] += len(rates)
            self.migration_stats['files_processed'] += 1
            self.migration_stats['files_successful'] += 1
            return True
            
        except Exception as e:
            print(f"  [ERROR] Error upserting to Supabase: {e}")
            self.migration_stats['errors'].append(f"{csv_path}: Upsert error - {e}")
            self.migration_stats['files_failed'] += 1
            self.migration_stats['files_processed'] += 1
            return False
    
    def find_exchange_rate_csvs(self, base_path: Optional[Path] = None) -> List[Path]:
        """Find all exchange_rates.csv files in fund directories"""
        if base_path is None:
            # Default: scan trading_data/funds directory
            # Script is in web_dashboard/, so go up one level to project root
            project_root = Path(__file__).parent.parent
            base_path = project_root / "trading_data" / "funds"
        
        csv_files = []
        
        if base_path.is_file() and base_path.name == "exchange_rates.csv":
            # Single file provided
            csv_files.append(base_path)
        elif base_path.is_dir():
            # Scan directory for exchange_rates.csv files
            for fund_dir in base_path.iterdir():
                if fund_dir.is_dir():
                    csv_file = fund_dir / "exchange_rates.csv"
                    if csv_file.exists():
                        csv_files.append(csv_file)
        elif base_path.exists():
            # Single CSV file path provided
            csv_files.append(base_path)
        
        return sorted(csv_files)
    
    def migrate_all(self, csv_path: Optional[Path] = None) -> bool:
        """Migrate all found CSV files"""
        print("=" * 60)
        print("EXCHANGE RATES MIGRATION")
        print("=" * 60)
        
        if self.dry_run:
            print("[DRY RUN] DRY RUN MODE - No changes will be made")
        print()
        
        # Initialize client
        if not self.initialize_client():
            return False
        
        # Find CSV files
        csv_files = self.find_exchange_rate_csvs(csv_path)
        
        if not csv_files:
            print("[ERROR] No exchange_rates.csv files found")
            if csv_path:
                print(f"   Searched: {csv_path}")
            else:
                print("   Searched: trading_data/funds/*/exchange_rates.csv")
            return False
        
        print(f"[INFO] Found {len(csv_files)} exchange_rates.csv file(s)")
        print()
        
        # Migrate each file
        for csv_file in csv_files:
            self.migrate_csv_file(csv_file)
        
        # Print summary
        self.print_summary()
        
        return self.migration_stats['files_failed'] == 0
    
    def print_summary(self):
        """Print migration summary"""
        print("\n" + "=" * 60)
        print("MIGRATION SUMMARY")
        print("=" * 60)
        print(f"Files processed: {self.migration_stats['files_processed']}")
        print(f"Files successful: {self.migration_stats['files_successful']}")
        print(f"Files failed: {self.migration_stats['files_failed']}")
        print(f"Total rates processed: {self.migration_stats['total_rates']}")
        print(f"Unique rates: {self.migration_stats['unique_rates']}")
        
        if self.migration_stats['errors']:
            print(f"\n[ERROR] Errors ({len(self.migration_stats['errors'])}):")
            for error in self.migration_stats['errors'][:10]:  # Show first 10
                print(f"   - {error}")
            if len(self.migration_stats['errors']) > 10:
                print(f"   ... and {len(self.migration_stats['errors']) - 10} more")
        else:
            print("\n[OK] No errors!")
        print("=" * 60)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Migrate exchange rates from CSV to Supabase"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run mode - show what would be migrated without making changes"
    )
    parser.add_argument(
        "--csv-path",
        type=str,
        help="Specific CSV file path or directory to scan (default: trading_data/funds)"
    )
    
    args = parser.parse_args()
    
    csv_path = None
    if args.csv_path:
        csv_path = Path(args.csv_path)
        if not csv_path.exists():
            print(f"[ERROR] Path not found: {csv_path}")
            return 1
    
    migrator = ExchangeRatesMigrator(dry_run=args.dry_run)
    success = migrator.migrate_all(csv_path)
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

