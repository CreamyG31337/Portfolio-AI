"""Fund Management User Interface.

This module provides interactive UI components for managing multiple investment funds
through the command-line interface.
"""

from typing import Optional, List, Dict, Any
import sys
from pathlib import Path

from display.console_output import print_success, print_error, print_warning, print_info, print_header, _safe_emoji
from utils.fund_manager import get_fund_manager, FundManager

# Colors for consistent styling (matching run.py)
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def print_colored(text: str, color: str = Colors.ENDC) -> None:
    """Print colored text to terminal."""
    print(f"{color}{text}{Colors.ENDC}")


class FundUI:
    """User interface for fund management operations."""
    
    def __init__(self):
        """Initialize the fund UI."""
        self.fund_manager = get_fund_manager()
    
    def show_fund_management_menu(self) -> None:
        """Display the main fund management menu and handle user interaction."""
        while True:
            self._display_fund_management_menu()
            
            choice = input(f"\n{Colors.YELLOW}Select option (1-6) or Enter to go back: {Colors.ENDC}").strip()
            
            if choice == "" or choice == "enter":
                break
            elif choice == "1":
                self._list_all_funds()
            elif choice == "2":
                self._switch_active_fund()
            elif choice == "3":
                self._create_new_fund()
            elif choice == "4":
                self._edit_fund_settings()
            elif choice == "5":
                self._import_fund_data()
            elif choice == "6":
                self._delete_fund()
            else:
                print_error("Invalid choice. Please select 1-6 or press Enter to go back.")
            
            if choice not in ["", "enter"]:
                input(f"\n{Colors.YELLOW}Press Enter to continue...{Colors.ENDC}")
    
    def _display_fund_management_menu(self) -> None:
        """Display the fund management menu."""
        active_fund = self.fund_manager.get_active_fund()
        active_display = f"Current Fund: {active_fund}" if active_fund else "No Active Fund"
        
        print_colored(f"\n{_safe_emoji('🏦')} FUND MANAGEMENT", Colors.HEADER + Colors.BOLD)
        print_colored("=" * 40, Colors.HEADER)
        print_colored(f"{active_display}", Colors.GREEN + Colors.BOLD)
        print_colored("=" * 40, Colors.HEADER)
        
        print_colored(f"\n[1] {_safe_emoji('📋')} List All Funds", Colors.CYAN)
        print_colored(f"[2] {_safe_emoji('🔄')} Switch Active Fund", Colors.CYAN)
        print_colored(f"[3] {_safe_emoji('➕')} Create New Fund", Colors.CYAN)
        print_colored(f"[4] {_safe_emoji('⚙️')} Edit Fund Settings", Colors.CYAN)
        print_colored(f"[5] {_safe_emoji('📁')} Import Fund Data", Colors.CYAN)
        print_colored(f"[6] {_safe_emoji('🗑️')} Delete Fund", Colors.CYAN)
        print_colored(f"Enter - {_safe_emoji('🔙')} Back to Configuration", Colors.CYAN)
    
    def _list_all_funds(self) -> None:
        """List all available funds with detailed information."""
        print_header(f"{_safe_emoji('📋')} Available Funds")
        
        funds = self.fund_manager.get_available_funds()
        if not funds:
            print_warning("No funds found. Create your first fund using option 3.")
            return
        
        active_fund = self.fund_manager.get_active_fund()
        
        for fund_name in funds:
            fund_info = self.fund_manager.get_fund_info(fund_name)
            if not fund_info:
                continue
            
            config = fund_info["config"]
            is_active = fund_info["is_active"]
            
            # Display fund header
            status = f"{_safe_emoji('🟢')} ACTIVE" if is_active else f"{_safe_emoji('⚪')} Inactive"
            print_colored(f"\n{status} {fund_name}", Colors.BOLD + (Colors.GREEN if is_active else Colors.CYAN))
            print_colored("-" * (len(fund_name) + 10), Colors.HEADER)
            
            # Display fund details
            print(f"  {_safe_emoji('📄')} Description: {config.get('description', 'N/A')}")
            print(f"  {_safe_emoji('💰')} Currency: {config.get('display_currency', 'N/A')}")
            print(f"  {_safe_emoji('🏷️')} Type: {config.get('fund_type', 'N/A')}")
            print(f"  {_safe_emoji('📅')} Created: {config.get('created_date', 'N/A')[:10]}")
            
            # Display data file status
            files = fund_info["files"]
            portfolio_exists = files.get("llm_portfolio_update.csv", {}).get("exists", False)
            trades_exists = files.get("llm_trade_log.csv", {}).get("exists", False)
            cash_exists = files.get("cash_balances.json", {}).get("exists", False)
            
            print(f"  {_safe_emoji('📊')} Portfolio: {_safe_emoji('✅') if portfolio_exists else _safe_emoji('❌')}")
            print(f"  {_safe_emoji('📈')} Trades: {_safe_emoji('✅') if trades_exists else _safe_emoji('❌')}")
            print(f"  {_safe_emoji('💵')} Cash: {_safe_emoji('✅') if cash_exists else _safe_emoji('❌')}")
    
    def _switch_active_fund(self) -> None:
        """Allow user to switch the active fund."""
        print_header(f"{_safe_emoji('🔄')} Switch Active Fund")
        
        funds = self.fund_manager.get_available_funds()
        if not funds:
            print_warning("No funds available to switch to.")
            return
        
        if len(funds) == 1:
            print_info("Only one fund available. No switching needed.")
            return
        
        active_fund = self.fund_manager.get_active_fund()
        
        print("Available funds:")
        for i, fund_name in enumerate(funds, 1):
            status = " (CURRENT)" if fund_name == active_fund else ""
            print(f"  [{i}] {fund_name}{status}")
        
        print(f"  [0] Cancel")
        
        while True:
            try:
                choice = input(f"\n{Colors.YELLOW}Select fund (0-{len(funds)}): {Colors.ENDC}").strip()
                
                if choice == "0":
                    print_info("Fund switching cancelled.")
                    return
                
                choice_num = int(choice)
                if 1 <= choice_num <= len(funds):
                    selected_fund = funds[choice_num - 1]
                    if selected_fund == active_fund:
                        print_info(f"'{selected_fund}' is already the active fund.")
                    else:
                        if self.fund_manager.set_active_fund(selected_fund):
                            print_success(f"Successfully switched to fund: {selected_fund}")
                            # Refresh fund manager instance to pick up the change immediately
                            from utils.fund_manager import get_fund_manager
                            self.fund_manager = get_fund_manager()
                        else:
                            print_error("Failed to switch fund.")
                    return
                else:
                    print_error(f"Invalid choice. Please select 0-{len(funds)}.")
                    
            except ValueError:
                print_error("Please enter a valid number.")
    
    def _create_new_fund(self) -> None:
        """Interactive fund creation wizard."""
        print_header(f"{_safe_emoji('➕')} Create New Fund")
        
        # Get fund name
        while True:
            fund_name = input(f"{Colors.YELLOW}Enter fund name (e.g., 'TFSA', 'RRSP'): {Colors.ENDC}").strip()
            
            if not fund_name:
                print_error("Fund name cannot be empty.")
                continue
            
            if fund_name in self.fund_manager.get_available_funds():
                print_error(f"Fund '{fund_name}' already exists.")
                continue
            
            if not fund_name.replace(" ", "").replace("-", "").replace("_", "").isalnum():
                print_error("Fund name can only contain letters, numbers, spaces, hyphens, and underscores.")
                continue
            
            break
        
        # Get fund type
        print(f"\n{Colors.CYAN}Fund Types:{Colors.ENDC}")
        fund_types = [
            ("1", "TFSA", "Tax-Free Savings Account (Growth-focused strategy)"),
            ("2", "RRSP", "Registered Retirement Savings Plan (Balanced dividend strategy)"),
            ("3", "Investment", "Regular investment account"),
            ("4", "Margin", "Margin trading account"),
            ("5", "Custom", "Enter custom type")
        ]
        
        for key, name, description in fund_types:
            print(f"  [{key}] {name} - {description}")
        
        while True:
            type_choice = input(f"\n{Colors.YELLOW}Select fund type (1-5): {Colors.ENDC}").strip()
            
            if type_choice in ["1", "2", "3", "4"]:
                fund_type = [t[1] for t in fund_types if t[0] == type_choice][0]
                break
            elif type_choice == "5":
                fund_type = input(f"{Colors.YELLOW}Enter custom fund type: {Colors.ENDC}").strip()
                if fund_type:
                    break
                else:
                    print_error("Custom type cannot be empty.")
            else:
                print_error("Invalid choice. Please select 1-5.")
        
        # Get display currency
        print(f"\n{Colors.CYAN}Display Currency:{Colors.ENDC}")
        currencies = [("1", "CAD"), ("2", "USD"), ("3", "Custom")]
        
        for key, curr in currencies:
            print(f"  [{key}] {curr}")
        
        while True:
            curr_choice = input(f"\n{Colors.YELLOW}Select currency (1-3): {Colors.ENDC}").strip()
            
            if curr_choice == "1":
                display_currency = "CAD"
                break
            elif curr_choice == "2":
                display_currency = "USD"
                break
            elif curr_choice == "3":
                custom_curr = input(f"{Colors.YELLOW}Enter currency code (e.g., EUR): {Colors.ENDC}").strip().upper()
                if custom_curr and len(custom_curr) == 3:
                    display_currency = custom_curr
                    break
                else:
                    print_error("Please enter a valid 3-letter currency code.")
            else:
                print_error("Invalid choice. Please select 1-3.")
        
        # Get description (optional)
        description = input(f"\n{Colors.YELLOW}Enter description (optional): {Colors.ENDC}").strip()
        
        # Ask about copying data from existing fund
        copy_from_fund = None
        existing_funds = self.fund_manager.get_available_funds()
        if existing_funds:
            print(f"\n{Colors.CYAN}Copy data from existing fund?{Colors.ENDC}")
            print("  [0] Start with empty data")
            
            for i, existing_fund in enumerate(existing_funds, 1):
                print(f"  [{i}] Copy from '{existing_fund}'")
            
            while True:
                copy_choice = input(f"\n{Colors.YELLOW}Select option (0-{len(existing_funds)}): {Colors.ENDC}").strip()
                
                try:
                    choice_num = int(copy_choice)
                    if choice_num == 0:
                        break
                    elif 1 <= choice_num <= len(existing_funds):
                        copy_from_fund = existing_funds[choice_num - 1]
                        break
                    else:
                        print_error(f"Invalid choice. Please select 0-{len(existing_funds)}.")
                except ValueError:
                    print_error("Please enter a valid number.")
        
        # Show thesis strategy info
        thesis_info = self._get_thesis_strategy_info(fund_type)
        
        # Confirmation
        print(f"\n{Colors.HEADER}Fund Creation Summary:{Colors.ENDC}")
        print(f"  Name: {fund_name}")
        print(f"  Type: {fund_type}")
        print(f"  Currency: {display_currency}")
        print(f"  Description: {description or 'None'}")
        print(f"  Copy from: {copy_from_fund or 'None (empty data)'}")
        if thesis_info:
            print(f"  Investment Strategy: {thesis_info}")
        
        confirm = input(f"\n{Colors.YELLOW}Create this fund? (y/N): {Colors.ENDC}").strip().lower()
        
        if confirm == 'y':
            success = self.fund_manager.create_fund(
                fund_name=fund_name,
                fund_type=fund_type,
                display_currency=display_currency,
                description=description,
                copy_from_fund=copy_from_fund
            )
            
            if success:
                print_success(f"Fund '{fund_name}' created successfully!")
                
                # Ask if user wants to switch to the new fund
                if len(self.fund_manager.get_available_funds()) > 1:
                    switch = input(f"\n{Colors.YELLOW}Switch to the new fund now? (Y/n): {Colors.ENDC}").strip().lower()
                    if switch != 'n':
                        self.fund_manager.set_active_fund(fund_name)
                        # Refresh fund manager instance to pick up the change immediately
                        from utils.fund_manager import get_fund_manager
                        self.fund_manager = get_fund_manager()
                else:
                    # Refresh fund manager even if not switching, in case it became the active fund
                    from utils.fund_manager import get_fund_manager
                    self.fund_manager = get_fund_manager()
            else:
                print_error("Failed to create fund. Check the logs for details.")
        else:
            print_info("Fund creation cancelled.")
    
    def _get_thesis_strategy_info(self, fund_type: str) -> Optional[str]:
        """Get brief strategy description for fund type."""
        fund_type_lower = fund_type.lower()
        
        if fund_type_lower == "tfsa":
            return "Growth-focused, tax-free strategy emphasizing capital appreciation"
        elif fund_type_lower == "rrsp":
            return "Balanced dividend strategy for tax-deferred retirement growth"
        else:
            return None
    
    def _edit_fund_settings(self) -> None:
        """Allow editing of fund settings."""
        print_header(f"{_safe_emoji('⚙️')} Edit Fund Settings")
        
        funds = self.fund_manager.get_available_funds()
        if not funds:
            print_warning("No funds available to edit.")
            return
        
        # Select fund to edit
        print("Available funds:")
        for i, fund_name in enumerate(funds, 1):
            print(f"  [{i}] {fund_name}")
        print(f"  [0] Cancel")
        
        while True:
            try:
                choice = input(f"\n{Colors.YELLOW}Select fund to edit (0-{len(funds)}): {Colors.ENDC}").strip()
                
                if choice == "0":
                    print_info("Edit cancelled.")
                    return
                
                choice_num = int(choice)
                if 1 <= choice_num <= len(funds):
                    selected_fund = funds[choice_num - 1]
                    break
                else:
                    print_error(f"Invalid choice. Please select 0-{len(funds)}.")
                    
            except ValueError:
                print_error("Please enter a valid number.")
        
        # Show current settings and allow editing
        config = self.fund_manager.get_fund_config(selected_fund)
        if not config:
            print_error("Failed to load fund configuration.")
            return
        
        fund_config = config["fund"]
        
        print(f"\n{Colors.HEADER}Current settings for '{selected_fund}':{Colors.ENDC}")
        print(f"  Name: {fund_config.get('name', 'N/A')}")
        print(f"  Description: {fund_config.get('description', 'N/A')}")
        print(f"  Type: {fund_config.get('fund_type', 'N/A')}")
        print(f"  Currency: {fund_config.get('display_currency', 'N/A')}")
        
        # Edit options
        while True:
            print(f"\n{Colors.CYAN}Edit Options:{Colors.ENDC}")
            print("  [1] Change Fund Name")
            print("  [2] Change Description")
            print("  [3] Change Fund Type")
            print("  [4] Change Display Currency")
            print("  [5] View All Settings")
            print("  [0] Done Editing")
            
            edit_choice = input(f"\n{Colors.YELLOW}Select option (0-5): {Colors.ENDC}").strip()
            
            if edit_choice == "0":
                break
            elif edit_choice == "1":
                self._edit_fund_name(selected_fund, config)
            elif edit_choice == "2":
                self._edit_fund_description(selected_fund, config)
            elif edit_choice == "3":
                self._edit_fund_type(selected_fund, config)
            elif edit_choice == "4":
                self._edit_fund_currency(selected_fund, config)
            elif edit_choice == "5":
                self._display_fund_settings(selected_fund, config)
            else:
                print_error("Invalid choice. Please select 0-5.")
        
        print_success(f"Fund '{selected_fund}' editing completed!")
    
    def _edit_fund_name(self, fund_name: str, config: Dict[str, Any]) -> None:
        """Edit fund name."""
        current_name = config["fund"].get("name", "")
        print(f"\n{Colors.CYAN}Current name: {current_name}{Colors.ENDC}")
        
        new_name = input(f"{Colors.YELLOW}Enter new fund name: {Colors.ENDC}").strip()
        
        if not new_name:
            print_error("Fund name cannot be empty.")
            return
        
        if new_name == current_name:
            print_info("Name unchanged.")
            return
        
        # Check if name already exists
        existing_funds = self.fund_manager.get_available_funds()
        if new_name in existing_funds and new_name != fund_name:
            print_error(f"Fund name '{new_name}' already exists.")
            return
        
        # Update the config
        config["fund"]["name"] = new_name
        
        # Save the updated config
        if self._save_fund_config(fund_name, config):
            print_success(f"Fund name updated to '{new_name}'")
        else:
            print_error("Failed to save fund configuration.")
    
    def _edit_fund_description(self, fund_name: str, config: Dict[str, Any]) -> None:
        """Edit fund description."""
        current_desc = config["fund"].get("description", "")
        print(f"\n{Colors.CYAN}Current description: {current_desc}{Colors.ENDC}")
        
        new_desc = input(f"{Colors.YELLOW}Enter new description: {Colors.ENDC}").strip()
        
        if new_desc == current_desc:
            print_info("Description unchanged.")
            return
        
        # Update the config
        config["fund"]["description"] = new_desc
        
        # Save the updated config
        if self._save_fund_config(fund_name, config):
            print_success(f"Fund description updated to '{new_desc}'")
        else:
            print_error("Failed to save fund configuration.")
    
    def _edit_fund_type(self, fund_name: str, config: Dict[str, Any]) -> None:
        """Edit fund type."""
        current_type = config["fund"].get("fund_type", "")
        print(f"\n{Colors.CYAN}Current type: {current_type}{Colors.ENDC}")
        
        print(f"\n{Colors.CYAN}Available fund types:{Colors.ENDC}")
        fund_types = [
            ("1", "investment", "General Investment Fund"),
            ("2", "tfsa", "Tax-Free Savings Account"),
            ("3", "rrsp", "Registered Retirement Savings Plan"),
            ("4", "webull", "Webull Trading Account (with FX fees)"),
            ("5", "wealthsimple", "Wealthsimple Trading Account (with fees)"),
            ("6", "custom", "Custom Type")
        ]
        
        for key, ftype, description in fund_types:
            print(f"  [{key}] {ftype} - {description}")
        
        while True:
            type_choice = input(f"\n{Colors.YELLOW}Select fund type (1-6): {Colors.ENDC}").strip()
            
            if type_choice in ["1", "2", "3", "4", "5"]:
                new_type = [t[1] for t in fund_types if t[0] == type_choice][0]
                break
            elif type_choice == "6":
                new_type = input(f"{Colors.YELLOW}Enter custom fund type: {Colors.ENDC}").strip().lower()
                if new_type:
                    break
                else:
                    print_error("Custom type cannot be empty.")
            else:
                print_error("Invalid choice. Please select 1-5.")
        
        if new_type == current_type:
            print_info("Type unchanged.")
            return
        
        # Update the config
        config["fund"]["fund_type"] = new_type
        
        # Update tax status based on fund type
        if new_type == "tfsa":
            config["fund"]["tax_status"] = "tax_free"
        elif new_type == "rrsp":
            config["fund"]["tax_status"] = "tax_deferred"
        else:
            config["fund"]["tax_status"] = "taxable"
        
        # Add Webull-specific configuration
        if new_type == "webull":
            config["fund"]["webull_fx_fee"] = {
                "enabled": True,
                "liquidation_fee": 2.99,  # $2.99 per USD holding
                "fx_fee_rate": 0.015,  # 1.5% FX fee
                "description": "Webull liquidation fee ($2.99/holding) + FX fee (1.5%)"
            }
        
        # Add Wealthsimple-specific configuration
        if new_type == "wealthsimple":
            config["fund"]["wealthsimple_fees"] = {
                "enabled": True,
                "fx_fee_rate": 0.015,  # 1.5% FX fee on USD holdings (same as Webull)
                "liquidation_fee": 0.0,  # No liquidation fees (unlike Webull's $2.99)
                "description": "Wealthsimple FX fees only (1.5% of USD holdings, no liquidation fees)"
            }
        
        # Save the updated config
        if self._save_fund_config(fund_name, config):
            print_success(f"Fund type updated to '{new_type}'")
        else:
            print_error("Failed to save fund configuration.")
    
    def _edit_fund_currency(self, fund_name: str, config: Dict[str, Any]) -> None:
        """Edit fund display currency."""
        current_currency = config["fund"].get("display_currency", "")
        print(f"\n{Colors.CYAN}Current currency: {current_currency}{Colors.ENDC}")
        
        print(f"\n{Colors.CYAN}Available currencies:{Colors.ENDC}")
        currencies = [("1", "CAD"), ("2", "USD"), ("3", "Custom")]
        
        for key, curr in currencies:
            print(f"  [{key}] {curr}")
        
        while True:
            curr_choice = input(f"\n{Colors.YELLOW}Select currency (1-3): {Colors.ENDC}").strip()
            
            if curr_choice == "1":
                new_currency = "CAD"
                break
            elif curr_choice == "2":
                new_currency = "USD"
                break
            elif curr_choice == "3":
                custom_curr = input(f"{Colors.YELLOW}Enter currency code (e.g., EUR): {Colors.ENDC}").strip().upper()
                if custom_curr and len(custom_curr) == 3:
                    new_currency = custom_curr
                    break
                else:
                    print_error("Please enter a valid 3-letter currency code.")
            else:
                print_error("Invalid choice. Please select 1-3.")
        
        if new_currency == current_currency:
            print_info("Currency unchanged.")
            return
        
        # Update the config
        config["fund"]["display_currency"] = new_currency
        
        # Save the updated config
        if self._save_fund_config(fund_name, config):
            print_success(f"Fund currency updated to '{new_currency}'")
        else:
            print_error("Failed to save fund configuration.")
    
    def _display_fund_settings(self, fund_name: str, config: Dict[str, Any]) -> None:
        """Display all current fund settings."""
        fund_config = config["fund"]
        
        print(f"\n{Colors.HEADER}Current settings for '{fund_name}':{Colors.ENDC}")
        print(f"  Name: {fund_config.get('name', 'N/A')}")
        print(f"  Description: {fund_config.get('description', 'N/A')}")
        print(f"  Type: {fund_config.get('fund_type', 'N/A')}")
        print(f"  Currency: {fund_config.get('display_currency', 'N/A')}")
        print(f"  Tax Status: {fund_config.get('tax_status', 'N/A')}")
        print(f"  Created: {fund_config.get('created_date', 'N/A')}")
    
    def _save_fund_config(self, fund_name: str, config: Dict[str, Any]) -> bool:
        """Save fund configuration to file."""
        try:
            import json
            from pathlib import Path
            
            fund_dir = self.fund_manager.funds_dir / fund_name
            config_path = fund_dir / "fund_config.json"
            
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
            
            return True
        except Exception as e:
            print_error(f"Failed to save configuration: {e}")
            return False
    
    def _import_fund_data(self) -> None:
        """Import data from external sources."""
        print_header(f"{_safe_emoji('📁')} Import Fund Data")
        
        print("Available import options:")
        print("  [1] Import Webull Trade Data")
        print("  [2] Manual File Import")
        print("  [0] Cancel")
        
        while True:
            choice = input(f"\n{Colors.YELLOW}Select import option (0-2): {Colors.ENDC}").strip()
            
            if choice == "0":
                print_info("Import cancelled.")
                return
            elif choice == "1":
                self._import_webull_data()
                break
            elif choice == "2":
                self._manual_file_import()
                break
            else:
                print_error("Invalid choice. Please select 0-2.")
    
    def _import_webull_data(self) -> None:
        """Import Webull trade data."""
        print_header(f"{_safe_emoji('📈')} Import Webull Trade Data")
        
        # Get CSV file path
        csv_path = input(f"{Colors.YELLOW}Enter path to Webull CSV file: {Colors.ENDC}").strip()
        
        if not csv_path:
            print_error("CSV file path is required.")
            return
        
        csv_file = Path(csv_path)
        if not csv_file.exists():
            print_error(f"File not found: {csv_file}")
            return
        
        # Ask for preview first
        preview_choice = input(f"\n{Colors.YELLOW}Preview import first? (y/N): {Colors.ENDC}").strip().lower()
        preview_first = preview_choice == 'y'
        
        try:
            from utils.webull_importer import import_webull_data
            
            if preview_first:
                print_info("Running preview...")
                results = import_webull_data(
                    csv_file_path=str(csv_file),
                    fund_name=self.fund_manager.get_active_fund(),
                    dry_run=True
                )
                
                if results["success"]:
                    self._display_import_preview(results)
                    
                    proceed = input(f"\n{Colors.YELLOW}Proceed with import? (y/N): {Colors.ENDC}").strip().lower()
                    if proceed != 'y':
                        print_info("Import cancelled.")
                        return
                else:
                    print_error(f"Preview failed: {results['message']}")
                    return
            
            # Perform the actual import
            print_info("Importing data...")
            results = import_webull_data(
                csv_file_path=str(csv_file),
                fund_name=self.fund_manager.get_active_fund(),
                dry_run=False
            )
            
            if results["success"]:
                print_success(f"✅ {results['message']}")
                print_info(f"Trades processed: {results['trades_processed']}")
                print_info(f"Trades imported: {results['trades_imported']}")
                if results['trades_skipped'] > 0:
                    print_warning(f"Trades skipped: {results['trades_skipped']}")
            else:
                print_error(f"❌ {results['message']}")
                
        except ImportError:
            print_error("Webull importer not available. Please ensure utils.webull_importer is installed.")
        except Exception as e:
            print_error(f"Import failed: {e}")
    
    def _display_import_preview(self, results: dict) -> None:
        """Display import preview results."""
        print(f"\n{Colors.HEADER}Import Preview:{Colors.ENDC}")
        print(f"  Trades to import: {results['trades_processed']}")
        print(f"  Total value: ${results.get('total_value', 0):,.2f}")
        
        symbol_summary = results.get('symbol_summary', {})
        if symbol_summary:
            print(f"\n{Colors.CYAN}Symbol Summary:{Colors.ENDC}")
            print(f"{'Symbol':<10} {'Buy':<8} {'Sell':<8} {'Net':<8} {'Value':<12}")
            print("-" * 50)
            
            for symbol, data in symbol_summary.items():
                net_qty = data['net_quantity']
                value = data['total_value']
                print(f"{symbol:<10} {data['Buy']:<8} {data['Sell']:<8} {net_qty:<8} ${value:<11,.2f}")
    
    def _manual_file_import(self) -> None:
        """Manual file import instructions."""
        print_header("📁 Manual File Import")
        print_info("To manually import data:")
        print("1. Copy your CSV/JSON files to the fund's directory:")
        print(f"   {self.fund_manager.funds_dir / self.fund_manager.get_active_fund()}")
        print("2. Ensure files follow the expected format:")
        print("   - llm_portfolio_update.csv")
        print("   - llm_trade_log.csv")
        print("   - cash_balances.json")
        print("   - exchange_rates.csv")
        print("3. Restart the trading bot to load the new data")
        
        active_fund = self.fund_manager.get_active_fund()
        if active_fund:
            data_dir = self.fund_manager.get_fund_data_directory(active_fund)
            print(f"\nActive fund data directory: {data_dir}")
    
    def _delete_fund(self) -> None:
        """Delete a fund with confirmation."""
        print_header("🗑️ Delete Fund")
        
        funds = self.fund_manager.get_available_funds()
        if not funds:
            print_warning("No funds available to delete.")
            return
        
        if len(funds) == 1:
            print_warning("Cannot delete the last remaining fund.")
            return
        
        # Select fund to delete
        print("Available funds:")
        for i, fund_name in enumerate(funds, 1):
            print(f"  [{i}] {fund_name}")
        print(f"  [0] Cancel")
        
        while True:
            try:
                choice = input(f"\n{Colors.YELLOW}Select fund to delete (0-{len(funds)}): {Colors.ENDC}").strip()
                
                if choice == "0":
                    print_info("Deletion cancelled.")
                    return
                
                choice_num = int(choice)
                if 1 <= choice_num <= len(funds):
                    selected_fund = funds[choice_num - 1]
                    break
                else:
                    print_error(f"Invalid choice. Please select 0-{len(funds)}.")
                    
            except ValueError:
                print_error("Please enter a valid number.")
        
        # Show fund info and get confirmation
        fund_info = self.fund_manager.get_fund_info(selected_fund)
        if fund_info:
            config = fund_info["config"]
            print(f"\n{Colors.RED}WARNING: This will permanently delete the fund and all its data!{Colors.ENDC}")
            print(f"Fund: {selected_fund}")
            print(f"Type: {config.get('fund_type', 'N/A')}")
            print(f"Description: {config.get('description', 'N/A')}")
            
            # Double confirmation
            confirm1 = input(f"\n{Colors.YELLOW}Are you sure you want to delete '{selected_fund}'? (yes/no): {Colors.ENDC}").strip().lower()
            
            if confirm1 == "yes":
                confirm2 = input(f"{Colors.RED}Type the fund name '{selected_fund}' to confirm deletion: {Colors.ENDC}").strip()
                
                if confirm2 == selected_fund:
                    success = self.fund_manager.delete_fund(selected_fund, confirm=True)
                    if success:
                        print_success(f"Fund '{selected_fund}' deleted successfully.")
                    else:
                        print_error("Failed to delete fund.")
                else:
                    print_info("Fund name doesn't match. Deletion cancelled.")
            else:
                print_info("Deletion cancelled.")


def show_fund_management_menu() -> None:
    """Show the fund management menu (convenience function)."""
    fund_ui = FundUI()
    fund_ui.show_fund_management_menu()


def get_current_fund_info() -> Dict[str, Any]:
    """Get information about the currently active fund.
    
    Returns:
        Dictionary with current fund information
    """
    fund_manager = get_fund_manager()
    active_fund = fund_manager.get_active_fund()
    
    if not active_fund:
        return {
            "name": "No Active Fund",
            "data_directory": None,
            "exists": False
        }
    
    return {
        "name": active_fund,
        "data_directory": fund_manager.get_fund_data_directory(active_fund),
        "exists": True,
        "config": fund_manager.get_fund_config(active_fund)
    }
