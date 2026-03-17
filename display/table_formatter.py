"""Table formatter module for Rich table formatting and portfolio display.

This module provides table formatting functionality using Rich tables with fallback
to plain text display. It includes JSON output capability for future web dashboard API
and handles data from any repository type.
"""

import json
import math
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union

# Optional pandas import
try:
    import pandas as pd
    _HAS_PANDAS = True
except ImportError:
    _HAS_PANDAS = False
    pd = None

# Import display utilities
from .console_output import print_info, get_console, has_rich_support
from .terminal_utils import get_optimal_table_width, is_using_test_data

# Rich imports with fallback
try:
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False

# Colorama imports for fallback
try:
    from colorama import Fore, Style
except ImportError:
    class DummyColor:
        def __getattr__(self, name):
            return ""
    Fore = Style = DummyColor()


class TableFormatter:
    """Table formatter class for creating portfolio and financial tables.
    
    This class handles both Rich table formatting and plain text fallback,
    with JSON output capability for future web dashboard integration.
    """
    
    def __init__(self, data_dir: Optional[str] = None, web_mode: bool = False):
        """Initialize the table formatter.
        
        Args:
            data_dir: Optional data directory path for context
            web_mode: Whether to optimize for web display
        """
        self.data_dir = data_dir
        self.web_mode = web_mode
        self.console = get_console()
        self.optimal_width = get_optimal_table_width(data_dir)
        self.using_test_data = is_using_test_data(data_dir)
    
    def _format_shares_for_display(self, shares_value) -> str:
        """Format shares for display with at least 2 decimal places when needed.
        
        Args:
            shares_value: The number of shares to format
            
        Returns:
            Formatted string with appropriate decimal places
        """
        if not shares_value or shares_value == 0:
            return "0"
        
        try:
            shares_float = float(shares_value)
            
            # Always show at least 2 decimal places for fractional shares
            if shares_float == int(shares_float):
                # Whole number - show as integer
                return f"{int(shares_float):,}"
            else:
                # Fractional shares - show with at least 2 decimal places
                # Format with 2 decimals and remove trailing zeros
                formatted = f"{shares_float:,.2f}".rstrip('0').rstrip('.')
                # If we removed too much, ensure we have at least 2 decimal places
                if '.' not in formatted:
                    formatted = f"{shares_float:,.2f}"
                return formatted
        except (ValueError, TypeError):
            return str(shares_value)
    
    def create_portfolio_table(self, portfolio_data: Union[List[Dict[str, Any]], 'pd.DataFrame'], 
                             current_date: Optional[str] = None,
                             output_format: str = "display") -> Optional[str]:
        """Create a portfolio table display with current prices, P&L, and position weights.
        
        Args:
            portfolio_data: List of portfolio position dictionaries OR pandas DataFrame (for backward compatibility)
            current_date: Optional current date string for title
            output_format: Output format - "display", "json", or "html"
            
        Returns:
            JSON string if output_format is "json", None otherwise
        """
        # Handle pandas DataFrame input for backward compatibility
        if _HAS_PANDAS and hasattr(portfolio_data, 'empty'):
            if portfolio_data.empty:
                print_info("Portfolio is currently empty")
                return None if output_format == "display" else json.dumps({"portfolio": []})
            # Convert DataFrame to list of dictionaries
            portfolio_data = portfolio_data.to_dict('records')
        elif not portfolio_data:
            print_info("Portfolio is currently empty")
            return None if output_format == "display" else json.dumps({"portfolio": []})
        
        # Prepare data for different output formats
        if output_format == "json":
            return self._create_portfolio_json(portfolio_data, current_date)
        elif output_format == "html":
            return self._create_portfolio_html(portfolio_data, current_date)
        else:
            return self._create_portfolio_display(portfolio_data, current_date)
    
    def _create_portfolio_display(self, portfolio_data: List[Dict[str, Any]], 
                                current_date: Optional[str] = None) -> None:
        """Create portfolio table for console display."""
        if not current_date:
            current_date = datetime.now().strftime("%Y-%m-%d")
        
        # Create safe table title for environments that can't handle Unicode
        from display.console_output import _safe_emoji
        safe_chart_emoji = _safe_emoji("📊")
        table_title = f"{safe_chart_emoji} Portfolio Snapshot - {current_date}"
        
        if has_rich_support() and self.console:
            self._create_rich_portfolio_table(portfolio_data, table_title)
        else:
            self._create_plain_portfolio_table(portfolio_data, table_title)
    
    def _create_rich_portfolio_table(self, portfolio_data: List[Dict[str, Any]], 
                                   table_title: str) -> None:
        """Create Rich-formatted portfolio table."""
        # Import safe emoji function
        from display.console_output import _safe_emoji
        
        # Determine optimal column widths based on environment
        company_max_width = 25 if self.optimal_width >= 140 else 15
        if self.using_test_data:
            company_max_width = 12  # Even more conservative for test data
        
        table = Table(
            title=table_title,
            show_header=True,
            header_style="bold magenta"
        )
        # Create safe column headers (headers can wrap, data stays no_wrap where appropriate)
        table.add_column(f"{_safe_emoji('🎯')}\nTicker", style="cyan", no_wrap=True, width=7, header_style="bold magenta")
        table.add_column(f"{_safe_emoji('🏢')}\nCompany", style="white", no_wrap=True, max_width=company_max_width, justify="left", header_style="bold magenta")
        table.add_column(f"{_safe_emoji('📅')}\nOpened", style="dim", no_wrap=True, width=11, header_style="bold magenta")
        table.add_column(f"{_safe_emoji('📈')}\nShares", justify="right", style="bright_white", width=10, header_style="bold magenta")
        table.add_column(f"{_safe_emoji('💵')}\nAvg Price", justify="right", style="yellow", width=11, header_style="bold magenta")
        table.add_column(f"{_safe_emoji('💰')}\nCurrent", justify="right", style="white", width=10, header_style="bold magenta")
        table.add_column(f"{_safe_emoji('💵')}\nValue", justify="right", style="bright_yellow", width=12, header_style="bold magenta")
        table.add_column(f"{_safe_emoji('📊')}\nTotal P&L", justify="right", style="magenta", width=17, header_style="bold magenta")
        # Column widths optimized for 1920x1080 with 125% scaling (Windows 11) - ~157 character terminal width
        table.add_column(f"{_safe_emoji('📈')}\n1-Day P&L", justify="right", style="cyan", width=16, header_style="bold magenta")
        table.add_column(f"{_safe_emoji('📊')}\n5-Day P&L", justify="right", style="bright_magenta", width=15, header_style="bold magenta")
        table.add_column(f"{_safe_emoji('🍕')}\nWght", justify="right", style="bright_blue", width=8, header_style="bold magenta")
        table.add_column(f"{_safe_emoji('🛑')}\nStop Loss", justify="right", style="red", width=8, header_style="bold magenta")
        
        def format_shares(shares_value):
            """Format shares with up to 6 significant digits, adjusting decimals based on magnitude."""
            from decimal import Decimal
            
            if shares_value == 0:
                return "0"
            
            # Ensure we're working with a Decimal, not float
            if isinstance(shares_value, float):
                shares = Decimal(str(shares_value))  # Convert float to Decimal via string to avoid precision issues
            else:
                shares = Decimal(str(shares_value))
            
            shares_float = float(shares)  # Only convert to float for final formatting
            if shares_float >= 1000:
                # For 1000+: show no decimals (e.g., 1234)
                return f"{shares_float:.0f}"
            elif shares_float >= 100:
                # For 100-999: show 3 decimals max (e.g., 123.456)
                return f"{shares_float:.3f}".rstrip('0').rstrip('.')
            elif shares_float >= 10:
                # For 10-99: show 4 decimals max (e.g., 12.3456)
                return f"{shares_float:.4f}".rstrip('0').rstrip('.')
            elif shares_float >= 1:
                # For 1-9: show 5 decimals max (e.g., 1.23456)
                return f"{shares_float:.5f}".rstrip('0').rstrip('.')
            else:
                # For <1: show 6 decimals max (e.g., 0.123456)
                return f"{shares_float:.6f}".rstrip('0').rstrip('.')
        
        def format_ticker_for_display(ticker: str) -> str:
            """Format ticker for display by removing common suffixes to save space."""
            if not ticker or ticker == 'N/A':
                return ticker
            
            # Common suffixes to remove for display
            suffixes_to_remove = ['.TO', '.V', '.CN', '.NE', '.TSX', '.TSXV']
            
            for suffix in suffixes_to_remove:
                if ticker.upper().endswith(suffix):
                    return ticker[:-len(suffix)]
            
            return ticker
        
        for row_index, position in enumerate(portfolio_data):
            # Determine background color for alternating rows (zebra stripes)
            row_style = "on grey11" if row_index % 2 == 1 else None

            # Truncate long company names for display
            company_raw = position.get('company', 'N/A')

            # Normalize company name to safe string for display
            if isinstance(company_raw, str):
                company_name = company_raw.strip() or 'N/A'
            elif isinstance(company_raw, (int, float)):
                if isinstance(company_raw, float) and math.isnan(company_raw):
                    company_name = 'N/A'
                else:
                    company_name = str(company_raw)
            else:
                company_name = 'N/A'

            display_name = (company_name[:company_max_width-3] + "..."
                            if len(company_name) > company_max_width
                            else company_name)
            
            # Calculate total value (handle Decimals properly)
            from decimal import Decimal
            
            shares_raw = position.get('shares', 0)
            current_price_raw = position.get('current_price', 0)
            
            # Ensure we're working with Decimals, not floats
            if isinstance(shares_raw, float):
                shares = Decimal(str(shares_raw))
            else:
                shares = Decimal(str(shares_raw)) if shares_raw != 0 else Decimal('0')
            
            if isinstance(current_price_raw, float):
                current_price = Decimal(str(current_price_raw)) if current_price_raw > 0 else Decimal('0')
            else:
                current_price = Decimal(str(current_price_raw)) if current_price_raw and current_price_raw > 0 else Decimal('0')
            
            total_value = shares * current_price if current_price > 0 else Decimal('0')
            total_value_display = f"${float(total_value):.2f}" if total_value > 0 else "N/A"

            # Calculate P&L values (handle Decimals properly)
            unrealized_pnl_raw = position.get('unrealized_pnl', 0) or 0
            cost_basis_raw = position.get('cost_basis', 0) or 0
            avg_price_raw = position.get('avg_price', 0) or 0
            
            # Convert to Decimal if needed
            if isinstance(unrealized_pnl_raw, float):
                unrealized_pnl = Decimal(str(unrealized_pnl_raw))
            else:
                unrealized_pnl = Decimal(str(unrealized_pnl_raw)) if unrealized_pnl_raw != 0 else Decimal('0')
            
            if isinstance(cost_basis_raw, float):
                cost_basis = Decimal(str(cost_basis_raw))
            else:
                cost_basis = Decimal(str(cost_basis_raw)) if cost_basis_raw != 0 else Decimal('0')
            
            if isinstance(avg_price_raw, float):
                avg_price = Decimal(str(avg_price_raw))
            else:
                avg_price = Decimal(str(avg_price_raw)) if avg_price_raw != 0 else Decimal('0')
            
            # Calculate total P&L percentage with color coding (dollar amount first, then percentage)
            if cost_basis > 0:
                total_pnl_pct = float((unrealized_pnl / cost_basis) * 100)
                if total_pnl_pct > 0:
                    total_pnl_display = f"[green]${float(unrealized_pnl):,.2f} +{total_pnl_pct:.1f}%[/green]"
                elif total_pnl_pct < 0:
                    total_pnl_display = f"[red]${float(abs(unrealized_pnl)):,.2f} {total_pnl_pct:.1f}%[/red]"
                else:
                    total_pnl_display = f"[cyan]${float(unrealized_pnl):,.2f} {total_pnl_pct:.1f}%[/cyan]"
            elif avg_price > 0 and current_price > 0:
                total_pnl_pct = float(((current_price - avg_price) / avg_price) * 100)
                if total_pnl_pct > 0:
                    total_pnl_display = f"[green]${float(unrealized_pnl):,.2f} +{total_pnl_pct:.1f}%[/green]"
                elif total_pnl_pct < 0:
                    total_pnl_display = f"[red]${float(abs(unrealized_pnl)):,.2f} {total_pnl_pct:.1f}%[/red]"
                else:
                    total_pnl_display = f"[cyan]${float(unrealized_pnl):,.2f} {total_pnl_pct:.1f}%[/cyan]"
            else:
                total_pnl_display = 'N/A'

            # Daily P&L (already calculated in trading_script.py as dollar amount)
            daily_pnl_dollar = position.get('daily_pnl', 'N/A')
            if daily_pnl_dollar != 'N/A' and daily_pnl_dollar != '$0.00':
                # Extract numeric value from daily_pnl_dollar (remove $ and convert to Decimal)
                daily_pnl_str = daily_pnl_dollar.replace('$', '').replace(',', '').replace('*', '')
                try:
                    daily_pnl_value = Decimal(daily_pnl_str)
                except:
                    daily_pnl_value = Decimal('0')

                # Calculate daily P&L percentage based on cost basis (previous day value)
                cost_basis = position.get('cost_basis', Decimal('0'))
                if cost_basis and cost_basis > 0:
                    daily_pnl_pct = float((float(daily_pnl_value) / float(cost_basis) * 100))
                else:
                    daily_pnl_pct = 0

                if daily_pnl_pct > 0:
                    daily_pnl_display = f"[green]${float(daily_pnl_value):,.2f} +{daily_pnl_pct:.1f}%[/green]"
                elif daily_pnl_pct < 0:
                    daily_pnl_display = f"[red]${float(abs(daily_pnl_value)):,.2f} {daily_pnl_pct:.1f}%[/red]"
                else:
                    daily_pnl_display = f"[cyan]${float(daily_pnl_value):,.2f} {daily_pnl_pct:.1f}%[/cyan]"
            else:
                # When daily P&L is $0.00 or N/A, percentage should also be 0.00%
                daily_pnl_display = "[cyan]$0.00 0.0%[/cyan]"
            
            # Get position weight from enhanced data
            weight_display = position.get('position_weight', 'N/A')
            
            # Format 5-day P&L with color coding (or partial period P&L)
            # Color Scheme:
            # - ORANGE: 1-2 days held (very new positions)
            # - YELLOW: 3-4 days held (partial periods)
            # - GREEN: 5+ days held with positive returns (contains '+' in percentage)
            # - RED: 5+ days held with negative returns (contains '-' in percentage)
            # - DEFAULT: Zero change or N/A
            five_day_pnl_raw = position.get('five_day_pnl', 'N/A')
            if five_day_pnl_raw != 'N/A':
                # Check if this is a partial period using the stored period type
                period_type = position.get('five_day_period_type', '')
                try:
                    # Determine color based on days held
                    if period_type in ['1d', '2d']:
                        # Orange for very new positions (1-2 days)
                        five_day_pnl_display = f"[orange1]{five_day_pnl_raw}[/orange1]"
                    elif period_type in ['3d', '4d']:
                        # Yellow for partial periods (3-4 days)
                        five_day_pnl_display = f"[yellow]{five_day_pnl_raw}[/yellow]"
                    else:
                        # Full 5-day+ period: use green/red based on performance
                        if '+' in five_day_pnl_raw:
                            five_day_pnl_display = f"[green]{five_day_pnl_raw}[/green]"
                        elif '-' in five_day_pnl_raw:
                            five_day_pnl_display = f"[red]{five_day_pnl_raw}[/red]"
                        else:
                            # Edge case: exactly 0% change
                            five_day_pnl_display = f"[cyan]{five_day_pnl_raw}[/cyan]"
                except:
                    # Fallback if parsing fails
                    five_day_pnl_display = five_day_pnl_raw
            else:
                five_day_pnl_display = 'N/A'
            
            # Color code ticker based on currency (remove suffixes for display)
            ticker = position.get('ticker', 'N/A')
            currency = position.get('currency', 'CAD')
            display_ticker = format_ticker_for_display(ticker)
            
            if currency == 'USD':
                ticker_display = f"[blue]{display_ticker}[/blue]"  # Blue for USD
            elif currency == 'CAD':
                ticker_display = f"[cyan]{display_ticker}[/cyan]"  # Cyan for CAD
            else:
                ticker_display = display_ticker  # Default color for unknown currencies
            
            table.add_row(
                ticker_display,
                display_name,
                position.get('opened_date', 'N/A'),
                format_shares(position.get('shares', 0)),
                f"${float(avg_price):.2f}",  # Average purchase price per share
                f"${float(current_price):.2f}" if current_price > 0 else "N/A",  # Current market price
                total_value_display,  # Total Value (shares * current price)
                total_pnl_display,  # Combined Total P&L: percentage [dollar amount]
                daily_pnl_display,  # Combined Daily P&L: percentage [dollar amount]
                five_day_pnl_display,  # 5-day P&L with color formatting
                weight_display,  # Position weight from enhanced data
                f"${float(Decimal(str(position.get('stop_loss', 0)))):.2f}" if position.get('stop_loss', 0) > 0 else "None",
                style=row_style  # Apply alternating background color
            )
        
        self.console.print(table)
    
    def _create_plain_portfolio_table(self, portfolio_data: List[Dict[str, Any]], 
                                    table_title: str) -> None:
        """Create plain text portfolio table."""
        print(f"\\n{Fore.MAGENTA}{table_title}:{Style.RESET_ALL}")
        
        def format_shares_plain(shares_value):
            """Format shares with up to 6 significant digits, adjusting decimals based on magnitude."""
            from decimal import Decimal
            
            if shares_value == 0:
                return "0"
            
            # Ensure we're working with a Decimal, not float
            if isinstance(shares_value, float):
                shares = Decimal(str(shares_value))  # Convert float to Decimal via string to avoid precision issues
            else:
                shares = Decimal(str(shares_value))
            
            shares_float = float(shares)  # Only convert to float for final formatting
            if shares_float >= 1000:
                # For 1000+: show no decimals (e.g., 1234)
                return f"{shares_float:.0f}"
            elif shares_float >= 100:
                # For 100-999: show 3 decimals max (e.g., 123.456)
                return f"{shares_float:.3f}".rstrip('0').rstrip('.')
            elif shares_float >= 10:
                # For 10-99: show 4 decimals max (e.g., 12.3456)
                return f"{shares_float:.4f}".rstrip('0').rstrip('.')
            elif shares_float >= 1:
                # For 1-9: show 5 decimals max (e.g., 1.23456)
                return f"{shares_float:.5f}".rstrip('0').rstrip('.')
            else:
                # For <1: show 6 decimals max (e.g., 0.123456)
                return f"{shares_float:.6f}".rstrip('0').rstrip('.')
        
        def format_ticker_for_display_plain(ticker: str) -> str:
            """Format ticker for display by removing common suffixes to save space."""
            if not ticker or ticker == 'N/A':
                return ticker
            
            # Common suffixes to remove for display
            suffixes_to_remove = ['.TO', '.V', '.CN', '.NE', '.TSX', '.TSXV']
            
            for suffix in suffixes_to_remove:
                if ticker.upper().endswith(suffix):
                    return ticker[:-len(suffix)]
            
            return ticker
        
        # Convert to DataFrame for better plain text formatting
        df_data = []
        for position in portfolio_data:
            # Calculate values (handle Decimals properly)
            from decimal import Decimal
            
            shares_raw = position.get('shares', 0)
            current_price_raw = position.get('current_price', 0)
            avg_price_raw = position.get('avg_price', 0)
            cost_basis_raw = position.get('cost_basis', 0)
            unrealized_pnl_raw = position.get('unrealized_pnl', 0)
            
            # Convert to Decimal if needed
            if isinstance(shares_raw, float):
                shares = Decimal(str(shares_raw))
            else:
                shares = Decimal(str(shares_raw)) if shares_raw != 0 else Decimal('0')
            
            if isinstance(current_price_raw, float):
                current_price = Decimal(str(current_price_raw)) if current_price_raw > 0 else Decimal('0')
            else:
                current_price = Decimal(str(current_price_raw)) if current_price_raw and current_price_raw > 0 else Decimal('0')
            
            if isinstance(avg_price_raw, float):
                avg_price = Decimal(str(avg_price_raw))
            else:
                avg_price = Decimal(str(avg_price_raw)) if avg_price_raw != 0 else Decimal('0')
            
            if isinstance(cost_basis_raw, float):
                cost_basis = Decimal(str(cost_basis_raw))
            else:
                cost_basis = Decimal(str(cost_basis_raw)) if cost_basis_raw != 0 else Decimal('0')
            
            if isinstance(unrealized_pnl_raw, float):
                unrealized_pnl = Decimal(str(unrealized_pnl_raw))
            else:
                unrealized_pnl = Decimal(str(unrealized_pnl_raw)) if unrealized_pnl_raw != 0 else Decimal('0')
            
            total_value = shares * current_price if current_price > 0 else Decimal('0')
            
            # Calculate P&L percentage with color coding (dollar amount first, then percentage)
            if cost_basis > 0:
                total_pnl_pct = float((unrealized_pnl / cost_basis) * 100)
                if total_pnl_pct > 0:
                    total_pnl_display = f"{Fore.GREEN}${float(unrealized_pnl):,.2f} +{total_pnl_pct:.1f}%{Style.RESET_ALL}"
                elif total_pnl_pct < 0:
                    total_pnl_display = f"{Fore.RED}${float(abs(unrealized_pnl)):,.2f} {total_pnl_pct:.1f}%{Style.RESET_ALL}"
                else:
                    total_pnl_display = f"${float(unrealized_pnl):,.2f} {total_pnl_pct:.1f}%"
            elif avg_price > 0 and current_price > 0:
                total_pnl_pct = float(((current_price - avg_price) / avg_price) * 100)
                if total_pnl_pct > 0:
                    total_pnl_display = f"{Fore.GREEN}${float(unrealized_pnl):,.2f} +{total_pnl_pct:.1f}%{Style.RESET_ALL}"
                elif total_pnl_pct < 0:
                    total_pnl_display = f"{Fore.RED}${float(abs(unrealized_pnl)):,.2f} {total_pnl_pct:.1f}%{Style.RESET_ALL}"
                else:
                    total_pnl_display = f"${float(unrealized_pnl):,.2f} {total_pnl_pct:.1f}%"
            else:
                total_pnl_display = 'N/A'
            
            # Daily P&L with color coding
            daily_pnl_dollar = position.get('daily_pnl', 'N/A')
            if daily_pnl_dollar != 'N/A' and daily_pnl_dollar != '$0.00':
                if avg_price > 0 and current_price > 0:
                    daily_pnl_pct = float(((current_price - avg_price) / avg_price) * 100)
                    # Extract numeric value from daily_pnl_dollar (remove $ and convert to Decimal)
                    daily_pnl_str = daily_pnl_dollar.replace('$', '').replace(',', '').replace('*', '')
                    try:
                        daily_pnl_value = Decimal(daily_pnl_str)
                    except:
                        daily_pnl_value = Decimal('0')
                    if daily_pnl_pct > 0:
                        daily_pnl_display = f"{Fore.GREEN}${float(daily_pnl_value):,.2f} +{daily_pnl_pct:.1f}%{Style.RESET_ALL}"
                    elif daily_pnl_pct < 0:
                        daily_pnl_display = f"{Fore.RED}${float(abs(daily_pnl_value)):,.2f} {daily_pnl_pct:.1f}%{Style.RESET_ALL}"
                    else:
                        daily_pnl_display = f"${float(daily_pnl_value):,.2f} {daily_pnl_pct:.1f}%"
                else:
                    daily_pnl_display = f"N/A {daily_pnl_dollar}"
            else:
                daily_pnl_display = daily_pnl_dollar
            
            # Format 5-day P&L with color coding for plain text (or partial period P&L)
            five_day_pnl_raw = position.get('five_day_pnl', 'N/A')
            if five_day_pnl_raw != 'N/A':
                # Parse the P&L string for plain text color coding
                try:
                    # Check if it's a partial period (indicated by "2d:", "3d:", "4d:" prefix)
                    if any(prefix in five_day_pnl_raw for prefix in ['2d:', '3d:', '4d:']):
                        # Yellow color for partial periods (less than 5 days)
                        five_day_pnl_display_plain = f"{Fore.YELLOW}{five_day_pnl_raw}{Style.RESET_ALL}"
                    else:
                        # Full 5-day period: use green/red based on performance
                        if '+' in five_day_pnl_raw:
                            five_day_pnl_display_plain = f"{Fore.GREEN}{five_day_pnl_raw}{Style.RESET_ALL}"
                        elif '-' in five_day_pnl_raw:
                            five_day_pnl_display_plain = f"{Fore.RED}{five_day_pnl_raw}{Style.RESET_ALL}"
                        else:
                            # Edge case: exactly 0% change
                            five_day_pnl_display_plain = five_day_pnl_raw
                except:
                    # Fallback if parsing fails
                    five_day_pnl_display_plain = five_day_pnl_raw
            else:
                five_day_pnl_display_plain = 'N/A'
            
            # Color code ticker based on currency for plain text (remove suffixes for display)
            ticker = position.get('ticker', 'N/A')
            currency = position.get('currency', 'CAD')
            display_ticker = format_ticker_for_display_plain(ticker)
            
            if currency == 'USD':
                ticker_display = f"{Fore.BLUE}{display_ticker}{Style.RESET_ALL}"  # Blue for USD
            elif currency == 'CAD':
                ticker_display = f"{Fore.CYAN}{display_ticker}{Style.RESET_ALL}"  # Cyan for CAD
            else:
                ticker_display = display_ticker  # Default color for unknown currencies
            
            df_data.append({
                'Ticker': ticker_display,
                'Company': position.get('company', 'N/A'),
                'Opened': position.get('opened_date', 'N/A'),
                'Shares': format_shares_plain(shares),
                'Price': f"${float(avg_price):.2f}",
                'Current': f"${float(current_price):.2f}" if current_price > 0 else "N/A",
                'Total Value': f"${float(total_value):.2f}" if total_value > 0 else "N/A",
                'Dollar P&L': f"${float(abs(unrealized_pnl)):,.2f}" if unrealized_pnl != 0 else "$0.00",
                'Total P&L': total_pnl_display,
                'Daily P&L': daily_pnl_display,
                '5-Day P&L': five_day_pnl_display_plain,
                'Weight': position.get('position_weight', 'N/A'),
                'Stop Loss': f"${float(Decimal(str(position.get('stop_loss', 0)))):.2f}" if position.get('stop_loss', 0) > 0 else "None",
                'Cost Basis': f"${float(cost_basis):.2f}"
            })

        if df_data and _HAS_PANDAS:
            df = pd.DataFrame(df_data)

            # Set pandas display options for better formatting
            pd.set_option('display.max_columns', None)
            pd.set_option('display.width', self.optimal_width)
            pd.set_option('display.max_colwidth', 18 if self.using_test_data else 20)

            print(df.to_string(index=False))

            # Reset pandas options
            pd.reset_option('display.max_columns')
            pd.reset_option('display.width')
            pd.reset_option('display.max_colwidth')
        elif df_data:
            # Fallback to simple table formatting without pandas
            headers = list(df_data[0].keys()) if df_data else []

            # Print headers
            header_line = " | ".join(f"{header:>12}" for header in headers)
            print(header_line)
            print("-" * len(header_line))

            # Print data rows
            for row in df_data:
                data_line = " | ".join(f"{str(row.get(header, 'N/A')):>12}" for header in headers)
                print(data_line)
    
    def _create_portfolio_json(self, portfolio_data: List[Dict[str, Any]], 
                             current_date: Optional[str] = None) -> str:
        """Create JSON output for portfolio data."""
        output = {
            "timestamp": current_date or datetime.now().isoformat(),
            "portfolio": portfolio_data,
            "metadata": {
                "total_positions": len(portfolio_data),
                "data_source": "csv" if not self.web_mode else "api"
            }
        }
        return json.dumps(output, indent=2)
    
    def _create_portfolio_html(self, portfolio_data: List[Dict[str, Any]], 
                             current_date: Optional[str] = None) -> str:
        """Create HTML table output for web display."""
        html = f"""
        <div class="portfolio-table">
            <h2>📊 Portfolio Snapshot - {current_date or datetime.now().strftime('%Y-%m-%d')}</h2>
            <table class="table table-striped">
                <thead>
                    <tr>
                        <th>🎯 Ticker</th>
                        <th>🏢 Company</th>
                        <th>📅 Opened</th>
                        <th>📈 Shares</th>
                        <th>💵 Price</th>
                        <th>💰 Current</th>
                        <th>💵 Total Value</th>
                        <th>📊 Total P&L</th>
                        <th>📈 Daily P&L</th>
                        <th>🍕 Weight</th>
                        <th>🛑 Stop Loss</th>
                        <th>💵 Cost Basis</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        for position in portfolio_data:
            # Calculate total value for HTML (handle Decimals properly)
            from decimal import Decimal
            
            shares_raw = position.get('shares', 0)
            current_price_raw = position.get('current_price', 0)
            
            # Convert to Decimal if needed
            if isinstance(shares_raw, float):
                shares = Decimal(str(shares_raw))
            else:
                shares = Decimal(str(shares_raw)) if shares_raw != 0 else Decimal('0')
            
            if isinstance(current_price_raw, float):
                current_price = Decimal(str(current_price_raw)) if current_price_raw > 0 else Decimal('0')
            else:
                current_price = Decimal(str(current_price_raw)) if current_price_raw and current_price_raw > 0 else Decimal('0')
            
            total_value = shares * current_price if current_price > 0 else Decimal('0')

            # Create combined P&L values for HTML
            unrealized_pnl = position.get('unrealized_pnl', 0)
            total_pnl_pct = position.get('total_pnl', 'N/A')
            daily_pnl_pct = position.get('daily_pnl', 'N/A')

            # Combine percentage and dollar amount
            if total_pnl_pct != 'N/A' and unrealized_pnl != 0:
                total_pnl_display = f"{total_pnl_pct} ${unrealized_pnl:+,.2f}"
            elif total_pnl_pct != 'N/A':
                total_pnl_display = f"{total_pnl_pct} $0.00"
            else:
                total_pnl_display = 'N/A'

            if daily_pnl_pct != 'N/A':
                daily_dollar_pnl = 0  # Simplified calculation
                daily_pnl_display = f"{daily_pnl_pct} ${daily_dollar_pnl:+,.2f}"
            else:
                daily_pnl_display = 'N/A'

            html += f"""
                    <tr>
                        <td>{position.get('ticker', 'N/A')}</td>
                        <td>{position.get('company', 'N/A')}</td>
                        <td>{position.get('opened_date', 'N/A')}</td>
                        <td>{float(shares):.4f}</td>
                        <td>${float(Decimal(str(position.get('avg_price', 0)))):.2f}</td>
                        <td>${float(current_price):.2f}</td>
                        <td>${float(total_value):.2f}</td>
                        <td>{total_pnl_display}</td>
                        <td>{daily_pnl_display}</td>
                        <td>{position.get('position_weight', 'N/A')}</td>
                        <td>${float(Decimal(str(position.get('stop_loss', 0)))):.2f}</td>
                        <td>${float(Decimal(str(position.get('cost_basis', 0)))):.2f}</td>
                    </tr>
            """
        
        html += """
                </tbody>
            </table>
        </div>
        """
        return html
    
    def create_ownership_table(self, ownership_data: Dict[str, Dict[str, Any]], 
                             output_format: str = "display") -> Optional[str]:
        """Create ownership details table.
        
        Args:
            ownership_data: Dictionary of ownership information by contributor
            output_format: Output format - "display", "json", or "html"
            
        Returns:
            JSON string if output_format is "json", None otherwise
        """
        if output_format == "json":
            return json.dumps({"ownership": ownership_data}, indent=2)
        
        if has_rich_support() and self.console:
            ownership_table = Table(
                title="👥 Ownership Details",
                show_header=True,
                header_style="bold magenta"
            )
            ownership_table.add_column("Contributor", style="white", no_wrap=True)
            ownership_table.add_column("Shares", justify="right", style="bright_white")
            ownership_table.add_column("Ownership %", justify="right", style="bright_blue")
            ownership_table.add_column("Contributed", justify="right", style="yellow")
            ownership_table.add_column("Current Value", justify="right", style="bright_yellow")
            ownership_table.add_column("Total P/L", justify="right", style="magenta")
            
            # Sort by ownership percentage (highest first)
            sorted_ownership = sorted(ownership_data.items(), 
                                    key=lambda x: x[1].get('ownership_pct', 0), reverse=True)
            
            for row_index, (contributor, data) in enumerate(sorted_ownership):
                # Determine background color for alternating rows (zebra stripes)
                row_style = "on grey11" if row_index % 2 == 1 else None

                # Format Total P/L with color coding
                total_pl = data.get('total_pl', 0)
                if total_pl > 0:
                    total_pl_display = f"[bold green]${total_pl:,.2f}[/bold green]"
                elif total_pl < 0:
                    total_pl_display = f"[bold red]${total_pl:,.2f}[/bold red]"
                else:
                    total_pl_display = f"[dim]${total_pl:,.2f}[/dim]"

                ownership_table.add_row(
                    contributor,
                    f"{data.get('shares', 0):.2f}",
                    f"{data.get('ownership_pct', 0):.1f}%",
                    f"${data.get('contributed', 0):,.2f}",
                    f"${data.get('current_value', 0):,.2f}",
                    total_pl_display,
                    style=row_style  # Apply alternating background color
                )
            
            self.console.print(ownership_table)
        else:
            print_info("Ownership Details:", "👥")
            for contributor, data in ownership_data.items():
                total_pl = data.get('total_pl', 0)
                if total_pl > 0:
                    total_pl_display = f"{Fore.GREEN}{Style.BRIGHT}${total_pl:,.2f}{Style.RESET_ALL}"
                elif total_pl < 0:
                    total_pl_display = f"{Fore.RED}{Style.BRIGHT}${total_pl:,.2f}{Style.RESET_ALL}"
                else:
                    total_pl_display = f"{Style.DIM}${total_pl:,.2f}{Style.RESET_ALL}"
                
                print(f"  {contributor}: {data.get('shares', 0):.2f} shares ({data.get('ownership_pct', 0):.1f}%), "
                      f"${data.get('contributed', 0):,.2f} contributed, "
                      f"${data.get('current_value', 0):,.2f} value, "
                      f"P/L: {total_pl_display}")
        
        return None
    
    def create_statistics_table(self, stats_data: Dict[str, float], 
                              output_format: str = "display") -> Optional[str]:
        """Create portfolio statistics table.
        
        Args:
            stats_data: Dictionary of portfolio statistics
            output_format: Output format - "display", "json", or "html"
            
        Returns:
            JSON string if output_format is "json", None otherwise
        """
        if output_format == "json":
            return json.dumps({"statistics": stats_data}, indent=2)
        
        if has_rich_support() and self.console:
            stats_table = Table(
                title="📊 Portfolio Statistics",
                show_header=True,
                header_style="bold blue"
            )
            stats_table.add_column("Statistic", style="cyan", no_wrap=True)
            stats_table.add_column("Amount", justify="right", style="yellow")

            # Helper function to get color style based on value
            def get_pnl_style(value: float) -> str:
                return "green" if value >= 0 else "red"

            stats_table.add_row("💰 Total Contributions", f"${stats_data.get('total_contributions', 0):,.2f}", style="on grey11")
            stats_table.add_row("💵 Total Cost Basis", f"${stats_data.get('total_cost_basis', 0):,.2f}")
            stats_table.add_row("📈 Current Portfolio Value", f"${stats_data.get('total_current_value', 0):,.2f}", style="on grey11")
            stats_table.add_row("💹 Unrealized P&L", f"${stats_data.get('total_pnl', 0):,.2f}",
                               style=get_pnl_style(stats_data.get('total_pnl', 0)))
            stats_table.add_row("💰 Realized P&L", f"${stats_data.get('total_realized_pnl', 0):,.2f}",
                               style=get_pnl_style(stats_data.get('total_realized_pnl', 0)))
            stats_table.add_row("📊 Total Portfolio P&L", f"${stats_data.get('total_portfolio_pnl', 0):,.2f}",
                               style=get_pnl_style(stats_data.get('total_portfolio_pnl', 0)))

            self.console.print(stats_table)
        else:
            print_info("Portfolio Statistics:", "📊")

            # Helper function to get color based on value for fallback display
            def get_pnl_color(value: float) -> str:
                return Fore.GREEN if value >= 0 else Fore.RED

            print(f"  Total Contributions: ${stats_data.get('total_contributions', 0):,.2f}")
            print(f"  Total Cost Basis: ${stats_data.get('total_cost_basis', 0):,.2f}")
            print(f"  Current Portfolio Value: ${stats_data.get('total_current_value', 0):,.2f}")

            unrealized_pnl = stats_data.get('total_pnl', 0)
            print(f"  Unrealized P&L: {get_pnl_color(unrealized_pnl)}${unrealized_pnl:,.2f}{Style.RESET_ALL}")

            realized_pnl = stats_data.get('total_realized_pnl', 0)
            print(f"  Realized P&L: {get_pnl_color(realized_pnl)}${realized_pnl:,.2f}{Style.RESET_ALL}")

            total_portfolio_pnl = stats_data.get('total_portfolio_pnl', 0)
            print(f"  Total Portfolio P&L: {get_pnl_color(total_portfolio_pnl)}${total_portfolio_pnl:,.2f}{Style.RESET_ALL}")
        
        return None
    
    def create_summary_table(self, summary_data: Dict[str, float], 
                           output_format: str = "display") -> Optional[str]:
        """Create financial summary table.
        
        Args:
            summary_data: Dictionary of financial summary data
            output_format: Output format - "display", "json", or "html"
            
        Returns:
            JSON string if output_format is "json", None otherwise
        """
        if output_format == "json":
            return json.dumps({"summary": summary_data}, indent=2)
        
        total_value = summary_data.get('portfolio_value', 0)
        total_pnl = summary_data.get('total_pnl', 0)
        cash = summary_data.get('cash_balance', 0)
        fund_total = summary_data.get('fund_contributions', 0)
        
        if has_rich_support() and self.console:
            summary_table = Table(
                title="💰 Financial Summary",
                show_header=True,
                header_style="bold magenta"
            )
            summary_table.add_column("Metric", style="cyan", no_wrap=True)
            summary_table.add_column("Amount", justify="right", style="green")
            
            summary_table.add_row("📊 Portfolio Value", f"${total_value:,.2f}", style="on grey11")
            summary_table.add_row("💹 Total P&L",
                                f"${total_pnl:,.2f}" if total_pnl >= 0 else f"[red]${total_pnl:,.2f}[/red]")
            summary_table.add_row("💰 Cash Balance", f"${cash:,.2f}", style="on grey11")
            summary_table.add_row("🏦 Total Equity", f"${total_value + cash:,.2f}")
            summary_table.add_row("💵 Fund Contributions", f"${fund_total:,.2f}", style="on grey11")
            
            self.console.print(summary_table)
        else:
            print_info(f"Portfolio Total Value: ${total_value:,.2f}", "📊")
            print(f"  Total P&L: ${total_pnl:,.2f}")
            print(f"  Cash Balance: ${cash:,.2f}")
            print(f"  Total Equity: ${total_value + cash:,.2f}")
            print(f"  Fund Contributions: ${fund_total:,.2f}")
        
        return None
    
    def create_unified_financial_table(self, stats_data: Dict[str, float], 
                                      summary_data: Dict[str, float]) -> None:
        """Create a unified financial overview table combining statistics and summary.
        
        Args:
            stats_data: Dictionary of portfolio statistics
            summary_data: Dictionary of financial summary data
        """
        if has_rich_support() and self.console:
            self._create_rich_unified_financial_table(stats_data, summary_data)
        else:
            self._create_plain_unified_financial_table(stats_data, summary_data)
    
    def create_financial_and_ownership_tables(self, stats_data: Dict[str, float], 
                                             summary_data: Dict[str, float],
                                             ownership_data: Dict[str, Dict[str, Any]]) -> None:
        """Create financial overview and ownership tables side by side.
        
        Args:
            stats_data: Dictionary of portfolio statistics
            summary_data: Dictionary of financial summary data
            ownership_data: Dictionary of ownership information by contributor
        """
        if has_rich_support() and self.console:
            self._create_rich_financial_and_ownership_tables(stats_data, summary_data, ownership_data)
        else:
            self._create_plain_financial_and_ownership_tables(stats_data, summary_data, ownership_data)
    
    def _create_rich_unified_financial_table(self, stats_data: Dict[str, float], 
                                            summary_data: Dict[str, float]) -> None:
        """Create Rich-formatted unified financial table."""
        
        # Create unified financial overview table
        financial_table = Table(
            title="💰 Financial Overview",
            show_header=True,
            header_style="bold magenta"
        )
        financial_table.add_column("Metric", style="cyan", no_wrap=True)
        financial_table.add_column("Amount", justify="right", style="yellow")
        
        # Helper function to get color style based on value
        def get_pnl_style(value: float) -> str:
            return "green" if value >= 0 else "red"
        
        # Extract values
        total_value = summary_data.get('portfolio_value', 0)
        cash = summary_data.get('cash_balance', 0)
        total_contributions = stats_data.get('total_contributions', 0)
        cost_basis = stats_data.get('total_cost_basis', 0)
        unrealized_pnl = stats_data.get('total_pnl', 0)
        realized_pnl = stats_data.get('total_realized_pnl', 0)
        total_portfolio_pnl = stats_data.get('total_portfolio_pnl', 0)
        total_equity = total_value + cash
        
        # Portfolio Value Section
        financial_table.add_row("📊 Current Portfolio Value", f"${total_value:,.2f}", style="on grey11")
        
        # Get platform-specific fees for later use
        webull_fx_fee = summary_data.get('webull_fx_fee', 0)
        
        # Cash details (if present in summary_data)
        cad_cash = summary_data.get('cad_cash', None)
        usd_cash = summary_data.get('usd_cash', None)
        usd_to_cad_rate = summary_data.get('usd_to_cad_rate', None)
        estimated_fx_fee_total_usd = summary_data.get('estimated_fx_fee_total_usd', None)
        estimated_fx_fee_total_cad = summary_data.get('estimated_fx_fee_total_cad', None)
        if cad_cash is not None and usd_cash is not None and usd_to_cad_rate is not None:
            financial_table.add_row("💰 Cash Balance (CAD eq)", f"${cash:,.2f}")
            financial_table.add_row("   • CAD Cash", f"${cad_cash:,.2f}", style="cyan on grey11")
            financial_table.add_row("   • USD Cash", f"${usd_cash:,.2f}", style="blue")
            financial_table.add_row("   • USD→CAD rate", f"{usd_to_cad_rate:.4f}", style="on grey11")
            # Totals by currency (cash + positions)
            usd_holdings_total_usd = summary_data.get('usd_holdings_total_usd')
            cad_holdings_total_cad = summary_data.get('cad_holdings_total_cad')
            if usd_holdings_total_usd is not None:
                financial_table.add_row("   • Total USD (cash+positions)", f"${usd_holdings_total_usd:,.2f} USD", style="blue")
                # Show FX fee with USD holdings since it only applies to USD
                if webull_fx_fee > 0:
                    # Platform-specific fee display
                    if webull_fx_fee > total_value * 0.01:  # Webull with liquidation fees
                        financial_table.add_row("     • Webull Fees ($2.99/holding + 1.5% FX)", f"-${webull_fx_fee:,.2f}", style="red")
                    else:  # Wealthsimple
                        financial_table.add_row("     • Wealthsimple FX Fee (1.5%)", f"-${webull_fx_fee:,.2f}", style="red")
                elif estimated_fx_fee_total_usd and estimated_fx_fee_total_usd > 0:
                    # Generic FX fee for non-platform funds
                    approx_cad = f" (≈ ${estimated_fx_fee_total_cad:,.2f} CAD)" if estimated_fx_fee_total_cad is not None else ""
                    financial_table.add_row("     • Est. USD FX fee on USD holdings (1.5%)", f"-${estimated_fx_fee_total_usd:,.2f} USD{approx_cad}", style="dim")
            if cad_holdings_total_cad is not None:
                financial_table.add_row("   • Total CAD (cash+positions)", f"${cad_holdings_total_cad:,.2f} CAD", style="cyan on grey11")
        else:
            financial_table.add_row("💰 Cash Balance", f"${cash:,.2f}")
        
        # Recalculate total_equity with webull_fx_fee for display
        net_equity = total_equity - webull_fx_fee
        
        financial_table.add_row("🏦 Total Equity", f"[bold]${total_equity:,.2f}[/bold]", style="on grey11")
        # Show net equity after FX fee if applicable
        if webull_fx_fee and webull_fx_fee > 0:
            net_equity_after_fee = total_equity - webull_fx_fee
            financial_table.add_row("   • Net Equity After FX Fee", f"[bold]${net_equity_after_fee:,.2f}[/bold]")

        # Investment Performance Section
        financial_table.add_row("💵 Total Contributions", f"${total_contributions:,.2f}")
        financial_table.add_row("📈 Total Cost Basis", f"${cost_basis:,.2f}", style="on grey11")

        # P&L Section with color coding AND alternating backgrounds
        # Combine P&L color with alternating background
        def get_combined_pnl_style_unified(value: float, is_odd_row: bool) -> str:
            pnl_color = "green" if value >= 0 else "red"
            background = "on grey11" if is_odd_row else ""
            if background:
                return f"{pnl_color} {background}"
            return pnl_color

        # Row 1 (odd): Unrealized P&L - should have grey background + pnl color
        unrealized_style = get_combined_pnl_style_unified(unrealized_pnl, True)
        financial_table.add_row("💹 Unrealized P&L", f"${unrealized_pnl:,.2f}",
                               style=unrealized_style)

        # Row 2 (even): Realized P&L - should have default background + pnl color
        realized_style = get_combined_pnl_style_unified(realized_pnl, False)
        financial_table.add_row("💰 Realized P&L", f"${realized_pnl:,.2f}",
                               style=realized_style)

        # Row 3 (odd): Total Portfolio P&L - should have grey background + pnl color
        total_pnl_style = get_combined_pnl_style_unified(total_portfolio_pnl, True)
        financial_table.add_row("📊 Total Portfolio P&L", f"[bold]${total_portfolio_pnl:,.2f}[/bold]",
                               style=total_pnl_style)

        # Calculate and display profit percentage based on cost basis
        if cost_basis > 0:
            # Use total portfolio P&L for profit percentage calculation
            profit_pct = (total_portfolio_pnl / cost_basis) * 100
            # Row 4 (even): Profit Percentage - should have default background + pnl color
            profit_pct_style = get_combined_pnl_style_unified(profit_pct, False)
            financial_table.add_row("📈 Profit Percentage (vs Cost Basis)", f"[bold]{profit_pct:+.2f}%[/bold]",
                                   style=profit_pct_style)
            # Add breakdown row
            financial_table.add_row("   • (Total Portfolio P&L ÷ Cost Basis)", 
                                   f"(${total_portfolio_pnl:,.2f} ÷ ${cost_basis:,.2f})", 
                                   style="dim")

        # Calculate and display overall performance
        if total_contributions > 0:
            net_pnl_vs_contrib = (net_equity - total_contributions)
            # Row 5 (odd): Net P&L vs Contributions - should have grey background + pnl color
            net_pnl_style = get_combined_pnl_style_unified(net_pnl_vs_contrib, True)
            financial_table.add_row("🧮 Net P&L vs Contributions", f"${net_pnl_vs_contrib:,.2f}",
                                   style=net_pnl_style)
            # Add breakdown row
            financial_table.add_row("   • (Total Equity - Total Contributions)", 
                                   f"${net_equity:,.2f} - ${total_contributions:,.2f}", 
                                   style="dim")

            overall_return_pct = (net_pnl_vs_contrib / total_contributions) * 100
            # Row 6 (even): Overall Return - should have default background + pnl color
            overall_return_style = get_combined_pnl_style_unified(overall_return_pct, False)
            financial_table.add_row("📈 Overall Return (vs Contributions)", f"[bold]{overall_return_pct:+.2f}%[/bold]",
                                   style=overall_return_style)
            # Add breakdown row
            financial_table.add_row("   • (Net P&L vs Contrib ÷ Total Contrib)", 
                                   f"(${net_pnl_vs_contrib:,.2f} ÷ ${total_contributions:,.2f})", 
                                   style="dim")


        self.console.print(financial_table)
    
    def _create_rich_financial_and_ownership_tables(self, stats_data: Dict[str, float], 
                                                   summary_data: Dict[str, float],
                                                   ownership_data: Dict[str, Dict[str, Any]]) -> None:
        """Create Rich-formatted financial and ownership tables side by side."""
        from rich.columns import Columns
        
        # Create financial overview table (reuse existing logic)
        financial_table = Table(
            title="💰 Financial Overview",
            show_header=True,
            header_style="bold magenta"
        )
        financial_table.add_column("Metric", style="cyan", no_wrap=True)
        financial_table.add_column("Amount", justify="right", style="yellow")
        
        # Helper function to get color style based on value
        def get_pnl_style(value: float) -> str:
            return "green" if value >= 0 else "red"
        
        # Extract values
        total_value = summary_data.get('portfolio_value', 0)
        cash = summary_data.get('cash_balance', 0)
        total_contributions = stats_data.get('total_contributions', 0)
        cost_basis = stats_data.get('total_cost_basis', 0)
        unrealized_pnl = stats_data.get('total_pnl', 0)
        realized_pnl = stats_data.get('total_realized_pnl', 0)
        total_portfolio_pnl = stats_data.get('total_portfolio_pnl', 0)
        total_equity = total_value + cash
        
        # Portfolio Value Section
        financial_table.add_row("📊 Current Portfolio Value", f"${total_value:,.2f}", style="on grey11")
        
        # Get platform-specific fees for later use
        webull_fx_fee = summary_data.get('webull_fx_fee', 0)
        
        # Cash details (if present in summary_data)
        cad_cash = summary_data.get('cad_cash', None)
        usd_cash = summary_data.get('usd_cash', None)
        usd_to_cad_rate = summary_data.get('usd_to_cad_rate', None)
        estimated_fx_fee_total_usd = summary_data.get('estimated_fx_fee_total_usd', None)
        estimated_fx_fee_total_cad = summary_data.get('estimated_fx_fee_total_cad', None)
        if cad_cash is not None and usd_cash is not None and usd_to_cad_rate is not None:
            financial_table.add_row("💰 Cash Balance (CAD eq)", f"${cash:,.2f}")
            financial_table.add_row("   • CAD Cash", f"${cad_cash:,.2f}", style="cyan on grey11")
            financial_table.add_row("   • USD Cash", f"${usd_cash:,.2f}", style="blue")
            financial_table.add_row("   • USD→CAD rate", f"{usd_to_cad_rate:.4f}", style="on grey11")
            # Totals by currency (cash + positions)
            usd_holdings_total_usd = summary_data.get('usd_holdings_total_usd')
            cad_holdings_total_cad = summary_data.get('cad_holdings_total_cad')
            if usd_holdings_total_usd is not None:
                financial_table.add_row("   • Total USD (cash+positions)", f"${usd_holdings_total_usd:,.2f} USD", style="blue")
                # Show FX fee with USD holdings since it only applies to USD
                if webull_fx_fee > 0:
                    # Platform-specific fee display
                    if webull_fx_fee > total_value * 0.01:  # Webull with liquidation fees
                        financial_table.add_row("     • Webull Fees ($2.99/holding + 1.5% FX)", f"-${webull_fx_fee:,.2f}", style="red")
                    else:  # Wealthsimple
                        financial_table.add_row("     • Wealthsimple FX Fee (1.5%)", f"-${webull_fx_fee:,.2f}", style="red")
                elif estimated_fx_fee_total_usd and estimated_fx_fee_total_usd > 0:
                    # Generic FX fee for non-platform funds
                    approx_cad = f" (≈ ${estimated_fx_fee_total_cad:,.2f} CAD)" if estimated_fx_fee_total_cad is not None else ""
                    financial_table.add_row("     • Est. USD FX fee on USD holdings (1.5%)", f"-${estimated_fx_fee_total_usd:,.2f} USD{approx_cad}", style="dim")
            if cad_holdings_total_cad is not None:
                financial_table.add_row("   • Total CAD (cash+positions)", f"${cad_holdings_total_cad:,.2f} CAD", style="cyan on grey11")
        else:
            financial_table.add_row("💰 Cash Balance", f"${cash:,.2f}")
        
        # Recalculate total_equity with webull_fx_fee for display
        net_equity = total_equity - webull_fx_fee
        
        financial_table.add_row("🏦 Total Equity", f"[bold]${total_equity:,.2f}[/bold]", style="on grey11")
        # Show net equity after FX fee if applicable
        if webull_fx_fee and webull_fx_fee > 0:
            net_equity_after_fee = total_equity - webull_fx_fee
            financial_table.add_row("   • Net Equity After FX Fee", f"[bold]${net_equity_after_fee:,.2f}[/bold]")

        # Investment Performance Section
        financial_table.add_row("💵 Total Contributions", f"${total_contributions:,.2f}")
        financial_table.add_row("📈 Total Cost Basis", f"${cost_basis:,.2f}", style="on grey11")

        # Audit metric: funds not yet allocated into positions (net of cash)
        unallocated_vs_cost = stats_data.get('unallocated_vs_cost', None)
        if unallocated_vs_cost is not None:
            financial_table.add_row("🧾 Unallocated vs Cost", f"${unallocated_vs_cost:,.2f}")

        # P&L Section with color coding AND alternating backgrounds
        # Combine P&L color with alternating background
        def get_combined_pnl_style(value: float, is_odd_row: bool) -> str:
            pnl_color = "green" if value >= 0 else "red"
            background = "on grey11" if is_odd_row else ""
            if background:
                return f"{pnl_color} {background}"
            return pnl_color

        # Row 1 (odd): Unrealized P&L - should have grey background + pnl color
        unrealized_style = get_combined_pnl_style(unrealized_pnl, True)
        financial_table.add_row("💹 Unrealized P&L", f"${unrealized_pnl:,.2f}",
                               style=unrealized_style)

        # Row 2 (even): Realized P&L - should have default background + pnl color
        realized_style = get_combined_pnl_style(realized_pnl, False)
        financial_table.add_row("💰 Realized P&L", f"${realized_pnl:,.2f}",
                               style=realized_style)

        # Row 3 (odd): Total Portfolio P&L - should have grey background + pnl color
        total_pnl_style = get_combined_pnl_style(total_portfolio_pnl, True)
        financial_table.add_row("📊 Total Portfolio P&L", f"[bold]${total_portfolio_pnl:,.2f}[/bold]",
                               style=total_pnl_style)

        # Calculate and display profit percentage based on cost basis
        if cost_basis > 0:
            # Use total portfolio P&L for profit percentage calculation
            profit_pct = (total_portfolio_pnl / cost_basis) * 100
            # Row 4 (even): Profit Percentage - should have default background + pnl color
            profit_pct_style = get_combined_pnl_style(profit_pct, False)
            financial_table.add_row("📈 Profit Percentage (vs Cost Basis)", f"[bold]{profit_pct:+.2f}%[/bold]",
                                   style=profit_pct_style)
            # Add breakdown row
            financial_table.add_row("   • (Total Portfolio P&L ÷ Cost Basis)", 
                                   f"(${total_portfolio_pnl:,.2f} ÷ ${cost_basis:,.2f})", 
                                   style="dim")

        # Calculate and display performance versus contributions (investor view)
        if total_contributions > 0:
            net_pnl_vs_contrib = (net_equity - total_contributions)
            # Row 5 (odd): Net P&L vs Contributions - should have grey background + pnl color
            net_pnl_style = get_combined_pnl_style(net_pnl_vs_contrib, True)
            financial_table.add_row("🧮 Net P&L vs Contributions", f"${net_pnl_vs_contrib:,.2f}",
                                   style=net_pnl_style)
            # Add breakdown row
            financial_table.add_row("   • (Total Equity - Total Contributions)", 
                                   f"${net_equity:,.2f} - ${total_contributions:,.2f}", 
                                   style="dim")

            overall_return_pct = (net_pnl_vs_contrib / total_contributions) * 100
            # Row 6 (even): Overall Return - should have default background + pnl color
            overall_return_style = get_combined_pnl_style(overall_return_pct, False)
            financial_table.add_row("📈 Overall Return (vs Contributions)", f"[bold]{overall_return_pct:+.2f}%[/bold]",
                                   style=overall_return_style)
            # Add breakdown row
            financial_table.add_row("   • (Net P&L vs Contrib ÷ Total Contrib)", 
                                   f"(${net_pnl_vs_contrib:,.2f} ÷ ${total_contributions:,.2f})", 
                                   style="dim")

        
        # Create ownership table
        ownership_table = Table(
            title="👥 Ownership Details",
            show_header=True,
            header_style="bold magenta"
        )
        ownership_table.add_column("Contributor", style="white", no_wrap=True)
        ownership_table.add_column("Shares", justify="right", style="bright_white")
        ownership_table.add_column("Ownership %", justify="right", style="bright_blue")
        ownership_table.add_column("Contributed", justify="right", style="yellow")
        ownership_table.add_column("Current Value", justify="right", style="bright_yellow")
        ownership_table.add_column("Total P/L", justify="right", style="magenta")
        
        # Sort by ownership percentage (highest first)
        sorted_ownership = sorted(ownership_data.items(), 
                                key=lambda x: x[1].get('ownership_pct', 0), reverse=True)
        
        # If no ownership data, show a dummy entry
        if not sorted_ownership:
            ownership_table.add_row(
                "No Contributors",
                "0.00",
                "0.0%",
                "$0.00",
                "$0.00",
                "$0.00",
                style="dim"
            )
        
        for row_index, (contributor, data) in enumerate(sorted_ownership):
            # Determine background color for alternating rows (zebra stripes)
            row_style = "on grey11" if row_index % 2 == 1 else None

            # Format Total P/L with color coding
            total_pl = data.get('total_pl', 0)
            if total_pl > 0:
                total_pl_display = f"[bold green]${total_pl:,.2f}[/bold green]"
            elif total_pl < 0:
                total_pl_display = f"[bold red]${total_pl:,.2f}[/bold red]"
            else:
                total_pl_display = f"[dim]${total_pl:,.2f}[/dim]"

            ownership_table.add_row(
                contributor,
                f"{data.get('shares', 0):.2f}",
                f"{data.get('ownership_pct', 0):.1f}%",
                f"${data.get('contributed', 0):,.2f}",
                f"${data.get('current_value', 0):,.2f}",
                total_pl_display,
                style=row_style  # Apply alternating background color
            )
        
        # Display tables side by side
        columns = Columns([financial_table, ownership_table], equal=True, expand=True)
        self.console.print(columns)
    
    def _create_plain_unified_financial_table(self, stats_data: Dict[str, float], 
                                             summary_data: Dict[str, float]) -> None:
        """Create plain text unified financial table."""
        from display.console_output import _safe_emoji
        
        # Helper function to get color based on value
        def get_pnl_color(value: float) -> str:
            return Fore.GREEN if value >= 0 else Fore.RED
        
        # Extract values
        total_value = summary_data.get('portfolio_value', 0)
        cash = summary_data.get('cash_balance', 0)
        total_contributions = stats_data.get('total_contributions', 0)
        cost_basis = stats_data.get('total_cost_basis', 0)
        unrealized_pnl = stats_data.get('total_pnl', 0)
        realized_pnl = stats_data.get('total_realized_pnl', 0)
        total_portfolio_pnl = stats_data.get('total_portfolio_pnl', 0)
        total_equity = total_value + cash
        
        print(f"\n{Fore.MAGENTA}{_safe_emoji('💰')} Financial Overview:{Style.RESET_ALL}")
        print("─" * 50)
        
        # Portfolio Value Section
        print(f"  Current Portfolio Value: ${total_value:,.2f}")
        # Cash details (if present)
        cad_cash = summary_data.get('cad_cash')
        usd_cash = summary_data.get('usd_cash')
        usd_to_cad_rate = summary_data.get('usd_to_cad_rate')
        estimated_fx_fee_total_usd = summary_data.get('estimated_fx_fee_total_usd')
        estimated_fx_fee_total_cad = summary_data.get('estimated_fx_fee_total_cad')
        if cad_cash is not None and usd_cash is not None and usd_to_cad_rate is not None:
            print(f"  Cash Balance (CAD eq): ${cash:,.2f}")
            print(f"    • CAD Cash: {Fore.CYAN}${cad_cash:,.2f}{Style.RESET_ALL}")
            print(f"    • USD Cash: {Fore.BLUE}${usd_cash:,.2f}{Style.RESET_ALL}")
            print(f"    • USD→CAD rate: {usd_to_cad_rate:.4f}")
            # Totals by currency (cash + positions)
            usd_holdings_total_usd = summary_data.get('usd_holdings_total_usd')
            cad_holdings_total_cad = summary_data.get('cad_holdings_total_cad')
            if usd_holdings_total_usd is not None:
                print(f"    • Total USD (cash+positions): {Fore.BLUE}${usd_holdings_total_usd:,.2f} USD{Style.RESET_ALL}")
            if cad_holdings_total_cad is not None:
                print(f"    • Total CAD (cash+positions): {Fore.CYAN}${cad_holdings_total_cad:,.2f} CAD{Style.RESET_ALL}")
            if estimated_fx_fee_total_usd and estimated_fx_fee_total_usd > 0:
                approx_cad = f" (≈ ${estimated_fx_fee_total_cad:,.2f} CAD)" if estimated_fx_fee_total_cad is not None else ""
                print(f"    • Est. USD FX fee on USD holdings (1.5%): {Fore.RED}-${estimated_fx_fee_total_usd:,.2f} USD{Style.RESET_ALL}{approx_cad}")
        else:
            print(f"  Cash Balance: ${cash:,.2f}")
        print(f"  {Fore.CYAN}Total Equity: ${total_equity:,.2f}{Style.RESET_ALL}")
        
        # Investment Performance Section  
        print(f"  Total Contributions: ${total_contributions:,.2f}")
        print(f"  Total Cost Basis: ${cost_basis:,.2f}")
        
        # Audit metric
        unallocated_vs_cost = stats_data.get('unallocated_vs_cost', None)
        if unallocated_vs_cost is not None:
            print(f"  Unallocated vs Cost: ${unallocated_vs_cost:,.2f}")
        
        # P&L Section with color coding
        print(f"  Unrealized P&L: {get_pnl_color(unrealized_pnl)}${unrealized_pnl:,.2f}{Style.RESET_ALL}")
        print(f"  Realized P&L: {get_pnl_color(realized_pnl)}${realized_pnl:,.2f}{Style.RESET_ALL}")
        print(f"  {Fore.CYAN}Total Portfolio P&L: {get_pnl_color(total_portfolio_pnl)}${total_portfolio_pnl:,.2f}{Style.RESET_ALL}")
        
        # Calculate and display performance versus contributions (investor view)
        if total_contributions > 0:
            net_pnl_vs_contrib = total_equity - total_contributions
            print(f"  Net P&L vs Contributions: {get_pnl_color(net_pnl_vs_contrib)}${net_pnl_vs_contrib:,.2f}{Style.RESET_ALL}")
            overall_return_pct = (net_pnl_vs_contrib / total_contributions) * 100
            print(f"  {Fore.CYAN}Overall Return: {get_pnl_color(overall_return_pct)}{overall_return_pct:+.2f}%{Style.RESET_ALL}")
    
    def _create_plain_financial_and_ownership_tables(self, stats_data: Dict[str, float], 
                                                   summary_data: Dict[str, float],
                                                   ownership_data: Dict[str, Dict[str, Any]]) -> None:
        """Create plain text financial and ownership tables side by side."""
        from display.console_output import _safe_emoji
        
        # Helper function to get color based on value
        def get_pnl_color(value: float) -> str:
            return Fore.GREEN if value >= 0 else Fore.RED
        
        # Extract financial values
        total_value = summary_data.get('portfolio_value', 0)
        cash = summary_data.get('cash_balance', 0)
        cad_cash = summary_data.get('cad_cash', None)
        usd_cash = summary_data.get('usd_cash', None)
        usd_to_cad_rate = summary_data.get('usd_to_cad_rate', None)
        estimated_cashout_fee_cad = summary_data.get('estimated_cashout_fee_cad', 0)
        total_contributions = stats_data.get('total_contributions', 0)
        cost_basis = stats_data.get('total_cost_basis', 0)
        unrealized_pnl = stats_data.get('total_pnl', 0)
        realized_pnl = stats_data.get('total_realized_pnl', 0)
        total_portfolio_pnl = stats_data.get('total_portfolio_pnl', 0)
        total_equity = total_value + cash
        net_pnl_vs_contrib = total_equity - total_contributions
        
        # Prepare financial data lines
        financial_lines = [
            f"{_safe_emoji('💰')} Financial Overview",
            "─" * 35,
            f"  Current Portfolio Value: ${total_value:,.2f}",
            # Cash section
            (f"  Cash Balance (CAD eq): ${cash:,.2f}" if cad_cash is not None and usd_cash is not None and usd_to_cad_rate is not None else f"  Cash Balance: ${cash:,.2f}"),
            (f"    • CAD Cash: {Fore.CYAN}${cad_cash:,.2f}{Style.RESET_ALL}" if cad_cash is not None else None),
            (f"    • USD Cash: {Fore.BLUE}${usd_cash:,.2f}{Style.RESET_ALL} (×{usd_to_cad_rate:.4f} CAD)" if usd_cash is not None and usd_to_cad_rate is not None else None),
            (f"    • Est. USD→CAD fee (1.5%): -${estimated_cashout_fee_cad:,.2f}" if estimated_cashout_fee_cad and estimated_cashout_fee_cad > 0 else None),
            f"  {Fore.CYAN}Total Equity: ${total_equity:,.2f}{Style.RESET_ALL}",
            f"  Total Contributions: ${total_contributions:,.2f}",
            f"  Total Cost Basis: ${cost_basis:,.2f}",
            (f"  Unallocated vs Cost: ${stats_data.get('unallocated_vs_cost', 0):,.2f}" if stats_data.get('unallocated_vs_cost', None) is not None else None),
            f"  Unrealized P&L: {get_pnl_color(unrealized_pnl)}${unrealized_pnl:,.2f}{Style.RESET_ALL}",
            f"  Realized P&L: {get_pnl_color(realized_pnl)}${realized_pnl:,.2f}{Style.RESET_ALL}",
            f"  {Fore.CYAN}Total Portfolio P&L: {get_pnl_color(total_portfolio_pnl)}${total_portfolio_pnl:,.2f}{Style.RESET_ALL}",
            f"  Net P&L vs Contributions: {get_pnl_color(net_pnl_vs_contrib)}${net_pnl_vs_contrib:,.2f}{Style.RESET_ALL}"
        ]
        
        # Add overall return if contributions exist
        if total_contributions > 0:
            overall_return_pct = (net_pnl_vs_contrib / total_contributions) * 100
            financial_lines.append(f"  {Fore.CYAN}Overall Return: {get_pnl_color(overall_return_pct)}{overall_return_pct:+.2f}%{Style.RESET_ALL}")
        
        # Prepare ownership data lines
        ownership_lines = [
            f"{_safe_emoji('👥')} Ownership Details",
            "─" * 35,
        ]
        
        # Sort by ownership percentage (highest first)
        sorted_ownership = sorted(ownership_data.items(), 
                                key=lambda x: x[1].get('ownership_pct', 0), reverse=True)
        
        # If no ownership data, show a dummy entry
        if not sorted_ownership:
            ownership_lines.append("  No Contributors: 0.0 shares (0.0%)")
            ownership_lines.append("    $0 contributed = $0 value P/L: $0.00")
        
        for contributor, data in sorted_ownership:
            shares = data.get('shares', 0)
            contributed = data.get('contributed', 0)
            ownership_pct = data.get('ownership_pct', 0)
            current_value = data.get('current_value', 0)
            total_pl = data.get('total_pl', 0)
            
            # Format Total P/L with color coding for plain text
            if total_pl > 0:
                total_pl_display = f"{Fore.GREEN}{Style.BRIGHT}${total_pl:,.2f}{Style.RESET_ALL}"
            elif total_pl < 0:
                total_pl_display = f"{Fore.RED}{Style.BRIGHT}${total_pl:,.2f}{Style.RESET_ALL}"
            else:
                total_pl_display = f"{Style.DIM}${total_pl:,.2f}{Style.RESET_ALL}"
            
            # Format contributor line
            contrib_line = f"  {contributor[:15]:<15}: {shares:>6.1f} shares ({ownership_pct:4.1f}%)"
            ownership_lines.append(contrib_line)
            ownership_lines.append(f"    ${contributed:>7,.0f} contributed = ${current_value:>8,.0f} value P/L: {total_pl_display}")
        
        # Display side by side
        print("\n")
        # Filter out None placeholder lines inserted above
        financial_lines = [line for line in financial_lines if line is not None]
        max_lines = max(len(financial_lines), len(ownership_lines))
        for i in range(max_lines):
            financial_line = financial_lines[i] if i < len(financial_lines) else ""
            ownership_line = ownership_lines[i] if i < len(ownership_lines) else ""
            
            # Pad the financial line to consistent width
            financial_padded = f"{financial_line:<30}"
            print(f"{financial_padded} {ownership_line}")
    
    def create_trade_menu(self) -> None:
        """Create the trading menu display."""
        if has_rich_support() and self.console:
            panel = Panel(
                "[bold green]📈 Trading Menu[/bold green]\\n\\n"
                "[cyan]'b'[/cyan] 🛒 Buy (Limit Order or Market Open Order)\\n"
                "[cyan]'s'[/cyan] 📤 Sell (Limit Order)\\n"
                "[cyan]'c'[/cyan] 💵 Log Contribution\\n"
                "[cyan]'w'[/cyan] 💸 Log Withdrawal\\n"
                "[cyan]'u'[/cyan] 🔄 Update Cash Balances\\n"
                "[cyan]'sync'[/cyan] 🔗 Sync Fund Contributions\\n"
                "[cyan]'backup'[/cyan] 💾 Create Backup\\n"
                "[cyan]'restore'[/cyan] 🔄 Restore from Backup\\n"
                "[cyan]Enter[/cyan] ➤  Continue to Portfolio Processing",
                border_style="green",
                width=62
            )
            self.console.print(panel)
        else:
            from .console_output import _safe_emoji
            print(f"\\n{Fore.GREEN}{_safe_emoji('📈')} Trading Menu:{Style.RESET_ALL}")
            print(f"{Fore.CYAN}'b'{Style.RESET_ALL} {_safe_emoji('🛒')} Buy (Limit Order or Market Open Order)")
            print(f"{Fore.CYAN}'s'{Style.RESET_ALL} {_safe_emoji('📤')} Sell (Limit Order)")
            print(f"{Fore.CYAN}'c'{Style.RESET_ALL} {_safe_emoji('💵')} Log Contribution")
            print(f"{Fore.CYAN}'w'{Style.RESET_ALL} {_safe_emoji('💸')} Log Withdrawal")
            print(f"{Fore.CYAN}'u'{Style.RESET_ALL} {_safe_emoji('🔄')} Update Cash Balances")
            print(f"{Fore.CYAN}'sync'{Style.RESET_ALL} {_safe_emoji('🔗')} Sync Fund Contributions")
            print(f"{Fore.CYAN}'backup'{Style.RESET_ALL} {_safe_emoji('💾')} Create Backup")
            print(f"{Fore.CYAN}'restore'{Style.RESET_ALL} {_safe_emoji('🔄')} Restore from Backup")
            print(f"{Fore.CYAN}Enter{Style.RESET_ALL} {_safe_emoji('➤')} Continue to Portfolio Processing")

    def create_trade_log_table(self, trades: List[Any], title: str = "Trade Log") -> None:
        """Create and display a trade log table.
        
        Args:
            trades: List of trade objects or dictionaries
            title: Title for the table
        """
        if not trades:
            print_info("No trades found in trade log")
            return
        
        # Sort trades chronologically (oldest first)
        sorted_trades = sorted(trades, key=lambda x: getattr(x, 'timestamp', getattr(x, 'date', '')))
        
        if has_rich_support() and self.console:
            self._create_rich_trade_log_table(sorted_trades, title)
        else:
            self._create_plain_trade_log_table(sorted_trades, title)
    
    def _create_rich_trade_log_table(self, trades: List[Any], title: str) -> None:
        """Create Rich-formatted trade log table."""
        from utils.timezone_utils import format_timestamp_for_display
        
        table = Table(title=title, show_header=True, header_style="bold magenta")
        table.add_column("Date", style="cyan", no_wrap=True)
        table.add_column("Ticker", style="green", no_wrap=True)
        table.add_column("Action", style="bold", no_wrap=True)
        table.add_column("Shares", justify="right", style="yellow")
        table.add_column("Price", justify="right", style="yellow")
        table.add_column("Cost Basis", justify="right", style="yellow")
        table.add_column("PnL", justify="right", style="yellow")
        table.add_column("Currency", style="blue", no_wrap=True)
        table.add_column("Reason", style="dim")
        
        total_pnl = 0
        buy_count = 0
        sell_count = 0
        
        for trade in trades:
            # Extract trade data
            timestamp = getattr(trade, 'timestamp', getattr(trade, 'date', ''))
            ticker = getattr(trade, 'ticker', getattr(trade, 'symbol', ''))
            action = getattr(trade, 'action', getattr(trade, 'side', ''))
            shares = getattr(trade, 'shares', getattr(trade, 'quantity', 0))
            price = getattr(trade, 'price', getattr(trade, 'execution_price', 0))
            cost_basis = getattr(trade, 'cost_basis', getattr(trade, 'total_cost', 0))
            pnl = getattr(trade, 'pnl', getattr(trade, 'profit_loss', 0))
            currency = getattr(trade, 'currency', 'USD')
            reason = getattr(trade, 'reason', getattr(trade, 'notes', ''))
            
            # Format timestamp
            if timestamp:
                try:
                    if hasattr(timestamp, 'strftime'):
                        formatted_date = format_timestamp_for_display(timestamp)
                    else:
                        formatted_date = str(timestamp)
                except:
                    formatted_date = str(timestamp)
            else:
                formatted_date = "N/A"
            
            # Format values
            shares_str = self._format_shares_for_display(shares)
            price_str = f"${price:,.2f}" if price else "$0.00"
            cost_basis_str = f"${cost_basis:,.2f}" if cost_basis else "$0.00"
            pnl_str = f"${pnl:,.2f}" if pnl else "$0.00"
            
            # Color code action
            if action.upper() == 'BUY':
                action_style = "bold green"
                buy_count += 1
            elif action.upper() == 'SELL':
                action_style = "bold red"
                sell_count += 1
            else:
                action_style = "bold blue"
            
            # Add row
            table.add_row(
                formatted_date,
                ticker,
                f"[{action_style}]{action}[/]",
                shares_str,
                price_str,
                cost_basis_str,
                pnl_str,
                currency,
                reason
            )
            
            total_pnl += pnl or 0
        
        # Display table
        self.console.print(table)
        
        # Add summary panel
        summary_text = f"Total Trades: {len(trades)} | Buy: {buy_count} | Sell: {sell_count} | Total P&L: ${total_pnl:,.2f}"
        summary_panel = Panel(summary_text, title="Trade Summary", border_style="green")
        self.console.print(summary_panel)
    
    def _create_plain_trade_log_table(self, trades: List[Any], title: str) -> None:
        """Create plain text trade log table."""
        from utils.timezone_utils import format_timestamp_for_display
        
        print(f"\n{title}")
        print("=" * len(title))
        
        # Header
        print(f"{'Date':<20} {'Ticker':<8} {'Action':<6} {'Shares':<10} {'Price':<10} {'Cost Basis':<12} {'PnL':<10} {'Currency':<8} {'Reason'}")
        print("-" * 100)
        
        total_pnl = 0
        buy_count = 0
        sell_count = 0
        
        for trade in trades:
            # Extract trade data
            timestamp = getattr(trade, 'timestamp', getattr(trade, 'date', ''))
            ticker = getattr(trade, 'ticker', getattr(trade, 'symbol', ''))
            action = getattr(trade, 'action', getattr(trade, 'side', ''))
            shares = getattr(trade, 'shares', getattr(trade, 'quantity', 0))
            price = getattr(trade, 'price', getattr(trade, 'execution_price', 0))
            cost_basis = getattr(trade, 'cost_basis', getattr(trade, 'total_cost', 0))
            pnl = getattr(trade, 'pnl', getattr(trade, 'profit_loss', 0))
            currency = getattr(trade, 'currency', 'USD')
            reason = getattr(trade, 'reason', getattr(trade, 'notes', ''))
            
            # Format timestamp
            if timestamp:
                try:
                    if hasattr(timestamp, 'strftime'):
                        formatted_date = format_timestamp_for_display(timestamp)
                    else:
                        formatted_date = str(timestamp)
                except:
                    formatted_date = str(timestamp)
            else:
                formatted_date = "N/A"
            
            # Format values
            shares_str = self._format_shares_for_display(shares)
            price_str = f"${price:,.2f}" if price else "$0.00"
            cost_basis_str = f"${cost_basis:,.2f}" if cost_basis else "$0.00"
            pnl_str = f"${pnl:,.2f}" if pnl else "$0.00"
            
            # Count actions
            if action.upper() == 'BUY':
                buy_count += 1
            elif action.upper() == 'SELL':
                sell_count += 1
            
            # Print row
            print(f"{formatted_date:<20} {ticker:<8} {action:<6} {shares_str:<10} {price_str:<10} {cost_basis_str:<12} {pnl_str:<10} {currency:<8} {reason}")
            
            total_pnl += pnl or 0
        
        # Print summary
        print("-" * 100)
        print(f"Total Trades: {len(trades)} | Buy: {buy_count} | Sell: {sell_count} | Total P&L: ${total_pnl:,.2f}")


# Convenience functions for backward compatibility
def create_portfolio_table(portfolio_data: Union[List[Dict[str, Any]], 'pd.DataFrame'], 
                         data_dir: Optional[str] = None,
                         current_date: Optional[str] = None,
                         output_format: str = "display") -> Optional[str]:
    """Create a portfolio table display.
    
    Convenience function that creates a TableFormatter instance and calls create_portfolio_table.
    Supports both pandas DataFrame (original) and list of dictionaries (new) for backward compatibility.
    """
    formatter = TableFormatter(data_dir=data_dir)
    return formatter.create_portfolio_table(portfolio_data, current_date, output_format)


def create_ownership_table(ownership_data: Dict[str, Dict[str, Any]], 
                         data_dir: Optional[str] = None,
                         output_format: str = "display") -> Optional[str]:
    """Create an ownership details table.
    
    Convenience function that creates a TableFormatter instance and calls create_ownership_table.
    """
    formatter = TableFormatter(data_dir=data_dir)
    return formatter.create_ownership_table(ownership_data, output_format)


def create_statistics_table(stats_data: Dict[str, float], 
                          data_dir: Optional[str] = None,
                          output_format: str = "display") -> Optional[str]:
    """Create a portfolio statistics table.
    
    Convenience function that creates a TableFormatter instance and calls create_statistics_table.
    """
    formatter = TableFormatter(data_dir=data_dir)
    return formatter.create_statistics_table(stats_data, output_format)


def create_summary_table(summary_data: Dict[str, float], 
                       data_dir: Optional[str] = None,
                       output_format: str = "display") -> Optional[str]:
    """Create a financial summary table.
    
    Convenience function that creates a TableFormatter instance and calls create_summary_table.
    """
    formatter = TableFormatter(data_dir=data_dir)
    return formatter.create_summary_table(summary_data, output_format)


def create_unified_financial_table(stats_data: Dict[str, float], 
                                   summary_data: Dict[str, float],
                                   data_dir: Optional[str] = None) -> None:
    """Create a unified financial overview table combining statistics and summary.
    
    Convenience function that creates a TableFormatter instance and displays unified financial table.
    
    Args:
        stats_data: Dictionary of portfolio statistics
        summary_data: Dictionary of financial summary data
        data_dir: Optional data directory path for context
    """
    formatter = TableFormatter(data_dir=data_dir)
    formatter.create_unified_financial_table(stats_data, summary_data)


def create_financial_and_ownership_tables(stats_data: Dict[str, float], 
                                         summary_data: Dict[str, float],
                                         ownership_data: Dict[str, Dict[str, Any]],
                                         data_dir: Optional[str] = None) -> None:
    """Create financial overview and ownership tables side by side.
    
    Convenience function that creates a TableFormatter instance and displays side-by-side tables.
    
    Args:
        stats_data: Dictionary of portfolio statistics
        summary_data: Dictionary of financial summary data
        ownership_data: Dictionary of ownership information by contributor
        data_dir: Optional data directory path for context
    """
    formatter = TableFormatter(data_dir=data_dir)
    formatter.create_financial_and_ownership_tables(stats_data, summary_data, ownership_data)


def print_trade_menu(data_dir: Optional[str] = None) -> None:
    """Print the trading menu.
    
    Convenience function that creates a TableFormatter instance and calls create_trade_menu.
    """
    formatter = TableFormatter(data_dir=data_dir)
    formatter.create_trade_menu()


# Additional backward compatibility aliases
def create_portfolio_table_original(portfolio_df) -> None:
    """Create a portfolio table display - original function signature for backward compatibility.
    
    This function matches the exact signature from the original trading_script.py:
    def create_portfolio_table(portfolio_df: pd.DataFrame) -> None
    """
    # Just call the main function - it already handles DataFrames correctly
    create_portfolio_table(portfolio_df)