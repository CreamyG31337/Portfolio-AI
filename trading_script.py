"""Refactored trading script with modular architecture.

This is the main orchestrator for the trading system, now using a modular architecture
with proper separation of concerns. The script coordinates between different modules
while maintaining backward compatibility with existing CSV files and workflows.

Key improvements:
- Modular architecture with clear separation of concerns
- Repository pattern for data access abstraction
- Dependency injection for component management
- Comprehensive error handling and logging
- Future-ready for database migration and web dashboard
"""

from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Load environment variables from .env file (for Supabase credentials)
try:
    from dotenv import load_dotenv
    load_dotenv()  # Load .env from current directory
    logger_early = logging.getLogger(__name__)
    if os.getenv("SUPABASE_URL"):
        logger_early.info("Loaded Supabase credentials from .env file")
except ImportError:
    pass  # dotenv is optional, environment variables may be set another way

# Modular startup check - handles path setup and dependency checking
try:
    from utils.script_startup import startup_check
    startup_check("trading_script.py")
except ImportError:
    # Fallback for minimal dependency checking if script_startup isn't available
    try:
        import pandas  # noqa: F401 - imported for availability check only
    except ImportError:
        print("\n❌ Missing Dependencies (trading_script.py)")
        print("Required packages not found. Please activate virtual environment:")
        if os.name == 'nt':  # Windows
            print("  venv\\Scripts\\activate")
        else:  # Mac/Linux
            print("  source venv/bin/activate")
        print("  python trading_script.py")
        print("\n💡 TIP: Use 'python run.py' to avoid dependency issues")
        sys.exit(1)

# Force fallback mode to avoid Windows console encoding issues
# os.environ["FORCE_FALLBACK"] = "true"

import pandas as pd

# Core system imports
from config.settings import Settings, configure_system
from config.constants import LOG_FILE, VERSION

# Repository and data access
from data.repositories.repository_factory import get_repository_container, configure_repositories
from data.repositories.base_repository import BaseRepository, RepositoryError
from data.models.portfolio import PortfolioSnapshot

# Business logic modules
from portfolio.portfolio_manager import PortfolioManager, PortfolioManagerError
from utils.fund_manager import get_fund_manager, invalidate_fund_manager_cache, FundManager
from portfolio.fund_manager import FundManager as ConfigFundManager, Fund
from portfolio.fifo_trade_processor import FIFOTradeProcessor
from portfolio.position_calculator import PositionCalculator
from portfolio.trading_interface import TradingInterface

from market_data.data_fetcher import MarketDataFetcher
from market_data.market_hours import MarketHours, MarketTimer
from market_data.price_cache import PriceCache

from financial.currency_handler import CurrencyHandler
from financial.pnl_calculator import PnLCalculator

# Display and utilities
from display.console_output import print_success, print_error, print_warning, print_info, print_header, print_environment_banner, _safe_emoji
from display.table_formatter import TableFormatter
from display.terminal_utils import check_table_display_issues

from utils.backup_manager import BackupManager
from utils.system_utils import setup_error_handlers, validate_system_requirements, log_system_info, InitializationError
from utils.hash_verification import require_script_integrity, initialize_launch_time, ScriptIntegrityError

# Global logger
logger = logging.getLogger(__name__)


class TradingSystemError(Exception):
    """Base exception for trading system errors."""
    pass


def setup_logging(settings: Settings) -> None:
    """Setup logging configuration.

    Args:
        settings: System settings containing logging configuration
    """
    log_config = settings.get_logging_config()

    # Configure root logger with UTF-8 encoding for Windows compatibility
    import io
    
    # Create a UTF-8 encoded stdout wrapper for Windows emoji support
    utf8_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    
    log_file = log_config.get('file', LOG_FILE)
    max_bytes = log_config.get('max_size_mb', 10) * 1024 * 1024  # Default 10MB
    backup_count = log_config.get('backup_count', 5)  # Default 5 backups
    
    logging.basicConfig(
        level=getattr(logging, log_config.get('level', 'INFO')),
        format=log_config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s'),
        handlers=[
            RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            ),
            logging.StreamHandler(utf8_stdout)
        ]
    )

    # Allow yfinance errors to be visible so we can identify real failures
    # We need to see when tickers genuinely fail to fetch data

    logger.info(f"Logging configured - Level: {log_config.get('level', 'INFO')}")


def check_dependencies() -> dict[str, bool]:
    """Check for optional dependencies and return availability status.

    Returns:
        Dictionary mapping dependency names to availability status
    """
    dependencies = {}

    # Check for market configuration
    try:
        from market_config import get_timezone_config  # noqa: F401
        dependencies['market_config'] = True
        logger.info("Market configuration module available")
    except ImportError:
        dependencies['market_config'] = False
        logger.warning("Market configuration module not found - using defaults")

    # Check for dual currency support
    try:
        from dual_currency import CashBalances  # noqa: F401
        dependencies['dual_currency'] = True
        logger.info("Dual currency module available")
    except ImportError:
        dependencies['dual_currency'] = False
        logger.warning("Dual currency module not found - single currency mode")

    # Check for pandas-datareader (Stooq fallback)
    try:
        import pandas_datareader.data as pdr  # noqa: F401
        dependencies['pandas_datareader'] = True
        logger.info("Pandas-datareader available for Stooq fallback")
    except ImportError:
        dependencies['pandas_datareader'] = False
        logger.warning("Pandas-datareader not available - limited fallback options")

    # Check for Rich/colorama display libraries
    try:
        from rich.console import Console  # noqa: F401
        from colorama import init  # noqa: F401
        dependencies['rich_display'] = True
        logger.info("Rich display libraries available")
    except ImportError:
        dependencies['rich_display'] = False
        logger.warning("Rich display libraries not available - using plain text")

    return dependencies


def initialize_repository(settings: Settings, fund: Fund | None = None) -> BaseRepository:
    """Initialize repository based on configuration.

    Args:
        settings: System settings containing repository configuration
        fund: Optional fund object to use for repository configuration

    Returns:
        Initialized repository instance

    Raises:
        InitializationError: If repository initialization fails
    """
    try:
        repo_config = settings.get_repository_config()

        # Override fund name from fund object if provided
        if fund:
            repo_config = {**repo_config, 'fund': fund.name}

        repository_type = repo_config.get('type', 'csv')

        # Force Supabase if configured or environment variable set
        force_supabase = repo_config.get('force_supabase', False) or os.getenv('REPOSITORY_TYPE') == 'supabase'
        if force_supabase and repository_type != 'supabase':
            logger.info("Forcing Supabase repository as per configuration or environment variable")
            repository_type = 'supabase'
            repo_config = {**repo_config, 'type': 'supabase'}

        logger.info(f"Initializing {repository_type} repository for fund: {repo_config.get('fund', 'N/A')}")

        # Clear any existing repositories to avoid stale cache
        get_repository_container().clear()

        # Configure repository container
        configure_repositories({'default': repo_config})

        # Get repository instance
        repository = get_repository_container().get_repository('default')

        logger.info(f"Repository initialized: {type(repository).__name__}")
        return repository

    except Exception as e:
        error_msg = f"Failed to initialize repository: {e}"
        logger.error(error_msg)
        raise InitializationError(error_msg) from e


def initialize_components(settings: Settings, repository: BaseRepository, dependencies: dict[str, bool], fund: Fund) -> None:
    """Initialize all system components with dependency injection.

    Args:
        settings: System settings
        repository: Initialized repository instance
        dependencies: Dictionary of available dependencies
        fund: The currently active fund

    Raises:
        InitializationError: If component initialization fails
    """
    global portfolio_manager, trade_processor, position_calculator, trading_interface
    global market_data_fetcher, market_hours, market_timer, price_cache
    global currency_handler, pnl_calculator, table_formatter, backup_manager

    try:
        logger.info("Initializing system components...")

        # Initialize portfolio components
        portfolio_manager = PortfolioManager(repository, fund)
        trade_processor = FIFOTradeProcessor(repository)
        position_calculator = PositionCalculator(repository)
        trading_interface = TradingInterface(repository, trade_processor)

        # Initialize market data components
        price_cache = PriceCache(settings=settings)
        market_data_fetcher = MarketDataFetcher(cache_instance=price_cache)
        market_hours = MarketHours(settings=settings)
        market_timer = MarketTimer(market_hours=market_hours)

        # Initialize financial components
        data_dir = Path(settings.get_data_directory())
        currency_handler = CurrencyHandler(data_dir=data_dir)
        pnl_calculator = PnLCalculator()

        # Initialize display components
        table_formatter = TableFormatter(
            data_dir=settings.get_data_directory(),
            web_mode=False
        )

        # Initialize utility components
        # backup_config = settings.get_backup_config()  # Unused for now
        # Use fund-specific backup directory instead of root backups folder
        fund_backup_dir = data_dir / "backups"
        backup_manager = BackupManager(
            data_dir=data_dir,
            backup_dir=fund_backup_dir
        )

        logger.info("All system components initialized successfully")

    except Exception as e:
        error_msg = f"Failed to initialize system components: {e}"
        logger.error(error_msg)
        raise InitializationError(error_msg) from e


def handle_graceful_degradation(dependencies: dict[str, bool]) -> None:
    """Handle graceful degradation for missing optional dependencies.

    Args:
        dependencies: Dictionary of available dependencies
    """
    if not dependencies.get('market_config', True):
        print_warning("Market configuration not available - using default timezone settings")

    if not dependencies.get('dual_currency', True):
        print_warning("Dual currency support not available - using single currency mode")

    if not dependencies.get('pandas_datareader', True):
        print_warning("Pandas-datareader not available - Stooq fallback disabled")

    if not dependencies.get('rich_display', True):
        print_warning("Rich display libraries not available - using plain text output")

    # Check for critical missing dependencies
    critical_missing = []

    if critical_missing:
        error_msg = f"Critical dependencies missing: {', '.join(critical_missing)}"
        print_error(error_msg)
        print_error("Please install missing dependencies and try again")
        sys.exit(1)


def parse_command_line_arguments() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed command-line arguments
    """
    parser = argparse.ArgumentParser(
        description="Trading System - Portfolio Management and Analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python trading_script.py                           # Use default data directory
  python trading_script.py --data-dir "trading_data/funds/TEST"   # Use test data directory
  python trading_script.py --config config.json     # Use custom configuration
  python trading_script.py --debug                  # Enable debug logging
  python trading_script.py --validate-only          # Only validate data integrity
        """
    )

    parser.add_argument(
        'file_path',
        nargs='?',
        default=None,
        help='Path to portfolio CSV file (optional, uses default from config)'
    )

    parser.add_argument(
        '--data-dir',
        type=str,
        default=None,
        help='Data directory path (overrides config setting)'
    )

    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='Path to configuration file'
    )

    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )

    parser.add_argument(
        '--validate-only',
        action='store_true',
        help='Only validate data integrity and exit'
    )

    parser.add_argument(
        '--backup',
        action='store_true',
        help='Create backup before processing'
    )

    parser.add_argument(
        '--force-fallback',
        action='store_true',
        help='Force fallback mode for testing'
    )

    parser.add_argument(
        '--sort',
        type=str,
        choices=['weight', 'ticker', 'pnl', 'value', 'shares', 'price'],
        default='weight',
        help='Sort portfolio by: weight (default), ticker (alphabetical), pnl, value, shares, or price'
    )

    parser.add_argument(
        '--non-interactive',
        action='store_true',
        help='Run without interactive menu and disable screen clearing (useful for debugging and logging)'
    )

    parser.add_argument(
        '--version',
        action='version',
        version=f'Trading System {VERSION}'
    )

    args = parser.parse_args()

    # Check for NON_INTERACTIVE environment variable
    if os.environ.get("NON_INTERACTIVE", "").lower() in ("true", "1", "yes"):
        args.non_interactive = True

    return args


