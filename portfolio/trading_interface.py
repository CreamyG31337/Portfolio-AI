"""Trading interface module.

This module provides the user interface layer for trading actions,
connecting menu selections to the underlying trade processing functions.
"""

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional, Dict, Any, List
import pandas as pd

from data.repositories.base_repository import BaseRepository
from portfolio.fifo_trade_processor import FIFOTradeProcessor
from display.console_output import print_success, print_error, print_info, print_warning

# Import market timing constants
from config.constants import MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE

logger = logging.getLogger(__name__)


class TradingInterface:
    """Handles user interface for trading actions."""

    def __init__(self, repository: BaseRepository, trade_processor: FIFOTradeProcessor):
        """Initialize trading interface.

        Args:
            repository: Repository for data access
            trade_processor: Trade processor for executing trades
        """
        self.repository = repository
        self.trade_processor = trade_processor
        logger.info("Trading interface initialized")

    def _get_trade_timestamp(self) -> datetime:
        """Get user-selected timestamp for trade execution.

        Returns:
            datetime: Selected timestamp for the trade
        """
        from datetime import time

        print_info("Select trade timestamp (Eastern Time - EDT/EST):")
        print("1. Market Open (9:30 AM EDT)")
        print("2. Custom Date/Time (enter in EDT/EST)")

        while True:
            try:
                choice = input("Enter choice (1-2): ").strip()

                if choice == '1':
                    # Market open (6:30 AM)
                    timestamp = datetime.combine(datetime.now().date(), time(MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE, 0))
                    print_success(f"Selected: Market Open ({timestamp.strftime('%Y-%m-%d %H:%M:%S')})")
                    return timestamp

                elif choice == '2':
                    # Custom date/time
                    try:
                        date_str = input("Enter date (YYYY-MM-DD) [today]: ").strip()
                        if not date_str:
                            date_str = datetime.now().strftime('%Y-%m-%d')

                        time_str = input("Enter time (HH:MM in EDT/EST) [current]: ").strip()
                        if not time_str:
                            time_str = datetime.now().strftime('%H:%M')

                        # Combine date and time
                        datetime_str = f"{date_str} {time_str}"
                        timestamp = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M')
                        print_success(f"Selected: Custom Time ({timestamp.strftime('%Y-%m-%d %H:%M:%S')})")
                        return timestamp

                    except ValueError as e:
                        print_error(f"Invalid date/time format: {e}")
                        continue

                else:
                    print_error("Invalid choice. Please enter 1 or 2")

            except KeyboardInterrupt:
                print_info("\nUsing current time as default")
                return datetime.now()
    
    def _validate_and_confirm_ticker(self, raw_ticker: str, price_hint: Optional[Decimal] = None) -> Optional[tuple[str, str, str]]:
        """Validate ticker and get user confirmation.
        
        Returns:
            Tuple of (corrected_ticker, currency, company_name) or None if user cancels
        """
        from utils.ticker_utils import detect_and_correct_ticker, get_company_name
        from financial.currency_handler import CurrencyHandler
        
        # Step 1: Auto-detect ticker with suffix (this may prompt user if multiple matches)
        corrected_ticker = detect_and_correct_ticker(raw_ticker, float(price_hint) if price_hint else None)
        
        # Step 2: Detect currency
        currency_handler = CurrencyHandler(Path(self.repository.data_dir))
        detected_currency = currency_handler.get_ticker_currency(corrected_ticker)
        
        # Step 3: Get company name
        company_name = get_company_name(corrected_ticker, detected_currency)
        
        # Step 4: Show final confirmation (no additional prompting)
        print_info("Stock Confirmation:")
        print(f"  Selected: {corrected_ticker} - {company_name} ({detected_currency})")
        
        # Just confirm the selection (no alternative options to avoid double-prompting)
        confirm = input("Proceed with this stock? (y/N): ").strip().lower()
        if confirm not in ('y', 'yes'):
            return None
        
        return (corrected_ticker, detected_currency, company_name)
    
    def log_contribution(self) -> bool:
        """Handle contribution logging action with enhanced contributor selection.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            print_info("Log Fund Contribution", "💵")
            
            # Get existing contributors
            contributors = self._get_existing_contributors()
            if contributors is None:
                return False
            
            if contributors.empty:
                print_warning("No contributors found. Please add contributors first using the 'Manage Contributors' option.")
                return False
            
            # Display contributors with numbers
            print("\n📋 Select Contributor:")
            print("─" * 50)
            for i, (_, contributor) in enumerate(contributors.iterrows(), 1):
                name = contributor['Contributor']
                email = contributor['Email'] if pd.notna(contributor['Email']) and contributor['Email'] else "No email"
                print(f"  {i:2d}. {name:<20} ({email})")
            print("─" * 50)
            
            # Get contributor selection
            while True:
                try:
                    selection = input(f"\nSelect contributor (1-{len(contributors)}): ").strip()
                    if not selection:
                        print_error("Selection cannot be empty")
                        continue
                    
                    choice = int(selection)
                    if 1 <= choice <= len(contributors):
                        selected_contributor = contributors.iloc[choice - 1]
                        break
                    else:
                        print_error(f"Please enter a number between 1 and {len(contributors)}")
                except ValueError:
                    print_error("Please enter a valid number")
                except KeyboardInterrupt:
                    print_info("\nOperation cancelled")
                    return False
            
            # Get contribution amount
            while True:
                try:
                    amount_str = input("Enter contribution amount: $").strip()
                    if not amount_str:
                        print_error("Amount cannot be empty")
                        continue
                    
                    amount = Decimal(amount_str)
                    if amount <= 0:
                        print_error("Contribution amount must be positive")
                        continue
                    break
                except ValueError:
                    print_error("Invalid amount format. Please enter a number.")
                except KeyboardInterrupt:
                    print_info("\nOperation cancelled")
                    return False
            
            # Get optional notes
            notes = input("Enter notes (optional): ").strip()
            
            # Save contribution to CSV
            contribution_data = {
                'Timestamp': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),
                'Contributor': selected_contributor['Contributor'],
                'Amount': amount,
                'Type': 'CONTRIBUTION',
                'Notes': notes,
                'Email': selected_contributor['Email'] if pd.notna(selected_contributor['Email']) else ''
            }
            
            self._save_contribution(contribution_data)
            print_success(f"Contribution of ${amount:,.2f} logged for {selected_contributor['Contributor']}")
            return True
            
        except Exception as e:
            logger.error(f"Error logging contribution: {e}")
            print_error(f"Failed to log contribution: {e}")
            return False
    
    def log_withdrawal(self) -> bool:
        """Handle withdrawal logging action with enhanced contributor selection.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            print_info("Log Fund Withdrawal", "💸")
            
            # Get existing contributors
            contributors = self._get_existing_contributors()
            if contributors is None:
                return False
            
            if contributors.empty:
                print_warning("No contributors found. Please add contributors first using the 'Manage Contributors' option.")
                return False
            
            # Display contributors with numbers
            print("\n📋 Select Contributor:")
            print("─" * 50)
            for i, (_, contributor) in enumerate(contributors.iterrows(), 1):
                name = contributor['Contributor']
                email = contributor['Email'] if pd.notna(contributor['Email']) and contributor['Email'] else "No email"
                print(f"  {i:2d}. {name:<20} ({email})")
            print("─" * 50)
            
            # Get contributor selection
            while True:
                try:
                    selection = input(f"\nSelect contributor (1-{len(contributors)}): ").strip()
                    if not selection:
                        print_error("Selection cannot be empty")
                        continue
                    
                    choice = int(selection)
                    if 1 <= choice <= len(contributors):
                        selected_contributor = contributors.iloc[choice - 1]
                        break
                    else:
                        print_error(f"Please enter a number between 1 and {len(contributors)}")
                except ValueError:
                    print_error("Please enter a valid number")
                except KeyboardInterrupt:
                    print_info("\nOperation cancelled")
                    return False
            
            # Get withdrawal amount
            while True:
                try:
                    amount_str = input("Enter withdrawal amount: $").strip()
                    if not amount_str:
                        print_error("Amount cannot be empty")
                        continue
                    
                    amount = Decimal(amount_str)
                    if amount <= 0:
                        print_error("Withdrawal amount must be positive")
                        continue
                    break
                except ValueError:
                    print_error("Invalid amount format. Please enter a number.")
                except KeyboardInterrupt:
                    print_info("\nOperation cancelled")
                    return False
            
            # Get optional notes
            notes = input("Enter notes (optional): ").strip()
            
            # Save withdrawal to CSV (as negative contribution)
            withdrawal_data = {
                'Timestamp': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),
                'Contributor': selected_contributor['Contributor'],
                'Amount': amount,
                'Type': 'WITHDRAWAL',
                'Notes': notes,
                'Email': selected_contributor['Email'] if pd.notna(selected_contributor['Email']) else ''
            }
            
            self._save_contribution(withdrawal_data)
            print_success(f"Withdrawal of ${amount:,.2f} logged for {selected_contributor['Contributor']}")
            return True
            
        except Exception as e:
            logger.error(f"Error logging withdrawal: {e}")
            print_error(f"Failed to log withdrawal: {e}")
            return False
    
    def update_cash_balances(self) -> bool:
        """Handle cash balance update action using enhanced cash balance manager.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            print_info("Update Cash Balances", "🔄")
            
            # Import the simple cash balance manager
            from financial.simple_cash_manager import SimpleCashManager
            
            # Initialize the manager
            manager = SimpleCashManager(Path(self.repository.data_dir))
            
            # Display current balances
            balances = manager.get_balances()
            print("Current cash balances:")
            print(f"  CAD: ${balances['CAD']:,.2f}")
            print(f"  USD: ${balances['USD']:,.2f}")
            
            # Calculate total CAD equivalent
            total_cad = balances['CAD'] + (balances['USD'] * Decimal('1.35'))
            print(f"  Total (CAD equiv): ${total_cad:,.2f}")
            
            # Get operation type
            print("\nOptions:")
            print("  'a' = Add cash")
            print("  'r' = Remove cash")
            print("  's' = Set exact balance")
            print("  'v' = View transaction history")
            
            operation = input("Choose operation: ").strip().lower()
            
            if operation == 'a':
                # Add cash - CAD
                try:
                    amount_str = input("Enter CAD amount to add: $").strip()
                    amount = Decimal(amount_str)
                    if amount <= 0:
                        print_error("Amount must be positive")
                        return False
                except (ValueError, InvalidOperation):
                    print_error("Invalid amount format")
                    return False
                
                description = input("Enter description (optional): ").strip()
                if not description:
                    description = f"Manual CAD deposit"
                
                if manager.add_cash('CAD', amount, description):
                    print_success(f"Added ${amount:,.2f} CAD")
                    return True
                else:
                    print_error("Failed to add CAD")
                    return False
                    
            elif operation == 'r':
                # Remove cash - CAD
                current_balance = manager.get_balance('CAD')
                print(f"Current CAD balance: ${current_balance:,.2f}")
                
                try:
                    amount_str = input("Enter CAD amount to remove: $").strip()
                    amount = Decimal(amount_str)
                    if amount <= 0:
                        print_error("Amount must be positive")
                        return False
                except (ValueError, InvalidOperation):
                    print_error("Invalid amount format")
                    return False
                
                allow_negative = False
                if current_balance < amount:
                    print(f"\n⚠️  Insufficient funds!")
                    print(f"Available: ${current_balance:,.2f}")
                    print(f"Requested: ${amount:,.2f}")
                    print(f"Shortfall: ${amount - current_balance:,.2f}")
                    
                    if input("Allow negative balance? (y/N): ").strip().lower() == 'y':
                        allow_negative = True
                    else:
                        print_error("Operation cancelled")
                        return False
                
                description = input("Enter description (optional): ").strip()
                if not description:
                    description = f"Manual CAD withdrawal"
                
                if manager.remove_cash('CAD', amount, description, allow_negative=allow_negative):
                    print_success(f"Removed ${amount:,.2f} CAD")
                    return True
                else:
                    print_error("Failed to remove CAD")
                    return False
                    
            elif operation == 's':
                # Set exact balance - CAD
                current_balance = manager.get_balance('CAD')
                print(f"Current CAD balance: ${current_balance:,.2f}")
                
                try:
                    amount_str = input("Enter new CAD balance: $").strip()
                    amount = Decimal(amount_str)
                    if amount < 0:
                        print_error("Balance cannot be negative")
                        return False
                except (ValueError, InvalidOperation):
                    print_error("Invalid amount format")
                    return False
                
                description = input("Enter description (optional): ").strip()
                if not description:
                    difference = amount - current_balance
                    if difference > 0:
                        description = f"CAD balance adjustment: +${difference:,.2f}"
                    elif difference < 0:
                        description = f"CAD balance adjustment: ${difference:,.2f}"
                    else:
                        description = "No change needed"
                
                if manager.set_balance('CAD', amount, description):
                    print_success(f"Set CAD balance to ${amount:,.2f}")
                    return True
                else:
                    print_error("Failed to set CAD balance")
                    return False
                    
            elif operation == 'v':
                # View transaction history
                transactions = manager.get_transactions(10)
                if not transactions:
                    print("No transactions found")
                    return True
                
                print(f"\nRecent Transactions (last 10):")
                print("-" * 70)
                print(f"{'Date':<12} {'Currency':<8} {'Amount':<12} {'Balance':<12} {'Description'}")
                print("-" * 70)
                
                for tx in transactions:
                    date_str = tx['timestamp'][:10]
                    amount_str = f"${tx['amount']:+,.2f}"
                    balance_str = f"${tx['balance_after']:,.2f}"
                    print(f"{date_str:<12} {tx['currency']:<8} {amount_str:<12} {balance_str:<12} {tx['description']}")
                
                return True
            else:
                print_error("Invalid operation")
                return False
            
        except Exception as e:
            logger.error(f"Error updating cash balances: {e}")
            print_error(f"Failed to update cash balances: {e}")
            return False
    
    
    
    def sync_fund_contributions(self) -> bool:
        """Handle fund contribution sync action.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            print_info("Sync Fund Contributions", "🔗")
            print_warning("Fund contribution sync not yet implemented")
            print_info("This feature will sync contributions from external sources")
            return True
            
        except Exception as e:
            logger.error(f"Error syncing fund contributions: {e}")
            print_error(f"Failed to sync fund contributions: {e}")
            return False
    
    def manage_contributors(self) -> bool:
        """Handle contributor management action using the modular approach.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            from portfolio.contributor_manager import ContributorManager, ContributorUI
            
            # Use the modular contributor management system
            contributor_manager = ContributorManager(self.repository)
            contributor_ui = ContributorUI(contributor_manager)
            
            return contributor_ui.manage_contributors_interactive()
            
        except Exception as e:
            logger.error(f"Error managing contributors: {e}")
            print_error(f"Failed to manage contributors: {e}")
            return False
    
    def _get_existing_contributors(self) -> Optional[pd.DataFrame]:
        """Get existing contributors from the fund contributions file.
        
        Returns:
            DataFrame of contributors or None if error
        """
        try:
            from portfolio.contributor_manager import ContributorManager
            contributor_manager = ContributorManager(self.repository)
            contributors = contributor_manager.get_contributors()
            
            if contributors.empty:
                return pd.DataFrame()
            
            # Get unique contributors (in case there are multiple entries per contributor)
            unique_contributors = contributors[['Contributor', 'Email']].drop_duplicates()
            return unique_contributors.sort_values('Contributor')
            
        except Exception as e:
            logger.error(f"Error getting contributors: {e}")
            print_error(f"Failed to load contributors: {e}")
            return None
    
    def _save_contribution(self, contribution_data: Dict[str, Any]) -> None:
        """Save contribution data to CSV file.
        
        Args:
            contribution_data: Dictionary containing contribution information
        """
        fund_file = Path(self.repository.data_dir) / "fund_contributions.csv"
        
        # Create DataFrame with new contribution
        new_df = pd.DataFrame([contribution_data])
        
        # Append to existing file or create new one
        if fund_file.exists():
            existing_df = pd.read_csv(fund_file)
            combined_df = pd.concat([existing_df, new_df], ignore_index=True)
        else:
            combined_df = new_df
        
        # Save to CSV
        combined_df.to_csv(fund_file, index=False)
        logger.info(f"Contribution saved to {fund_file}")