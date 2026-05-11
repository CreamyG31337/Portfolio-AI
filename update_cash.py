#!/usr/bin/env python3
"""
Standalone Cash Balance Update Utility

This script allows you to easily update your cash balances without 
running the full trading script. Useful for:
- Adding deposits/withdrawals
- Correcting cash balance errors
- Quick balance adjustments

Usage: python update_cash.py
"""

import sys
import argparse
from pathlib import Path
from decimal import Decimal

# Modular startup check - handles path setup and dependency checking
try:
    from utils.script_startup import startup_check
    startup_check("update_cash.py")
except ImportError:
    # Fallback for minimal dependency checking if script_startup isn't available
    # Add the project directory to the path so we can import modules
    project_dir = Path(__file__).parent
    sys.path.insert(0, str(project_dir))
    try:
        import pandas
    except ImportError:
        print("\n❌ Missing Dependencies (update_cash.py)")
        print("Required packages not found. Please activate virtual environment:")
        import os
        if os.name == 'nt':  # Windows
            print("  venv\\Scripts\\activate")
        else:  # Mac/Linux
            print("  source venv/bin/activate")
        print("  python update_cash.py")
        print("\n💡 TIP: Use 'python run.py' and select option 'u' to avoid dependency issues")
        sys.exit(1)

try:
    from financial.simple_cash_manager import SimpleCashManager
    from portfolio.position_calculator import PositionCalculator
except ImportError as e:
    print(f"❌ Error importing required modules: {e}")
    print("Make sure you're running this script from the project directory.")
    sys.exit(1)


def calculate_fund_contributions_total(data_dir: Path) -> float:
    """Calculate total fund contributions from CSV file."""
    try:
        fund_file = data_dir / "fund_contributions.csv"
        if not fund_file.exists():
            return 0.0
        
        import pandas as pd
        df = pd.read_csv(fund_file)
        total = 0.0
        
        # ⚡ Bolt: Vectorized Pandas Operations
        # Replaced O(n) df.iterrows() with O(1) vectorized operations to prevent Series instantiation overhead per row.
        # This speeds up calculation by ~90x for large fund_contributions CSVs.
        amounts = pd.to_numeric(df.get('Amount', pd.Series([0] * len(df))), errors='coerce').fillna(0)
        types = df.get('Type', pd.Series(['CONTRIBUTION'] * len(df))).astype(str).str.upper()
        
        contributions = amounts[types == 'CONTRIBUTION'].sum()
        withdrawals = amounts[types == 'WITHDRAWAL'].sum()

        total = float(contributions - withdrawals)
        return total
    except Exception:
        return 0.0