def initialize_system(args: argparse.Namespace) -> tuple[Settings, BaseRepository, dict[str, bool], FundManager]:
    """Initialize the trading system with configuration and dependencies.

    Args:
        args: Parsed command-line arguments

    Returns:
        Tuple of (settings, repository, dependencies, fund_manager)

    Raises:
        InitializationError: If system initialization fails
    """
    try:
        print_header("Trading System Initialization", _safe_emoji("🚀"))

        # Configure system settings
        settings = configure_system(args.config)

        # Setup logging
        setup_logging(settings)

        # Initialize Fund Manager for fund configuration loading
        config_fund_manager = ConfigFundManager(Path('funds.yml'))

        # Also initialize the active fund manager for fund switching functionality
        from utils.fund_manager import FundManager as ActiveFundManager
        import tempfile
        temp_dir = Path(tempfile.gettempdir()) / "trading_data_active"
        temp_dir.mkdir(exist_ok=True)
        fund_manager = ActiveFundManager(temp_dir)

        # Check dependencies
        dependencies = check_dependencies()

        # Handle graceful degradation
        handle_graceful_degradation(dependencies)

        # Determine which fund to use
        if args.data_dir:
            # Find fund by data directory
            fund_name = config_fund_manager.get_fund_by_data_directory(args.data_dir)
            if fund_name:
                fund = config_fund_manager.get_fund_by_id(fund_name)
                if not fund:
                    raise InitializationError(f"Fund '{fund_name}' not found in funds.yml")
                print_warning(f"Command line data directory override: {args.data_dir}")
                print_info(f"Using fund: {Path(args.data_dir).name}")
            else:
                # Data directory doesn't match any fund, use default but override directory
                fund = config_fund_manager.get_fund_by_id('default')
                if not fund:
                    raise InitializationError("Default fund not found in funds.yml")
                print_warning(f"Command line data directory override: {args.data_dir}")
                print_warning(f"Data directory doesn't match any fund, using default fund: {fund.name}")
        else:
            # Use default fund
            fund = config_fund_manager.get_fund_by_id('default')
            if not fund:
                raise InitializationError("Default fund not found in funds.yml")

        # Get repository configuration from repository_config.json
        # (Funds no longer specify repository type - it's global)
        repo_config = settings.get_repository_config()

        # Add fund name to repository config
        repo_config['fund'] = fund.name

        # Set data directory (either from command line or derive from fund name)
        if args.data_dir:
            settings.set('repository.csv.data_directory', args.data_dir)
            # Also update the main data_directory in repository config
            repo_config['data_directory'] = args.data_dir
        else:
            # Derive data directory from fund name
            fund_data_dir = f"trading_data/funds/{fund.name}"
            settings.set('repository.csv.data_directory', fund_data_dir)
            # Also update the main data_directory in repository config
            repo_config['data_directory'] = fund_data_dir

        # Update the repository config with the correct data directory
        settings.set('repository', repo_config)

        # Show environment banner (after command-line overrides)
        data_dir = settings.get_data_directory()
        print_environment_banner(data_dir)

        if args.debug:
            settings.set('logging.level', 'DEBUG')
            # Reconfigure logging with new debug level
            setup_logging(settings)

        repository = initialize_repository(settings, fund)

        # Initialize components
        initialize_components(settings, repository, dependencies, fund)

        print_success("System initialization completed successfully")

        return settings, repository, dependencies, fund_manager

    except Exception as e:
        error_msg = f"System initialization failed: {e}"
        print_error(error_msg)
        logger.error(error_msg, exc_info=True)
        raise InitializationError(error_msg) from e


def verify_script_before_action() -> None:
    """Verify script integrity before allowing sensitive operations.

    Raises:
        ScriptIntegrityError: If script integrity cannot be verified
    """
    try:
        project_root = Path(__file__).parent.absolute()
        require_script_integrity(project_root)
    except ScriptIntegrityError as e:
        print_error(f"Script integrity verification failed: {e}")
        print_error("Trading operations are disabled for security reasons")
        raise
    except Exception as e:
        print_error(f"Script integrity check failed: {e}")
        print_error("Trading operations are disabled for security reasons")
        raise ScriptIntegrityError(f"Script integrity check failed: {e}") from e


def generate_benchmark_graph(settings: Settings) -> None:
    """Generate a benchmark performance graph for the last 365 days.

    Args:
        settings: System settings containing data directory configuration
    """
    try:
        import matplotlib
        matplotlib.use('Agg')  # Use non-interactive backend
        import matplotlib.pyplot as plt
        import pandas as pd
        import yfinance as yf
        from pathlib import Path

        print_info("Setting up benchmark graph generation...")

        # Get data directory
        data_dir = settings.get_data_directory()
        if not data_dir:
            print_error("No data directory configured")
            return

        # Calculate date range for last 365 days
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)

        print_info(f"Generating benchmark graph from {start_date.date()} to {end_date.date()}")

        # Define benchmark configurations
        benchmarks = {
            'sp500': {'ticker': '^GSPC', 'name': 'S&P 500', 'color': 'blue'},
            'qqq': {'ticker': 'QQQ', 'name': 'Nasdaq-100 (QQQ)', 'color': 'orange'},
            'russell2000': {'ticker': '^RUT', 'name': 'Russell 2000', 'color': 'green'},
            'vti': {'ticker': 'VTI', 'name': 'Total Stock Market (VTI)', 'color': 'red'}
        }

        # Create date range for the last 365 days
        date_range = pd.date_range(start=start_date, end=end_date, freq='D')

        # Download and process each benchmark
        benchmark_data = {}
        for key, config in benchmarks.items():
            try:
                print_info(f"Downloading {config['name']} data...")

                # Download with extra buffer days
                download_start = start_date - timedelta(days=5)
                download_end = end_date + timedelta(days=5)

                data = yf.download(config['ticker'], start=download_start, end=download_end,
                                 progress=False, auto_adjust=False)

                if data.empty:
                    print_warning(f"No data available for {config['name']}")
                    return

                # Reset index and clean up columns
                data = data.reset_index()
                if isinstance(data.columns, pd.MultiIndex):
                    data.columns = data.columns.get_level_values(0)

                # Find baseline price (first available price in our date range)
                data['Date_Only'] = pd.to_datetime(data['Date']).dt.date
                baseline_data = data[data['Date_Only'] >= start_date.date()]

                if len(baseline_data) > 0:
                    baseline_price = baseline_data['Close'].iloc[0]
                else:
                    # Fallback to first available price
                    baseline_price = data['Close'].iloc[0]

                # Normalize to $100 baseline
                scaling_factor = 100.0 / baseline_price
                data['Normalized_Value'] = data['Close'] * scaling_factor

                # Create complete date range and merge
                portfolio_date_range = pd.DataFrame({'Date': [d.date() for d in date_range]})
                data_clean = data[['Date_Only', 'Normalized_Value']].copy()

                merged = portfolio_date_range.merge(data_clean, left_on='Date', right_on='Date_Only', how='left')
                merged['Normalized_Value'] = merged['Normalized_Value'].ffill().bfill()

                # Convert back to datetime and apply market timing
                merged['Date'] = pd.to_datetime(merged['Date'])

                # Apply market close timing (1:00 PM PST) for consistency
                for idx, row in merged.iterrows():
                    date_only = row['Date'].date()
                    weekday = pd.to_datetime(date_only).weekday()

                    if weekday < 5:  # Trading day
                        market_close_time = pd.to_datetime(date_only) + timedelta(hours=13)
                        merged.at[idx, 'Date'] = market_close_time
                    else:  # Weekend
                        weekend_market_close = pd.to_datetime(date_only) + timedelta(hours=13)
                        merged.at[idx, 'Date'] = weekend_market_close

                benchmark_data[key] = merged[['Date', 'Normalized_Value']].copy()
                print_success(f"Processed {config['name']} data: {len(merged)} days")

            except Exception as e:
                print_warning(f"Error downloading {config['name']}: {e}")
                return

        if not benchmark_data:
            print_error("No benchmark data could be downloaded")
            return

        # Create the graph
        print_info("Creating benchmark performance graph...")

        plt.figure(figsize=(16, 9))
        plt.style.use("seaborn-v0_8-whitegrid")

        # Plot each benchmark
        colors = ['blue', 'orange', 'green', 'red', 'purple', 'brown']
        styles = ['-', '--', '-.', ':', (0, (3, 1, 1, 1)), (0, (5, 5))]
        markers = ['o', 's', '^', 'v', 'D', 'p']

        for i, (key, data) in enumerate(benchmark_data.items()):
            config = benchmarks[key]
            color = colors[i % len(colors)]
            style = styles[i % len(styles)]
            marker = markers[i % len(markers)]

            # Calculate final performance
            final_value = data['Normalized_Value'].iloc[-1]
            performance = final_value - 100.0

            plt.plot(
                data['Date'],
                data['Normalized_Value'],
                label=f"{config['name']} ({performance:+.1f}%)",
                color=color,
                linestyle=style,
                linewidth=2,
                marker=marker,
                markersize=3,
                alpha=0.8
            )

        # Add weekend shading
        def add_weekend_shading():
            current_date = start_date.date()
            end_date_only = end_date.date()

            while current_date <= end_date_only:
                weekday = pd.to_datetime(current_date).weekday()

                if weekday == 5:  # Saturday
                    weekend_start = pd.to_datetime(current_date)
                    weekend_end = weekend_start + timedelta(days=2)

                    plt.axvspan(weekend_start, weekend_end,
                               color='lightgray', alpha=0.2, zorder=0)
                    current_date += timedelta(days=2)
                else:
                    current_date += timedelta(days=1)

        add_weekend_shading()

        # Add break-even line
        plt.axhline(y=100, color='gray', linestyle=':', alpha=0.7, linewidth=1.5, label='Break-even')

        # Formatting
        plt.title("Benchmark Performance Comparison\nLast 365 Days (Normalized to $100)", fontsize=14, fontweight='bold')
        plt.xlabel("Date", fontsize=12)
        plt.ylabel("Performance Index (100 = Break-even)", fontsize=12)

        # Date formatting
        import matplotlib.dates as mdates
        plt.gca().xaxis.set_major_locator(mdates.MonthLocator())
        plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        plt.gca().xaxis.set_minor_locator(mdates.WeekdayLocator(byweekday=mdates.MO))

        plt.grid(True, which='major', alpha=0.3)
        plt.grid(True, which='minor', alpha=0.1)
        plt.legend(loc='upper left', frameon=True, fancybox=True, shadow=True)
        plt.xticks(rotation=45)

        # Adjust layout
        plt.subplots_adjust(left=0.08, bottom=0.12, right=0.95, top=0.88)

        # Save the graph
        graphs_dir = Path("graphs")
        graphs_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"benchmark_comparison_365days_{timestamp}.png"
        filepath = graphs_dir / filename

        plt.savefig(filepath, dpi=300, bbox_inches="tight", facecolor='white', edgecolor='none')
        print_success(f"Benchmark graph saved to: {filepath.resolve()}")

        # Close the figure to free memory
        plt.close()

        # Try to open the graph
        try:
            import os
            import platform
            import subprocess

            system = platform.system()
            if system == "Windows":
                os.startfile(str(filepath))
                print_info("Graph opened in default viewer")
            elif system == "Darwin":  # macOS
                subprocess.run(["open", str(filepath)], check=True)
                print_info("Graph opened in default viewer")
            else:  # Linux
                subprocess.run(["xdg-open", str(filepath)], check=True)
                print_info("Graph opened in default viewer")
        except Exception as e:
            print_warning(f"Could not open graph automatically: {e}")
            print_info(f"Graph saved at: {filepath.resolve()}")

    except ImportError as e:
        print_error(f"Required packages not available: {e}")
        print_info("Please ensure matplotlib, pandas, and yfinance are installed")
    except Exception as e:
        print_error(f"Error generating benchmark graph: {e}")
        logger.error(f"Benchmark graph generation error: {e}", exc_info=True)


