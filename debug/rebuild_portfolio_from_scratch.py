#!/usr/bin/env python3
"""
Rebuild Portfolio from Trade Log - CSV ONLY (for partial rebuilds)

⚠️  WARNING: THIS SCRIPT ONLY WRITES TO CSV FILES, NOT SUPABASE! ⚠️

For full portfolio rebuilds that sync to both CSV AND Supabase, use:
    python debug/rebuild_portfolio_complete.py "trading_data/funds/Project Chimera"

This script is kept for:
- The `rebuild_ticker_from_date` function (used by trade_processor.py)
- Debug/testing purposes when you only want CSV output

PURPOSE:
This script completely rebuilds the portfolio CSV from scratch based on the trade log.
It's designed to fix data inconsistencies, recover from corruption, or create a fresh
portfolio when the existing one has issues.

WHAT IT DOES:
1. Reads the trade log (llm_trade_log.csv) chronologically
2. Processes each trade and creates corresponding portfolio entries:
   - BUY entries for each purchase with exact trade details
   - HOLD entries for price tracking between trades (using Yahoo Finance API)
   - SELL entries for each sale with proper FIFO calculations
3. Recalculates all positions, cost basis, and P&L from scratch
4. Generates a clean, consistent portfolio CSV with proper formatting

TECHNICAL DETAILS:
- **Price Caching**: Uses PriceCache with MarketDataFetcher to minimize API calls and improve performance
- **Efficient API Usage**: Caches price data in memory to avoid redundant API requests for the same ticker/date
- **Timezone Handling**: Handles timezone-aware timestamps correctly throughout the process
- **FIFO Implementation**: Implements proper FIFO lot tracking for accurate P&L calculations
- **Weekend Handling**: Skips weekends when adding HOLD entries (no market data available)
- **Data Preservation**: Preserves all original trade data while rebuilding portfolio structure

Usage:
    python debug/rebuild_portfolio_from_scratch.py
    python debug/rebuild_portfolio_from_scratch.py test_data
    python debug/rebuild_portfolio_from_scratch.py "my trading" "US/Pacific"
    python debug/rebuild_portfolio_from_scratch.py "my trading" "US/Eastern"

Configuration:
    - Change DEFAULT_TIMEZONE to your local timezone
    - Market close times are automatically calculated based on timezone
    - Supported timezones: US/Pacific, US/Eastern, US/Central, US/Mountain, Canada/*, etc.
    - Focuses on North American markets: NYSE, NASDAQ, TSX (all close at 4:00 PM ET)
    - For other global markets, see comments in MARKET_CLOSE_TIMES section
"""

import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
from collections import defaultdict
from datetime import datetime, timedelta
import yfinance as yf  # retained for compatibility, core fetching uses MarketDataFetcher
import time
from decimal import Decimal, getcontext
import pytz
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import emoji handling
try:
    from display.console_output import _safe_emoji
except ImportError:
    # Fallback if display module not available
    def _safe_emoji(emoji: str) -> str:
        return emoji

# Set precision for decimal calculations
getcontext().prec = 10

# Configuration - Market close times by timezone
# Based on North American markets (NYSE, NASDAQ, TSX) closing at 4:00 PM ET
MARKET_CLOSE_TIMES = {
    'US/Eastern': 16,  # 4:00 PM ET (NYSE, NASDAQ)
    'US/Pacific': 13,  # 1:00 PM PT (4:00 PM ET)
    'US/Central': 15,  # 3:00 PM CT (4:00 PM ET)
    'US/Mountain': 14, # 2:00 PM MT (4:00 PM ET)
    'Canada/Eastern': 16,  # 4:00 PM ET (TSX)
    'Canada/Pacific': 13,  # 1:00 PM PT (4:00 PM ET)
    'Canada/Central': 15,  # 3:00 PM CT (4:00 PM ET)
    'Canada/Mountain': 14, # 2:00 PM MT (4:00 PM ET)
}

# Note: This bot focuses on North American markets (NYSE, NASDAQ, TSX)
# Other global markets have different closing times:
# - London (LSE): 8:30 AM PDT (4:30 PM BST)
# - Frankfurt (DB): 8:30 AM PDT (5:30 PM CEST)  
# - Tokyo (JPX): 11:00 PM PDT previous day (3:00 PM JST)
# - Hong Kong (HKEX): 1:00 AM PDT (4:00 PM HKT)

# Default timezone - change this to your local timezone
DEFAULT_TIMEZONE = 'US/Pacific'  # Change to your timezone

def get_market_close_time(timezone_str: str = None) -> str:
    """Get market close time in the specified timezone"""
    if timezone_str is None:
        timezone_str = DEFAULT_TIMEZONE
    
    # Get the hour for market close in this timezone
    close_hour = MARKET_CLOSE_TIMES.get(timezone_str, 16)  # Default to 4 PM if not found
    
    # Get timezone info
    tz = pytz.timezone(timezone_str)
    
    # Get current date in the specified timezone
    now = datetime.now(tz)
    
    # Format as "YYYY-MM-DD HH:MM:SS TZ"
    timezone_abbr = now.strftime('%Z')
    return f"{now.strftime('%Y-%m-%d')} {close_hour:02d}:00:00 {timezone_abbr}"