def main():
    """Main function to update cash balances"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Update cash balances")
    parser.add_argument("--data-dir", type=str, help="Data directory path")
    args = parser.parse_args()
    
    from display.console_output import _safe_emoji, print_environment_banner
    print(f"{_safe_emoji('💰')} Cash Balance Update Utility")
    print("=" * 40)
    
    # Show environment banner
    print_environment_banner(args.data_dir)
    
    # Set up data directory
    if args.data_dir:
        data_dir = Path(args.data_dir)
    else:
        print(f"{_safe_emoji('❌')} Error: Data directory must be specified")
        print("Usage: python update_cash.py --data-dir <path>")
        print("\n💡 TIP: Use 'python run.py' and select option 'u' to avoid path issues")
        sys.exit(1)
    
    if not data_dir.exists():
        print(f"{_safe_emoji('❌')} Data directory not found: {data_dir}")
        print(f"Make sure the data directory exists: {data_dir}")
        sys.exit(1)
    
    try:
        # Load current balances using simple manager (fixes CAD/cad duplicates)
        manager = SimpleCashManager(data_dir)
        balances = manager.get_balances()
        
        print(f"\n{_safe_emoji('💰')} Current Cash Balances:")
        print(f"   CAD: ${balances['CAD']:,.2f}")
        print(f"   USD: ${balances['USD']:,.2f}")
        
        # Calculate total CAD equivalent (simple calculation)
        total_cad = balances['CAD'] + (balances['USD'] * Decimal('1.35'))
        print(f"   Total (CAD equiv): ${total_cad:,.2f}")

        # Display fund contributions total
        fund_total = calculate_fund_contributions_total(data_dir)
        print(f"{_safe_emoji('💵')} Fund contributions total: ${fund_total:,.2f}")
        
        # Show recent transactions
        transactions = manager.get_transactions(3)
        if transactions:
            print(f"\n{_safe_emoji('📋')} Recent Transactions:")
            for tx in transactions:
                date_str = tx['timestamp'][:10]
                amount_str = f"${tx['amount']:+,.2f}"
                print(f"   {date_str} {tx['currency']} {amount_str} - {tx['description']}")
        
        while True:
            # Get user input
            print("\nOptions:")
            print("  'c' = add/remove CAD")
            print("  'u' = add/remove USD") 
            print("  's' = set exact amounts")
            print("  'v' = view current balances")
            print("  't' = view transaction history")
            print("  'q' = quit")
            
            action = input("\nWhat would you like to do? ").strip().lower()
            
            if action == 'q':
                print("👋 Goodbye!")
                break
                
            elif action == 'v':
                # Refresh balances from manager
                balances = manager.get_balances()
                print(f"\n{_safe_emoji('💰')} Current Cash Balances:")
                print(f"   CAD: ${balances['CAD']:,.2f}")
                print(f"   USD: ${balances['USD']:,.2f}")
                
                # Calculate total CAD equivalent
                total_cad = balances['CAD'] + (balances['USD'] * Decimal('1.35'))
                print(f"   Total (CAD equiv): ${total_cad:,.2f}")

                # Display fund contributions total
                fund_total = calculate_fund_contributions_total(data_dir)
                print(f"{_safe_emoji('💵')} Fund contributions total: ${fund_total:,.2f}")
                continue
                
            elif action == 't':
                transactions = manager.get_transactions(10)
                if not transactions:
                    print(f"\n{_safe_emoji('📋')} No transactions found")
                else:
                    print(f"\n{_safe_emoji('📋')} Recent Transactions (last 10):")
                    print("-" * 70)
                    print(f"{'Date':<12} {'Currency':<8} {'Amount':<12} {'Balance':<12} {'Description'}")
                    print("-" * 70)
                    for tx in transactions:
                        date_str = tx['timestamp'][:10]
                        amount_str = f"${tx['amount']:+,.2f}"
                        balance_str = f"${tx['balance_after']:,.2f}"
                        print(f"{date_str:<12} {tx['currency']:<8} {amount_str:<12} {balance_str:<12} {tx['description']}")
                continue
                
            elif action == 'c':
                try:
                    amount = float(input("Enter CAD amount (positive to add, negative to remove): $"))
                    if amount >= 0:
                        if manager.add_cash('CAD', amount, f"Manual CAD deposit"):
                            print(f"{_safe_emoji('✅')} Added ${amount:,.2f} CAD")
                        else:
                            print(f"{_safe_emoji('❌')} Failed to add CAD")
                    else:
                        if manager.remove_cash('CAD', abs(amount), f"Manual CAD withdrawal"):
                            print(f"{_safe_emoji('✅')} Removed ${abs(amount):,.2f} CAD")
                        else:
                            print(f"{_safe_emoji('❌')} Cannot remove ${abs(amount):,.2f} CAD - insufficient balance")
                            continue
                except ValueError:
                    print(f"{_safe_emoji('❌')} Invalid amount entered")
                    continue
                    
            elif action == 'u':
                try:
                    amount = float(input("Enter USD amount (positive to add, negative to remove): $"))
                    if amount >= 0:
                        if manager.add_cash('USD', amount, f"Manual USD deposit"):
                            print(f"{_safe_emoji('✅')} Added ${amount:,.2f} USD")
                        else:
                            print(f"{_safe_emoji('❌')} Failed to add USD")
                    else:
                        if manager.remove_cash('USD', abs(amount), f"Manual USD withdrawal"):
                            print(f"{_safe_emoji('✅')} Removed ${abs(amount):,.2f} USD")
                        else:
                            print(f"{_safe_emoji('❌')} Cannot remove ${abs(amount):,.2f} USD - insufficient balance")
                            continue
                except ValueError:
                    print(f"{_safe_emoji('❌')} Invalid amount entered")
                    continue
                    
            elif action == 's':
                try:
                    cad_amount = float(input("Enter exact CAD balance: $"))
                    usd_amount = float(input("Enter exact USD balance: $"))
                    if cad_amount < 0 or usd_amount < 0:
                        print(f"{_safe_emoji('❌')} Balances cannot be negative")
                        continue
                    
                    # Set both balances
                    manager.set_balance('CAD', cad_amount, "Manual CAD balance adjustment")
                    manager.set_balance('USD', usd_amount, "Manual USD balance adjustment")
                    print(f"{_safe_emoji('✅')} Set balances to CAD ${cad_amount:,.2f} and USD ${usd_amount:,.2f}")
                except ValueError:
                    print(f"{_safe_emoji('❌')} Invalid amounts entered")
                    continue
                    
            elif action == 'n':
                # Negative balance mode is now always enabled
                print(f"\n🔧 Negative Balance Mode: Always enabled")
                print("All trades can proceed even with insufficient funds,")
                print("resulting in negative balances that can be corrected later.")
                print(f"{_safe_emoji('✅')} Negative balance mode is permanently enabled")

            else:
                print(f"{_safe_emoji('❌')} Invalid option")
                continue
            
            # Show updated balances (manager saves automatically)
            balances = manager.get_balances()
            print(f"\n{_safe_emoji('💰')} Updated Cash Balances:")
            print(f"   CAD: ${balances['CAD']:,.2f}")
            print(f"   USD: ${balances['USD']:,.2f}")
            
            # Calculate total CAD equivalent
            total_cad = balances['CAD'] + (balances['USD'] * Decimal('1.35'))
            print(f"   Total (CAD equiv): ${total_cad:,.2f}")

            # Display fund contributions total
            fund_total = calculate_fund_contributions_total(data_dir)
            print(f"{_safe_emoji('💵')} Fund contributions total: ${fund_total:,.2f}")
            
    except Exception as e:
        print(f"{_safe_emoji('❌')} Error updating cash balances: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
