"""Console output module for colored messages and formatting.

This module provides colored console output functions that work with both Rich and colorama,
with graceful fallback to plain text. The functions are designed to work with data from
any repository type and provide consistent messaging across the trading system.
"""

import os
import sys
from pathlib import Path
from typing import Optional


def _can_handle_unicode() -> bool:
    """Check if the current environment can handle Unicode characters."""
    try:
        # Get the current encoding
        encoding = sys.stdout.encoding or 'utf-8'
        
        # Check if encoding supports Unicode
        if encoding.lower() in ['cp1252', 'latin1', 'ascii', 'charmap']:
            return False
        
        # Test encoding a simple Unicode character using escape sequence
        test_char = "\U0001f4c8"  # 📈 emoji using escape sequence
        test_char.encode(encoding)
        
        # Additional check for Windows Terminal vs Command Prompt
        import os
        if os.name == 'nt':  # Windows
            # Check if we're in Windows Terminal (which supports Unicode better)
            wt_session = os.environ.get('WT_SESSION')
            if wt_session:
                return True
            # Check for modern Windows 10+ with UTF-8 support
            try:
                import locale
                encoding = locale.getpreferredencoding()
                if 'utf' in encoding.lower():
                    return True
            except:
                pass
        
        return True
    except (UnicodeEncodeError, LookupError):
        return False


# Initialize fallback variables
_FORCE_FALLBACK = False  # Allow Rich display by default
_FORCE_COLORAMA_ONLY = os.environ.get("FORCE_COLORAMA_ONLY", "").lower() in ("true", "1", "yes", "on")


def _safe_emoji(emoji: str) -> str:
    """Return emoji if supported, otherwise return a safe alternative."""
    # Check if we can handle Unicode first
    if not _can_handle_unicode():
        # Return safe alternatives for common emojis
        emoji_map = {
            "🔥": "*",
            "🚀": ">>",
            "💼": "[PORT]",
            "⚡": "!",
            "📊": "[STATS]",
            "💰": "$",
            "🛒": "[BUY]",
            "📤": "[SELL]",
            "💵": "$",
            "💸": "-$",
            "🔄": "~",
            "🔗": "&",
            "💾": "[BACKUP]",
            "❌": "X",
            "📋": "[LIST]",
            "🔷": "◆",
            "✅": "OK",
            "⚠️": "!",
            "ℹ️": "INFO",
            "🤖": "[AI]",
            "➤": "->",
            "🎯": "[TARGET]",
            "🏢": "[COMPANY]",
            "📅": "[DATE]",
            "📈": "[^]",
            "🍕": "[WORK]",
            "🛑": "[STOP]",
            "💹": "[PROFIT]",
            "👥": "[ORG]",
            "🏦": "[BANK]"
        }
        return emoji_map.get(emoji, "*")
    
    # If we can handle Unicode, return the emoji
    return emoji

# Color and formatting imports with fallback handling
try:
    from colorama import init, Fore, Back, Style
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.text import Text
    init(autoreset=True)  # Initialize colorama
    _HAS_RICH = True
    # Try to create Rich console, but be more permissive
    try:
        console = Console()
        # Test if Rich can actually render without crashing
        test_output = console.render_str("test")
    except Exception:
        # Only disable Rich if it completely fails
        _HAS_RICH = False
        console = None
except ImportError:
    _HAS_RICH = False
    console = None
    # Create dummy classes for fallback
    class DummyColor:
        def __getattr__(self, name):
            return ""
    
    Fore = Back = Style = DummyColor()


def set_force_fallback(force_fallback: bool = True, colorama_only: bool = False) -> None:
    """Force fallback mode for testing purposes.
    
    Args:
        force_fallback: If True, disable Rich and use colorama/plain text
        colorama_only: If True, disable Rich but keep colorama (only works if force_fallback=True)
    """
    global _HAS_RICH, _FORCE_FALLBACK, _FORCE_COLORAMA_ONLY
    
    _FORCE_FALLBACK = force_fallback
    _FORCE_COLORAMA_ONLY = colorama_only
    
    if force_fallback:
        _HAS_RICH = False
        if not colorama_only:
            # Also disable colorama for plain text testing
            global Fore, Back, Style
            class DummyColor:
                def __getattr__(self, name):
                    return ""
            
            Fore = Back = Style = DummyColor()


