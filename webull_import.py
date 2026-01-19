#!/usr/bin/env python3
"""
Webull Import Command Line Interface

This script provides a command-line interface for importing Webull trade data
into the trading bot system.
"""

import argparse
import sys
from pathlib import Path

# Add the project root to the Python path
sys.path.insert(0, str(Path(__file__).parent))

from utils.webull_importer import import_webull_data
from display.console_output import print_success, print_error, print_warning, print_info, print_header
from utils.fund_manager import get_fund_manager


def main():
    """Main entry point for the Webull import script."""
    parser = argparse.ArgumentParser(
        description="Import Webull trade data into the trading bot system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview import without actually importing
  python webull_import.py webull_data.csv --dry-run
  
  # Import into specific fund
  python webull_import.py webull_data.csv --fund "RRSP Lance Webull"
  
  # Import into active fund
  python webull_import.py webull_data.csv
        """
    )
    
    parser.add_argument(
        "csv_file",
        help="Path to the Webull CSV file to import"
    )
    
    parser.add_argument(
        "--fund",
        help="Name of the fund to import into (default: active fund)"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the import without actually importing data"
    )
    
    parser.add_argument(
        "--list-funds",
        action="store_true",
        help="List available funds and exit"
    )
    
    args = parser.parse_args()
    
    # Handle list funds option
    if args.list_funds:
        list_available_funds()
        return
    
    # Validate CSV file exists
    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        print_error(f"CSV file not found: {csv_path}")
        sys.exit(1)
    
    # Show import information
    print_header("🚀 Webull Trade Data Import")
    print_info(f"CSV File: {csv_path}")
    print_info(f"Fund: {args.fund or 'Active Fund'}")
    print_info(f"Mode: {'Preview (Dry Run)' if args.dry_run else 'Import'}")
    print()
    
    # Perform the import
    try:
        results = import_webull_data(
            csv_file_path=str(csv_path),
            fund_name=args.fund,
            dry_run=args.dry_run
        )
        
        # Display results
        if results["success"]:
            print_success(f"✅ {results['message']}")
            
            if results.get("preview"):
                display_preview_results(results)
            else:
                display_import_results(results)
        else:
            print_error(f"❌ {results['message']}")
            sys.exit(1)
            
    except Exception as e:
        print_error(f"❌ Import failed: {e}")
        sys.exit(1)


def list_available_funds():
    """List all available funds."""
    print_header("📊 Available Funds")
    
    try:
        fund_manager = get_fund_manager()
        funds = fund_manager.get_available_funds()
        active_fund = fund_manager.get_active_fund()
        
        if not funds:
            print_warning("No funds available")
            return
        
        for i, fund_name in enumerate(funds, 1):
            status = " (ACTIVE)" if fund_name == active_fund else ""
            print(f"  [{i}] {fund_name}{status}")
        
        print()
        print_info(f"Active Fund: {active_fund or 'None'}")
        
    except Exception as e:
        print_error(f"Failed to list funds: {e}")


def display_preview_results(results: dict):
    """Display preview results."""
    print()
    print_header("📋 Import Preview")
    
    print_info(f"Trades to import: {results['trades_processed']}")
    print_info(f"Total value: ${results.get('total_value', 0):,.2f}")
    
    symbol_summary = results.get('symbol_summary', {})
    if symbol_summary:
        print()
        print("Symbol Summary:")
        print("-" * 60)
        print(f"{'Symbol':<10} {'Buy Qty':<10} {'Sell Qty':<10} {'Net Qty':<10} {'Value':<15}")
        print("-" * 60)
        
        for symbol, data in symbol_summary.items():
            net_qty = data['net_quantity']
            value = data['total_value']
            print(f"{symbol:<10} {data['Buy']:<10} {data['Sell']:<10} {net_qty:<10} ${value:<14,.2f}")
    
    print()
    print_warning("This is a preview. Use without --dry-run to actually import the data.")


def display_import_results(results: dict):
    """Display import results."""
    print()
    print_header("📊 Import Results")
    
    print_info(f"Trades processed: {results['trades_processed']}")
    print_info(f"Trades imported: {results['trades_imported']}")
    print_info(f"Trades skipped: {results['trades_skipped']}")
    print_info(f"Portfolio updates: {results['portfolio_updates']}")
    print_info(f"Trade log entries: {results['trade_log_entries']}")
    
    if results['trades_skipped'] > 0:
        print_warning(f"{results['trades_skipped']} trades were skipped due to errors")


if __name__ == "__main__":
    main()
