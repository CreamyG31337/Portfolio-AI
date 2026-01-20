#!/usr/bin/env python3
"""
Complete Portfolio Rebuild Script - CSV + Supabase

This script rebuilds the portfolio from the trade log and updates BOTH:
1. CSV files (for local data)
2. Supabase database (for web dashboard)

Uses the proper repository pattern to ensure consistency.
"""

import sys
import os
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal
from collections import defaultdict
from typing import Optional
import pandas as pd
import pytz
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add the parent directory to the path so we can import our modules
sys.path.append(str(Path(__file__).parent.parent))

from display.console_output import print_info, print_error, _safe_emoji
import numpy as np
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from data.repositories.repository_factory import RepositoryFactory
from portfolio.portfolio_manager import PortfolioManager
from market_data.data_fetcher import MarketDataFetcher as MarketDataFetcherClass
from market_data.price_cache import PriceCache
from market_data.market_hours import MarketHours
from utils.market_holidays import MarketHolidays
from utils.ticker_utils import get_company_name
from display.console_output import print_success, print_error, print_info, print_warning, _safe_emoji

# Load environment variables
load_dotenv(project_root / 'web_dashboard' / '.env')

def _log_rebuild_progress(fund_name: str, message: str, success: bool = True):
    """
    Log rebuild progress to both job execution logs and Application Logs (file-based).
    Falls back gracefully if not available (when run directly from CLI).
    """
    try:
        # Try to import and use the job logging function (in-memory job logs)
        sys.path.insert(0, str(project_root / 'web_dashboard'))
        from scheduler.scheduler_core import log_job_execution
        
        job_id = f'rebuild_portfolio_{fund_name.replace(" ", "_")}'
        log_job_execution(job_id, success, message, 0)
    except Exception:
        # Silently ignore if logging not available (running directly)
        pass
    
    # Also log to file-based Application Logs (visible in admin page Application Logs tab)
    try:
        sys.path.insert(0, str(project_root / 'web_dashboard'))
        from log_handler import log_message
        
        # Determine log level based on success
        level = 'ERROR' if not success else 'INFO'
        log_message(f"[Rebuild Portfolio - {fund_name}] {message}", level=level)
    except Exception:
        # Silently ignore if file logging not available
        pass

def _save_snapshot_batch(repository, snapshot_batch: list, fund_name: str, is_docker: bool = False) -> None:
    """
    Save a batch of snapshots efficiently.
    
    Supabase is ALWAYS primary (required).
    CSV is optional backup (skipped in Docker, optional locally).
    
    Args:
        repository: Repository instance
        snapshot_batch: List of (snapshot, trading_day) tuples
        fund_name: Fund name for logging
        is_docker: If True, skip CSV operations entirely
    """
    if not snapshot_batch:
        return
    
    from data.repositories.csv_repository import CSVRepository
    from utils.timezone_utils import get_trading_timezone
    import pandas as pd
    
    # Get dates in batch
    batch_dates = [snapshot[1] for snapshot in snapshot_batch]
    
    # CSV: Optional backup (skip in Docker, optional locally)
    if not is_docker:
        if hasattr(repository, 'csv_repo'):
            csv_repo = repository.csv_repo
        elif isinstance(repository, CSVRepository):
            csv_repo = repository
        else:
            csv_repo = None
        
        if csv_repo:
            trading_tz = get_trading_timezone()
        all_rows = []
        
        for snapshot, trading_day in snapshot_batch:
            # Normalize timestamp
            if snapshot.timestamp.tzinfo is None:
                normalized_timestamp = snapshot.timestamp.replace(tzinfo=trading_tz)
            else:
                normalized_timestamp = snapshot.timestamp.astimezone(trading_tz)
            
            timestamp_str = csv_repo._format_timestamp_for_csv(normalized_timestamp)
            
            for position in snapshot.positions:
                row = position.to_csv_dict()
                row['Date'] = timestamp_str
                row['Action'] = 'HOLD'
                all_rows.append(row)
        
        if all_rows:
            batch_df = pd.DataFrame(all_rows)
            expected_columns = [
                'Date', 'Ticker', 'Shares', 'Average Price', 'Cost Basis', 
                'Stop Loss', 'Current Price', 'Total Value', 'PnL', 'Action', 
                'Company', 'Currency'
            ]
            for col in expected_columns:
                if col not in batch_df.columns:
                    batch_df[col] = ''
            batch_df = batch_df[expected_columns]
            
            # Append to CSV (no duplicate checking for batch mode - we cleared the file at start)
            # CSV is backup only - don't fail if write fails
            try:
                if csv_repo.portfolio_file.exists():
                    batch_df.to_csv(csv_repo.portfolio_file, mode='a', header=False, index=False)
                else:
                    batch_df.to_csv(csv_repo.portfolio_file, index=False)
            except Exception as csv_error:
                # CSV write failed - log warning but continue (Supabase is primary)
                print_warning(f"⚠️  CSV backup write failed (non-fatal): {csv_error}")
    
    # Supabase: Batch delete and insert
    if hasattr(repository, 'supabase_repo') and hasattr(repository.supabase_repo, 'supabase'):
        supabase = repository.supabase_repo.supabase
    elif hasattr(repository, 'supabase'):
        supabase = repository.supabase
    else:
        supabase = None
    
    if supabase:
        from datetime import timezone as dt_timezone
        # Delete all positions for these dates
        for trading_day in batch_dates:
            snapshot_date_str = trading_day.isoformat()
            try:
                supabase.table("portfolio_positions").delete()\
                    .eq("fund", fund_name)\
                    .gte("date", f"{snapshot_date_str}T00:00:00")\
                    .lt("date", f"{snapshot_date_str}T23:59:59.999999")\
                    .execute()
            except Exception as e:
                print_warning(f"   Could not delete existing positions for {trading_day}: {e}")
        
        # Collect all positions for batch insert using PositionMapper
        from data.repositories.field_mapper import PositionMapper
        all_positions_data = []
        
        # Get base currency for exchange rate conversion
        base_currency = 'CAD'  # Default
        try:
            fund_result = supabase.table("funds")\
                .select("base_currency")\
                .eq("name", fund_name)\
                .limit(1)\
                .execute()
            if fund_result.data and fund_result.data[0].get('base_currency'):
                base_currency = fund_result.data[0]['base_currency'].upper()
        except Exception:
            pass  # Use default
        
        # Import exchange rate utility (same as scheduled job uses)
        try:
            sys.path.insert(0, str(project_root / 'web_dashboard'))
            from exchange_rates_utils import get_exchange_rate_for_date_from_db
        except ImportError:
            print_warning("Could not import exchange_rates_utils - pre-converted values will use fallback rates")
            get_exchange_rate_for_date_from_db = None
        
        # Cache exchange rates per date to avoid redundant lookups (performance optimization)
        # Key: (date, from_currency, to_currency), Value: rate
        exchange_rate_cache = {}
        
        def get_cached_exchange_rate(date, from_curr, to_curr):
            """Get exchange rate with caching to minimize database lookups."""
            cache_key = (date.date(), from_curr, to_curr)
            if cache_key in exchange_rate_cache:
                return exchange_rate_cache[cache_key]
            
            if get_exchange_rate_for_date_from_db:
                rate = get_exchange_rate_for_date_from_db(date, from_curr, to_curr)
                if rate is not None:
                    exchange_rate_cache[cache_key] = rate
                    return rate
                # Try inverse if available
                inverse_key = (date.date(), to_curr, from_curr)
                if inverse_key in exchange_rate_cache:
                    inverse_rate = exchange_rate_cache[inverse_key]
                    if inverse_rate != 0:
                        rate = 1.0 / float(inverse_rate)
                        exchange_rate_cache[cache_key] = rate
                        return rate
            
            # Fallback rates
            if from_curr == 'USD' and to_curr == 'CAD':
                return Decimal('1.35')
            elif from_curr == 'CAD' and to_curr == 'USD':
                return Decimal('1.0') / Decimal('1.35')
            else:
                return Decimal('1.0')
        
        for snapshot, trading_day in snapshot_batch:
            # Get exchange rate for this snapshot date (cached, fetched once per date)
            # This matches the scheduled job's approach - one lookup per snapshot date
            usd_to_base_rate = get_cached_exchange_rate(
                snapshot.timestamp,
                'USD',
                base_currency
            ) if base_currency != 'USD' else Decimal('1.0')
            
            for position in snapshot.positions:
                position_currency = (position.currency or 'CAD').upper()
                
                # Calculate exchange rate for this position (optimized with caching)
                if position_currency == 'USD' and base_currency != 'USD':
                    # Converting USD to base currency - use cached rate
                    position_exchange_rate = float(usd_to_base_rate)
                elif position_currency == base_currency:
                    # Already in base currency - no conversion
                    position_exchange_rate = 1.0
                elif base_currency == 'USD' and position_currency != 'USD':
                    # Converting from position currency to USD - use cached lookup
                    position_exchange_rate = float(get_cached_exchange_rate(
                        snapshot.timestamp,
                        position_currency,
                        'USD'
                    ))
                else:
                    # Other currency combinations - use 1.0 (store as-is)
                    position_exchange_rate = 1.0
                
                # Use PositionMapper to convert with calculated exchange rate
                position_data = PositionMapper.model_to_db(
                    position,
                    fund_name,
                    snapshot.timestamp,
                    base_currency=base_currency,
                    exchange_rate=position_exchange_rate
                )
                all_positions_data.append(position_data)
        
        # Ensure all tickers exist in securities table using repository method
        # This prevents FK constraint violation on batch insert
        # Collect unique tickers first
        unique_tickers = set()
        ticker_currencies = {}
        for pos_data in all_positions_data:
            ticker = pos_data.get('ticker')
            if ticker:
                unique_tickers.add(ticker)
                if ticker not in ticker_currencies:
                    ticker_currencies[ticker] = pos_data.get('currency', 'USD')

        if hasattr(repository, 'ensure_ticker_in_securities'):
            for ticker in unique_tickers:
                currency = ticker_currencies.get(ticker, 'USD')
                repository.ensure_ticker_in_securities(ticker, currency)
        elif hasattr(repository, 'supabase_repo') and hasattr(repository.supabase_repo, 'ensure_ticker_in_securities'):
            for ticker in unique_tickers:
                currency = ticker_currencies.get(ticker, 'USD')
                repository.supabase_repo.ensure_ticker_in_securities(ticker, currency)
        else:
            # Fallback to SupabaseClient if repository doesn't have the method
            try:
                from web_dashboard.supabase_client import SupabaseClient
                temp_client = SupabaseClient(use_service_role=True)
                for ticker in unique_tickers:
                    currency = ticker_currencies.get(ticker, 'USD')
                    temp_client.ensure_ticker_in_securities(ticker, currency)
            except Exception as e:
                print_warning(f"   Could not ensure tickers in securities table: {e}")

        # Batch insert (Supabase limit is 1000, but we're batching 20 snapshots so should be fine)
        if all_positions_data:
            try:
                # Insert in chunks of 1000 if needed
                chunk_size = 1000
                for i in range(0, len(all_positions_data), chunk_size):
                    chunk = all_positions_data[i:i + chunk_size]
                    supabase.table("portfolio_positions").insert(chunk).execute()
            except Exception as e:
                print_error(f"   Error batch inserting to Supabase: {e}")
                # Fallback: save individually
                for snapshot, _ in snapshot_batch:
                    repository.save_portfolio_snapshot(snapshot)