def switch_fund_workflow(args: argparse.Namespace, settings: Settings, fund_manager: FundManager) -> None:
    """Handle fund switching workflow.

    Args:
        args: Parsed command-line arguments
        settings: System settings
        fund_manager: Active fund manager instance (for set_active_fund functionality)
    """
    try:
        print_header("Switch Fund", _safe_emoji("🏦"))

        # Get available funds from the config fund manager
        from portfolio.fund_manager import FundManager as ConfigFundManager
        config_fund_manager = ConfigFundManager(Path('funds.yml'))
        funds = config_fund_manager.get_all_funds()
        if not funds:
            print_error("No funds available")
            return

        # Display available funds
        print_info("Available funds:")
        print()
        for i, fund in enumerate(funds, 1):
            print(f"  [{i}] {fund.name}")
            print(f"      ID: {fund.id}")
            print(f"      Description: {fund.description}")
            print()

        # Get user selection
        try:
            choice = input(f"Select fund (1-{len(funds)}) or 'q' to cancel: ").strip().lower()

            if choice == 'q':
                print_info("Fund switching cancelled")
                return

            fund_index = int(choice) - 1
            if fund_index < 0 or fund_index >= len(funds):
                print_error("Invalid selection")
                return

            selected_fund = funds[fund_index]
            print_success(f"Switching to fund: {selected_fund.name}")

            # Get global repository configuration (funds don't specify repository type anymore)
            repo_config = settings.get_repository_config()
            repo_config['fund'] = selected_fund.name
            settings.set('repository', repo_config)

            # Update the data directory setting to match the fund
            fund_data_dir = f"trading_data/funds/{selected_fund.name}"
            settings.set('repository.csv.data_directory', fund_data_dir)

            # Clear the repository cache to force a fresh instance
            from data.repositories.repository_factory import get_repository_container
            get_repository_container().clear()

            # Re-initialize repository with new fund's settings
            new_repository = initialize_repository(settings)

            # Re-initialize components with new fund
            initialize_components(settings, new_repository, check_dependencies(), selected_fund)

            # Update fund manager's active fund
            fund_manager.set_active_fund(selected_fund.name)

            # Invalidate the global fund manager cache to ensure all instances pick up the new active fund
            invalidate_fund_manager_cache()

            # Update global references
            global repository, portfolio_manager
            repository = new_repository
            # Note: fund_manager stays the same, we're just switching which fund is active

            print_success(f"Successfully switched to {selected_fund.name}")

            # Refresh the portfolio display with new fund
            run_portfolio_workflow(args, settings, new_repository, trading_interface, fund_manager, clear_caches=False)

        except ValueError:
            print_error("Invalid input. Please enter a number or 'q'")
            return
        except KeyboardInterrupt:
            print_info("\nFund switching cancelled")
            return

    except Exception as e:
        error_msg = f"Fund switching failed: {e}"
        print_error(error_msg)
        logger.error(error_msg, exc_info=True)