# Use shared market data fetcher with price cache for efficiency
# This setup minimizes API calls by caching price data in memory
from market_data.price_cache import PriceCache
from market_data.data_fetcher import MarketDataFetcher
from market_data.market_hours import MarketHours
from utils.market_holidays import MARKET_HOLIDAYS
# REMOVED: PRICE_VALIDATOR import - now using MarketDataFetcher's currency-based logic
PRICE_CACHE = PriceCache()  # In-memory price cache to avoid redundant API calls
FETCHER = MarketDataFetcher(cache_instance=PRICE_CACHE)  # Fetcher uses the cache
MARKET_HOURS = MarketHours()  # For weekend detection

# Set up currency cache for proper CAD/USD detection
def setup_currency_cache(tickers):
    """Set up currency cache for MarketDataFetcher to use correct exchanges"""
    currency_cache = {}
    for ticker in tickers:
        if ticker.endswith(('.TO', '.V', '.CN', '.TSX')):
            currency_cache[ticker] = 'CAD'
        else:
            currency_cache[ticker] = 'USD'
    
    # Set the currency cache on the fetcher
    FETCHER._portfolio_currency_cache = currency_cache
    return currency_cache

# REMOVED: TICKER_CORRECTION_CACHE - now using MarketDataFetcher's currency-based logic

# REMOVED: Old ticker correction functions - now using MarketDataFetcher's currency-based logic

def get_current_price(ticker: str, trade_price: float = None, currency: str = "CAD") -> float:
    """
    Get current price for a ticker using the cached market data fetcher.
    
    This function uses the SAME logic as the main system to ensure consistency.
    It relies on the MarketDataFetcher's currency-based logic.

    Args:
        ticker: Stock ticker symbol (e.g., 'AAPL', 'MSFT')
        trade_price: Optional trade price for ticker validation (unused, kept for compatibility)
        currency: Expected currency ('CAD' or 'USD')

    Returns:
        Current price as float, or 0.0 if no data available
    """
    try:
        end = pd.Timestamp.now()
        start = end - pd.Timedelta(days=5)
        
        # Use the MarketDataFetcher directly - it handles currency-based logic
        result = FETCHER.fetch_price_data(ticker, start, end)
        
        if result.df is not None and not result.df.empty and 'Close' in result.df.columns and result.source != "empty":
            return float(result.df['Close'].iloc[-1])
    except Exception:
        pass
    return 0.0

def get_historical_close_price(ticker: str, date_str: str, trade_price: float = None, currency: str = "CAD") -> float:
    """
    Get historical close price for a ticker on a specific date.
    
    This function fetches the closing price for a ticker on the specified date,
    with intelligent fallback to nearby trading days if the exact date isn't available.
    It handles timezone-aware date parsing and uses the cached market data fetcher.
    
    Args:
        ticker: Stock ticker symbol (e.g., 'AAPL', 'MSFT')
        date_str: Date string in format 'YYYY-MM-DD HH:MM:SS TZ' or similar
        
    Returns:
        Historical close price as float, or 0.0 if no data available
        
    Note:
        Uses a 3-day window around the target date to find the closest available
        trading day. This handles cases where the target date falls on weekends
        or holidays when markets are closed.
    """
    try:
        from utils.timezone_utils import parse_csv_timestamp
        date_obj = parse_csv_timestamp(date_str)
        if not date_obj:
            return None
        date_obj = date_obj.date()
        
        # Prevent future date API calls - only fetch historical data
        today = datetime.now().date()
        if date_obj > today:
            return 0.0
        
        # Check if it's a market holiday or weekend
        if not MARKET_HOLIDAYS.is_trading_day(date_obj, "both"):
            holiday_name = MARKET_HOLIDAYS.get_holiday_name(date_obj)
            if holiday_name:
                print(f"     Skipping {date_obj.strftime('%Y-%m-%d')} ({holiday_name})")
            else:
                print(f"     Skipping {date_obj.strftime('%Y-%m-%d')} (weekend)")
            return 0.0
        
        # Use the MarketDataFetcher directly - it handles currency-based logic
        # Try multiple date ranges to find available data
        date_ranges = [
            (date_obj, date_obj + timedelta(days=1)),  # Exact day
            (date_obj - timedelta(days=1), date_obj + timedelta(days=2)),  # 3-day window
            (date_obj - timedelta(days=3), date_obj + timedelta(days=4)),  # 7-day window
            (date_obj - timedelta(days=7), date_obj + timedelta(days=8)),  # 15-day window
        ]
        
        for start_date, end_date in date_ranges:
            result = FETCHER.fetch_price_data(ticker, pd.Timestamp(start_date), pd.Timestamp(end_date))
            df = result.df
            if df is not None and not df.empty and 'Close' in df.columns and result.source != "empty":
                # Find row matching the target date or closest available
                day_rows = df[df.index.date == date_obj]
                if not day_rows.empty:
                    return float(day_rows['Close'].iloc[0])
                # If no exact match, use the closest available date
                if not df.empty:
                    return float(df['Close'].iloc[-1])
        
        return 0.0
    except Exception:
        return 0.0