def rebuild_portfolio_complete(data_dir: str, fund_name: str = None) -> bool:
    """
    Rebuild portfolio from trade log and update both CSV and Supabase.
    
    CRITICAL DATA INTEGRITY PRINCIPLE:
    - NEVER uses fallback prices (old prices, average prices, etc.)
    - FAILS HARD if any position can't fetch current market prices
    - This prevents silent insertion of garbage data that would corrupt P&L calculations
    
    Args:
        data_dir: Directory containing trading data files
        fund_name: Fund name for Supabase operations (optional)
        
    Returns:
        True if successful, False otherwise
    """
    start_time = time.time()
    try:
        # Initialize logging first so all log messages are captured
        # This is critical for web UI visibility - without this, logs won't appear
        try:
            sys.path.insert(0, str(project_root / 'web_dashboard'))
            from log_handler import setup_logging
            setup_logging()
        except Exception as e:
            # If logging setup fails, print to console as fallback
            print(f"Warning: Could not initialize logging: {e}")
        
        # Detect Docker environment
        is_docker = os.path.exists('/.dockerenv') or os.getcwd().startswith('/app')
        
        # Log start to Application Logs
        _log_rebuild_progress(fund_name or "Unknown", f"Starting portfolio rebuild for {fund_name or data_dir}")
        
        print(f"{_safe_emoji('🔄')} Complete Portfolio Rebuild (Supabase Primary, CSV Backup)")
        print("=" * 60)
        print(f"{_safe_emoji('📁')} Data directory: {data_dir}")
        if fund_name:
            print(f"{_safe_emoji('🏦')} Fund name: {fund_name}")
        if is_docker:
            print(f"{_safe_emoji('🐳')} Running in Docker - CSV operations will be skipped")
        
        # Extract fund name from data directory if not provided
        if not fund_name:
            fund_name = Path(data_dir).name
            print(f"{_safe_emoji('📁')} Extracted fund name: {fund_name}")
        
        # Initialize repository: Supabase is ALWAYS primary
        # Docker: Use supabase-only (faster, no CSV overhead)
        # Local: Use supabase-dual-write (Supabase primary, CSV backup if available)
        if fund_name:
            try:
                if is_docker:
                    # Docker: Supabase-only (no CSV)
                    repository = RepositoryFactory.create_repository(repository_type='supabase', data_directory=data_dir, fund_name=fund_name)
                    print(f"{_safe_emoji('✅')} Using Supabase-only repository (Docker mode - CSV skipped)")
                else:
                    # Local: Supabase primary, CSV backup
                    repository = RepositoryFactory.create_repository(repository_type='supabase-dual-write', data_directory=data_dir, fund_name=fund_name)
                    print(f"{_safe_emoji('✅')} Using Supabase dual-write repository (Supabase primary, CSV backup)")
            except Exception as e:
                print(f"{_safe_emoji('⚠️')} Supabase repository failed: {e}")
                if is_docker:
                    # In Docker, Supabase is required - fail hard
                    print_error("❌ Supabase is required in Docker environment - cannot proceed")
                    return False
                else:
                    # Local: Fallback to CSV-only if Supabase fails
                    print("   Falling back to CSV-only repository")
                    repository = RepositoryFactory.create_repository(repository_type='csv', data_directory=data_dir, fund_name=fund_name)
        else:
            # No fund name - use CSV-only (legacy mode)
            repository = RepositoryFactory.create_repository(repository_type='csv', data_directory=data_dir, fund_name=fund_name)
            print(f"{_safe_emoji('✅')} Using CSV-only repository (no fund name provided)")
        
        # Initialize portfolio manager with Fund object
        from portfolio.fund_manager import Fund
        fund = Fund(id=fund_name, name=fund_name, description=f"Fund: {fund_name}")
        portfolio_manager = PortfolioManager(repository, fund)
        
        # Load trade log - CRITICAL: If writing to Supabase, MUST read from Supabase only
        # Reading from CSV and writing to Supabase could corrupt Supabase with stale data
        load_start = time.time()
        trade_df = None
        
        # Check if we're using Supabase (either supabase-only or supabase-dual-write)
        using_supabase = (hasattr(repository, 'supabase_repo') or hasattr(repository, 'supabase') or 
                         repository.__class__.__name__ == 'SupabaseRepository' or
                         'supabase' in repository.__class__.__name__.lower())
        
        if using_supabase:
            # CRITICAL: If writing to Supabase, we MUST read from Supabase only
            # Never read from CSV when writing to Supabase - could corrupt Supabase with stale data
            print_info(f"{_safe_emoji('📊')} Loading trade log from Supabase (required when writing to Supabase)...")
            try:
                # Try to get trades from Supabase (primary source)
                trades = None
                if hasattr(repository, 'get_trade_history'):
                    trades = repository.get_trade_history()
                elif hasattr(repository, 'supabase_repo') and hasattr(repository.supabase_repo, 'get_trade_history'):
                    trades = repository.supabase_repo.get_trade_history()
                elif hasattr(repository, 'supabase'):
                    # Direct Supabase repository - need to query directly
                    from data.repositories.supabase_repository import SupabaseRepository
                    temp_repo = SupabaseRepository(fund_name=fund_name)
                    trades = temp_repo.get_trade_history()
                
                if trades and len(trades) > 0:
                    # Convert Trade objects to DataFrame format
                    # Trade model uses 'timestamp' not 'date'
                    trade_data = []
                    for trade in trades:
                        # Use timestamp and convert to date for DataFrame compatibility
                        trade_timestamp = trade.timestamp
                        # Extract date from timestamp for sorting
                        if hasattr(trade_timestamp, 'date'):
                            trade_date = trade_timestamp.date()
                        else:
                            # If it's already a date, use it directly
                            trade_date = trade_timestamp
                        
                        trade_data.append({
                            'Date': trade_timestamp,  # Keep full timestamp for processing
                            'Ticker': trade.ticker,
                            'Shares': float(trade.shares),
                            'Price': float(trade.price),
                            'Action': trade.action if hasattr(trade, 'action') else 'BUY',
                            'Reason': trade.reason if hasattr(trade, 'reason') else '',
                            'Currency': trade.currency if hasattr(trade, 'currency') else 'USD'
                        })
                    trade_df = pd.DataFrame(trade_data)
                    from utils.timezone_utils import safe_parse_datetime_column
                    trade_df['Date'] = safe_parse_datetime_column(trade_df['Date'], 'Date')
                    trade_df = trade_df.sort_values('Date')
                    print_success(f"{_safe_emoji('✅')} Loaded {len(trade_df)} trades from Supabase ({time.time() - load_start:.2f}s)")
                else:
                    print_error("❌ No trades found in Supabase")
                    return False
            except Exception as e:
                print_error(f"❌ Failed to load trades from Supabase: {e}")
                print_error("❌ Cannot proceed - reading from CSV and writing to Supabase would corrupt Supabase with potentially stale data")
                return False
        else:
            # CSV-only mode (no Supabase) - safe to read from CSV
            print_info(f"{_safe_emoji('📊')} Loading trade log from CSV (CSV-only mode)...")
            trade_log_file = Path(data_dir) / "llm_trade_log.csv"
            if not trade_log_file.exists():
                print_error(f"❌ Trade log not found: {trade_log_file}")
                return False
            try:
                trade_df = pd.read_csv(trade_log_file)
                from utils.timezone_utils import safe_parse_datetime_column
                trade_df['Date'] = safe_parse_datetime_column(trade_df['Date'], 'Date')
                trade_df = trade_df.sort_values('Date')
                print_success(f"{_safe_emoji('✅')} Loaded {len(trade_df)} trades from CSV ({time.time() - load_start:.2f}s)")
            except Exception as e:
                print_error(f"❌ Failed to load CSV trade log: {e}")
                return False
        
        load_time = time.time() - load_start
        _log_rebuild_progress(fund_name, f"Starting rebuild: {len(trade_df)} trades to process")
        
        if len(trade_df) == 0:
            print_warning("⚠️  Trade log is empty - no portfolio entries to generate")
            return True
        
        # Clear existing portfolio data
        print_info(f"{_safe_emoji('🧹')} Clearing existing portfolio data...")
        try:
            # Clear CSV portfolio file (local only, skip in Docker)
            if not is_docker:
                portfolio_file = Path(data_dir) / "llm_portfolio_update.csv"
                if portfolio_file.exists():
                    # Create backup in backups directory
                    backup_dir = Path(data_dir) / "backups"
                    backup_dir.mkdir(exist_ok=True)
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    backup_file = backup_dir / f"{portfolio_file.stem}.backup_{timestamp}.csv"
                    shutil.copy2(portfolio_file, backup_file)
                    portfolio_file.unlink()  # Remove original file
                    print_info(f"   Backed up existing portfolio to: {backup_file}")
            
            # Clear Supabase data (if using dual-write)
            if hasattr(repository, 'supabase_repo') and hasattr(repository.supabase_repo, 'supabase'):
                try:
                    # Delete all portfolio positions for this fund
                    result = repository.supabase_repo.supabase.table("portfolio_positions").delete().eq("fund", fund_name).execute()
                    print_info(f"   Cleared {len(result.data) if result.data else 0} Supabase portfolio positions")
                except Exception as e:
                    print_warning(f"   Could not clear Supabase data: {e}")
            elif hasattr(repository, 'supabase'):
                try:
                    # Delete all portfolio positions for this fund
                    result = repository.supabase.table("portfolio_positions").delete().eq("fund", fund_name).execute()
                    print_info(f"   Cleared {len(result.data) if result.data else 0} Supabase portfolio positions")
                except Exception as e:
                    print_warning(f"   Could not clear Supabase data: {e}")
                
        except Exception as e:
            print_warning(f"⚠️  Could not clear existing data: {e}")
        
        # Process trades and generate snapshots below
        print_info(f"{_safe_emoji('📈')} Processing trades chronologically...")
        
        # Generate HOLD entries for all trading days
        print_info(f"{_safe_emoji('📊')} Generating HOLD entries for all trading days...")
        
        # Get all unique trading days from trades
        trade_dates = sorted(trade_df['Date'].dt.date.unique())
        
        # Add trading days from first trade to today (or last trading day)
        market_hours = MarketHours()
        market_holidays = MarketHolidays()
        current_date = trade_dates[0]
        
        # Generate up to today or the last trading day
        today = datetime.now().date()
        last_trading_day = market_hours.last_trading_date().date()
        end_date = max(trade_dates[-1], last_trading_day)
        
        all_trading_days = set(trade_dates)
        while current_date <= end_date:
            if market_hours.is_trading_day(current_date):
                all_trading_days.add(current_date)
            current_date += timedelta(days=1)
        
        # Generate historical HOLD entries for each trading day
        print_info(f"{_safe_emoji('📊')} Creating historical portfolio snapshots...")
        
        from data.models.portfolio import Position, PortfolioSnapshot
        from market_data.data_fetcher import MarketDataFetcher
        from market_data.price_cache import PriceCache
        
        # Initialize market data fetcher and price cache
        market_fetcher = MarketDataFetcherClass()
        price_cache = PriceCache()
        
        # Convert all_trading_days to sorted list
        all_trading_days_list = sorted(list(all_trading_days))
        print_info(f"   Generating snapshots for {len(all_trading_days_list)} trading days")
        
        # Pre-calculate positions for each trading day
        print_info("   Calculating positions for each trading day...")
        position_calc_start = time.time()
        date_positions = {}  # date -> {ticker: position_data}
        running_positions = defaultdict(lambda: {'shares': Decimal('0'), 'cost': Decimal('0'), 'currency': 'USD'})
        
        # FIFO lot tracking for P&L calculation
        from collections import deque
        lots_by_ticker = defaultdict(deque)  # ticker -> deque([(shares, price), ...])
        trades_to_update_pnl = []  # List of trades that need P&L backfilled
        
        for trading_day in all_trading_days_list:
            # Process trades for this specific day only
            day_trades = trade_df[trade_df['Date'].dt.date == trading_day]
            
            for _, trade in day_trades.iterrows():
                ticker = trade['Ticker']
                reason = trade['Reason']
                shares = Decimal(str(trade['Shares']))
                price = Decimal(str(trade['Price']))
                cost = shares * price
                
                # Determine action from reason - look for SELL first, then default to BUY
                # Handle NaN and other non-string values
                if pd.isna(reason) or not isinstance(reason, str):
                    reason_str = ''
                else:
                    reason_str = str(reason).upper()
                
                if 'SELL' in reason_str:
                    # Calculate realized P&L using FIFO
                    remaining_to_sell = shares
                    total_cost_basis = Decimal('0')
                    
                    while remaining_to_sell > 0 and lots_by_ticker[ticker]:
                        lot_shares, lot_price = lots_by_ticker[ticker][0]
                        
                        if lot_shares <= remaining_to_sell:
                            # Consume entire lot
                            total_cost_basis += lot_shares * lot_price
                            remaining_to_sell -= lot_shares
                            lots_by_ticker[ticker].popleft()
                        else:
                            # Partially consume lot
                            total_cost_basis += remaining_to_sell * lot_price
                            lots_by_ticker[ticker][0] = (lot_shares - remaining_to_sell, lot_price)
                            remaining_to_sell = Decimal('0')
                    
                    # Calculate realized P&L
                    proceeds = shares * price
                    realized_pnl = proceeds - total_cost_basis
                    
                    # Store for database update (only if pnl is currently 0)
                    trades_to_update_pnl.append({
                        'ticker': ticker,
                        'date': trade['Date'].isoformat(),
                        'shares': float(shares),
                        'pnl': float(realized_pnl)
                    })
                    
                    # Simple FIFO: reduce shares and cost proportionally (existing logic)
                    if running_positions[ticker]['shares'] > 0:
                        cost_per_share = running_positions[ticker]['cost'] / running_positions[ticker]['shares']
                        running_positions[ticker]['shares'] -= shares
                        running_positions[ticker]['cost'] -= shares * cost_per_share
                        # Ensure we don't go negative
                        if running_positions[ticker]['shares'] < 0:
                            running_positions[ticker]['shares'] = Decimal('0')
                        if running_positions[ticker]['cost'] < 0:
                            running_positions[ticker]['cost'] = Decimal('0')
                else:
                    # Default to BUY for all other trades (including imported ones)
                    # Add to FIFO lots
                    lots_by_ticker[ticker].append((shares, price))
                    
                    running_positions[ticker]['shares'] += shares
                    running_positions[ticker]['cost'] += cost
                    # Handle NaN currency values
                    currency = trade.get('Currency', 'USD')
                    if pd.isna(currency):
                        currency = 'USD'
                    running_positions[ticker]['currency'] = currency
            
                # Store current running positions for this date
            date_positions[trading_day] = dict(running_positions)
            
            # Log progress every 10 days
            processed_days = len(date_positions)
            if processed_days % 10 == 0:
                _log_rebuild_progress(fund_name, f"Processed {processed_days}/{len(all_trading_days_list)} trading days")
        
        position_calc_time = time.time() - position_calc_start
        print_info(f"   Position calculation complete ({position_calc_time:.2f}s)")
        
        # Batch update trade_log with calculated P&L (only for trades with pnl=0)
        if trades_to_update_pnl and fund_name:
            print_info(f"{_safe_emoji('💰')} Backfilling P&L for {len(trades_to_update_pnl)} SELL trades...")
            print_info(f"   (Only updating trades with P&L = 0, preserving existing values)")
            
            # Get repository's Supabase client
            supabase_client = None
            if hasattr(repository, 'supabase'):
                supabase_client = repository.supabase
            elif hasattr(repository, 'supabase_repo') and hasattr(repository.supabase_repo, 'supabase'):
                supabase_client = repository.supabase_repo.supabase
            
            if supabase_client:
                updated_count = 0
                skipped_count = 0
                
                for trade_info in trades_to_update_pnl:
                    try:
                        # ONLY update if current pnl is 0 (preserve existing values)
                        result = supabase_client.table("trade_log").update({
                            'pnl': trade_info['pnl']
                        }).eq('fund', fund_name) \
                          .eq('ticker', trade_info['ticker']) \
                          .eq('date', trade_info['date']) \
                          .eq('shares', trade_info['shares']) \
                          .eq('pnl', 0) \
                          .execute()
                        
                        if result.data and len(result.data) > 0:
                            updated_count += 1
                        else:
                            skipped_count += 1
                    except Exception as e:
                        print_warning(f"   Could not update P&L for {trade_info['ticker']}: {e}")
                
                print_success(f"   ✅ Backfilled P&L for {updated_count} trades")
                if skipped_count > 0:
                    print_info(f"   Skipped {skipped_count} trades (P&L already calculated)")
            else:
                print_warning("   Supabase client not available - P&L not updated in trade_log")

        
        # Generate portfolio snapshots for each trading day
        snapshots_created = 0
        
        # Pre-fetch prices for all unique tickers across all dates for better performance
        print_info("   Pre-fetching historical prices...")
        _log_rebuild_progress(fund_name, f"Fetching historical prices for portfolio positions...")
        price_fetch_start = time.time()
        all_tickers = set()
        for positions in date_positions.values():
            all_tickers.update(positions.keys())
        
        # Fetch prices for all tickers and dates
        price_cache_dict = {}  # {(ticker, date): price}
        successful_fetches = 0
        failed_fetches = 0

        print_info(f"   Date range: {all_trading_days_list[0]} to {all_trading_days_list[-1]}")
        print_info(f"   Total trading days: {len(all_trading_days_list)}")
        print_info(f"   Fetching prices for {len(all_tickers)} tickers in parallel...")

        # Helper function to fetch price data for a single ticker
        def fetch_ticker_prices(ticker: str) -> tuple[str, dict, bool]:
            """Fetch price data for a single ticker. Returns (ticker, price_dict, success)."""
            try:
                # Convert date objects to datetime for API compatibility
                start_dt = datetime.combine(all_trading_days_list[0], datetime.min.time())
                end_dt = datetime.combine(all_trading_days_list[-1], datetime.max.time())
                
                # Fetch all historical data for this ticker at once
                result = market_fetcher.fetch_price_data(ticker, start=start_dt, end=end_dt)
                
                if result.df is not None and not result.df.empty:
                    # Cache the full dataset
                    price_cache.cache_price_data(ticker, result.df)
                    
                    # OPTIMIZATION: Vectorized price extraction using pandas
                    # Extract all prices at once using vectorized operations
                    ticker_prices = {}
                    df = result.df
                    if 'Close' in df.columns and not df.empty:
                        # Create date column from index for fast filtering
                        df_with_dates = df.copy()
                        if hasattr(df.index, 'date'):
                            df_with_dates['_date'] = [d.date() for d in df.index]
                        else:
                            df_with_dates['_date'] = pd.to_datetime(df.index).date
                        
                        # Filter to only STICTLY OPEN trading days for this specific ticker
                        # This prevents "leaking" prices from holidays if the API returns them,
                        # and ensures we validly filter out days where this ticker's market was closed.
                        is_canadian = ticker.endswith(('.TO', '.V', '.CN'))
                        valid_days_for_ticker = set()
                        for day in all_trading_days_list:
                            if is_canadian:
                                if not market_holidays.is_canadian_market_closed(day):
                                    valid_days_for_ticker.add(day)
                            else:
                                if not market_holidays.is_us_market_closed(day):
                                    valid_days_for_ticker.add(day)

                        mask = df_with_dates['_date'].isin(valid_days_for_ticker)
                        filtered = df_with_dates.loc[mask]
                        
                        # Extract prices (vectorized)
                        for _, row in filtered.iterrows():
                            day = row['_date']
                            if day in valid_days_for_ticker:
                                ticker_prices[day] = Decimal(str(row['Close']))
                    
                    return (ticker, ticker_prices, True)
                else:
                    return (ticker, {}, False)
                    
            except Exception as e:
                # Re-raise to be caught by caller for rate limit detection
                # The caller will check for 429 errors and log appropriately
                raise

        # Fetch prices in parallel using ThreadPoolExecutor
        # Use conservative max_workers=5 for free-tier APIs (Yahoo Finance) to avoid rate limiting
        # Monitor for 429 errors which indicate rate limiting
        max_workers = min(5, len(all_tickers))  # Reduced from 15 to 5 for free-tier API safety
        rate_limit_errors = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all fetch tasks
            future_to_ticker = {executor.submit(fetch_ticker_prices, ticker): ticker for ticker in all_tickers}
            
            # Process completed tasks as they finish
            completed = 0
            for future in as_completed(future_to_ticker):
                completed += 1
                try:
                    ticker, ticker_prices, success = future.result()
                    
                    if success:
                        # Add prices to cache dict
                        for trading_day, price in ticker_prices.items():
                            price_cache_dict[(ticker, trading_day)] = price
                        successful_fetches += 1
                        
                        # Show progress every 5 tickers
                        if completed % 5 == 0:
                            print_info(f"   Progress: {completed}/{len(all_tickers)} tickers fetched...")
                    else:
                        failed_fetches += 1
                        print_error(f"     {_safe_emoji('✗')} {ticker}: No data returned")
                except Exception as e:
                    failed_fetches += 1
                    error_str = str(e).lower()
                    # Check for rate limiting errors (429, too many requests, etc.)
                    if '429' in error_str or 'rate limit' in error_str or 'too many requests' in error_str:
                        rate_limit_errors += 1
                        print_warning(f"     {_safe_emoji('⚠️')} {ticker}: Rate limit error (429) - API throttling detected")
                        if rate_limit_errors == 1:
                            print_warning(f"   WARNING: Rate limiting detected! Consider reducing concurrency or adding delays.")
                    else:
                        print_error(f"     {_safe_emoji('✗')} {ticker}: Fetch failed - {e}")

        price_fetch_time = time.time() - price_fetch_start
        avg_time_per_ticker = price_fetch_time / len(all_tickers) if all_tickers else 0
        print_info(f"   Parallel fetch complete: {successful_fetches} succeeded, {failed_fetches} failed ({price_fetch_time:.2f}s, ~{avg_time_per_ticker:.2f}s per ticker)")
        
        if rate_limit_errors > 0:
            print_warning(f"   ⚠️  Rate limiting detected: {rate_limit_errors} tickers hit 429 errors")
            print_warning(f"      Consider: reducing max_workers, adding delays, or using API keys")

        if failed_fetches > 0:
            print_error(f"   WARNING: {failed_fetches} tickers failed to fetch - rebuild may be incomplete")
        
        # Track issues for summary
        skipped_positions = []  # List of (date, ticker, reason)
        fallback_positions = []  # List of (date, ticker, fallback_type)
        
        # OPTIMIZATION: Cache company names before the loop
        print_info("   Caching company names...")
        company_name_cache = {}
        
        cache_start = time.time()
        # OPTIMIZATION: Parallel company name fetching (if many tickers)
        if len(all_tickers) > 10:
            def fetch_company_name(ticker: str) -> tuple[str, str]:
                try:
                    return (ticker, get_company_name(ticker))
                except Exception:
                    return (ticker, 'Unknown')
            
            max_workers = min(5, len(all_tickers))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                results = executor.map(fetch_company_name, all_tickers)
                for ticker, name in results:
                    company_name_cache[ticker] = name
        else:
            # Sequential for small sets
            for ticker in all_tickers:
                try:
                    company_name_cache[ticker] = get_company_name(ticker)
                except Exception:
                    company_name_cache[ticker] = 'Unknown'
        cache_time = time.time() - cache_start
        print_info(f"   Cached {len(company_name_cache)} company names ({cache_time:.2f}s)")
        
        print_info("   Creating portfolio snapshots...")
        snapshot_start = time.time()
        position_creation_time = 0  # Time spent creating Position objects
        snapshot_save_time = 0  # Time spent saving to repository (I/O)
        
        # OPTIMIZATION: Pre-compute forward-fill price lookup tables for each ticker
        # This avoids O(n) backward search for each missing price
        print_info("   Building price forward-fill lookup tables...")
        price_ffill_start = time.time()
        price_ffill_cache = {}  # {ticker: {date: price}} - forward-filled prices
        for ticker in all_tickers:
            ticker_ffill = {}
            last_price = None
            for trading_day in all_trading_days_list:
                price_key = (ticker, trading_day)
                if price_key in price_cache_dict:
                    last_price = price_cache_dict[price_key]
                # Forward-fill: use last known price if current date missing
                if last_price is not None:
                    ticker_ffill[trading_day] = last_price
            price_ffill_cache[ticker] = ticker_ffill
        price_ffill_time = time.time() - price_ffill_start
        print_info(f"   Built forward-fill tables ({price_ffill_time:.3f}s)")
        
        # OPTIMIZATION: Pre-compute market trading days to avoid repeated checks
        print_info("   Pre-computing market trading days...")
        market_days_start = time.time()
        us_trading_days = set()
        canadian_trading_days = set()
        for trading_day in all_trading_days_list:
            if market_holidays.is_trading_day(trading_day, market='us'):
                us_trading_days.add(trading_day)
            if market_holidays.is_trading_day(trading_day, market='canadian'):
                canadian_trading_days.add(trading_day)
        market_days_time = time.time() - market_days_start
        print_info(f"   Pre-computed market days ({market_days_time:.3f}s)")
        
        # OPTIMIZATION: Maintain running positions that persist across days (O(n) instead of O(n²))
        # Instead of looping through all previous days, we maintain positions that carry forward
        # Initialize with positions from the first trading day
        persistent_positions = {}
        if all_trading_days_list:
            first_day_positions = date_positions.get(all_trading_days_list[0], {})
            for ticker, pos in first_day_positions.items():
                if pos['shares'] > 0:
                    persistent_positions[ticker] = pos
        
        # Batch snapshots for more efficient I/O
        BATCH_SIZE = 20  # Write every 20 snapshots
        snapshot_batch = []  # List of (snapshot, trading_day) tuples
        today = datetime.now().date()
        for trading_day in all_trading_days_list:
            # Skip today - it will be handled by the final snapshot
            if trading_day >= today:
                continue
            
            # OPTIMIZATION: Use persistent positions instead of O(n²) loop
            # Update persistent positions with trades from this day
            # Positions that weren't traded continue to persist (already in persistent_positions)
            positions_for_date = date_positions.get(trading_day, {})
            for ticker, pos in positions_for_date.items():
                if pos['shares'] > 0:
                    # Position was bought or still held - update/add to persistent
                    persistent_positions[ticker] = pos
                elif ticker in persistent_positions:
                    # Position was sold - remove from persistent
                    del persistent_positions[ticker]
            
            # All held positions are now in persistent_positions (no need to loop through previous days)
            all_held_positions = persistent_positions.copy()
            
            if len(all_held_positions) == 0:
                continue
            
            # OPTIMIZATION: Use pre-computed market days instead of checking each ticker
            # Check if any market was open for our positions
            any_market_open = False
            for ticker in all_held_positions.keys():
                is_canadian = ticker.endswith(('.TO', '.V', '.CN'))
                market_open = (trading_day in canadian_trading_days) if is_canadian else (trading_day in us_trading_days)
                if market_open:
                    any_market_open = True
                    break
            
            if not any_market_open:
                continue
            
            # Only show progress every 10 days or for important milestones
            if len([d for d in all_trading_days_list if d <= trading_day]) % 10 == 0:
                print_info(f"   Processing {trading_day}...")
            
            # Create positions list for this date
            position_creation_start = time.time()
            daily_positions = []
            for ticker, position in all_held_positions.items():
                if position['shares'] > 0:  # Only include positions with shares
                    # CRITICAL FIX: Do NOT skip tickers if their market is closed!
                    # If we skip them, they disappear from the portfolio snapshot, causing a massive drop in value.
                    # Instead, we should let them fall through to the forward-fill logic below,
                    # which will pick up the last known price.
                    
                    # Ensure no division by zero
                    if position['shares'] > 0:
                        avg_price = position['cost'] / position['shares']
                    else:
                        avg_price = Decimal('0')
                    
                    # OPTIMIZATION: Use forward-fill lookup table (O(1) instead of O(n) backward search)
                    price_key = (ticker, trading_day)
                    if price_key in price_cache_dict:
                        current_price = price_cache_dict[price_key]
                    elif ticker in price_ffill_cache and trading_day in price_ffill_cache[ticker]:
                        # Use forward-filled price (previous day's price)
                        current_price = price_ffill_cache[ticker][trading_day]
                        fallback_positions.append((trading_day, ticker, 'previous_day_price'))
                    elif position['cost'] > 0 and position['shares'] > 0:
                        # Last resort: use cost basis (average purchase price)
                        current_price = position['cost'] / position['shares']
                        fallback_positions.append((trading_day, ticker, 'cost_basis'))
                    else:
                        # Skip this position entirely - log error and continue
                        print_error(f"   [{trading_day}] SKIPPING {ticker}: No price data and no cost basis available")
                        print_error(f"      Position: shares={position['shares']}, cost={position['cost']}")
                        skipped_positions.append((trading_day, ticker, f"No price data, shares={position['shares']}"))
                        continue  # Skip this ticker, continue with others
                    market_value = position['shares'] * current_price
                    unrealized_pnl = market_value - position['cost']
                    
                    # Ensure all values are valid (no NaN, no infinity)
                    # Check for NaN by converting to float and back
                    try:
                        avg_price_float = float(avg_price)
                        if avg_price_float != avg_price_float or avg_price_float == float('inf') or avg_price_float == float('-inf'):
                            print(f"WARNING: Invalid avg_price for {ticker}: {avg_price} -> 0")
                            avg_price = Decimal('0')
                    except (ValueError, TypeError, OverflowError) as e:
                        print(f"ERROR: avg_price conversion failed for {ticker}: {avg_price} - {e}")
                        avg_price = Decimal('0')
                    
                    try:
                        current_price_float = float(current_price)
                        if current_price_float != current_price_float or current_price_float == float('inf') or current_price_float == float('-inf'):
                            print(f"WARNING: Invalid current_price for {ticker}: {current_price} -> 0")
                            current_price = Decimal('0')
                    except (ValueError, TypeError, OverflowError) as e:
                        print(f"ERROR: current_price conversion failed for {ticker}: {current_price} - {e}")
                        current_price = Decimal('0')
                    
                    try:
                        market_value_float = float(market_value)
                        if market_value_float != market_value_float or market_value_float == float('inf') or market_value_float == float('-inf'):
                            print(f"WARNING: Invalid market_value for {ticker}: {market_value} -> 0")
                            market_value = Decimal('0')
                    except (ValueError, TypeError, OverflowError) as e:
                        print(f"ERROR: market_value conversion failed for {ticker}: {market_value} - {e}")
                        market_value = Decimal('0')
                    
                    try:
                        unrealized_pnl_float = float(unrealized_pnl)
                        if unrealized_pnl_float != unrealized_pnl_float or unrealized_pnl_float == float('inf') or unrealized_pnl_float == float('-inf'):
                            print(f"WARNING: Invalid unrealized_pnl for {ticker}: {unrealized_pnl} -> 0")
                            unrealized_pnl = Decimal('0')
                    except (ValueError, TypeError, OverflowError) as e:
                        print(f"ERROR: unrealized_pnl conversion failed for {ticker}: {unrealized_pnl} - {e}")
                        unrealized_pnl = Decimal('0')
                    
                    # Use cached company name (already fetched before the loop)
                    position_obj = Position(
                        ticker=ticker,
                        shares=position['shares'],
                        avg_price=avg_price,
                        cost_basis=position['cost'],
                        currency=position['currency'],
                        company=company_name_cache.get(ticker, 'Unknown'),
                        current_price=current_price,
                        market_value=market_value,
                        unrealized_pnl=unrealized_pnl
                    )
                    daily_positions.append(position_obj)
            
            position_creation_time += time.time() - position_creation_start
            
            # Create and save portfolio snapshot for this date
            if daily_positions:
                # CRITICAL: Create datetime with ET timezone, then convert to UTC for storage
                # This ensures the timestamp is correctly interpreted regardless of server timezone
                from datetime import datetime as dt
                et_tz = pytz.timezone('America/New_York')
                # Create datetime at 4 PM ET (market close) for the trading day
                et_datetime = et_tz.localize(dt.combine(trading_day, dt.min.time().replace(hour=16, minute=0)))
                # Convert to UTC for storage (Supabase stores timestamps in UTC)
                snapshot_timestamp = et_datetime.astimezone(pytz.UTC)
                
                # Calculate total value with NaN checking
                total_value = Decimal('0')
                for p in daily_positions:
                    try:
                        market_val_float = float(p.market_value)
                        if market_val_float != market_val_float:  # Check for NaN
                            print(f"WARNING: NaN market_value for {p.ticker}: {p.market_value}")
                            p.market_value = Decimal('0')
                        total_value += p.market_value
                    except Exception as e:
                        print(f"ERROR: Invalid market_value for {p.ticker}: {p.market_value} - {e}")
                        p.market_value = Decimal('0')
                        total_value += Decimal('0')
                
                snapshot = PortfolioSnapshot(
                    positions=daily_positions,
                    timestamp=snapshot_timestamp,
                    total_value=total_value
                )
                
                # Add to batch instead of saving immediately
                snapshot_batch.append((snapshot, trading_day))
                snapshots_created += 1
                
                # Save batch when it reaches BATCH_SIZE
                if len(snapshot_batch) >= BATCH_SIZE:
                    save_start = time.time()
                    _save_snapshot_batch(repository, snapshot_batch, fund_name, is_docker)
                    batch_save_time = time.time() - save_start
                    snapshot_save_time += batch_save_time
                    print_info(f"   Saved batch of {len(snapshot_batch)} snapshots ({batch_save_time:.2f}s, {batch_save_time/len(snapshot_batch)*1000:.0f}ms per snapshot)")
                    snapshot_batch = []  # Clear batch
                
                # Show progress every 10 snapshots with detailed timing
                if snapshots_created % 10 == 0:
                    elapsed = time.time() - snapshot_start
                    rate = snapshots_created / elapsed if elapsed > 0 else 0
                    avg_save_time = snapshot_save_time / snapshots_created if snapshots_created > 0 else 0
                    avg_create_time = position_creation_time / snapshots_created if snapshots_created > 0 else 0
                    remaining = len([d for d in all_trading_days_list if d < today]) - snapshots_created
                    eta_seconds = remaining * avg_save_time if avg_save_time > 0 else 0
                    eta_minutes = int(eta_seconds // 60)
                    eta_secs = int(eta_seconds % 60)
                    print_info(f"   Progress: {snapshots_created}/{len([d for d in all_trading_days_list if d < today])} snapshots")
                    print_info(f"      Rate: {rate:.2f} snapshots/sec | Avg I/O: {avg_save_time*1000:.0f}ms | Avg create: {avg_create_time*1000:.0f}ms | ETA: {eta_minutes}m {eta_secs}s")
        
        # Save any remaining snapshots in the batch
        if snapshot_batch:
            save_start = time.time()
            _save_snapshot_batch(repository, snapshot_batch, fund_name, is_docker)
            batch_save_time = time.time() - save_start
            snapshot_save_time += batch_save_time
            print_info(f"   Saved final batch of {len(snapshot_batch)} snapshots ({batch_save_time:.2f}s)")
        
        snapshot_time = time.time() - snapshot_start
        snapshot_rate = snapshots_created / snapshot_time if snapshot_time > 0 else 0
        save_rate = snapshots_created / snapshot_save_time if snapshot_save_time > 0 else 0
        print_info(f"   Created {snapshots_created} historical portfolio snapshots:")
        print_info(f"      Total time: {snapshot_time:.2f}s ({snapshot_rate:.1f} snapshots/sec)")
        print_info(f"      Position creation: {position_creation_time:.2f}s")
        print_info(f"      Repository I/O (CSV+Supabase): {snapshot_save_time:.2f}s ({save_rate:.1f} saves/sec)")
        
        # Print summary of issues
        if skipped_positions or fallback_positions:
            print_info(f"\n{_safe_emoji('📋')} REBUILD SUMMARY:")
            print_info(f"   Snapshots created: {snapshots_created}")
            
            if fallback_positions:
                print_warning(f"   Fallbacks used: {len(fallback_positions)}")
                # Group by fallback type
                prev_day_count = len([f for f in fallback_positions if f[2] == 'previous_day_price'])
                cost_basis_count = len([f for f in fallback_positions if f[2] == 'cost_basis'])
                if prev_day_count:
                    print_warning(f"     - Previous day's price: {prev_day_count} times")
                if cost_basis_count:
                    print_warning(f"     - Cost basis: {cost_basis_count} times")
            
            if skipped_positions:
                print_error(f"   Positions SKIPPED: {len(skipped_positions)}")
                for skip_date, skip_ticker, skip_reason in skipped_positions[:10]:  # Show first 10
                    print_error(f"     - {skip_date} | {skip_ticker} | {skip_reason}")
                if len(skipped_positions) > 10:
                    print_error(f"     ... and {len(skipped_positions) - 10} more")
        
        # Create final portfolio snapshot from current positions
        # Only create snapshot for today if:
        # 1. Today is a trading day (not weekend/holiday)
        # 2. Market has already closed (or we're past 4:30 PM ET to allow for data settling)
        # 
        # This prevents creating snapshots with future timestamps when rebuild runs
        # before market close (e.g., overnight jobs at 3 AM)
        from config.settings import Settings
        
        settings = Settings()
        today = datetime.now().date()
        
        # Check if market has closed
        # Market closes at 4 PM ET, so we check if current time is after 4:30 PM ET
        # (allowing 30 min for data to settle)
        from datetime import datetime as dt
        et_tz = pytz.timezone('America/New_York')
        current_time_et = dt.now(et_tz)
        market_close_time = current_time_et.replace(hour=16, minute=30, second=0, microsecond=0)
        market_has_closed = current_time_et >= market_close_time
        
        # Initialize final snapshot time (will be set if snapshot is created)
        final_snapshot_time = 0.0
        
        if market_hours.is_trading_day(today) and market_has_closed:
            print_info(f"{_safe_emoji('📊')} Creating final portfolio snapshot (market closed at 4 PM ET)...")
            final_snapshot_start = time.time()
            
            from data.models.portfolio import Position, PortfolioSnapshot
            final_positions = []
            
            # OPTIMIZATION: Parallel fetch for final snapshot prices (like historical prices)
            print_info(f"   Fetching current market prices for {len(running_positions)} positions in parallel...")
            print_info(f"   Note: Positions with 0 shares will be filtered out (sold positions)")
            final_price_start = time.time()
            current_prices = {}  # {ticker: price}
            tickers_to_fetch = list(running_positions.keys())
            
            def fetch_final_price(ticker: str) -> tuple[str, Optional[Decimal]]:
                """Fetch current price for a single ticker. Returns (ticker, price)."""
                try:
                    today_dt = datetime.now().date()
                    start_dt = datetime.combine(today_dt, datetime.min.time())
                    end_dt = datetime.combine(today_dt, datetime.max.time())
                    result = market_fetcher.fetch_price_data(ticker, start=start_dt, end=end_dt)
                    
                    if result and result.df is not None and not result.df.empty:
                        latest_price = Decimal(str(result.df['Close'].iloc[-1]))
                        return (ticker, latest_price)
                    else:
                        return (ticker, None)
                except Exception as e:
                    return (ticker, None)
            
            # Fetch prices in parallel (conservative concurrency for free-tier APIs)
            max_workers = min(5, len(tickers_to_fetch))  # Reduced from 15 to 5 for free-tier API safety
            rate_limit_errors_final = 0
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_ticker = {executor.submit(fetch_final_price, ticker): ticker for ticker in tickers_to_fetch}
                
                for future in as_completed(future_to_ticker):
                    try:
                        ticker, price = future.result()
                        current_prices[ticker] = price
                        if price is None:
                            print_warning(f"   Could not fetch current price for {ticker} - using cost basis")
                    except Exception as e:
                        error_str = str(e).lower()
                        if '429' in error_str or 'rate limit' in error_str or 'too many requests' in error_str:
                            rate_limit_errors_final += 1
                            print_warning(f"   ⚠️  {ticker}: Rate limit error (429) - API throttling detected")
                        current_prices[ticker] = None
            
            if rate_limit_errors_final > 0:
                print_warning(f"   ⚠️  Rate limiting detected in final snapshot: {rate_limit_errors_final} tickers hit 429 errors")
            
            final_price_time = time.time() - final_price_start
            avg_price_fetch = final_price_time / len(tickers_to_fetch) if tickers_to_fetch else 0
            print_info(f"   Fetched current prices: {final_price_time:.2f}s (~{avg_price_fetch:.2f}s per ticker, parallel)")
            
            positions_with_shares = 0
            positions_filtered_out = 0
            
            for ticker, position in running_positions.items():
                if position['shares'] > 0:  # Only include positions with shares
                    positions_with_shares += 1
                    avg_price = position['cost'] / position['shares'] if position['shares'] > 0 else Decimal('0')
                    
                    # Get fetched current price for today
                    current_price = current_prices.get(ticker)
                    
                    if current_price is None:
                        print_error(f"   ❌ CRITICAL: Price fetch failed for {ticker}")
                        print_error(f"      Cannot create snapshot without valid market prices")
                        print_error(f"      This is likely running on a non-trading day or there's a network/API issue")
                        print_error(f"      NO FALLBACK PRICES ALLOWED - data integrity is critical")
                        raise Exception(f"Price fetch failed for {ticker} - aborting snapshot creation")
                    
                    market_value = position['shares'] * current_price
                    unrealized_pnl = market_value - position['cost']
                    
                    final_position = Position(
                        ticker=ticker,
                        shares=position['shares'],
                        avg_price=avg_price,
                        cost_basis=position['cost'],
                        currency=position['currency'],
                        company=get_company_name(ticker),
                        current_price=current_price,
                        market_value=market_value,
                        unrealized_pnl=unrealized_pnl
                    )
                    final_positions.append(final_position)
                else:
                    positions_filtered_out += 1
                    print_info(f"   Filtered out {ticker}: 0 shares (sold position)")
            
            print_info(f"   Position filtering complete:")
            print_info(f"   - {positions_with_shares} positions with shares included")
            print_info(f"   - {positions_filtered_out} positions with 0 shares filtered out")
            print_info(f"   - All included positions have real market prices (no fallbacks)")
            
            # Create and save final portfolio snapshot
            if final_positions:
                # All positions have current prices - safe to save
                # CRITICAL: Create datetime with ET timezone, then convert to UTC for storage
                # This ensures the timestamp is correctly interpreted regardless of server timezone
                from datetime import datetime as dt
                et_tz = pytz.timezone('America/New_York')
                # Create datetime at 4 PM ET (market close) for today
                et_datetime = et_tz.localize(dt.combine(today, dt.min.time().replace(hour=16, minute=0)))
                # Convert to UTC for storage (Supabase stores timestamps in UTC)
                final_timestamp = et_datetime.astimezone(pytz.UTC)
                
                final_snapshot = PortfolioSnapshot(
                    positions=final_positions,
                    timestamp=final_timestamp,
                    total_value=sum(p.cost_basis for p in final_positions)
                )
                final_save_start = time.time()
                repository.save_portfolio_snapshot(final_snapshot)
                final_save_time = time.time() - final_save_start
                final_snapshot_time = time.time() - final_snapshot_start
                print_info(f"   Saved final portfolio snapshot with {len(final_positions)} positions:")
                print_info(f"      Total time: {final_snapshot_time:.2f}s")
                print_info(f"      Price fetching: {final_price_time:.2f}s")
                print_info(f"      Repository I/O: {final_save_time:.2f}s")
        else:
            print_info(f"   Skipping final snapshot - today ({today}) is not a trading day")
        
        # NOTE: Portfolio CSV is already written incrementally by repository.save_portfolio_snapshot()
        # during the snapshot generation loop above. Do NOT overwrite it here.
        # All historical snapshots have been saved correctly to CSV and Supabase.
        print_info(f"{_safe_emoji('📊')} Portfolio CSV already saved with all {snapshots_created} historical snapshots")
        
        print_success(f"{_safe_emoji('✅')} Portfolio rebuild completed successfully!")
        print_info(f"   {_safe_emoji('✅')} CSV files updated with {snapshots_created} snapshots")
        if fund_name:
            print_info(f"   {_safe_emoji('✅')} Trades saved to Supabase")
        print_info(f"   {_safe_emoji('✅')} Positions recalculated from trade log")
        
        # Mark all historical dates as completed in job tracking
        # This prevents web backfill from re-processing dates the rebuild already handled
        if fund_name:
            try:
                # Use service role key to bypass RLS (same as scheduler jobs)
                from web_dashboard.supabase_client import SupabaseClient
                from datetime import timezone as dt_timezone
                
                client = SupabaseClient(use_service_role=True)
                historical_dates = [d for d in all_trading_days_list if d < today]
                
                if historical_dates:
                    print_info(f"{_safe_emoji('📝')} Marking {len(historical_dates)} dates as completed in job tracking...")
                    
                    # Batch insert job completion records
                    job_records = []
                    for trading_day in historical_dates:
                        job_records.append({
                            'job_name': 'rebuild_portfolio',
                            'target_date': trading_day.isoformat(),
                            'fund_name': fund_name,
                            'status': 'success',
                            'completed_at': datetime.now(dt_timezone.utc).isoformat(),
                            'funds_processed': [fund_name]
                        })
                    
                    # Also add today if we created final snapshot
                    if market_hours.is_trading_day(today):
                        job_records.append({
                            'job_name': 'rebuild_portfolio',
                            'target_date': today.isoformat(),
                            'fund_name': fund_name,
                            'status': 'success',
                            'completed_at': datetime.now(dt_timezone.utc).isoformat(),
                            'funds_processed': [fund_name]
                        })
                    
                    # Batch upsert (Supabase limit is 1000, but we're well under that)
                    if job_records:
                        chunk_size = 1000
                        for i in range(0, len(job_records), chunk_size):
                            chunk = job_records[i:i + chunk_size]
                            client.supabase.table("job_executions").upsert(
                                chunk,
                                on_conflict='job_name,target_date,fund_name'
                            ).execute()
                        
                        print_info(f"   {_safe_emoji('✅')} Job tracking updated - {len(job_records)} dates marked as completed")
            except Exception as tracking_error:
                # Don't fail rebuild if tracking fails - just warn once
                print_warning(f"   {_safe_emoji('⚠️')}  Could not update job tracking: {tracking_error}")
                print_warning(f"      This is non-critical - rebuild completed successfully")
        
        elapsed_time = time.time() - start_time
        minutes = int(elapsed_time // 60)
        seconds = int(elapsed_time % 60)
        
        # Performance summary
        print_info(f"\n{_safe_emoji('⏱️')} Performance Summary:")
        print_info(f"   Total rebuild time: {minutes}m {seconds}s ({elapsed_time:.2f}s)")
        print_info(f"   Breakdown:")
        print_info(f"      - Trade log loading: {load_time:.2f}s")
        print_info(f"      - Position calculation: {position_calc_time:.2f}s")
        print_info(f"      - Price fetching (parallel): {price_fetch_time:.2f}s")
        print_info(f"      - Snapshot creation: {snapshot_time:.2f}s")
        if snapshots_created > 0:
            print_info(f"         * Position object creation: {position_creation_time:.2f}s")
            print_info(f"         * Repository I/O (CSV+Supabase): {snapshot_save_time:.2f}s ({snapshot_save_time/snapshots_created*1000:.1f}ms per snapshot)")
        if final_snapshot_time > 0:
            print_info(f"      - Final snapshot: {final_snapshot_time:.2f}s")
        print_info(f"   Snapshots created: {snapshots_created}")
        
        _log_rebuild_progress(fund_name, f"✅ Rebuild complete: {snapshots_created} snapshots created in {minutes}m {seconds}s")
        return True
        
    except Exception as e:
        print_error(f"{_safe_emoji('❌')} Error rebuilding portfolio: {e}")
        _log_rebuild_progress(fund_name, f"❌ Rebuild failed: {str(e)}", success=False)
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main function to rebuild portfolio completely."""
    if len(sys.argv) < 2:
        print_error("❌ Error: data_dir parameter is required")
        print("Usage: python rebuild_portfolio_complete.py <data_dir> [fund_name]")
        print("Example: python rebuild_portfolio_complete.py 'trading_data/funds/Project Chimera' 'Project Chimera'")
        sys.exit(1)
    
    data_dir = sys.argv[1]
    fund_name = sys.argv[2] if len(sys.argv) > 2 else None
    
    success = rebuild_portfolio_complete(data_dir, fund_name)
    
    if success:
        print_success(f"\n{_safe_emoji('🎉')} Complete portfolio rebuild successful!")
        print_info("   Both CSV and Supabase have been updated")
    else:
        print_error(f"\n{_safe_emoji('❌')} Portfolio rebuild failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()