def print_success(message: str, emoji: str = _safe_emoji("✅")) -> None:
    """Print a success message with green color and emoji.
    
    Args:
        message: The success message to display
        emoji: The emoji to display with the message (default: ✅)
    """
    safe_emoji = _safe_emoji(emoji)
    safe_message = format_text_for_console(message)
    if _HAS_RICH and console and not _FORCE_FALLBACK:
        try:
            console.print(f"{safe_emoji} {safe_message}", style="bold green")
        except UnicodeEncodeError:
            print(f"SUCCESS: {safe_message}")
    else:
        print(f"{Fore.GREEN}{safe_emoji} {safe_message}{Style.RESET_ALL}")


def print_error(message: str, emoji: str = _safe_emoji("❌")) -> None:
    """Print an error message with red color and emoji.
    
    Args:
        message: The error message to display
        emoji: The emoji to display with the message (default: ❌)
    """
    safe_emoji = _safe_emoji(emoji)
    safe_message = format_text_for_console(message)
    if _HAS_RICH and console and not _FORCE_FALLBACK:
        try:
            console.print(f"{safe_emoji} {safe_message}", style="bold red")
        except UnicodeEncodeError:
            print(f"ERROR: {safe_message}")
    else:
        print(f"{Fore.RED}{safe_emoji} {safe_message}{Style.RESET_ALL}")


def print_warning(message: str, emoji: str = _safe_emoji("⚠️")) -> None:
    """Print a warning message with yellow color and emoji.
    
    Args:
        message: The warning message to display
        emoji: The emoji to display with the message (default: ⚠️)
    """
    safe_emoji = _safe_emoji(emoji)
    safe_message = format_text_for_console(message)
    if _HAS_RICH and console and not _FORCE_FALLBACK:
        try:
            console.print(f"{safe_emoji} {safe_message}", style="bold yellow")
        except UnicodeEncodeError:
            print(f"WARNING: {safe_message}")
    else:
        print(f"{Fore.YELLOW}{safe_emoji} {safe_message}{Style.RESET_ALL}")


def print_info(message: str, emoji: str = "ℹ️") -> None:
    """Print an info message with blue color and emoji.
    
    Args:
        message: The info message to display
        emoji: The emoji to display with the message (default: ℹ️)
    """
    safe_emoji = _safe_emoji(emoji)
    safe_message = format_text_for_console(message)
    if _HAS_RICH and console and not _FORCE_FALLBACK:
        try:
            console.print(f"{safe_emoji} {safe_message}", style="bold blue")
        except UnicodeEncodeError:
            print(f"INFO: {safe_message}")
    else:
        print(f"{Fore.BLUE}{safe_emoji} {safe_message}{Style.RESET_ALL}")




def format_text_for_console(text: str) -> str:
    """Format a block of text for the current console capabilities.

    - If Unicode is supported, return text unchanged.
    - If not, replace known emojis with safe ASCII via _safe_emoji and ensure encodable.
    """
    if _can_handle_unicode():
        return text
    # Replace known emojis with safe alternatives
    replacements = {
        "🔥": _safe_emoji("🔥"),
        "🚀": _safe_emoji("🚀"),
        "💼": _safe_emoji("💼"),
        "⚡": _safe_emoji("⚡"),
        "📊": _safe_emoji("📊"),
        "💰": _safe_emoji("💰"),
        "🛒": _safe_emoji("🛒"),
        "📤": _safe_emoji("📤"),
        "💵": _safe_emoji("💵"),
        "💸": _safe_emoji("💸"),
        "🔄": _safe_emoji("🔄"),
        "🔗": _safe_emoji("🔗"),
        "💾": _safe_emoji("💾"),
        "❌": _safe_emoji("❌"),
        "📋": _safe_emoji("📋"),
        "🔷": _safe_emoji("🔷"),
        "✅": _safe_emoji("✅"),
        "⚠️": _safe_emoji("⚠️"),
        "ℹ️": _safe_emoji("ℹ️"),
        "🤖": _safe_emoji("🤖"),
        "➤": _safe_emoji("➤"),
        "🎯": _safe_emoji("🎯"),
        "🏢": _safe_emoji("🏢"),
        "📅": _safe_emoji("📅"),
        "📈": _safe_emoji("📈"),
        "🍕": _safe_emoji("🍕"),
        "🛑": _safe_emoji("🛑"),
        "💹": _safe_emoji("💹"),
        "👥": _safe_emoji("👥"),
        "🏦": _safe_emoji("🏦"),
    }
    out = text
    for k, v in replacements.items():
        if k in out:
            out = out.replace(k, v)
    # Ensure encodable for the console to avoid crashes
    try:
        out.encode(sys.stdout.encoding or 'utf-8')
        return out
    except (UnicodeEncodeError, LookupError):
        return out.encode('ascii', 'ignore').decode('ascii')


