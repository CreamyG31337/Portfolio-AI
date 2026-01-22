"""
Webull Trade Data Import System

This module provides functionality to import trade data from Webull CSV exports
and convert them to the trading bot's internal format.
"""

import csv
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import logging

from display.console_output import print_success, print_error, print_warning, print_info
from utils.fund_manager import get_fund_manager

logger = logging.getLogger(__name__)


class WebullImporter:
    """Handles import of Webull trade data into the trading system."""
    
    def __init__(self, fund_name: str = None):
        """Initialize the Webull importer.
        
        Args:
            fund_name: Name of the fund to import data into. If None, uses active fund.
        """
        self.fund_manager = get_fund_manager()
        self.fund_name = fund_name or self.fund_manager.get_active_fund()
        
        if not self.fund_name:
            raise ValueError("No fund specified and no active fund available")
        
        self.fund_dir = self.fund_manager.funds_dir / self.fund_name
        if not self.fund_dir.exists():
            raise ValueError(f"Fund directory '{self.fund_dir}' does not exist")
    
    def import_webull_csv(self, csv_file_path: str, dry_run: bool = False) -> Dict[str, Any]:
        """Import Webull CSV data into the trading system.
        
        Args:
            csv_file_path: Path to the Webull CSV file
            dry_run: If True, only validate and preview data without importing
            
        Returns:
            Dictionary with import results and statistics
        """
        try:
            # Parse the CSV file
            trades = self._parse_webull_csv(csv_file_path)
            
            if not trades:
                return {
                    "success": False,
                    "message": "No valid trades found in CSV file",
                    "trades_processed": 0
                }
            
            # Validate trades
            validation_results = self._validate_trades(trades)
            
            if not validation_results["valid"]:
                return {
                    "success": False,
                    "message": f"Validation failed: {validation_results['errors']}",
                    "trades_processed": 0
                }
            
            if dry_run:
                return self._preview_import(trades)
            
            # Import the trades
            import_results = self._import_trades(trades)
            
            return {
                "success": True,
                "message": f"Successfully imported {import_results['trades_imported']} trades",
                "trades_processed": len(trades),
                "trades_imported": import_results["trades_imported"],
                "trades_skipped": import_results["trades_skipped"],
                "portfolio_updates": import_results["portfolio_updates"],
                "trade_log_entries": import_results["trade_log_entries"]
            }
            
        except Exception as e:
            logger.error(f"Error importing Webull CSV: {e}")
            return {
                "success": False,
                "message": f"Import failed: {str(e)}",
                "trades_processed": 0
            }
    
    def _parse_webull_csv(self, csv_file_path: str) -> List[Dict[str, Any]]:
        """Parse Webull CSV file and extract trade data.
        
        Args:
            csv_file_path: Path to the CSV file
            
        Returns:
            List of parsed trade dictionaries
        """
        trades = []
        
        with open(csv_file_path, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            
            for row_num, row in enumerate(reader, 1):
                try:
                    trade = self._parse_webull_row(row, row_num)
                    if trade:
                        trades.append(trade)
                except Exception as e:
                    print_warning(f"Skipping row {row_num}: {e}")
                    continue
        
        return trades
    
    def _parse_webull_row(self, row: Dict[str, str], row_num: int) -> Optional[Dict[str, Any]]:
        """Parse a single row from Webull CSV.
        
        Args:
            row: CSV row as dictionary
            row_num: Row number for error reporting
            
        Returns:
            Parsed trade dictionary or None if invalid
        """
        try:
            # Extract basic trade information
            symbol = row.get('Symbol', '').strip()
            side = row.get('Side', '').strip()
            filled_qty = row.get('Filled Qty', '').strip()
            avg_price = row.get('Average Filled Price', '').strip()
            filled_time = row.get('Filled Time', '').strip()
            order_status = row.get('Order Status', '').strip()
            
            # Validate required fields
            if not all([symbol, side, filled_qty, avg_price, filled_time]):
                raise ValueError("Missing required fields")
            
            if order_status != 'Filled':
                raise ValueError(f"Order not filled (status: {order_status})")
            
            # Parse quantities and prices
            try:
                quantity = int(float(filled_qty))
                price = Decimal(avg_price)
            except (ValueError, TypeError) as e:
                raise ValueError(f"Invalid quantity or price: {e}")
            
            # Determine action based on side
            action = "Buy" if side.upper() == "BUY" else "Sell"
            
            # Parse timestamp
            timestamp = self._parse_webull_timestamp(filled_time)
            
            # Calculate total value
            total_value = quantity * price
            
            # Create trade record
            trade = {
                "symbol": symbol,
                "action": action,
                "quantity": quantity,
                "price": price,
                "total_value": total_value,
                "timestamp": timestamp,
                "original_timestamp": filled_time,  # Preserve original timestamp with timezone
                "currency": self._detect_currency(symbol),  # Detect currency based on ticker
                "source": "Webull",
                "original_row": row_num
            }
            
            return trade
            
        except Exception as e:
            raise ValueError(f"Row {row_num}: {e}")
    
    def _parse_webull_timestamp(self, timestamp_str: str) -> datetime:
        """Parse Webull timestamp string.
        
        Args:
            timestamp_str: Timestamp string from Webull (e.g., "09/03/2025 15:49:04 EDT")
            
        Returns:
            Parsed datetime object with timezone info preserved
        """
        try:
            # Parse the timestamp with timezone
            if " EDT" in timestamp_str:
                timestamp_clean = timestamp_str.replace(" EDT", "")
                dt = datetime.strptime(timestamp_clean, "%m/%d/%Y %H:%M:%S")
                # Add timezone info back
                return dt.replace(tzinfo=None)  # Keep as naive datetime but preserve the original format
            elif " EST" in timestamp_str:
                timestamp_clean = timestamp_str.replace(" EST", "")
                dt = datetime.strptime(timestamp_clean, "%m/%d/%Y %H:%M:%S")
                return dt.replace(tzinfo=None)
            else:
                # Fallback for timestamps without timezone
                return datetime.strptime(timestamp_str, "%m/%d/%Y %H:%M:%S")
            
        except ValueError as e:
            raise ValueError(f"Invalid timestamp format: {timestamp_str} - {e}")
    
    def _validate_trades(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Validate parsed trades for consistency and completeness.
        
        Args:
            trades: List of parsed trade dictionaries
            
        Returns:
            Validation results dictionary
        """
        errors = []
        warnings = []
        
        # Check for duplicate trades (same symbol, action, quantity, price, time)
        seen_trades = set()
        for trade in trades:
            trade_key = (
                trade["symbol"],
                trade["action"],
                trade["quantity"],
                trade["price"],
                trade["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
            )
            
            if trade_key in seen_trades:
                warnings.append(f"Duplicate trade detected: {trade['symbol']} {trade['action']} {trade['quantity']} @ {trade['price']}")
            else:
                seen_trades.add(trade_key)
        
        # Check for unusual prices (very high or very low)
        for trade in trades:
            if trade["price"] > 10000:
                warnings.append(f"Unusually high price for {trade['symbol']}: ${trade['price']}")
            elif trade["price"] < 0.01:
                warnings.append(f"Unusually low price for {trade['symbol']}: ${trade['price']}")
        
        # Check for unusual quantities
        for trade in trades:
            if trade["quantity"] > 10000:
                warnings.append(f"Unusually high quantity for {trade['symbol']}: {trade['quantity']}")
            elif trade["quantity"] <= 0:
                errors.append(f"Invalid quantity for {trade['symbol']}: {trade['quantity']}")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }
    
    def _preview_import(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Preview what would be imported without actually importing.
        
        Args:
            trades: List of parsed trade dictionaries
            
        Returns:
            Preview results dictionary
        """
        # Group trades by symbol and action
        symbol_summary = {}
        total_value = Decimal('0')
        
        for trade in trades:
            symbol = trade["symbol"]
            action = trade["action"]
            quantity = trade["quantity"]
            price = trade["price"]
            value = trade["total_value"]
            
            if symbol not in symbol_summary:
                symbol_summary[symbol] = {"Buy": 0, "Sell": 0, "net_quantity": 0, "total_value": Decimal('0')}
            
            symbol_summary[symbol][action] += quantity
            symbol_summary[symbol]["total_value"] += value
            symbol_summary[symbol]["net_quantity"] += quantity if action == "Buy" else -quantity
            total_value += value if action == "Buy" else -value
        
        return {
            "success": True,
            "message": f"Preview: {len(trades)} trades ready for import",
            "trades_processed": len(trades),
            "total_value": float(total_value),
            "symbol_summary": symbol_summary,
            "preview": True
        }
    
    def _import_trades(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Import trades into the trading system.
        
        Args:
            trades: List of parsed trade dictionaries
            
        Returns:
            Import results dictionary
        """
        trades_imported = 0
        trades_skipped = 0
        portfolio_updates = 0
        trade_log_entries = 0
        
        # Load existing portfolio data
        portfolio_data = self._load_portfolio_data()
        trade_log_data = self._load_trade_log_data()
        
        # Create a set of existing trades for idempotency
        # Key: (Date, Ticker, Shares, Price)
        existing_trades = set()
        for entry in trade_log_data:
            try:
                # Format: Date, Ticker, Shares, Price, Cost Basis, PnL, Reason, Currency
                # We normalize to string representation to be safe.
                key = (
                    entry.get("Date", "").strip(),
                    entry.get("Ticker", "").strip(),
                    str(float(entry.get("Shares", "0"))),  # Normalize number format
                    str(float(entry.get("Price", "0")))    # Normalize number format
                )
                existing_trades.add(key)
            except (ValueError, TypeError):
                continue

        for trade in trades:
            try:
                # Add to trade log
                trade_log_entry = self._create_trade_log_entry(trade)

                # Check if exists
                entry_key = (
                    trade_log_entry["Date"].strip(),
                    trade_log_entry["Ticker"].strip(),
                    str(float(trade_log_entry["Shares"])),
                    str(float(trade_log_entry["Price"]))
                )

                if entry_key in existing_trades:
                    # Duplicate found
                    # We count it as skipped but don't consider it an error
                    continue

                trade_log_data.append(trade_log_entry)
                trade_log_entries += 1
                
                # Update portfolio
                portfolio_updated = self._update_portfolio(portfolio_data, trade)
                if portfolio_updated:
                    portfolio_updates += 1
                
                trades_imported += 1
                # Add to local set to catch duplicates within the same batch
                existing_trades.add(entry_key)
                
            except Exception as e:
                print_warning(f"Failed to import trade {trade['symbol']} {trade['action']}: {e}")
                trades_skipped += 1
                continue
        
        # Save updated data
        self._save_portfolio_data(portfolio_data)
        self._save_trade_log_data(trade_log_data)
        
        return {
            "trades_imported": trades_imported,
            "trades_skipped": trades_skipped,
            "portfolio_updates": portfolio_updates,
            "trade_log_entries": trade_log_entries
        }
    
    def _create_trade_log_entry(self, trade: Dict[str, Any]) -> Dict[str, Any]:
        """Create a trade log entry from a trade.

        Args:
            trade: Trade dictionary

        Returns:
            Trade log entry dictionary
        """
        # Preserve the original timezone from the Webull data
        original_timestamp = trade.get("original_timestamp", "")
        if "EDT" in original_timestamp:
            timezone_suffix = " EDT"
        elif "EST" in original_timestamp:
            timezone_suffix = " EST"
        else:
            timezone_suffix = " EDT"  # Default to EDT

        # Create proper reason based on action for rebuild script compatibility
        action = trade.get("action", "Buy")
        if action.upper() == "SELL":
            reason = f"Sell - Limit Order"
        elif action.upper() == "BUY":
            reason = f"Buy - Limit Order"
        else:
            reason = f"Imported from Webull (Row {trade['original_row']})"

        return {
            "Date": trade["timestamp"].strftime("%Y-%m-%d %H:%M:%S") + timezone_suffix,
            "Ticker": trade["symbol"],
            "Shares": trade["quantity"],
            "Price": float(trade["price"]),
            "Cost Basis": float(trade["total_value"]),
            "PnL": 0.0,
            "Reason": reason,
            "Currency": trade["currency"]
        }
    
    def _update_portfolio(self, portfolio_data: List[Dict[str, Any]], trade: Dict[str, Any]) -> bool:
        """Update portfolio data with a trade.
        
        Args:
            portfolio_data: Current portfolio data
            trade: Trade to process
            
        Returns:
            True if portfolio was updated, False otherwise
        """
        symbol = trade["symbol"]
        action = trade["action"]
        quantity = trade["quantity"]
        price = trade["price"]
        
        # Find existing position
        existing_position = None
        for i, position in enumerate(portfolio_data):
            if position.get("Ticker") == symbol:
                existing_position = i
                break
        
        if action == "Buy":
            if existing_position is not None:
                # Update existing position
                position = portfolio_data[existing_position]
                old_shares = int(position.get("Shares", 0))
                old_avg_price = Decimal(str(position.get("Average Price", 0)))
                old_cost_basis = Decimal(str(position.get("Cost Basis", 0)))
                
                new_shares = old_shares + quantity
                new_cost_basis = old_cost_basis + (quantity * price)
                new_avg_price = new_cost_basis / new_shares if new_shares > 0 else Decimal('0')
                
                position["Shares"] = new_shares
                position["Average Price"] = float(new_avg_price)
                position["Cost Basis"] = float(new_cost_basis)
                position["Total Value"] = float(new_shares * price)  # Current value
                position["PnL"] = float((new_shares * price) - new_cost_basis)
            else:
                # Create new position
                new_position = {
                    "Date": trade["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
                    "Ticker": symbol,
                    "Shares": quantity,
                    "Average Price": float(price),
                    "Cost Basis": float(quantity * price),
                    "Stop Loss": 0.0,
                    "Current Price": float(price),
                    "Total Value": float(quantity * price),
                    "PnL": 0.0,
                    "Action": "Buy",
                    "Company": self._get_company_name(symbol, currency=trade["currency"]),
                    "Currency": trade["currency"]
                }
                portfolio_data.append(new_position)
            
            return True
            
        elif action == "Sell":
            if existing_position is not None:
                position = portfolio_data[existing_position]
                current_shares = int(position.get("Shares", 0))
                
                if current_shares >= quantity:
                    # Partial or complete sell
                    remaining_shares = current_shares - quantity
                    old_cost_basis = Decimal(str(position.get("Cost Basis", 0)))
                    cost_per_share = old_cost_basis / current_shares if current_shares > 0 else Decimal('0')
                    remaining_cost_basis = remaining_shares * cost_per_share
                    
                    if remaining_shares > 0:
                        # Partial sell - update position
                        position["Shares"] = remaining_shares
                        position["Cost Basis"] = float(remaining_cost_basis)
                        position["Average Price"] = float(cost_per_share)
                        position["Total Value"] = float(remaining_shares * price)
                        position["PnL"] = float((remaining_shares * price) - remaining_cost_basis)
                    else:
                        # Complete sell - remove position
                        portfolio_data.pop(existing_position)
                else:
                    # Short sell or error
                    print_warning(f"Cannot sell {quantity} shares of {symbol} - only {current_shares} available")
                    return False
            else:
                print_warning(f"Cannot sell {symbol} - no existing position")
                return False
            
            return True
        
        return False
    
    def _load_portfolio_data(self) -> List[Dict[str, Any]]:
        """Load existing portfolio data from CSV."""
        portfolio_file = self.fund_dir / "llm_portfolio_update.csv"
        
        if not portfolio_file.exists():
            return []
        
        portfolio_data = []
        with open(portfolio_file, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                portfolio_data.append(row)
        
        return portfolio_data
    
    def _save_portfolio_data(self, portfolio_data: List[Dict[str, Any]]) -> None:
        """Save portfolio data to CSV."""
        portfolio_file = self.fund_dir / "llm_portfolio_update.csv"
        
        if not portfolio_data:
            return
        
        fieldnames = [
            "Date", "Ticker", "Shares", "Average Price", "Cost Basis", "Stop Loss",
            "Current Price", "Total Value", "PnL", "Action", "Company", "Currency"
        ]
        
        with open(portfolio_file, 'w', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(portfolio_data)
    
    def _load_trade_log_data(self) -> List[Dict[str, Any]]:
        """Load existing trade log data from CSV."""
        trade_log_file = self.fund_dir / "llm_trade_log.csv"
        
        if not trade_log_file.exists():
            return []
        
        trade_log_data = []
        with open(trade_log_file, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                trade_log_data.append(row)
        
        return trade_log_data
    
    def _save_trade_log_data(self, trade_log_data: List[Dict[str, Any]]) -> None:
        """Save trade log data to CSV."""
        trade_log_file = self.fund_dir / "llm_trade_log.csv"
        
        if not trade_log_data:
            return
        
        fieldnames = ["Date", "Ticker", "Shares", "Price", "Cost Basis", "PnL", "Reason", "Currency"]
        
        with open(trade_log_file, 'w', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(trade_log_data)

    def _detect_currency(self, ticker: str) -> str:
        """Detect currency based on ticker characteristics."""
        ticker = ticker.upper().strip()
        
        # Check for Canadian ticker suffixes
        if any(ticker.endswith(suffix) for suffix in ['.TO', '.V', '.CN', '.NE']):
            return 'CAD'
        
        # Default to USD for everything else
        # No hardcoded lists - rely on Currency field in trade log
        return 'USD'

    def _get_company_name(self, ticker: str, currency: str = None) -> str:
        """Get company name for ticker symbol using the ticker_utils function."""
        try:
            from utils.ticker_utils import get_company_name
            return get_company_name(ticker, currency=currency)
        except Exception as e:
            logger.warning(f"Failed to get company name for {ticker}: {e}")
            return ticker  # Fallback to ticker symbol


def import_webull_data(csv_file_path: str, fund_name: str = None, dry_run: bool = False) -> Dict[str, Any]:
    """Convenience function to import Webull data.
    
    Args:
        csv_file_path: Path to the Webull CSV file
        fund_name: Name of the fund to import into (optional)
        dry_run: If True, only preview the import
        
    Returns:
        Import results dictionary
    """
    try:
        importer = WebullImporter(fund_name)
        return importer.import_webull_csv(csv_file_path, dry_run)
    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to initialize importer: {str(e)}",
            "trades_processed": 0
        }