def switch_repository_workflow() -> None:
    """Handle repository switching workflow (CSV/Supabase)."""
    try:
        print_header("Switch Repository", _safe_emoji("🔄"))

        # Check current repository status
        try:
            from simple_repository_switch import show_status
            print_info("Current repository status:")
            show_status()
        except Exception as e:
            print_warning(f"Could not get current status: {e}")

        print()
        print_info("Available repositories:")
        print("  [1] CSV (Local files)")
        print("  [2] Supabase (Cloud database)")
        print()

        # Get user selection
        try:
            choice = input("Select repository (1-2) or 'q' to cancel: ").strip().lower()

            if choice == 'q':
                print_info("Repository switching cancelled")
                return

            if choice == '1':
                print_info("Switching to CSV repository...")
                import subprocess
                import sys
                result = subprocess.run([sys.executable, "simple_repository_switch.py", "csv"],
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    print_success("Successfully switched to CSV repository")
                    print_info("You can now use local CSV files for data storage")
                else:
                    print_error(f"Failed to switch to CSV: {result.stderr}")
                    return

            elif choice == '2':
                print_info("Switching to Supabase repository...")
                print_warning("Make sure environment variables are set:")
                print("  SUPABASE_URL and SUPABASE_ANON_KEY")

                confirm = input("Continue with Supabase switch? (y/N): ").strip().lower()
                if confirm != 'y':
                    print_info("Supabase switching cancelled")
                    return

                import subprocess
                import sys
                result = subprocess.run([sys.executable, "simple_repository_switch.py", "supabase"],
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    print_success("Successfully switched to Supabase repository")
                    print_info("You can now use cloud database for data storage")
                else:
                    print_error(f"Failed to switch to Supabase: {result.stderr}")
                    return
            else:
                print_error("Invalid selection")
                return

            # Test the new repository
            print_info("Testing new repository...")
            result = subprocess.run([sys.executable, "simple_repository_switch.py", "test"],
                                  capture_output=True, text=True)
            if result.returncode == 0:
                print_success("Repository test passed")
            else:
                print_warning(f"Repository test had issues: {result.stderr}")

        except ValueError:
            print_error("Invalid input. Please enter 1, 2, or 'q'")
            return
        except KeyboardInterrupt:
            print_info("\nRepository switching cancelled")
            return

    except Exception as e:
        error_msg = f"Repository switching failed: {e}"
        print_error(error_msg)
        logger.error(error_msg, exc_info=True)


def run_portfolio_workflow(args: argparse.Namespace, settings: Settings, repository: BaseRepository, trading_interface: TradingInterface, fund_manager: FundManager = None, clear_caches: bool = False) -> None:
    """Run the main portfolio management workflow.

    Args:
        args: Parsed command-line arguments
        settings: System settings
        repository: Initialized repository
        trading_interface: Trading interface for user actions
        fund_manager: Fund manager instance (optional)
        clear_caches: Whether to clear caches before refreshing (used when called from 'r' action)
    """
    try:
        print_header("Portfolio Management Workflow", _safe_emoji("📊"))

        # Clear only main trading screen caches if requested (when 'r' is pressed)
        if clear_caches:
            print_info("Clearing main trading screen caches...")

            # Clear price cache (market data used by main screen)
            try:
                if price_cache:
                    price_cache.invalidate_all()
                    print_success("Price cache cleared")
                else:
                    print_warning("Price cache not available")
            except Exception as e:
                logger.warning(f"Failed to clear price cache: {e}")
                print_warning(f"Failed to clear price cache: {e}")

            # Clear exchange rate cache (currency conversion used by main screen)
            try:
                if currency_handler:
                    currency_handler.clear_exchange_rate_cache()
                    print_success("Exchange rate cache cleared")
                else:
                    print_warning("Currency handler not available")
            except Exception as e:
                logger.warning(f"Failed to clear exchange rate cache: {e}")
                print_warning(f"Failed to clear exchange rate cache: {e}")

            # Clear fundamentals cache (company names and sector info used by main screen)
            try:
                if market_data_fetcher:
                    # Clear in-memory fundamentals cache
                    if hasattr(market_data_fetcher, '_fund_cache'):
                        market_data_fetcher._fund_cache.clear()
                    if hasattr(market_data_fetcher, '_fund_cache_meta'):
                        market_data_fetcher._fund_cache_meta.clear()

                    # Clear disk-based fundamentals cache
                    fund_cache_path = market_data_fetcher._get_fund_cache_path()
                    if fund_cache_path and fund_cache_path.exists():
                        try:
                            fund_cache_path.unlink()
                            print_success("Fundamentals cache cleared (disk and memory)")
                        except Exception as disk_error:
                            logger.warning(f"Failed to clear fundamentals cache file: {disk_error}")
                            print_success("Fundamentals cache cleared (memory only)")
                    else:
                        print_success("Fundamentals cache cleared (memory)")
                else:
                    print_warning("Market data fetcher not available")
            except Exception as e:
                logger.warning(f"Failed to clear fundamentals cache: {e}")
                print_warning(f"Failed to clear fundamentals cache: {e}")

            print_info("Cache clearing completed - ticker correction and other unrelated caches preserved")

        # Validate data integrity if requested
        if args.validate_only:
            print_info("Running data integrity validation...")
            validation_errors = repository.validate_data_integrity()

            if validation_errors:
                print_error(f"Data validation failed with {len(validation_errors)} errors:")
                for error in validation_errors:
                    print_error(f"  • {error}")
                sys.exit(1)  # sys is imported at the top of the file
            else:
                print_success("Data validation passed - no issues found")
                return

        # Create backup if requested
        if args.backup or settings.get('backup.auto_backup_on_save', True):
            print_info("Creating data backup...")
            backup_path = backup_manager.create_backup()
            print_success(f"Backup created: {backup_path}")

        # Check terminal display capabilities
        check_table_display_issues()

        # Load portfolio data
        import time
        print_info("Loading portfolio data...")
        portfolio_load_start = time.time()
        
        # Get latest snapshot using view-based method (includes company names from securities table)
        latest_snapshot = portfolio_manager.get_latest_portfolio()
        
        if not latest_snapshot:
            print_warning("No portfolio data found")
            return
        
        portfolio_load_time = time.time() - portfolio_load_start
        print_success(f"Loaded portfolio with {len(latest_snapshot.positions)} positions ({portfolio_load_time:.2f}s)")
        
        # Load historical snapshots for duplicate checking (separate from display data)
        # Use repository directly to avoid duplicate check raising exception
        # We'll check duplicates ourselves with strict=False to just warn
        snapshots_load_start = time.time()
        try:
            portfolio_snapshots = portfolio_manager.load_portfolio()
        except PortfolioManagerError as e:
            # If load_portfolio() raised due to duplicates, load data directly from repository
            # to allow us to check and warn instead of crashing
            print_warning("Duplicate snapshots detected during load - loading data directly for validation")
            portfolio_snapshots = portfolio_manager.repository.get_portfolio_data()
        snapshots_load_time = time.time() - snapshots_load_start
        if snapshots_load_time > 0.5:
            print_info(f"   Historical snapshots loaded: {snapshots_load_time:.2f}s")

        # Optional: Additional validation
        from utils.validation import check_duplicate_snapshots, validate_snapshot_timestamps

        # Check for duplicates (with strict=False to just warn in production)
        has_duplicates, duplicates = check_duplicate_snapshots(portfolio_snapshots, strict=False)
        if has_duplicates:
            print_warning(f"WARNING: Found duplicate snapshots for {len(duplicates)} dates")
            print_warning("   Run 'rebuild' from the menu to fix")

        # Validate timestamps
        if not validate_snapshot_timestamps(portfolio_snapshots):
            print_info("INFO: Some snapshots have non-standard timestamps")

        # Update exchange rates CSV with current rates
        print_info("Updating exchange rates...")
        exchange_rates_start = time.time()
        currency_handler.update_exchange_rates_csv()
        exchange_rates_time = time.time() - exchange_rates_start
        if exchange_rates_time > 0.5:
            print_info(f"   Exchange rates updated: {exchange_rates_time:.2f}s")

        # Fetch current market data with cache-first optimization
        print_info("Fetching current market data...")
        market_data_start = time.time()
        tickers = [pos.ticker for pos in latest_snapshot.positions]

        if tickers:
            # Populate currency cache from portfolio positions before fetching
            # This ensures we know which tickers are USD vs CAD to avoid wrong Canadian fallbacks
            for pos in latest_snapshot.positions:
                currency = pos.currency or 'USD'
                if currency:
                    market_data_fetcher._portfolio_currency_cache[pos.ticker.upper()] = currency.upper()
            
            end_date = datetime.now()
            # Go back about 15 calendar days to ensure we get at least 10 trading days
            start_date = end_date - timedelta(days=15)

            # Cache-first approach: Check cache first, only fetch missing data
            market_data = {}
            cache_hits = 0
            api_calls = 0

            for ticker in tickers:
                try:
                    # First, try to get cached data
                    cached_data = price_cache.get_cached_price(ticker, start_date, end_date)

                    if cached_data is not None and not cached_data.empty:
                        # Use cached data
                        market_data[ticker] = cached_data
                        cache_hits += 1
                        logger.debug(f"Cache hit for {ticker}: {len(cached_data)} rows")
                    else:
                        # Cache miss - fetch fresh data
                        result = market_data_fetcher.fetch_price_data(ticker, start_date, end_date)
                        if not result.df.empty:
                            market_data[ticker] = result.df
                            # Update price cache with fresh data
                            price_cache.cache_price_data(ticker, result.df, result.source)
                            api_calls += 1
                            logger.debug(f"API fetch for {ticker}: {len(result.df)} rows from {result.source}")
                        else:
                            market_data[ticker] = pd.DataFrame()
                            logger.warning(f"No data returned for {ticker}")

                except Exception as e:
                    logger.warning(f"Failed to fetch data for {ticker}: {e}")
                    market_data[ticker] = pd.DataFrame()

            # Report optimization results
            market_data_time = time.time() - market_data_start
            if cache_hits > 0:
                print_success(f"Updated market data for {len(market_data)} tickers ({cache_hits} from cache, {api_calls} fresh fetches) ({market_data_time:.2f}s)")
            else:
                print_success(f"Updated market data for {len(market_data)} tickers ({market_data_time:.2f}s)")

        # Collect warnings/info messages during metrics calculation to display at bottom
        # Set this up BEFORE calculating metrics so we capture all warnings
        import logging
        from collections import deque
        
        # Store collected messages and original filters
        warning_messages = deque(maxlen=50)
        original_filters = {}
        
        def suppress_warnings_filter(record):
            """Filter to suppress specific warning/info messages and collect them instead."""
            msg = record.getMessage()
            keywords = [
                'Using estimated fees for Webull',
                'NAV FALLBACK',
                'No timestamp for contribution',
                'Missing timestamp for contribution'
            ]
            if any(keyword in msg for keyword in keywords):
                warning_messages.append({
                    'level': record.levelname,
                    'message': msg
                })
                return False  # Suppress this message
            return True  # Allow other messages through
        
        # Apply filter to StreamHandlers to suppress these messages during table generation
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            if isinstance(handler, logging.StreamHandler):
                original_filters[id(handler)] = handler.filters[:]
                handler.addFilter(suppress_warnings_filter)
        
        # Also apply to specific loggers
        main_logger = logging.getLogger('__main__')
        pos_calc_logger = logging.getLogger('portfolio.position_calculator')
        for handler in main_logger.handlers + pos_calc_logger.handlers:
            if isinstance(handler, logging.StreamHandler):
                if id(handler) not in original_filters:
                    original_filters[id(handler)] = handler.filters[:]
                handler.addFilter(suppress_warnings_filter)
        
        # Calculate portfolio metrics
        print_info("Calculating portfolio metrics...")
        metrics_start = time.time()

        # Update positions with current prices
        updated_positions = []
        for position in latest_snapshot.positions:
            cached_data = price_cache.get_cached_price(position.ticker)
            if cached_data is not None and not cached_data.empty:
                # Get the latest close price from the cached data and convert to Decimal
                from decimal import Decimal
                current_price = Decimal(str(cached_data['Close'].iloc[-1]))

                # Extra debug for GLCC
                if position.ticker == 'GLCC':
                    logger.info(f"\n{'='*60}")
                    logger.info("GLCC PRICE UPDATE DEBUG:")
                    logger.info(f"  Position from DB: avg_price={position.avg_price}, current_price={position.current_price}")
                    logger.info(f"  Cached price data: {len(cached_data)} rows")
                    logger.info(f"  Latest cached price: ${current_price}")
                    logger.info(f"  Shares: {position.shares}")

                updated_position = position_calculator.update_position_with_price(
                    position, current_price
                )

                # Extra debug for GLCC
                if position.ticker == 'GLCC':
                    logger.info(f"  Updated position: avg_price={updated_position.avg_price}, current_price={updated_position.current_price}")
                    logger.info(f"  Market value: {updated_position.market_value}")
                    logger.info(f"  Unrealized P&L: {updated_position.unrealized_pnl}")
                    logger.info(f"{'='*60}\n")

                updated_positions.append(updated_position)
                logger.debug(f"Updated {position.ticker} with cached price: ${current_price}")
            else:
                # Fallback: use the current price from the position itself (from CSV)
                if position.current_price is not None:
                    updated_positions.append(position)
                    logger.debug(f"Using CSV price for {position.ticker}: ${position.current_price}")
                else:
                    updated_positions.append(position)
                    logger.debug(f"No price data for {position.ticker}")

        # Calculate P&L metrics
        pnl_metrics = pnl_calculator.calculate_portfolio_pnl(updated_positions)

        # Calculate additional display metrics
        enhanced_positions = []
        from decimal import Decimal

        # Calculate total portfolio value with proper currency conversion
        total_portfolio_value = Decimal('0')
        from utils.currency_converter import load_exchange_rates, convert_usd_to_cad
        from pathlib import Path

        # Load exchange rates for currency conversion
        exchange_rates = load_exchange_rates(Path(repository.data_dir))

        for pos in updated_positions:
            if pos.market_value is not None:
                if pos.currency == 'USD':
                    # Convert USD to CAD
                    market_value_cad = convert_usd_to_cad(pos.market_value, exchange_rates)
                else:
                    # Already in CAD (or assume CAD if currency field missing)
                    market_value_cad = pos.market_value
                total_portfolio_value += market_value_cad


        # Debug output to file when in non-interactive mode (screen clearing is disabled)
        if args.non_interactive:
            with open('debug_output.txt', 'w') as debug_file:
                debug_file.write("\n=== STARTING POSITION PROCESSING ===\n")
                debug_file.write(f"Number of positions to process: {len(updated_positions)}\n")
                debug_file.flush()

        # OPTIMIZATION: Get all trade history once instead of per-position (N+1 query fix)
        # Build a lookup dictionary: ticker -> list of trades
        position_process_start = time.time()
        trade_history_lookup = {}
        try:
            all_trades = repository.get_trade_history()  # Get all trades for the fund
            for trade in all_trades:
                if trade.ticker not in trade_history_lookup:
                    trade_history_lookup[trade.ticker] = []
                trade_history_lookup[trade.ticker].append(trade)
        except Exception as e:
            logger.warning(f"Failed to load trade history for opened_date lookup: {e}")
            trade_history_lookup = {}
        
        for position in updated_positions:
            if args.non_interactive:
                with open('debug_output.txt', 'a') as debug_file:
                    debug_file.write(f"Processing position: {position.ticker}\n")
                    debug_file.flush()
            pos_dict = position.to_dict()

            # Calculate position weight
            if total_portfolio_value > 0 and position.market_value:
                weight_percentage = (position.market_value / total_portfolio_value) * 100
                pos_dict['position_weight'] = f"{weight_percentage:.1f}%"
            else:
                pos_dict['position_weight'] = "N/A"

            # Add total_pnl field for sorting (use calculated unrealized_pnl)
            calculated_pnl = position.calculated_unrealized_pnl
            if calculated_pnl != 0:
                pos_dict['total_pnl'] = f"${calculated_pnl:.2f}"
            else:
                pos_dict['total_pnl'] = "$0.00"

            # Get open date from trade log (optimized - use lookup dictionary)
            try:
                trades = trade_history_lookup.get(position.ticker, [])
                if trades:
                    # Find first BUY trade for this ticker
                    buy_trades = [t for t in trades if t.action.upper() == 'BUY']
                    if buy_trades:
                        first_buy = min(buy_trades, key=lambda t: t.timestamp)
                        pos_dict['opened_date'] = first_buy.timestamp.strftime('%m-%d-%y')
                        logger.debug(f"Found open date for {position.ticker}: {pos_dict['opened_date']}")
                    else:
                        pos_dict['opened_date'] = "N/A"
                        logger.debug(f"No BUY trades found for {position.ticker}")
                else:
                    pos_dict['opened_date'] = "N/A"
                    logger.debug(f"No trades found for {position.ticker}")
            except Exception as e:
                logger.warning(f"Could not get open date for {position.ticker}: {e}")
                pos_dict['opened_date'] = "N/A"

            # Calculate daily P&L using historical portfolio data
            # SHARED LOGIC: Same function used by prompt_generator.py when user hits 'd' in menu
            # Smart logic: If today's snapshot exists in CSV, we exclude it because we've updated with fresh prices
            # If today's snapshot doesn't exist (pre-market), we use all snapshots as-is
            today_date = datetime.now().date()
            latest_snapshot_date = portfolio_snapshots[-1].timestamp.date() if portfolio_snapshots else None

            if latest_snapshot_date == today_date:
                # Today's snapshot exists - exclude it since we have fresh prices
                historical_snapshots = portfolio_snapshots[:-1] if len(portfolio_snapshots) > 1 else []
            else:
                # Pre-market or weekend - use all snapshots as-is
                historical_snapshots = portfolio_snapshots

            if args.non_interactive:
                with open('debug_output.txt', 'a') as debug_file:
                    debug_file.write(f"  Calculating 1-day P&L for {position.ticker}:\n")
                    debug_file.write(f"    Current price: {position.current_price}\n")
                    debug_file.write(f"    Shares: {position.shares}\n")
                    debug_file.write(f"    Latest snapshot date: {latest_snapshot_date}\n")
                    debug_file.write(f"    Today's date: {today_date}\n")
                    debug_file.write(f"    Using {len(historical_snapshots)} snapshots for comparison\n")
                    debug_file.flush()

            # Calculate daily P&L from historical snapshots
            from financial.pnl_calculator import calculate_daily_pnl_from_snapshots
            pos_dict['daily_pnl'] = calculate_daily_pnl_from_snapshots(position, historical_snapshots)


            # 5-day P&L with open-date check (show N/A if opened < 5 trading days ago)
            try:
                # Explicitly import pandas here to ensure it's available in this scope
                import pandas as pd
                from decimal import Decimal

                # Reuse existing opened_date calculation from above
                opened_date_str = pos_dict.get('opened_date', 'N/A')
                if args.non_interactive:
                    with open('debug_output.txt', 'a') as debug_file:
                        debug_file.write(f"  5-day P&L calc for {position.ticker}: opened_date={opened_date_str}\n")
                        debug_file.flush()
                # logger.debug(f"{position.ticker}: Starting 5-day P&L calculation with opened_date: {opened_date_str}")

                if opened_date_str != 'N/A':
                    # Parse the opened date (format: 'MM-DD-YY')
                    try:
                        opened_dt = datetime.strptime(opened_date_str, '%m-%d-%y')
                        # Handle 2-digit year: assume 20xx for years 00-30, 19xx for years 31-99
                        if opened_dt.year < 2000:
                            opened_dt = opened_dt.replace(year=opened_dt.year + 2000)
                        # Make it timezone-aware
                        tz = market_hours.get_trading_timezone()
                        opened_dt = tz.localize(opened_dt)
                        now_tz = datetime.now(tz)

                        # Count trading days between open and now (inclusive)
                        days_held_trading = market_hours.trading_days_between(opened_dt, now_tz)

                        logger.debug(f"{position.ticker}: opened {opened_date_str}, {days_held_trading} trading days held")

                        # Check if we have a current price first
                        if position.current_price is None:
                            pos_dict['five_day_pnl'] = "N/A"
                            logger.debug(f"{position.ticker}: No current price available for 5-day P&L")
                        # For positions with 2-4 trading days, show partial period P&L in yellow
                        elif 1 < days_held_trading < 5:
                            try:
                                # Use cached historical data for partial period calculation
                                cached_hist = price_cache.get_cached_price(position.ticker)
                                has_data = False
                                if cached_hist is not None:
                                    if isinstance(cached_hist, pd.DataFrame):
                                        has_data = not cached_hist.empty

                                if has_data and isinstance(cached_hist, pd.DataFrame):
                                    # Handle different possible column names for closing price
                                    close_col = None
                                    for col_name in ['Close', 'close', 'CLOSE', 'Adj Close', 'adj_close']:
                                        if col_name in cached_hist.columns:
                                            close_col = col_name
                                            break

                                    if close_col is not None:
                                        closes_series = cached_hist[close_col]
                                        # For partial periods, use available data (need at least days_held_trading + 1)
                                        required_data_points = days_held_trading + 1
                                        if len(closes_series) >= required_data_points:
                                            # Get price from beginning of holding period
                                            start_price_float = closes_series.iloc[-required_data_points]
                                            start_price = Decimal(str(start_price_float))
                                            current_price = position.current_price

                                            # Calculate partial period P&L
                                            period = pnl_calculator.calculate_period_pnl(
                                                current_price,
                                                start_price,
                                                position.shares,
                                                period_name=f"{days_held_trading}_day"
                                            )

                                            abs_pnl = period.get(f'{days_held_trading}_day_absolute_pnl')
                                            pct_pnl = period.get(f'{days_held_trading}_day_percentage_pnl')

                                            if abs_pnl is not None and pct_pnl is not None:
                                                # Format with day prefix to indicate partial period
                                                pct_value = float(pct_pnl) * 100
                                                if abs_pnl >= 0:
                                                    pos_dict['five_day_pnl'] = f"${abs_pnl:.2f} +{pct_value:.1f}%"
                                                    pos_dict['five_day_period_type'] = f"{days_held_trading}d"  # Store period info for coloring
                                                else:
                                                    pos_dict['five_day_pnl'] = f"${abs(abs_pnl):.2f} {pct_value:.1f}%"
                                                    pos_dict['five_day_period_type'] = f"{days_held_trading}d"  # Store period info for coloring

                                                if args.non_interactive:
                                                    with open('debug_output.txt', 'a') as debug_file:
                                                        debug_file.write(f"    {position.ticker}: ✓ {days_held_trading}-day P&L calculated: {pos_dict['five_day_pnl']}\n")
                                                        debug_file.flush()
                                                logger.debug(f"{position.ticker}: {days_held_trading}-day P&L calculated: {pos_dict['five_day_pnl']}")
                                            else:
                                                pos_dict['five_day_pnl'] = "N/A"
                                        else:
                                            pos_dict['five_day_pnl'] = "N/A"
                                    else:
                                        pos_dict['five_day_pnl'] = "N/A"
                                else:
                                    pos_dict['five_day_pnl'] = "N/A"
                            except Exception as partial_error:
                                pos_dict['five_day_pnl'] = "N/A"
                                logger.debug(f"{position.ticker}: Partial period calculation error: {str(partial_error)}")
                        # Too new (1 day or less) - show N/A
                        elif days_held_trading <= 1:
                            pos_dict['five_day_pnl'] = "N/A"
                            if args.non_interactive:
                                with open('debug_output.txt', 'a') as debug_file:
                                    debug_file.write(f"    {position.ticker}: Too new for multi-day P&L ({days_held_trading} <= 1 day)\n")
                                    debug_file.flush()
                            logger.debug(f"{position.ticker}: Too new for multi-day P&L ({days_held_trading} <= 1 day)")
                        else:
                            # Use cached historical data instead of fetching again
                            try:
                                cached_hist = price_cache.get_cached_price(position.ticker)
                                has_data = False
                                if cached_hist is not None:
                                    if isinstance(cached_hist, pd.DataFrame):
                                        has_data = not cached_hist.empty
                                    else:
                                        logger.warning(f"{position.ticker}: Cached data is not a DataFrame type: {type(cached_hist)}")

                                if args.non_interactive:
                                    with open('debug_output.txt', 'a') as debug_file:
                                        debug_file.write(f"    {position.ticker}: Cache lookup - found data: {has_data}\n")
                                        debug_file.flush()

                                if has_data and isinstance(cached_hist, pd.DataFrame):

                                    # Handle different possible column names for closing price
                                    close_col = None
                                    for col_name in ['Close', 'close', 'CLOSE', 'Adj Close', 'adj_close']:
                                        if col_name in cached_hist.columns:
                                            close_col = col_name
                                            break

                                    if close_col is not None:
                                        if args.non_interactive:
                                            with open('debug_output.txt', 'a') as debug_file:
                                                debug_file.write(f"      {position.ticker}: Cache validation passed (using {close_col} column)\n")
                                                debug_file.flush()

                                        closes_series = cached_hist[close_col]
                                        logger.debug(f"{position.ticker}: Using cached historical closes ({len(closes_series)} days)")

                                        # Need at least 6 trading days of data (5 days ago + today)
                                        if args.non_interactive:
                                            with open('debug_output.txt', 'a') as debug_file:
                                                debug_file.write(f"      {position.ticker}: Has {len(closes_series)} days of data\n")
                                                debug_file.flush()
                                        if len(closes_series) >= 6:
                                            if args.non_interactive:
                                                with open('debug_output.txt', 'a') as debug_file:
                                                    debug_file.write(f"        {position.ticker}: Starting 5-day P&L calculation...\n")
                                                    debug_file.flush()

                                            # Get price from 5 trading days ago (6th from last)
                                            start_price_5d_float = closes_series.iloc[-6]
                                            # Convert to Decimal to match position.current_price type
                                            start_price_5d = Decimal(str(start_price_5d_float))
                                            current_price = position.current_price

                                            if args.non_interactive:
                                                with open('debug_output.txt', 'a') as debug_file:
                                                    debug_file.write(f"        {position.ticker}: Price 5-days ago: ${start_price_5d_float}, current: ${current_price}\n")
                                                    debug_file.flush()

                                            logger.debug(f"{position.ticker}: 5-day ago price: ${start_price_5d:.2f}, current: ${current_price:.2f}")

                                            # Calculate P&L from 5 trading days ago to current price
                                            # Ensure all inputs are Decimal type for financial calculations
                                            if args.non_interactive:
                                                with open('debug_output.txt', 'a') as debug_file:
                                                    debug_file.write(f"        {position.ticker}: Calling pnl_calculator.calculate_period_pnl()...\n")
                                                    debug_file.flush()

                                            try:
                                                period = pnl_calculator.calculate_period_pnl(
                                                    current_price,
                                                    start_price_5d,
                                                    position.shares,
                                                    period_name="five_day"
                                                )

                                                if args.non_interactive:
                                                    with open('debug_output.txt', 'a') as debug_file:
                                                        debug_file.write(f"        {position.ticker}: P&L calculation returned: {period}\n")
                                                        debug_file.flush()

                                                # Extract and format the P&L results
                                                abs_pnl = period.get('five_day_absolute_pnl')
                                                pct_pnl = period.get('five_day_percentage_pnl')

                                                if args.non_interactive:
                                                    with open('debug_output.txt', 'a') as debug_file:
                                                        debug_file.write(f"        {position.ticker}: Extracting P&L values: abs_pnl={abs_pnl}, pct_pnl={pct_pnl}\n")
                                                        debug_file.flush()

                                                if args.non_interactive:
                                                    with open('debug_output.txt', 'a') as debug_file:
                                                        debug_file.write(f"        {position.ticker}: Checking P&L values - abs_pnl is not None: {abs_pnl is not None}, pct_pnl is not None: {pct_pnl is not None}\n")
                                                        debug_file.flush()

                                                if abs_pnl is not None and pct_pnl is not None:
                                                    # Format like the daily P&L: "$123.45 +1.2%" or "-$123.45 -1.2%"
                                                    pct_value = float(pct_pnl) * 100
                                                    if abs_pnl >= 0:
                                                        pos_dict['five_day_pnl'] = f"${abs_pnl:.2f} +{pct_value:.1f}%"
                                                    else:
                                                        pos_dict['five_day_pnl'] = f"${abs(abs_pnl):.2f} {pct_value:.1f}%"

                                                    if args.non_interactive:
                                                        with open('debug_output.txt', 'a') as debug_file:
                                                            debug_file.write(f"        {position.ticker}: ✓ 5-day P&L calculated: {pos_dict['five_day_pnl']}\n")
                                                            debug_file.flush()
                                                    logger.debug(f"{position.ticker}: 5-day P&L calculated: {pos_dict['five_day_pnl']}")
                                                else:
                                                    pos_dict['five_day_pnl'] = "N/A"
                                                    if args.non_interactive:
                                                        with open('debug_output.txt', 'a') as debug_file:
                                                            debug_file.write(f"        {position.ticker}: ✗ P&L calculation returned None values\n")
                                                            debug_file.flush()
                                                    logger.debug(f"{position.ticker}: P&L calculation returned None")

                                            except Exception as pnl_error:
                                                if args.non_interactive:
                                                    with open('debug_output.txt', 'a') as debug_file:
                                                        debug_file.write(f"        {position.ticker}: ✗ P&L calculation error: {str(pnl_error)}\n")
                                                        debug_file.flush()
                                                pos_dict['five_day_pnl'] = "N/A"
                                                logger.debug(f"{position.ticker}: P&L calculation error: {str(pnl_error)}")
                                        else:
                                            pos_dict['five_day_pnl'] = "N/A"
                                            if args.non_interactive:
                                                with open('debug_output.txt', 'a') as debug_file:
                                                    debug_file.write(f"      {position.ticker}: ✗ Insufficient historical data ({len(closes_series)} < 6)\n")
                                                    debug_file.flush()
                                            logger.debug(f"{position.ticker}: Insufficient historical data ({len(closes_series)} < 6)")
                                    else:
                                        pos_dict['five_day_pnl'] = "N/A"
                                        if args.non_interactive:
                                            with open('debug_output.txt', 'a') as debug_file:
                                                debug_file.write(f"      {position.ticker}: ✗ No close price column found\n")
                                                debug_file.flush()
                                        logger.debug(f"{position.ticker}: No close price column found")
                                else:
                                    pos_dict['five_day_pnl'] = "N/A"
                                    if args.non_interactive:
                                        with open('debug_output.txt', 'a') as debug_file:
                                            debug_file.write(f"      {position.ticker}: ✗ Cache validation failed\n")
                                            debug_file.flush()
                                    logger.debug(f"{position.ticker}: No price data available")
                            except Exception as cache_error:
                                pos_dict['five_day_pnl'] = "N/A"
                                if args.non_interactive:
                                    with open('debug_output.txt', 'a') as debug_file:
                                        debug_file.write(f"      {position.ticker}: ✗ Error in cache processing: {str(cache_error)}\n")
                                        debug_file.flush()
                                logger.debug(f"{position.ticker}: Cache processing error: {str(cache_error)}")
                                logger.debug(f"{position.ticker}: No price data available")
                    except Exception as date_parse_error:
                        logger.debug(f"{position.ticker}: Date parsing error: {date_parse_error}")
                        pos_dict['five_day_pnl'] = "N/A"
                else:
                    pos_dict['five_day_pnl'] = "N/A"
                    logger.debug(f"{position.ticker}: No opened date available")


            except Exception as e:
                logger.warning(f"Could not calculate 5-day P&L for {position.ticker}: {e}")
                logger.debug(f"Full 5-day P&L error for {position.ticker}", exc_info=True)
                pos_dict['five_day_pnl'] = "N/A"

            enhanced_positions.append(pos_dict)

        position_process_time = time.time() - position_process_start
        if position_process_time > 0.5:  # Only show if it took significant time
            print_info(f"   Position processing: {position_process_time:.2f}s")

        # Sort positions based on command-line argument
        def get_sort_key(pos_dict, sort_by):
            """Extract sort key based on the specified sort option."""
            if sort_by == 'weight':
                # Sort by weight percentage (highest first)
                weight_str = pos_dict.get('position_weight', '0.0%')
                if weight_str == 'N/A':
                    return -1  # Put N/A values at the end
                try:
                    return float(weight_str.replace('%', ''))
                except (ValueError, AttributeError):
                    return -1
            elif sort_by == 'ticker':
                # Sort by ticker alphabetically
                return pos_dict.get('ticker', '').upper()
            elif sort_by == 'pnl':
                # Sort by total P&L (highest first)
                pnl_str = pos_dict.get('total_pnl', '$0.00')
                if pnl_str == 'N/A':
                    return -999999  # Put N/A values at the end
                try:
                    # Remove $ and , from P&L string
                    pnl_clean = pnl_str.replace('$', '').replace(',', '').replace('+', '')
                    return float(pnl_clean)
                except (ValueError, AttributeError):
                    return -999999
            elif sort_by == 'value':
                # Sort by total value (highest first)
                value_str = pos_dict.get('total_value', '$0.00')
                if value_str == 'N/A':
                    return -999999  # Put N/A values at the end
                try:
                    # Remove $ and , from value string
                    value_clean = value_str.replace('$', '').replace(',', '')
                    return float(value_clean)
                except (ValueError, AttributeError):
                    return -999999
            elif sort_by == 'shares':
                # Sort by number of shares (highest first)
                shares = pos_dict.get('shares', 0)
                try:
                    return float(shares)
                except (ValueError, TypeError):
                    return 0
            elif sort_by == 'price':
                # Sort by current price (highest first)
                price_str = pos_dict.get('current_price', '$0.00')
                if price_str == 'N/A':
                    return -999999  # Put N/A values at the end
                try:
                    # Remove $ from price string
                    price_clean = price_str.replace('$', '')
                    return float(price_clean)
                except (ValueError, AttributeError):
                    return -999999
            else:
                # Default to weight sorting
                return get_sort_key(pos_dict, 'weight')

        # Sort positions based on the specified sort option
        reverse_sort = args.sort in ['weight', 'pnl', 'value', 'shares', 'price']  # These sort highest first
        enhanced_positions.sort(key=lambda pos: get_sort_key(pos, args.sort), reverse=reverse_sort)

        # Clear screen before displaying portfolio (unless in non-interactive mode)
        import os
        import pandas as pd
        from pathlib import Path
        if not args.non_interactive:
            os.system('cls' if os.name == 'nt' else 'clear')

        # Get market timer info for header
        market_time_info = ""
        try:
            market_time_info = market_timer.display_market_timer(compact=True)
        except Exception as e:
            logger.debug(f"Could not get market timer header: {e}")
            # Fallback to simple time display
            try:
                tz = market_hours.get_trading_timezone()
                now = datetime.now(tz)
                market_time_info = f"{_safe_emoji('⏰')} {now.strftime('%Y-%m-%d %H:%M:%S')} PDT | {_safe_emoji('🔴')} MARKET CLOSED"
            except Exception:
                market_time_info = ""

        # Get fund name for display
        fund_indicator = ""
        try:
            from utils.fund_ui import get_current_fund_info

            # Get fund information for display
            fund_info = get_current_fund_info()
            if fund_info.get("exists"):
                fund_name = fund_info.get("name", "Unknown")
                fund_indicator = f"{_safe_emoji('📊')} {fund_name}"
            else:
                # Fallback - extract fund name from data directory
                from pathlib import Path
                fund_name = Path(repository.data_dir).name
                fund_indicator = f"{_safe_emoji('📊')} {fund_name}"
        except Exception:
            fund_indicator = ""

        # Get data source indicator for display
        data_source_indicator = ""
        try:
            # Check what type of repository we're using
            repo_type = type(repository).__name__
            if "CSV" in repo_type:
                # CSV repository - show file path
                data_source_indicator = f"{_safe_emoji('💾')} CSV"
            elif "Supabase" in repo_type or "Database" in repo_type:
                # Supabase/Database repository - show cloud indicator
                data_source_indicator = f"{_safe_emoji('☁️')} Supabase"
            else:
                # Unknown repository type - show generic indicator
                data_source_indicator = f"{_safe_emoji('🗄️')} {repo_type.replace('Repository', '')}"
        except Exception:
            # If we can't determine the repository type, don't show indicator
            data_source_indicator = ""

        # Get experiment timeline for header
        timeline_info = ""
        try:
            from utils.timeline_utils import format_timeline_display
            timeline_info = format_timeline_display(repository.data_dir)
        except Exception as e:
            logger.debug(f"Could not get experiment timeline: {e}")

        # Display portfolio table with market timer, timeline, and fund in header
        timeline_part = f"{_safe_emoji('📅')} {timeline_info}" if timeline_info else ""

        # Build header with all available information
        header_parts = ["Portfolio Summary"]
        if market_time_info:
            header_parts.append(market_time_info)
        if timeline_part:
            header_parts.append(timeline_part)
        if fund_indicator:
            header_parts.append(fund_indicator)
        if data_source_indicator:
            header_parts.append(data_source_indicator)

        header_title = " | ".join(header_parts)

        # UPDATE CSV BEFORE DISPLAYING - This ensures the portfolio data is current
        try:
            # Create updated snapshot with current prices
            # updated_snapshot = PortfolioSnapshot(  # Unused for now
            #     positions=updated_positions,
            #     timestamp=datetime.now(),
            #     total_value=sum(((pos.market_value or Decimal('0')) for pos in updated_positions), Decimal('0'))
            # )

            # Use centralized portfolio update logic
            from utils.portfolio_update_logic import should_update_portfolio

            needs_update, reason = should_update_portfolio(market_hours, portfolio_manager)
            if needs_update:
                # should_update_prices = True  # Variable is set but not used
                logger.info(reason)
            else:
                print_info(f"Portfolio prices not updated ({reason})")

            # Portfolio refresh logic - creates missing HOLD entries and updates prices
            from utils.portfolio_refresh import refresh_portfolio_prices_if_needed

            was_updated, reason = refresh_portfolio_prices_if_needed(
                market_hours=market_hours,
                portfolio_manager=portfolio_manager,
                repository=repository,
                market_data_fetcher=market_data_fetcher,
                price_cache=price_cache,
                verbose=False  # Use logger instead of print for main trading script
            )

            if was_updated:
                logger.info(f"Portfolio prices updated: {reason}")
                print_success("Portfolio snapshot updated successfully")
            else:
                logger.debug(f"Portfolio prices not updated: {reason}")

        except Exception as e:
            logger.warning(f"Could not save portfolio snapshot: {e}")
            print_warning(f"Could not save portfolio snapshot: {e}")

        print_header(header_title, _safe_emoji("📊"))
        table_formatter.create_portfolio_table(enhanced_positions)

        # Display additional tables
        print()  # Add spacing

        # Load fund contributions data first
        fund_contributions = []
        try:
            # Check if using Supabase repository
            if hasattr(repository, 'supabase') and repository.supabase:
                # Read from Supabase
                from web_dashboard.supabase_client import SupabaseClient
                client = SupabaseClient()
                result = client.supabase.table('fund_contributions').select('*').eq('fund', repository.fund).execute()

                if result.data:
                    # Convert Supabase format to CSV format for compatibility
                    for record in result.data:
                        # Ensure timestamp is included (should always exist per schema, but handle gracefully)
                        timestamp = record.get('timestamp')
                        if not timestamp:
                            logger.warning(f"Missing timestamp for contribution from {record.get('contributor', 'Unknown')} - record ID: {record.get('id', 'unknown')}")
                        
                        fund_contributions.append({
                            'Contributor': record['contributor'],
                            'Amount': record['amount'],
                            'Type': record['contribution_type'],
                            'Email': record.get('email', ''),
                            'Notes': record.get('notes', ''),
                            'Timestamp': timestamp
                        })
                    logger.debug(f"Loaded {len(fund_contributions)} contributions from Supabase")
            else:
                # Read from CSV file (original behavior)
                fund_file = Path(repository.data_dir) / "fund_contributions.csv"
                if fund_file.exists():
                    df = pd.read_csv(fund_file)
                    fund_contributions = df.to_dict('records')
                    logger.debug(f"Loaded {len(fund_contributions)} contributions from CSV")
        except Exception as e:
            logger.debug(f"Could not load fund contributions: {e}")

            # Calculate and display portfolio statistics
        try:
            # Use the updated snapshot with current prices, not the stale latest_snapshot
            updated_snapshot_for_metrics = PortfolioSnapshot(
                positions=updated_positions,
                timestamp=datetime.now(),
                total_value=sum(((pos.market_value or Decimal('0')) for pos in updated_positions), Decimal('0'))
            )
            portfolio_metrics = position_calculator.calculate_portfolio_metrics(updated_snapshot_for_metrics)

            webull_fx_fee = Decimal('0')

            # Calculate total contributions from fund data
            total_contributions = 0
            if fund_contributions:
                from decimal import Decimal
                for contribution in fund_contributions:
                    raw_amount = contribution.get('Amount', contribution.get('amount', 0))
                    try:
                        amount = Decimal(str(raw_amount))
                    except Exception:
                        amount = Decimal('0')
                    contrib_type = contribution.get('Type', contribution.get('type', 'CONTRIBUTION'))
                    ctype = str(contrib_type).upper()
                    if ctype in ('CONTRIBUTION', 'ADJUSTMENT'):
                        total_contributions += amount
                    elif ctype in ('WITHDRAWAL', 'FEE', 'FX_FEE', 'MAINTENANCE_FEE', 'BANK_FEE'):
                        total_contributions -= amount

            # Get realized P&L from FIFO processor
            realized_summary = trade_processor.get_realized_pnl_summary()
            from decimal import Decimal
            total_realized_pnl = realized_summary.get('total_realized_pnl', Decimal('0'))

            # Convert all Decimal values to float for JSON serialization
            # Note: Floats introduce potential precision loss but are required for JSON compatibility
            # All calculations are done with Decimals above this point for accuracy
            stats_data = {
                'total_contributions': float(total_contributions),
                'total_cost_basis': float(portfolio_metrics.get('total_cost_basis', Decimal('0'))),
                'total_current_value': float(total_portfolio_value),
                'total_pnl': float(pnl_metrics.get('total_absolute_pnl', Decimal('0'))),
                'total_realized_pnl': float(total_realized_pnl),
                'total_portfolio_pnl': float(pnl_metrics.get('total_absolute_pnl', Decimal('0')) + total_realized_pnl)
            }

            # Load cash balances and compute CAD-equivalent summary
            from financial.currency_handler import CurrencyHandler
            from decimal import Decimal
            cash_balance = Decimal('0')
            cad_cash = Decimal('0')
            usd_cash = Decimal('0')
            usd_to_cad_rate = Decimal('0')
            estimated_fx_fee_total_usd = Decimal('0')
            estimated_fx_fee_total_cad = Decimal('0')
            try:
                handler = CurrencyHandler(Path(repository.data_dir))
                balances = handler.load_cash_balances()
                # Raw balances as Decimal
                cad_cash = balances.cad
                usd_cash = balances.usd
                # Rate and CAD equivalent
                usd_to_cad_rate = handler.get_exchange_rate('USD','CAD')
                total_cash_cad_equiv_dec = balances.total_cad_equivalent(usd_to_cad_rate)
                cash_balance = total_cash_cad_equiv_dec
                # Compute per-currency holdings
                usd_positions_value_usd = Decimal('0')
                cad_positions_value_cad = Decimal('0')
                try:
                    for pos in updated_positions:
                        try:
                            if pos.market_value is None:
                                return
                            # Use the currency field from the position data instead of detecting from ticker
                            if pos.currency == 'USD':
                                usd_positions_value_usd += (pos.market_value or Decimal('0'))
                            elif pos.currency == 'CAD':
                                cad_positions_value_cad += (pos.market_value or Decimal('0'))
                        except Exception:
                            return
                except Exception:
                    usd_positions_value_usd = Decimal('0')
                    cad_positions_value_cad = Decimal('0')
                total_usd_holdings = usd_cash + usd_positions_value_usd
                total_cad_holdings = cad_cash + cad_positions_value_cad
                # Estimated simple FX fee at 1.5% on USD holdings
                if total_usd_holdings > 0:
                    estimated_fx_fee_total_usd = (total_usd_holdings * Decimal('0.015')).quantize(Decimal('0.01'))
                    estimated_fx_fee_total_cad = (estimated_fx_fee_total_usd * usd_to_cad_rate).quantize(Decimal('0.01'))
            except Exception as e:
                logger.debug(f"Could not load or compute cash balances: {e}")
                total_cash_cad_equiv_dec = Decimal('0')
                usd_to_cad_rate = Decimal('0')
                estimated_fx_fee_total_usd = Decimal('0')
                estimated_fx_fee_total_cad = Decimal('0')

            # Determine if the Webull FX fee should be applied for display
            try:
                fund_manager_utils = get_fund_manager()
                data_dir_name = Path(settings.get_data_directory()).name
                fund_config = fund_manager_utils.get_fund_config(data_dir_name)
                fund_type = fund_config.get('fund', {}).get('fund_type') if fund_config else None

                if fund_type == 'webull':
                    # Webull: $2.99 per holding + 1.5% of USD holdings
                    # Count USD holdings (positions with USD currency)
                    usd_holdings_count = 0
                    try:
                        # Get current positions to count USD holdings
                        latest_snapshot = repository.get_latest_portfolio_snapshot()
                        if latest_snapshot:
                            for position in latest_snapshot.positions:
                                if position.currency == 'USD':
                                    usd_holdings_count += 1
                    except Exception as e:
                        logger.debug(f"Could not count USD holdings: {e}")

                    liquidation_fee = Decimal('2.99') * usd_holdings_count
                    fx_fee = estimated_fx_fee_total_cad
                    webull_fx_fee = liquidation_fee + fx_fee
                    logger.info(f"Using estimated fees for Webull fund display: ${liquidation_fee} liquidation + ${fx_fee} FX = ${webull_fx_fee}")
                elif fund_type == 'wealthsimple':
                    # Wealthsimple: Only 1.5% of USD holdings (no $2.99 fees)
                    webull_fx_fee = estimated_fx_fee_total_cad
                    logger.debug(f"Using estimated FX fee for Wealthsimple fund display: ${webull_fx_fee}")
                else:
                    # For other fund types, keep webull_fx_fee at 0
                    webull_fx_fee = Decimal('0')
            except Exception as e:
                logger.debug(f"Could not determine fund type for fee calculation: {e}")
                # On error, default to no fees
                webull_fx_fee = Decimal('0')

            # Apply platform fees to portfolio value
            net_portfolio_value = total_portfolio_value - webull_fx_fee

            # Prepare summary data - convert Decimal to float for JSON serialization
            # CRITICAL: Floats introduce precision loss but are required for JSON compatibility
            # All financial calculations above use Decimal for accuracy, only converted here for storage
            summary_data = {
                'portfolio_value': float(net_portfolio_value),
                'total_pnl': float(pnl_metrics.get('total_absolute_pnl', Decimal('0'))),
                'cash_balance': float(cash_balance),
                'cad_cash': float(cad_cash),
                'usd_cash': float(usd_cash),
                'usd_to_cad_rate': float(usd_to_cad_rate),
                'estimated_fx_fee_total_usd': float(estimated_fx_fee_total_usd),
                'estimated_fx_fee_total_cad': float(estimated_fx_fee_total_cad),
                'usd_positions_value_usd': float(usd_positions_value_usd),
                'cad_positions_value_cad': float(cad_positions_value_cad),
                'usd_holdings_total_usd': float(total_usd_holdings),
                'cad_holdings_total_cad': float(total_cad_holdings),
                'total_equity_cad': float(net_portfolio_value + cash_balance),
                'fund_contributions': float(stats_data.get('total_contributions', 0.0)),
                'webull_fx_fee': float(webull_fx_fee)
            }

            # Enrich stats with audit metrics - convert to float for JSON serialization
            # WARNING: Using floats here introduces precision loss, but necessary for JSON storage
            # The calculations are done with Decimal precision, only converted at the last moment
            try:
                equity = summary_data.get('portfolio_value', 0.0) + summary_data.get('cash_balance', 0.0)
                stats_data['unallocated_vs_cost'] = float(stats_data.get('total_contributions', 0.0) - stats_data.get('total_cost_basis', 0.0) - summary_data.get('cash_balance', 0.0))
                stats_data['net_pnl_vs_contrib'] = float(equity - stats_data.get('total_contributions', 0.0))
            except Exception as audit_e:
                logger.debug(f"Could not compute audit metrics: {audit_e}")

            # Calculate ownership information to display alongside financial overview
            ownership_data = {}
            try:
                if fund_contributions:
                    # Toggle whether cash is included in ownership allocations via env var
                    include_cash_in_ownership = True
                    try:
                        include_env = os.environ.get('OWNERSHIP_INCLUDE_CASH', '1').strip().lower()
                        include_cash_in_ownership = include_env not in ('0', 'false', 'no')
                    except Exception:
                        include_cash_in_ownership = True

                    base_value_dec = Decimal(str(total_portfolio_value))
                    fund_total_value_dec = base_value_dec + total_cash_cad_equiv_dec if include_cash_in_ownership else base_value_dec

                    # Fetch historical fund values for accurate NAV calculation
                    historical_fund_values = {}
                    historical_cost_basis = {}  # For uninvested cash calculation
                    try:
                        # Get all contribution timestamps
                        contribution_dates = []
                        for contrib in fund_contributions:
                            ts = contrib.get('Timestamp', '')
                            if ts:
                                try:
                                    if isinstance(ts, datetime):
                                        contribution_dates.append(ts)
                                    elif isinstance(ts, str):
                                        for fmt in ['%Y-%m-%d %H:%M:%S %Z', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
                                            try:
                                                dt = datetime.strptime(ts.split('+')[0].split('.')[0], fmt)
                                                contribution_dates.append(dt)
                                                break
                                            except ValueError:
                                                continue
                                except Exception:
                                    pass
                        
                        if contribution_dates:
                            min_date = min(contribution_dates)
                            max_date = max(contribution_dates)
                            
                            # Get portfolio snapshots for the contribution period
                            snapshots = repository.get_portfolio_data(date_range=(min_date, datetime.now()))
                            if snapshots:
                                for snapshot in snapshots:
                                    date_str = snapshot.timestamp.strftime('%Y-%m-%d')
                                    # Calculate total value AND cost basis for this snapshot
                                    total_value = sum(
                                        pos.shares * pos.current_price 
                                        for pos in snapshot.positions 
                                        if pos.current_price is not None
                                    )
                                    total_cost_basis = sum(
                                        pos.cost_basis if pos.cost_basis else Decimal('0')
                                        for pos in snapshot.positions
                                    )
                                    if total_value > 0:
                                        historical_fund_values[date_str] = Decimal(str(total_value))
                                        historical_cost_basis[date_str] = Decimal(str(total_cost_basis))
                                
                                logger.debug(f"Retrieved {len(historical_fund_values)} historical fund values for NAV calculation")
                                
                                # Check for missing dates and warn
                                contribution_date_strs = set(d.strftime('%Y-%m-%d') for d in contribution_dates)
                                if len(historical_fund_values) < len(contribution_date_strs):
                                    missing_dates = contribution_date_strs - set(historical_fund_values.keys())
                                    print_warning(f"⚠️  NAV: Missing historical data for {len(missing_dates)} date(s): {', '.join(sorted(missing_dates)[:3])}{'...' if len(missing_dates) > 3 else ''}")
                    except Exception as hist_err:
                        logger.warning(f"Could not retrieve historical fund values: {hist_err}")
                        print_warning(f"⚠️  NAV: Could not retrieve historical fund values - using time-weighted estimation")
                        # Will fall back to time-weighted estimation in calculate_ownership_percentages

                    ownership_raw = position_calculator.calculate_ownership_percentages(
                        fund_contributions, fund_total_value_dec, historical_fund_values, historical_cost_basis
                    )

                    # Calculate total shares in portfolio for proportional ownership
                    from decimal import Decimal
                    try:
                        total_shares = sum((pos.shares for pos in updated_positions), start=Decimal('0')) if updated_positions else Decimal('0')
                        # logger.debug(f"Calculated total shares: {total_shares}")
                    except Exception as calc_error:
                        logger.warning(f"Could not calculate total shares: {calc_error}")
                        total_shares = Decimal('0')

                    for contributor, data in ownership_raw.items():
                        ownership_pct = data.get('ownership_percentage', Decimal('0'))
                        # Calculate proportional shares owned by this contributor
                        # Since this is a pooled fund, shares are owned collectively, but we show
                        # proportional ownership based on each contributor's percentage of the fund
                        contributor_shares = (ownership_pct / Decimal('100')) * total_shares if total_shares > 0 else Decimal('0')

                        # Convert Decimal to float for JSON serialization
                        # WARNING: Float conversion introduces precision loss but is required for JSON compatibility
                        # All ownership calculations above use Decimal for accuracy
                        ownership_data[contributor] = {
                            'shares': float(contributor_shares),  # Proportional share ownership
                            'contributed': float(data.get('net_contribution', Decimal('0'))),
                            'ownership_pct': float(ownership_pct),
                            'current_value': float(data.get('current_value', Decimal('0'))),
                            'total_pl': float(data.get('gain_loss', Decimal('0')))  # Total P/L for this contributor
                        }

                        # logger.debug(f"Contributor {contributor}: {contributor_shares:.4f} shares ({ownership_pct:.1f}% ownership)")
            except Exception as e:
                logger.error(f"Could not calculate ownership data: {e}")

            metrics_time = time.time() - metrics_start
            if metrics_time > 0.5:
                print_info(f"   Portfolio metrics calculated: {metrics_time:.2f}s")
            
            # Display financial overview and ownership tables side by side
            if ownership_data:
                table_formatter.create_financial_and_ownership_tables(stats_data, summary_data, ownership_data)
            else:
                # Fallback to just financial table if no ownership data
                table_formatter.create_unified_financial_table(stats_data, summary_data)
            
            print()  # Add spacing
        except Exception as e:
            logger.debug(f"Could not calculate portfolio statistics or financial summary: {e}")
            print_warning(f"Could not display portfolio metrics: {e}")
        
        # Remove filters and display collected messages at bottom (outside try block to ensure it runs)
        # Check if warning_messages exists in function scope
        try:
            # Try to access warning_messages - it's defined in outer scope of this function
            _test = warning_messages
            _test2 = original_filters
            has_warning_vars = True
        except NameError:
            has_warning_vars = False
        
        if has_warning_vars:
            # Restore original filters
            try:
                root_logger = logging.getLogger()
                for handler in root_logger.handlers:
                    if isinstance(handler, logging.StreamHandler) and id(handler) in original_filters:
                        handler.filters = original_filters[id(handler)]
                
                main_logger = logging.getLogger('__main__')
                pos_calc_logger = logging.getLogger('portfolio.position_calculator')
                for handler in main_logger.handlers + pos_calc_logger.handlers:
                    if isinstance(handler, logging.StreamHandler) and id(handler) in original_filters:
                        handler.filters = original_filters[id(handler)]
            except Exception:
                pass
            
            # Display collected warnings/info at bottom after tables
            if warning_messages:
                print()  # Add spacing before warnings
                print_warning("Additional Information:")
                # Remove duplicates by converting to set of tuples, then back to list
                seen = set()
                unique_messages = []
                for msg_info in warning_messages:
                    msg_key = (msg_info['level'], msg_info['message'])
                    if msg_key not in seen:
                        seen.add(msg_key)
                        unique_messages.append(msg_info)
                
                for msg_info in unique_messages:
                    # Sanitize message to remove Unicode characters that cause encoding issues
                    message = msg_info['message']
                    # Remove logger prefixes like "WARNING: " that are already in the message
                    if message.startswith('WARNING: '):
                        message = message[9:]  # Remove "WARNING: " prefix
                    elif message.startswith('INFO: '):
                        message = message[6:]  # Remove "INFO: " prefix
                    # Replace common Unicode characters with ASCII equivalents
                    message = message.replace('⚠️', '')
                    message = message.replace('✓', '[OK]')
                    message = message.strip()
                    # Remove any other problematic Unicode characters
                    try:
                        message.encode('cp1252')
                    except UnicodeEncodeError:
                        # Fallback: remove non-ASCII characters
                        message = message.encode('ascii', 'ignore').decode('ascii')
                    
                    if msg_info['level'] == 'WARNING':
                        print_warning(f"  - {message}")
                    else:
                        print_info(f"  - {message}")
                print()  # Add spacing after warnings

        # Check if running in non-interactive mode
        if args.non_interactive:
            print_info("Running in non-interactive mode - exiting after display")
            return

        # Display trading menu
        print()  # Add spacing

        # Get market timer info for trading menu header
        menu_time_info = ""
        try:
            menu_time_info = market_timer.display_market_timer(compact=True)
        except Exception as e:
            logger.debug(f"Could not get market timer for menu: {e}")

        # Add fund indicator and market timer to Trading Actions header
        header_parts = ["Trading Actions"]
        if menu_time_info:
            header_parts.append(menu_time_info)
        if fund_indicator:
            header_parts.append(fund_indicator)

        trading_header_title = " | ".join(header_parts)
        print_header(trading_header_title, _safe_emoji("💰"))
        # Use fancy Unicode borders if supported, otherwise ASCII fallback
        from display.console_output import _can_handle_unicode
        from colorama import Fore, Style

        # Use safe emoji function for consistent Unicode handling

        if _can_handle_unicode():
            # Define box width and create properly aligned menu
            box_width = 67
            border_line = "┌" + "─" * (box_width - 2) + "┐"
            end_line = "└" + "─" * (box_width - 2) + "┘"

            def create_menu_line(content):
                """Create a menu line with proper spacing accounting for emoji width."""
                # Calculate actual visual width - emojis appear to take 1 extra space
                visual_len = len(content)
                emoji_count = 0
                for char in content:
                    if ord(char) > 127:  # Likely emoji or Unicode
                        emoji_count += 1
                        visual_len += 1  # Each emoji takes 1 extra visual space

                # Calculate padding to align right border
                content_space = 1  # Leading space after │
                border_space = 1   # Trailing space before │
                padding_needed = box_width - content_space - visual_len - border_space - 1  # -1 for trailing │

                return f"{Fore.GREEN}{Style.BRIGHT}│{Style.RESET_ALL} {content}{' ' * max(0, padding_needed)}{Fore.GREEN}{Style.BRIGHT}│{Style.RESET_ALL}"

            # Print lime-colored box
            print(f"{Fore.GREEN}{Style.BRIGHT}{border_line}{Style.RESET_ALL}")
            # Create aligned menu with consistent spacing
            print(create_menu_line(f"{_safe_emoji('🛒')} 'b'       Buy (Limit Order or Market Open Order)"))
            print(create_menu_line(f"{_safe_emoji('📤')} 's'       Sell (Limit Order)"))
            print(create_menu_line(f"{_safe_emoji('💵')} 'c'       Log Contribution"))
            print(create_menu_line(f"{_safe_emoji('💸')} 'w'       Log Withdrawal"))
            print(create_menu_line(f"{_safe_emoji('👥')} 'm'       Manage Contributors"))
            print(create_menu_line(f"{_safe_emoji('🔄')} 'u'       Update Cash Balances"))
            print(create_menu_line(f"{_safe_emoji('🔗')} 'sync'    Sync Fund Contributions"))
            print(create_menu_line(f"{_safe_emoji('💾')} 'backup'  Create Backup"))
            print(create_menu_line(f"{_safe_emoji('💾')} 'restore' Restore from Backup"))
            print(create_menu_line(f"{_safe_emoji('🧹')} '9'       Clean Old Backups"))
            print(create_menu_line(f"{_safe_emoji('📊')} '0'       Backup Statistics"))
            print(create_menu_line(f"{_safe_emoji('🔄')} 'r'       Refresh Portfolio (clear cache)"))
            print(create_menu_line(f"{_safe_emoji('🏦')} 'f'       Switch Fund"))
            print(create_menu_line(f"{_safe_emoji('🔄')} 'd'       Switch Repository (CSV/Supabase)"))
            print(create_menu_line(f"{_safe_emoji('🔧')} 'rebuild' Rebuild Portfolio from Trade Log"))
            print(create_menu_line(f"{_safe_emoji('📊')} 'o'       Sort Portfolio"))
            print(create_menu_line(f"{_safe_emoji('💾')} 'cache'   Manage Cache"))
            print(create_menu_line(f"{_safe_emoji('❌')} Enter     Quit"))
            print(f"{Fore.GREEN}{Style.BRIGHT}{end_line}{Style.RESET_ALL}")
        else:
            print("+---------------------------------------------------------------+")
            print("| 'b' [B] Buy (Limit Order or Market Open Order)              |")
            print("| 's' [S] Sell (Limit Order)                                  |")
            print("| 'c' $ Log Contribution                                      |")
            print("| 'w' -$ Log Withdrawal                                       |")
            print("| 'm' [M] Manage Contributors                                 |")
            print("| 'u' ~ Update Cash Balances                                  |")
            print("| 'sync' & Sync Fund Contributions                            |")
            print("| 'backup' [B] Create Backup                                  |")
            print("| 'restore' ~ Restore from Backup                             |")
            print("| '9' [9] Clean Old Backups                                  |")
            print("| '0' [0] Backup Statistics                                   |")
            print("| 'r' ~ Refresh Portfolio (clear cache)                      |")
            print("| 'f' ~ Switch Fund                                           |")
            print("| 'd' [D] Switch Repository (CSV/Supabase)                    |")
            print("| 'rebuild' [R] Rebuild Portfolio from Trade Log              |")
            print("| 'o' [O] Sort Portfolio                                      |")
            print(f"| 'cache' {_safe_emoji('💾')} Manage Cache                                     |")
            print("| Enter -> Quit                                               |")
            print("+---------------------------------------------------------------+")
        print()

        # Get user input for trading action
        try:
            action = input("Select an action: ").strip().lower()

            if action == '' or action == 'enter':
                print_info("Exiting trading system...")
                return
            elif action == 'r':
                verify_script_before_action()
                print_info("Refreshing portfolio...")
                # Recursive call to refresh with cache clearing enabled
                run_portfolio_workflow(args, settings, repository, trading_interface, fund_manager, clear_caches=True)
                return
            elif action == 'f':
                if fund_manager is None:
                    print_error("Fund manager not available")
                    return
                switch_fund_workflow(args, settings, fund_manager)
                return
            elif action == 'd':
                switch_repository_workflow()
                return
            elif action == 'rebuild':
                verify_script_before_action()
                print_info("Rebuilding portfolio from trade log...")
                # Import and run the rebuild script
                import subprocess
                import sys
                from pathlib import Path

                # Get the data directory from settings
                data_dir = settings.get_data_directory()

                # Run the rebuild script
                rebuild_script = Path(__file__).parent / "debug" / "rebuild_portfolio_complete.py"
                if rebuild_script.exists():
                    try:
                        result = subprocess.run([
                            sys.executable, str(rebuild_script), data_dir
                        ], capture_output=True, text=True)

                        if result.returncode == 0:
                            print_success("Portfolio rebuilt successfully!")
                            print(result.stdout)
                        else:
                            print_error("Portfolio rebuild failed!")
                            print("STDOUT:", result.stdout)
                            print("STDERR:", result.stderr)
                    except Exception as e:
                        print_error(f"Error running rebuild script: {e}")
                else:
                    print_error("Rebuild script not found!")
                return
            elif action == 'o':
                print_info("Changing portfolio sorting...")
                print("\n" + "="*60)
                print("📊 SORTING OPTIONS:")
                print("  [1] Weight % (highest first)    [2] Ticker (A-Z)           [3] P&L (highest first)")
                print("  [4] Total Value (highest first) [5] Shares (highest first) [6] Price (highest first)")
                print("  [Enter] Keep current sort        [q] Back to main menu")
                print("="*60)

                try:
                    choice = input("\nSelect sorting option (1-6, Enter, or q): ").strip().lower()

                    if choice == 'q':
                        print("Returning to main menu...")
                        return
                    elif choice == '' or choice == 'enter':
                        print("Keeping current sort...")
                        return
                    elif choice in ['1', '2', '3', '4', '5', '6']:
                        sort_options = {
                            '1': 'weight',
                            '2': 'ticker',
                            '3': 'pnl',
                            '4': 'value',
                            '5': 'shares',
                            '6': 'price'
                        }

                        new_sort = sort_options[choice]
                        print(f"Re-sorting by {new_sort}...")

                        # Re-sort the positions
                        reverse_sort = new_sort in ['weight', 'pnl', 'value', 'shares', 'price']
                        enhanced_positions.sort(key=lambda pos: get_sort_key(pos, new_sort), reverse=reverse_sort)

                        # Clear screen and re-display
                        import os
                        os.system('cls' if os.name == 'nt' else 'clear')

                        # Re-display header and table
                        print_header(header_title, _safe_emoji("📊"))
                        table_formatter.create_portfolio_table(enhanced_positions)

                        print_success(f"Portfolio sorted by {new_sort}")
                        return
                    else:
                        print("Invalid choice, keeping current sort...")
                        return

                except KeyboardInterrupt:
                    print("\nReturning to main menu...")
                    return
                except Exception as e:
                    logger.debug(f"Error in sorting menu: {e}")
                    print("Error in sorting menu, returning to main menu...")
                    return
            elif action == 'backup':
                print_info("Creating backup...")
                backup_name = backup_manager.create_backup()
                print_success(f"Backup created: {backup_name}")
            elif action == 'c':
                verify_script_before_action()
                trading_interface.log_contribution()
            elif action == 'w':
                verify_script_before_action()
                trading_interface.log_withdrawal()
            elif action == 'm':
                verify_script_before_action()
                trading_interface.manage_contributors()
            elif action == 'u':
                verify_script_before_action()
                trading_interface.update_cash_balances()
            elif action == 'sync':
                verify_script_before_action()
                trading_interface.sync_fund_contributions()
            elif action == 'restore':
                print_warning("Restore functionality not yet implemented")
                print_info("This feature will be added in future updates")
            elif action == '9':
                try:
                    from utils.backup_cleanup import BackupCleanupUtility
                    cleanup_util = BackupCleanupUtility()

                    print_header("Backup Cleanup")
                    print_info("This will remove old backup files to free up space.")

                    # Ask for confirmation and days
                    try:
                        days_input = input("Enter number of days (backups older than this will be deleted) [7]: ").strip()
                        days = int(days_input) if days_input else 7
                    except ValueError:
                        print_warning("Invalid input, using default of 7 days")
                        days = 7

                    # Show what would be deleted
                    print_info(f"Checking for backups older than {days} days...")
                    results = cleanup_util.cleanup_old_backups_by_age(days=days, dry_run=True)

                    total_files = sum(results.values())
                    if total_files == 0:
                        print_success("No old backup files found to clean up!")
                        return

                    # Ask for confirmation
                    confirm = input(f"Found {total_files} old backup files. Delete them? (y/N): ").strip().lower()
                    if confirm in ['y', 'yes']:
                        print_info("Deleting old backup files...")
                        results = cleanup_util.cleanup_old_backups_by_age(days=days, dry_run=False)
                        total_deleted = sum(results.values())
                        print_success(f"Cleaned up {total_deleted} old backup files!")
                    else:
                        print_info("Cleanup cancelled.")

                except ImportError as e:
                    print_error(f"Backup cleanup not available: {e}")
                    print_info("This feature requires the backup cleanup module.")
                except Exception as e:
                    print_error(f"Error during backup cleanup: {e}")
                    logger.error(f"Backup cleanup error: {e}", exc_info=True)
            elif action == '0':
                try:
                    from utils.backup_cleanup import BackupCleanupUtility
                    cleanup_util = BackupCleanupUtility()
                    cleanup_util.list_backup_stats()
                except ImportError as e:
                    print_error(f"Backup statistics not available: {e}")
                    print_info("This feature requires the backup cleanup module.")
                except Exception as e:
                    print_error(f"Error getting backup statistics: {e}")
                    logger.error(f"Backup statistics error: {e}", exc_info=True)
            elif action == 'cache':
                try:
                    from utils.cache_ui import show_cache_management_menu
                    show_cache_management_menu()
                except ImportError as e:
                    print_error(f"Cache management not available: {e}")
                    print_info("This feature requires the cache management module.")
                return
            else:
                print_warning("Invalid action selected")

        except KeyboardInterrupt:
            print_info("\nExiting trading system...")
            return
        except Exception as e:
            logger.debug(f"Error in trading menu: {e}")
            print_warning("Error in trading menu")

        print_success("Portfolio workflow completed successfully")

    except Exception as e:
        error_msg = f"Portfolio workflow failed: {e}"
        print_error(error_msg)
        logger.error(error_msg, exc_info=True)
        raise


def main() -> None:
    """Main entry point for the trading system.

    This function orchestrates the entire trading system workflow:
    1. Parse command-line arguments
    2. Initialize system components with dependency injection
    3. Run the portfolio management workflow
    4. Handle errors gracefully with proper cleanup
    """
    try:
        # Initialize launch time for integrity checking
        initialize_launch_time()

        # Parse command-line arguments
        args = parse_command_line_arguments()

        # Store global references for cleanup
        global settings, repository, fund_manager

        # Initialize system
        system_settings, system_repository, dependencies, fund_manager = initialize_system(args)

        # Store global references
        settings = system_settings
        repository = system_repository

        # Run main workflow
        run_portfolio_workflow(args, system_settings, system_repository, trading_interface, fund_manager, clear_caches=False)

    except KeyboardInterrupt:
        print_warning("\nOperation cancelled by user")
        sys.exit(0)

    except InitializationError as e:
        print_error(f"System initialization failed: {e}")
        sys.exit(1)

    except RepositoryError as e:
        print_error(f"Data access error: {e}")
        sys.exit(1)

    except TradingSystemError as e:
        print_error(f"Trading system error: {e}")
        sys.exit(1)

    except ScriptIntegrityError as e:
        print_error(f"Script integrity error: {e}")
        sys.exit(1)

    except Exception as e:
        print_error(f"Unexpected error: {e}")
        logger.error("Unexpected error in main", exc_info=True)
        sys.exit(1)

    finally:
        # Cleanup resources
        cleanup_system()


def cleanup_system() -> None:
    """Cleanup system resources and connections."""
    try:
        # Use globals() to safely check if repository exists
        if 'repository' in globals() and repository:
            # Close any open connections or resources
            if hasattr(repository, 'close'):
                repository.close()

        logger.info("System cleanup completed")

    except Exception as e:
        logger.error(f"Error during system cleanup: {e}")





if __name__ == "__main__":
    # Setup error handlers before anything else
    setup_error_handlers()

    # Validate system requirements
    validate_system_requirements()

    # Log system information
    log_system_info(VERSION)

    # Run main function
    main()