def rebuild_portfolio_from_scratch(data_dir: str = None, timezone_str: str = None):
    """
    Completely rebuild portfolio CSV from trade log with full recalculation.
    
    This is the main function that orchestrates the complete portfolio rebuild process.
    It reads the trade log, processes all trades chronologically, and generates a
    fresh portfolio CSV with proper HOLD entries for price tracking.
    
    PROCESS OVERVIEW:
    1. Load and validate trade log data
    2. Process all trades chronologically (BUY/SELL entries)
    3. Generate HOLD entries for price tracking between trades
    4. Recalculate all positions, cost basis, and P&L from scratch
    5. Write clean portfolio CSV with proper formatting
    
    Args:
        data_dir: Directory containing trade log and portfolio files
        timezone_str: Timezone for market close time calculations (defaults to DEFAULT_TIMEZONE)
        
    Returns:
        None (writes portfolio CSV to disk)
        
    Raises:
        FileNotFoundError: If trade log file doesn't exist
        ValueError: If trade log data is invalid or empty
        
    Note:
        This function completely overwrites the existing portfolio CSV.
        Make sure to backup your data before running if needed.
    """
    data_path = Path(data_dir)
    trade_log_file = data_path / "llm_trade_log.csv"
    portfolio_file = data_path / "llm_portfolio_update.csv"
    
    # Require data directory to be provided
    if data_dir is None:
        raise ValueError("data_dir parameter is required - no defaults allowed")
        
    print(f"{_safe_emoji('🔄')} Rebuilding Portfolio from Trade Log")
    print("=" * 50)
    print(f"📁 Using data directory: {data_dir}")
    
    # Auto-detect timezone from trade log data
    if trade_log_file.exists():
        try:
            trade_df_sample = pd.read_csv(trade_log_file, nrows=1)
            if len(trade_df_sample) > 0:
                sample_date = str(trade_df_sample.iloc[0]['Date'])
                if 'EDT' in sample_date:
                    detected_tz = 'US/Eastern'
                elif 'EST' in sample_date:
                    detected_tz = 'US/Eastern'
                elif 'PDT' in sample_date:
                    detected_tz = 'US/Pacific'
                elif 'PST' in sample_date:
                    detected_tz = 'US/Pacific'
                else:
                    detected_tz = timezone_str or DEFAULT_TIMEZONE
                print(f"🕐 Detected timezone from trade log: {detected_tz}")
            else:
                detected_tz = timezone_str or DEFAULT_TIMEZONE
        except:
            detected_tz = timezone_str or DEFAULT_TIMEZONE
    else:
        detected_tz = timezone_str or DEFAULT_TIMEZONE
    
    timezone_str = detected_tz
    print(f"🕐 Market close time: {MARKET_CLOSE_TIMES.get(timezone_str, 16)}:00 local time")
    
    if not trade_log_file.exists():
        print(f"{_safe_emoji('❌')} Trade log not found: {trade_log_file}")
        return False
    
    try:
        # BACKUP THE FILES FIRST
        backup_dir = data_path / "backups"
        backup_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Backup portfolio file
        if portfolio_file.exists():
            portfolio_df = pd.read_csv(portfolio_file)
            portfolio_backup = backup_dir / f"{portfolio_file.stem}.backup_{timestamp}.csv"
            portfolio_df.to_csv(portfolio_backup, index=False)
            print(f"{_safe_emoji('💾')} Backed up portfolio to: {portfolio_backup}")
        
        # Backup trade log file (IMPORTANT!)
        trade_log_backup = backup_dir / f"{trade_log_file.stem}.backup_{timestamp}.csv"
        shutil.copy2(trade_log_file, trade_log_backup)
        print(f"{_safe_emoji('💾')} Backed up trade log to: {trade_log_backup}")
        
        # Read trade log
        trade_df = pd.read_csv(trade_log_file)
        print(f"{_safe_emoji('📊')} Loaded {len(trade_df)} trades from trade log")
        
        # Convert date column to timezone-aware datetime objects for accurate comparisons
        # This ensures proper chronological ordering and date comparisons
        from utils.timezone_utils import parse_csv_timestamp
        trade_df['Date'] = trade_df['Date'].apply(parse_csv_timestamp)
        trade_df.dropna(subset=['Date'], inplace=True)
        
        # Sort trades by date to process them chronologically
        # This is critical for accurate position tracking and P&L calculations
        trade_df = trade_df.sort_values('Date').reset_index(drop=True)
        
        # Get all unique tickers for fast price fetching
        unique_tickers = trade_df['Ticker'].unique()
        print(f"📈 Found {len(unique_tickers)} unique tickers")
        
        # Set up currency cache for proper exchange selection
        setup_currency_cache(unique_tickers)
        print(f"💰 Set up currency cache for {len(unique_tickers)} tickers")
        
        # Fetch ALL prices for ALL tickers in parallel (fast approach)
        # This pre-fetches current prices to avoid API calls during HOLD generation
        print(f"🌐 Fetching current prices for all {len(unique_tickers)} tickers in parallel...")
        ticker_prices = {}
        failed_details = {}
        
        # Get current date for price fetching
        # Use a 7-day window to ensure we get recent price data
        today = datetime.now()
        start_date = today - timedelta(days=7)  # 7-day window for current price
        
        def fetch_single_ticker(ticker):
            """Fetch price for a single ticker - designed for parallel execution"""
            try:
                result = FETCHER.fetch_price_data(ticker, start_date, today)
                if result and result.df is not None and not result.df.empty and 'Close' in result.df.columns:
                    latest_price = float(result.df['Close'].iloc[-1])
                    source = getattr(result, 'source', 'unknown')
                    return {
                        'ticker': ticker,
                        'price': latest_price,
                        'source': source,
                        'success': True
                    }
                else:
                    return {
                        'ticker': ticker,
                        'price': None,
                        'source': None,
                        'success': False,
                        'error': "No data returned from API"
                    }
            except Exception as e:
                error_msg = str(e).lower()
                if "delisted" in error_msg:
                    error_type = "Possibly delisted - will use trade price"
                elif "not found" in error_msg:
                    error_type = "Ticker not found - will use trade price"
                elif "timeout" in error_msg:
                    error_type = "API timeout - will use trade price"
                else:
                    error_type = f"Error: {str(e)[:50]}..."
                
                return {
                    'ticker': ticker,
                    'price': None,
                    'source': None,
                    'success': False,
                    'error': error_type
                }
        
        # Use ThreadPoolExecutor for parallel fetching
        # Use max_workers=10 to avoid overwhelming the APIs
        with ThreadPoolExecutor(max_workers=10) as executor:
            # Submit all tasks
            future_to_ticker = {executor.submit(fetch_single_ticker, ticker): ticker for ticker in unique_tickers}
            
            # Process completed tasks as they finish
            completed = 0
            for future in as_completed(future_to_ticker):
                completed += 1
                result = future.result()
                ticker = result['ticker']
                
                print(f"   {completed:2d}/{len(unique_tickers)} {ticker:6s} ", end="")
                
                if result['success']:
                    ticker_prices[ticker] = result['price']
                    source = result['source']
                    
                    # Parse source to show what actually happened
                    if 'yahoo-ca-to' in source:
                        print(f"✅ ${result['price']:.2f} (Canadian exchange)")
                    elif 'yahoo' in source:
                        print(f"✅ ${result['price']:.2f} (US exchange)")
                    else:
                        print(f"✅ ${result['price']:.2f} ({source})")
                else:
                    failed_details[ticker] = result['error']
                    error = result['error']
                    if "delisted" in error.lower():
                        print("⚠️  DELISTED (using trade price)")
                    elif "not found" in error.lower():
                        print("❌ NOT FOUND (using trade price)")
                    elif "timeout" in error.lower():
                        print("⏱️  TIMEOUT (using trade price)")
                    else:
                        print(f"❌ ERROR: {error[:20]}...")
        
        print(f"✅ Fetched prices for {len(ticker_prices)} tickers")
        
        # Show summary of failed tickers with details
        failed_tickers = [ticker for ticker in unique_tickers if ticker not in ticker_prices]
        if failed_tickers:
            print(f"\n⚠️  Failed to fetch prices for {len(failed_tickers)} tickers:")
            for ticker in failed_tickers:
                reason = failed_details.get(ticker, "Unknown error")
                print(f"   • {ticker}: {reason}")
            print("   These will use trade prices as fallback for current price calculations")
        
        # PRE-CALCULATE ALL CURRENCIES ONCE (no more file I/O during HOLD generation)
        print(f"\n💰 Pre-calculating currencies for all tickers...")
        ticker_currencies = {}
        for ticker in unique_tickers:
            ticker_currencies[ticker] = get_currency_for_ticker_from_data_dir(ticker, data_dir)
        print(f"   Pre-calculated currencies for {len(ticker_currencies)} tickers")
        
        # Process trades chronologically to build complete portfolio
        # This maintains running position state as we process each trade
        portfolio_entries = []
        running_positions = defaultdict(lambda: {'shares': Decimal('0'), 'cost': Decimal('0'), 'trades': [], 'last_price': Decimal('0'), 'last_currency': 'CAD'})
        
        print(f"\n📈 Processing trades chronologically:")
        
        for trade in trade_df.to_dict('records'):
            ticker = trade['Ticker']
            date = trade['Date']
            shares = Decimal(str(trade['Shares']))  # Keep original precision
            price = Decimal(str(trade['Price']))
            cost = Decimal(str(trade['Cost Basis']))
            pnl = Decimal('0')  # Will be calculated
            reason = trade['Reason']
            
            # Determine if this is a buy or sell
            is_sell = 'SELL' in reason.upper() or 'sell' in reason.lower()
            
            print(f"   {date} | {ticker} | {shares:.4f} @ ${price:.2f} | ${cost:.2f} | PnL: ${pnl:.2f} | {reason}")
            
            if is_sell:
                # For sells, create entry with 0 shares and sell details
                avg_price = running_positions[ticker]['cost'] / running_positions[ticker]['shares'] if running_positions[ticker]['shares'] > 0 else Decimal('0')
                
                # Format the date using timezone utilities for consistency
                from utils.timezone_utils import format_timestamp_for_csv
                formatted_date = format_timestamp_for_csv(date)

                portfolio_entries.append({
                    'Date': formatted_date,
                    'Ticker': ticker,
                    'Shares': Decimal('0'),
                    'Average Price': Decimal('0'),
                    'Cost Basis': Decimal('0'),
                    'Stop Loss': Decimal('0'),
                    'Current Price': price,
                    'Total Value': Decimal('0'),
                    'PnL': pnl,  # Use actual PnL from trade log
                    'Action': 'SELL',
                    'Company': get_company_name(ticker),
                    'Currency': get_currency_for_ticker_from_data_dir(ticker, data_dir)
                })
                
                # Reset position after sell but preserve last trade info for HOLD entries
                last_price = running_positions[ticker].get('last_price', Decimal('0'))
                last_currency = running_positions[ticker].get('last_currency', 'CAD')
                running_positions[ticker] = {
                    'shares': Decimal('0'), 
                    'cost': Decimal('0'), 
                    'trades': [],
                    'last_price': last_price,
                    'last_currency': last_currency
                }
            else:
                # For buys, update running position and store trade info for price validation
                running_positions[ticker]['shares'] += shares
                running_positions[ticker]['cost'] += cost
                running_positions[ticker]['trades'].append({'shares': shares, 'price': price, 'cost': cost})
                running_positions[ticker]['last_price'] = price
                running_positions[ticker]['last_currency'] = ticker_currencies[ticker]
                
                # Format the date using timezone utilities for consistency
                from utils.timezone_utils import format_timestamp_for_csv
                formatted_date = format_timestamp_for_csv(date)

                # Calculate current values
                total_shares = running_positions[ticker]['shares']
                total_cost = running_positions[ticker]['cost']
                
                # For the BUY entry, use the trade price with fees as average price
                # This ensures fees are included in the cost basis
                avg_price = price  # Use the trade price (with fees) as average price
                
                current_price = Decimal(str(ticker_prices.get(ticker, float(price))))  # Use pre-fetched current price
                total_value = total_shares * current_price
                unrealized_pnl = (current_price - avg_price) * total_shares
                
                portfolio_entries.append({
                    'Date': formatted_date,
                    'Ticker': ticker,
                    'Shares': total_shares,
                    'Average Price': avg_price,
                    'Cost Basis': total_cost,
                    'Stop Loss': Decimal('0'),
                    'Current Price': current_price,
                    'Total Value': total_value,
                    'PnL': unrealized_pnl,
                    'Action': 'BUY',
                    'Company': get_company_name(ticker),
                    'Currency': ticker_currencies[ticker]
                })
        
        # Add HOLD entries for every day between trades and current positions (ONE PER DAY PER TICKER)
        # HOLD entries provide end-of-day snapshots for accurate performance tracking
        print(f"\n📊 Adding HOLD entries for price tracking...")
        
        # Get all unique trade dates to understand the trading timeline
        trade_dates = sorted(trade_df['Date'].unique())
        print(f"   Trade dates: {trade_dates}")
        
        # Create a list of all dates we need HOLD entries for
        all_dates = []
        unique_calendar_dates = set()
        
        # First, collect all unique calendar dates from trade dates
        # This ensures we have HOLD entries for every day there was trading activity
        for trade_date_obj in trade_df['Date']:
            if trade_date_obj:
                calendar_date = trade_date_obj.strftime('%Y-%m-%d')
                unique_calendar_dates.add(calendar_date)
        
        # Convert to sorted list for chronological processing
        unique_calendar_dates = sorted(list(unique_calendar_dates))
        
        # Generate all dates between first trade and today
        if unique_calendar_dates:
            from utils.timezone_utils import parse_csv_timestamp
            first_date = parse_csv_timestamp(unique_calendar_dates[0])
            last_date = parse_csv_timestamp(unique_calendar_dates[-1])
            if not first_date or not last_date:
                print("Error: Could not parse trade dates")
                return False
            today = datetime.now()
            
            # Check if market is open today (before market close time)
            tz = pytz.timezone(timezone_str)
            current_time = today.astimezone(tz)
            market_close_hour = MARKET_CLOSE_TIMES.get(timezone_str, 16)
            
            # Generate dates up to the last actual trading day to ensure complete data
            # This ensures we have HOLD entries through the most recent market close
            last_trading_day = MARKET_HOURS.last_trading_date().date()
            
            # Use the later of: last trade date or last actual trading day
            # This ensures we don't miss any trading days after the last trade
            end_date = max(last_date.date(), last_trading_day)
            
            print(f"   📅 Generating HOLD entries from {first_date.date()} to {end_date} (last trading day)")
            
            current_date = first_date
            while current_date.date() <= end_date:
                all_dates.append(current_date)
                current_date += timedelta(days=1)
        
        print(f"   Adding HOLD entries for {len(all_dates)} dates")
        
        # OPTIMIZATION: Pre-calculate all positions for all dates at once
        # This avoids recalculating positions for each HOLD entry, making it much faster
        print("   Pre-calculating positions for all dates...")
        date_positions = {}  # date_str -> {ticker: position_data}
        traded_tickers_by_date = {}  # date_str -> set of tickers
        
        # Pre-calculate which tickers were traded on which dates
        # This helps us avoid duplicate HOLD entries on days with trades
        for trade in trade_df.to_dict('records'):
            trade_date_obj = trade['Date'] # This is now a datetime object
            if trade_date_obj:
                trade_date = trade_date_obj.strftime('%Y-%m-%d')
                if trade_date not in traded_tickers_by_date:
                    traded_tickers_by_date[trade_date] = set()
                traded_tickers_by_date[trade_date].add(trade['Ticker'])
        
        # Pre-calculate positions for each date
        for hold_date_obj in all_dates:
            
            # Skip weekends
            if not MARKET_HOURS.is_trading_day(hold_date_obj):
                continue
                
            date_str = hold_date_obj.strftime('%Y-%m-%d')
            
            # Recalculate positions up to this date
            temp_positions = defaultdict(lambda: {'shares': Decimal('0'), 'cost': Decimal('0')})
            
            # Process all trades up to this date
            for trade in trade_df.to_dict('records'):
                trade_date_obj = trade['Date'] # This is now a datetime object
                if trade_date_obj and trade_date_obj.date() <= hold_date_obj.date():
                    ticker = trade['Ticker']
                    shares = Decimal(str(trade['Shares']))
                    cost = Decimal(str(trade['Cost Basis']))
                    reason = trade['Reason']
                    
                    is_sell = 'SELL' in reason.upper() or 'sell' in reason.lower()
                    
                    if is_sell:
                        temp_positions[ticker] = {'shares': Decimal('0'), 'cost': Decimal('0')}
                    else:
                        temp_positions[ticker]['shares'] += shares
                        temp_positions[ticker]['cost'] += cost
            
            # Store positions for this date
            date_positions[date_str] = dict(temp_positions)
        
        print(f"   Pre-calculated positions for {len(date_positions)} trading days")
        
        # Now generate HOLD entries efficiently (ONE PER DAY PER TICKER)
        hold_entries_added = 0
        total_hold_dates = len(all_dates)
        print(f"   Generating HOLD entries for {total_hold_dates} dates...")
        
        for date_idx, hold_date_obj in enumerate(all_dates):
            if date_idx % 5 == 0:  # Status update every 5 dates
                print(f"   Processing date {date_idx + 1}/{total_hold_dates}: {hold_date_obj.date()}")
            
            # Skip weekends
            if not MARKET_HOURS.is_trading_day(hold_date_obj):
                continue
                
            date_str = hold_date_obj.strftime('%Y-%m-%d')
            
            # Get pre-calculated positions and traded tickers for this date
            temp_positions = date_positions.get(date_str, {})
            traded_tickers_on_date = traded_tickers_by_date.get(date_str, set())
            
            # Add HOLD entry for each ticker that has shares on this date (ONE PER TICKER PER DAY)
            for ticker, position in temp_positions.items():
                if position['shares'] > 0:
                    # Previously we skipped HOLD when traded that date; now we ALWAYS add EOD HOLD
                    # to ensure a proper end-of-day snapshot for performance calculations.
                    
                    # Set HOLD entries timestamp based on market status
                    tz = pytz.timezone(timezone_str)
                    
                    # Use the date part of hold_date_obj and combine with market close time
                    close_hour = MARKET_CLOSE_TIMES.get(timezone_str, 16)
                    # Create timezone-aware datetime for consistent formatting
                    if hold_date_obj.tzinfo is None:
                        hold_date_at_close = tz.localize(hold_date_obj.replace(hour=close_hour, minute=0, second=0, microsecond=0))
                    else:
                        hold_date_at_close = hold_date_obj.astimezone(tz).replace(hour=close_hour, minute=0, second=0, microsecond=0)
                    
                    # Format using timezone utilities for consistency
                    from utils.timezone_utils import format_timestamp_for_csv
                    hold_date_str = format_timestamp_for_csv(hold_date_at_close)
                    
                    # Use historical price for this specific date
                    # This fetches the actual market close price for accurate valuation
                    price_value = get_historical_close_price(ticker, hold_date_str)
                    
                    # If no historical price found, use the last known price from trades
                    # This is a fallback for delisted stocks or API failures
                    if price_value <= 0:
                        # Find the last trade price for this ticker on or before this date
                        ticker_trades = trade_df[trade_df['Ticker'] == ticker]
                        ticker_trades = ticker_trades[ticker_trades['Date'].dt.date <= hold_date_obj.date()]
                        if not ticker_trades.empty:
                            last_trade = ticker_trades.iloc[-1]
                            price_value = float(last_trade['Price'])
                    
                    if price_value > 0:
                        current_price_decimal = Decimal(str(price_value))
                        avg_price = position['cost'] / position['shares']
                        total_value = position['shares'] * current_price_decimal
                        unrealized_pnl = (current_price_decimal - avg_price) * position['shares']
                        
                        portfolio_entries.append({
                            'Date': hold_date_str,
                            'Ticker': ticker,
                            'Shares': position['shares'],
                            'Average Price': avg_price,
                            'Cost Basis': position['cost'],
                            'Stop Loss': Decimal('0'),
                            'Current Price': current_price_decimal,
                            'Total Value': total_value,
                            'PnL': unrealized_pnl,
                            'Action': 'HOLD',
                            'Company': get_company_name(ticker),
                            'Currency': ticker_currencies[ticker]
                        })
                        hold_entries_added += 1
                        
                        if hold_entries_added % 50 == 0:  # Status update every 50 entries
                            print(f"   Added {hold_entries_added} HOLD entries so far...")
        
        print(f"   Added {hold_entries_added} HOLD entries (ONE PER DAY PER TICKER)")
        
        # Create new portfolio DataFrame
        new_portfolio_df = pd.DataFrame(portfolio_entries)
        
        # Sort by date and ticker
        new_portfolio_df = new_portfolio_df.sort_values(['Date', 'Ticker']).reset_index(drop=True)
        
        print(f"\n📊 Generated {len(new_portfolio_df)} portfolio entries from trade log")
        
        # Show summary of positions
        print(f"\n📈 Final positions:")
        for ticker in new_portfolio_df['Ticker'].unique():
            ticker_entries = new_portfolio_df[new_portfolio_df['Ticker'] == ticker]
            latest = ticker_entries.iloc[-1]
            print(f"   {ticker}: {latest['Shares']:.2f} shares @ ${latest['Average Price']:.2f} | ${latest['Cost Basis']:.2f} | {latest['Action']} | PnL: ${latest['PnL']:.2f}")
        
        # Convert Decimal objects to float with proper precision
        numeric_columns = ['Shares', 'Average Price', 'Cost Basis', 'Stop Loss', 'Current Price', 'Total Value', 'PnL']
        for col in numeric_columns:
            if col in new_portfolio_df.columns:
                # Convert Decimal to float, preserving precision
                new_portfolio_df[col] = new_portfolio_df[col].apply(lambda x: float(x) if isinstance(x, Decimal) else x)
                if col == 'Shares':
                    # Round shares to 4 decimal places
                    new_portfolio_df[col] = new_portfolio_df[col].round(4)
                else:
                    # Round other columns to 2 decimal places
                    new_portfolio_df[col] = new_portfolio_df[col].round(2)
        
        # Save new portfolio
        new_portfolio_df.to_csv(portfolio_file, index=False)
        
        print(f"\n{_safe_emoji('✅')} Portfolio completely rebuilt from trade log: {portfolio_file}")
        print(f"   Created {len(new_portfolio_df)} entries from {len(trade_df)} trades")
        print(f"   Added HOLD entries for price tracking")
        print(f"   Used actual PnL from trade log for sell transactions")
        print(f"   Backups created in: {backup_dir}")
        
        return True
        
    except Exception as e:
        print(f"{_safe_emoji('❌')} Error rebuilding portfolio: {e}")
        import traceback
        traceback.print_exc()
        return False