def print_header(title: str, emoji: str = "🔷", width: int = 60) -> None:
    """Print a formatted header with emoji and enhanced styling.
    
    Args:
        title: The header title to display
        emoji: The emoji to display with the title (default: 🔷)
        width: The width of the header line (default: 60)
    """
    safe_emoji = _safe_emoji(emoji)
    header_text = f"{safe_emoji} {title} {safe_emoji}"
    
    if _HAS_RICH and console and not _FORCE_FALLBACK:
        try:
            from rich.panel import Panel
            from rich.text import Text
            
            # Create gradient-style panel with bold text (centered)
            panel = Panel(
                Text(header_text, style="bold bright_white", justify="center"),
                style="bright_cyan",
                padding=(0, 1)
            )
            console.print(panel)
        except (UnicodeEncodeError, ImportError):
            # Fallback to simple Rich formatting
            try:
                console.print(f"{'='*width}", style="bright_cyan")
                console.print(f"{header_text:^{width}}", style="bold bright_white on bright_cyan")
                console.print(f"{'='*width}", style="bright_cyan")
            except Exception:
                # Final fallback to plain text
                print(f"{'='*width}")
                print(f"{header_text:^{width}}")
                print(f"{'='*width}")
    else:
        # Enhanced Colorama styling with background
        print(f"{Fore.CYAN}{Style.BRIGHT}{'='*width}{Style.RESET_ALL}")
        print(f"{Back.CYAN}{Fore.WHITE}{Style.BRIGHT}{header_text:^{width}}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{Style.BRIGHT}{'='*width}{Style.RESET_ALL}")


def print_separator(width: int = 60, char: str = "─") -> None:
    """Print a separator line with cyan color.
    
    Args:
        width: The width of the separator line (default: 60)
        char: The character to use for the separator (default: ─)
    """
    if _HAS_RICH and console and not _FORCE_FALLBACK:
        console.print(f"{char*width}", style="cyan")
    else:
        print(f"{Fore.CYAN}{char*width}{Style.RESET_ALL}")


def display_market_time_header(market_time_info: dict) -> None:
    """Display market time information in a formatted header.

    Args:
        market_time_info: Dictionary containing market time information
                         Expected keys: 'current_time', 'market_status', 'next_open', etc.
    """
    if not market_time_info:
        return

    if _HAS_RICH and console and not _FORCE_FALLBACK:
        # Rich formatting with table
        from rich.table import Table
        from rich.text import Text

        time_table = Table(show_header=False, show_edge=False, pad_edge=False)
        time_table.add_column("Time", style="bold cyan", width=15)
        time_table.add_column("Value", style="bold white", width=20)

        for key, value in market_time_info.items():
            time_table.add_row(f"{key}:", str(value))

        console.print(time_table)
    else:
        # Colorama fallback
        for key, value in market_time_info.items():
            print(f"{Fore.CYAN}{key}:{Style.RESET_ALL} {Fore.WHITE}{value}{Style.RESET_ALL}")


def display_market_timer(timer_info: dict, compact: bool = False) -> None:
    """Display market timer information in a formatted header.

    Args:
        timer_info: Dictionary containing market timer information
                   Expected keys: 'current_time', 'market_status', 'next_event', etc.
        compact: If True, use compact single-line format
    """
    if not timer_info:
        return

    if compact:
        # Compact format for headers
        status_emoji = "🟢" if timer_info.get('is_market_open', False) else "🔴"
        safe_status_emoji = _safe_emoji(status_emoji)
        timer_str = (f"{_safe_emoji('⏰')} {timer_info['current_time']} | "
                    f"{safe_status_emoji} {timer_info['market_status']} | "
                    f"{timer_info['next_event']} in {timer_info['countdown']}")
        print(f"{Fore.CYAN}{timer_str}{Style.RESET_ALL}")
        return

    # Full format display
    if _HAS_RICH and console and not _FORCE_FALLBACK:
        from rich.table import Table
        from rich.text import Text

        timer_table = Table(show_header=False, show_edge=False, pad_edge=False)
        timer_table.add_column("Info", style="bold cyan", width=15)
        timer_table.add_column("Value", style="bold white", width=25)

        for key, value in timer_info.items():
            if key != 'is_market_open':  # Skip internal flag
                display_key = key.replace('_', ' ').title()
                timer_table.add_row(f"{display_key}:", str(value))

        console.print(timer_table)
    else:
        # Colorama fallback
        for key, value in timer_info.items():
            if key != 'is_market_open':  # Skip internal flag
                display_key = key.replace('_', ' ').title()
                print(f"{Fore.CYAN}{display_key}:{Style.RESET_ALL} {Fore.WHITE}{value}{Style.RESET_ALL}")