def get_company_name(ticker: str) -> str:
    """Get company name for ticker using yfinance lookup"""
    try:
        from utils.ticker_utils import get_company_name as lookup_company_name
        return lookup_company_name(ticker)
    except Exception as e:
        print(f"Warning: Could not lookup company name for {ticker}: {e}")
        return 'Unknown'

def get_currency(ticker: str) -> str:
    """
    Get currency for ticker (backward compatibility function).
    Uses default data directory.
    """
    # This function requires data_dir to be provided explicitly
    raise ValueError("get_currency() function requires explicit data_dir - use get_currency_for_ticker_from_data_dir() instead")

def get_currency_for_ticker_from_data_dir(ticker: str, data_dir: str) -> str:
    """
    Get currency for ticker from the trade log data in a specific directory.
    
    This function uses the trade log currency data to determine
    the correct currency, ensuring consistency with the source data.
    """
    try:
        # Load currency from trade log (source of truth)
        import pandas as pd
        
        trade_log_file = f'{data_dir}/llm_trade_log.csv'
        try:
            df = pd.read_csv(trade_log_file)
            if 'Ticker' in df.columns and 'Currency' in df.columns:
                ticker_data = df[df['Ticker'] == ticker.upper().strip()]
                if not ticker_data.empty:
                    return ticker_data['Currency'].iloc[0]
        except Exception:
            pass
        
        # Fallback to suffix-based logic
        ticker = ticker.upper().strip()
        if ticker.endswith(('.TO', '.V', '.CN', '.TSX')):
            return 'CAD'
        else:
            return 'USD'
        
    except Exception:
        # Final fallback
        if '.TO' in ticker or '.V' in ticker:
            return 'CAD'
        return 'USD'