def format_money_display(amount: float, currency: str = "CAD", 
                        color: Optional[str] = None, emoji: str = "") -> str:
    """Format money amount for display with color and emoji.
    
    Args:
        amount: The monetary amount to format
        currency: The currency code (default: CAD)
        color: The color to use (green, red, yellow, etc.)
        emoji: The emoji to display with the amount
        
    Returns:
        Formatted money string with color and emoji
    """
    formatted = f"{amount:,.2f} {currency}"
    
    if color and not _FORCE_FALLBACK:
        if _HAS_RICH and console:
            # Rich formatting
            return f"{emoji} {formatted}" if emoji else formatted
        else:
            # Colorama formatting
            color_map = {
                'green': Fore.GREEN,
                'red': Fore.RED,
                'yellow': Fore.YELLOW,
                'blue': Fore.BLUE,
                'cyan': Fore.CYAN,
                'magenta': Fore.MAGENTA,
                'white': Fore.WHITE
            }
            color_code = color_map.get(color.lower(), Fore.WHITE)
            return f"{color_code}{emoji} {formatted}{Style.RESET_ALL}"
    
    return f"{emoji} {formatted}" if emoji else formatted


def get_console():
    """Get the Rich console instance if available.
    
    Returns:
        Rich Console instance or None if not available
    """
    if _HAS_RICH and console and not _FORCE_FALLBACK:
        return console
    return None


def has_rich_support() -> bool:
    """Check if Rich formatting is available and enabled.
    
    Returns:
        True if Rich is available and not in fallback mode
    """
    return _HAS_RICH and console and not _FORCE_FALLBACK


def has_color_support() -> bool:
    """Check if any color formatting is available.
    
    Returns:
        True if either Rich or colorama is available
    """
    return (_HAS_RICH and console and not _FORCE_FALLBACK) or not _FORCE_COLORAMA_ONLY


def detect_environment(data_dir: Optional[str] = None) -> str:
    """Detect the current environment based on data directory.
    
    Args:
        data_dir: Optional data directory path to check
        
    Returns:
        Environment name: 'PRODUCTION', 'DEVELOPMENT', or 'UNKNOWN'
    """
    if not data_dir:
        return 'UNKNOWN'
    
    data_path = Path(data_dir).resolve()
    path_str = str(data_path).lower()
    
    # Check for new fund-based structure
    if 'trading_data/funds/' in path_str or 'trading_data\\funds\\' in path_str:
        # Extract fund name from path
        fund_name = data_path.name.lower()
        
        # Check for development/test funds
        if fund_name in ['test', 'dev', 'development', 'debug']:
            return 'DEVELOPMENT'
        
        # Check for production funds (default for most fund types)
        if fund_name in ['project chimera', 'production', 'prod', 'main']:
            return 'PRODUCTION'
        
        # For other fund types, determine based on fund configuration
        try:
            from portfolio.fund_manager import FundManager
            fm = FundManager(Path('funds.yml'))
            fund_id = fm.get_fund_by_data_directory(data_dir)
            if fund_id:
                fund = fm.get_fund_by_id(fund_id)
                if fund:
                    # Check fund config file for fund type
                    fund_config_path = Path(data_dir) / "fund_config.json"
                    if fund_config_path.exists():
                        import json
                        with open(fund_config_path, 'r') as f:
                            fund_config = json.load(f)
                            fund_type = fund_config.get("fund", {}).get("fund_type", "").lower()
                            if fund_type in ['test', 'development', 'debug']:
                                return 'DEVELOPMENT'
                            # Default to production for investment, rrsp, tfsa, etc.
                            return 'PRODUCTION'
        except:
            pass
        
        # If we can't determine from config, default to production for fund structure
        return 'PRODUCTION'
    
    # Legacy environment detection
    # Check for development environment
    if 'dev' in path_str or 'test' in path_str:
        return 'DEVELOPMENT'
    
    # Check for production environment
    if 'prod' in path_str or 'production' in path_str:
        return 'PRODUCTION'
    
    # Check for legacy test_data directory
    if 'test_data' in path_str:
        return 'DEVELOPMENT'
    
    # Check for legacy my trading directory
    if 'my trading' in path_str:
        return 'PRODUCTION'
    
    return 'UNKNOWN'


def get_environment_banner(data_dir: Optional[str] = None) -> str:
    """Get a formatted environment banner.
    
    Args:
        data_dir: Optional data directory path to check
        
    Returns:
        Formatted environment banner string
    """
    env = detect_environment(data_dir)
    
    if env == 'DEVELOPMENT':
        return f"{_safe_emoji('🔧')} DEVELOPMENT ENVIRONMENT {_safe_emoji('🔧')}"
    elif env == 'PRODUCTION':
        return f"{_safe_emoji('🚨')} PRODUCTION ENVIRONMENT {_safe_emoji('🚨')}"
    else:
        return f"{_safe_emoji('❓')} UNKNOWN ENVIRONMENT {_safe_emoji('❓')}"


def print_environment_banner(data_dir: Optional[str] = None) -> None:
    """Print a prominent environment banner.
    
    Args:
        data_dir: Optional data directory path to check
    """
    env = detect_environment(data_dir)
    banner = get_environment_banner(data_dir)
    
    # Try to get fund information for better context
    fund_name = "Unknown Fund"
    fund_type = ""
    try:
        # Extract fund name from data directory if it's a fund-based path
        if data_dir and ('trading_data/funds/' in data_dir or 'trading_data\\funds\\' in data_dir):
            from pathlib import Path
            # Use folder name as fund name, get fund type from config
            fund_name = Path(data_dir).name
            fund_type = ""
            try:
                # Try to get fund type from fund config file
                fund_config_path = Path(data_dir) / "fund_config.json"
                if fund_config_path.exists():
                    import json
                    with open(fund_config_path, 'r') as f:
                        fund_config = json.load(f)
                        fund_type = fund_config.get("fund", {}).get("fund_type", "")
            except:
                pass
        else:
            # Fallback to extracting from data directory name
            if data_dir:
                from pathlib import Path
                fund_name = Path(data_dir).name
    except:
        pass
    
    if env == 'DEVELOPMENT':
        print_warning(f"\n{'=' * 60}")
        print_warning(f"  {banner}")
        print_warning(f"  {_safe_emoji('🏦')} Fund: {fund_name}")
        if fund_type:
            print_warning(f"  {_safe_emoji('📋')} Type: {fund_type.upper()}")
        print_warning(f"  {_safe_emoji('📁')} Data Directory: {data_dir or 'Not specified'}")
        print_warning(f"  {_safe_emoji('⚠️')}  Safe to modify - This is test data")
        print_warning(f"{'=' * 60}\n")
    elif env == 'PRODUCTION':
        print_error(f"\n{'=' * 60}")
        print_error(f"  {banner}")
        print_error(f"  {_safe_emoji('🏦')} Fund: {fund_name}")
        if fund_type:
            print_error(f"  {_safe_emoji('📋')} Type: {fund_type.upper()}")
        print_error(f"  {_safe_emoji('📁')} Data Directory: {data_dir or 'Not specified'}")
        print_error(f"  {_safe_emoji('⚠️')}  CAUTION: This is LIVE PRODUCTION DATA")
        print_error(f"{'=' * 60}\n")
    else:
        print_warning(f"\n{'=' * 60}")
        print_warning(f"  {banner}")
        print_warning(f"  {_safe_emoji('🏦')} Fund: {fund_name}")
        if fund_type:
            print_warning(f"  {_safe_emoji('📋')} Type: {fund_type.upper()}")
        print_warning(f"  {_safe_emoji('📁')} Data Directory: {data_dir or 'Not specified'}")
        print_warning(f"  {_safe_emoji('⚠️')}  Environment could not be determined")
        print_warning(f"{'=' * 60}\n")