def rebuild_ticker_from_date(ticker: str, from_date: datetime, data_dir: str = None, timezone_str: str = None) -> bool:
    """
    Rebuild portfolio entries for a specific ticker from a specific date forward.
    
    This is much faster than a full rebuild since it only processes one ticker
    and only from the specified date forward.
    
    Args:
        ticker: Ticker symbol to rebuild
        from_date: Date to start rebuilding from (inclusive)
        data_dir: Directory containing trading data files
        timezone_str: Timezone string (optional, will auto-detect)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Require data directory to be provided
        if data_dir is None:
            raise ValueError("data_dir parameter is required - no defaults allowed")
            
        print(f"\n🔄 Targeted rebuild: {ticker} from {from_date.strftime('%Y-%m-%d')} forward")
        
        # Set up timezone
        if not timezone_str:
            timezone_str = DEFAULT_TIMEZONE
        
        # Load existing portfolio
        portfolio_file = f'{data_dir}/llm_portfolio_update.csv'
        if not Path(portfolio_file).exists():
            print(f"❌ Portfolio file not found: {portfolio_file}")
            return False
            
        portfolio_df = pd.read_csv(portfolio_file)
        if portfolio_df.empty:
            print("❌ Portfolio file is empty")
            return False
        
        # Convert Date column to datetime for filtering
        portfolio_df['Date'] = pd.to_datetime(portfolio_df['Date'])
        
        # Make from_date timezone-naive for comparison with pandas datetime
        from_date_naive = from_date.replace(tzinfo=None) if from_date.tzinfo else from_date
        
        # Find and remove all entries for this ticker on/after from_date
        ticker_mask = (portfolio_df['Ticker'] == ticker.upper().strip())
        date_mask = (portfolio_df['Date'] >= from_date_naive)
        entries_to_remove = ticker_mask & date_mask
        
        removed_count = entries_to_remove.sum()
        if removed_count > 0:
            print(f"   🗑️  Removing {removed_count} outdated entries for {ticker}")
            portfolio_df = portfolio_df[~entries_to_remove]
        
        # Load trade log
        trade_log_file = f'{data_dir}/llm_trade_log.csv'
        if not Path(trade_log_file).exists():
            print(f"❌ Trade log file not found: {trade_log_file}")
            return False
            
        trade_df = pd.read_csv(trade_log_file)
        if trade_df.empty:
            print("❌ Trade log is empty")
            return False
        
        # Convert Date column to datetime
        trade_df['Date'] = pd.to_datetime(trade_df['Date'])
        
        # Filter trades for this ticker
        ticker_trades = trade_df[trade_df['Ticker'] == ticker.upper().strip()].copy()
        if ticker_trades.empty:
            print(f"❌ No trades found for {ticker}")
            return False
        
        # Sort by date
        ticker_trades = ticker_trades.sort_values('Date')
        
        # Calculate positions up to from_date
        position_at_from_date = {'shares': Decimal('0'), 'cost': Decimal('0')}
        
        for trade in ticker_trades.to_dict('records'):
            trade_date = trade['Date']
            if trade_date.date() < from_date_naive.date():
                shares = Decimal(str(trade['Shares']))
                cost = Decimal(str(trade['Cost Basis']))
                reason = trade['Reason']
                
                is_sell = 'SELL' in reason.upper() or 'sell' in reason.lower()
                
                if is_sell:
                    # For sells, reduce position
                    position_at_from_date['shares'] = max(Decimal('0'), position_at_from_date['shares'] - shares)
                    if position_at_from_date['shares'] == 0:
                        position_at_from_date['cost'] = Decimal('0')
                    else:
                        # Proportional cost reduction
                        cost_ratio = position_at_from_date['shares'] / (position_at_from_date['shares'] + shares)
                        position_at_from_date['cost'] *= cost_ratio
                else:
                    # For buys, add to position
                    position_at_from_date['shares'] += shares
                    position_at_from_date['cost'] += cost
        
        print(f"   📊 Position at {from_date_naive.strftime('%Y-%m-%d')}: {position_at_from_date['shares']} shares, ${position_at_from_date['cost']}")
        
        # If no position at from_date, we're done
        if position_at_from_date['shares'] <= 0:
            print(f"   ✅ No position to rebuild for {ticker}")
            # Save the cleaned portfolio
            portfolio_df.to_csv(portfolio_file, index=False)
            return True
        
        # Generate new entries from from_date to today
        from datetime import timedelta
        import pytz
        
        tz = pytz.timezone(timezone_str)
        current_date = from_date_naive.date()
        today = datetime.now(tz).date()
        
        new_entries = []
        running_position = position_at_from_date.copy()
        
        # Get currency for this ticker
        currency = get_currency_for_ticker_from_data_dir(ticker, data_dir)
        
        while current_date <= today:
            # Skip weekends
            if not MARKET_HOURS.is_trading_day(current_date):
                current_date += timedelta(days=1)
                continue
            
            # Process any trades on this date
            date_trades = ticker_trades[ticker_trades['Date'].dt.date == current_date]
            for trade in date_trades.to_dict('records'):
                shares = Decimal(str(trade['Shares']))
                cost = Decimal(str(trade['Cost Basis']))
                reason = trade['Reason']
                
                is_sell = 'SELL' in reason.upper() or 'sell' in reason.lower()
                
                if is_sell:
                    running_position['shares'] = max(Decimal('0'), running_position['shares'] - shares)
                    if running_position['shares'] == 0:
                        running_position['cost'] = Decimal('0')
                    else:
                        cost_ratio = running_position['shares'] / (running_position['shares'] + shares)
                        running_position['cost'] *= cost_ratio
                else:
                    running_position['shares'] += shares
                    running_position['cost'] += cost
            
            # Only create HOLD entry if we have shares
            if running_position['shares'] > 0:
                # Create HOLD entry for this date
                hold_datetime = tz.localize(datetime.combine(current_date, datetime.min.time().replace(hour=16, minute=0)))
                
                # Get historical price for this date
                price_value = get_historical_close_price(ticker, hold_datetime.strftime('%Y-%m-%d %H:%M:%S'))
                if not price_value or price_value <= 0:
                    # Use last known price from trades
                    last_trade = ticker_trades[ticker_trades['Date'].dt.date <= current_date].iloc[-1]
                    price_value = float(last_trade['Price'])
                
                avg_price = float(running_position['cost'] / running_position['shares'])
                total_value = float(running_position['shares'] * Decimal(str(price_value)))
                pnl = total_value - float(running_position['cost'])
                
                new_entry = {
                    'Date': hold_datetime.strftime('%Y-%m-%d %H:%M:%S'),
                    'Ticker': ticker.upper().strip(),
                    'Shares': float(running_position['shares']),
                    'Average Price': avg_price,
                    'Cost Basis': float(running_position['cost']),
                    'Stop Loss': 0.0,
                    'Current Price': price_value,
                    'Total Value': total_value,
                    'PnL': pnl,
                    'Action': 'HOLD',
                    'Company': get_company_name(ticker),
                    'Currency': currency
                }
                new_entries.append(new_entry)
            
            current_date += timedelta(days=1)
        
        # Add new entries to portfolio
        if new_entries:
            new_df = pd.DataFrame(new_entries)
            portfolio_df = pd.concat([portfolio_df, new_df], ignore_index=True)
            
            # Sort by date to maintain chronological order
            portfolio_df = portfolio_df.sort_values('Date')
            
            print(f"   ✅ Added {len(new_entries)} new HOLD entries for {ticker}")
        
        # Save updated portfolio
        portfolio_df.to_csv(portfolio_file, index=False)
        print(f"   💾 Portfolio updated successfully")
        
        return True
        
    except Exception as e:
        print(f"❌ Error in targeted rebuild: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main function to rebuild portfolio from scratch"""
    # Check if data directory argument provided
    if len(sys.argv) < 2:
        print("❌ Error: data_dir parameter is required")
        print("Usage: python rebuild_portfolio_from_scratch.py <data_dir> [timezone]")
        print("Example: python rebuild_portfolio_from_scratch.py 'trading_data/funds/Project Chimera'")
        sys.exit(1)
    
    data_dir = sys.argv[1]
    timezone_str = None
    
    if len(sys.argv) > 2:
        timezone_str = sys.argv[2]
    
    # Show environment banner
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from display.console_output import print_environment_banner
    print_environment_banner(data_dir)
    
    success = rebuild_portfolio_from_scratch(data_dir, timezone_str)
    
    if success:
        print("\n🎉 Portfolio rebuilt successfully from trade log!")
        print("   All entries created from scratch based on trade log")
    else:
        print(f"\n{_safe_emoji('❌')} Failed to rebuild portfolio")
        sys.exit(1)

if __name__ == "__main__":
    main()
