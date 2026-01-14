#!/usr/bin/env python3
"""
Streamlit utilities for fetching data from Supabase
"""

import os
from datetime import datetime
from typing import Dict, List, Optional, Any
import pandas as pd
import numpy as np
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

try:
    from supabase_client import SupabaseClient
    from auth_utils import get_user_token
    from log_handler import log_execution_time
    from exchange_rates_utils import reload_exchange_rate_for_date
    import streamlit as st
except ImportError:
    # Fallback if supabase_client not available
    SupabaseClient = None
    get_user_token = None
    log_execution_time = lambda x=None: lambda f: f # No-op decorator fallback
    reload_exchange_rate_for_date = None
    st = None

# ============================================================
# CACHE VERSION - Auto-derived from BUILD_TIMESTAMP (set by Woodpecker CI)
# Every deployment gets a new cache version, automatically invalidating stale data
# Falls back to app startup time if BUILD_TIMESTAMP not set
# ============================================================
_startup_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
CACHE_VERSION = os.getenv("BUILD_TIMESTAMP", _startup_timestamp)

# ============================================================
# CURRENCY REGISTRY - Extensible currency support
# ============================================================
SUPPORTED_CURRENCIES = {
    'CAD': 'Canadian Dollar',
    'USD': 'US Dollar',
    # Future currencies can be added here:
    # 'EUR': 'Euro',
    # 'GBP': 'British Pound',
    # 'JPY': 'Japanese Yen',
}


def get_supported_currencies() -> Dict[str, str]:
    """Get dictionary of supported currencies.
    
    Returns:
        Dictionary mapping currency codes to display names
    """
    return SUPPORTED_CURRENCIES.copy()


def get_user_display_currency() -> str:
    """Get user's preferred display currency.
    
    Returns:
        Currency code (default: 'CAD')
    """
    try:
        from user_preferences import get_user_currency
        currency = get_user_currency()
        return currency if currency else 'CAD'
    except ImportError:
        return 'CAD'


def get_exchange_rate_for_display(from_currency: str, to_currency: str, date: Optional[datetime] = None) -> Optional[float]:
    """Get exchange rate for converting from one currency to display currency.
    
    Handles both directions and attempts inverse rate if direct rate not available.
    
    Args:
        from_currency: Source currency code
        to_currency: Target currency code (display currency)
        date: Optional date for historical rates (uses latest if None)
        
    Returns:
        Exchange rate as float, or None if not available
    """
    if from_currency == to_currency:
        return 1.0
    
    client = get_supabase_client()
    if not client:
        return None
    
    try:
        # Try to get direct rate
        if date is None:
            rate = client.get_latest_exchange_rate(from_currency, to_currency)
        else:
            rate = client.get_exchange_rate(date, from_currency, to_currency)
        
        if rate is not None:
            return float(rate)
        
        # Try inverse rate (1 / reverse rate)
        if date is None:
            inverse_rate = client.get_latest_exchange_rate(to_currency, from_currency)
        else:
            inverse_rate = client.get_exchange_rate(date, to_currency, from_currency)
        
        if inverse_rate is not None and inverse_rate != 0:
            return 1.0 / float(inverse_rate)
        
        return None
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Error getting exchange rate {from_currency}→{to_currency}: {e}")
        return None


def convert_to_display_currency(value: float, from_currency: str, date: Optional[datetime] = None, display_currency: Optional[str] = None) -> float:
    """Convert a value from one currency to the user's display currency.
    
    Args:
        value: Value to convert
        from_currency: Source currency code
        date: Optional date for historical rates (uses latest if None)
        display_currency: Optional display currency (uses user preference if None)
        
    Returns:
        Converted value in display currency
    """
    if display_currency is None:
        display_currency = get_user_display_currency()
    
    # Same currency, no conversion needed
    if from_currency.upper() == display_currency.upper():
        return value
    
    # Get exchange rate
    rate = get_exchange_rate_for_display(from_currency, display_currency, date)
    
    if rate is None:
        # Fallback: use default rates for common pairs
        if from_currency.upper() == 'USD' and display_currency.upper() == 'CAD':
            rate = 1.35
        elif from_currency.upper() == 'CAD' and display_currency.upper() == 'USD':
            rate = 1.0 / 1.35
        else:
            # Unknown pair, return value as-is with warning
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"No exchange rate found for {from_currency}→{display_currency}, returning original value")
            return value
    
    return value * float(rate)


@st.cache_data(ttl=3600)  # Cache for 1 hour - exchange rates are relatively stable
def fetch_latest_rates_bulk(currencies: List[str], target_currency: str) -> Dict[str, float]:
    """
    Fetch latest exchange rates for a list of currencies to the target currency in one go.
    Returns a dictionary: {currency_code: rate}
    """
    if not currencies:
        return {}
        
    # unique currencies, upper case, remove target currency if present
    unique_currencies = list(set([str(c).upper() for c in currencies if c and str(c).upper() != target_currency.upper()]))
    
    if not unique_currencies:
        return {}

    client = get_supabase_client()
    if not client:
        # Fallback constants
        return {c: 1.0 for c in unique_currencies}
        
    try:
        # Simplest robust valid approach: Fetch all rates involving these currencies from the last 30 days
        # and pick the latest one in Python.
        import datetime
        thirty_days_ago = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime('%Y-%m-%d')
        
        response = client.supabase.table('exchange_rates').select('*') \
            .gte('timestamp', thirty_days_ago) \
            .execute()
            
        if not response.data:
            return {}
            
        # Process in python to find latest rate for each
        latest_rates = {} # (from, to) -> (timestamp, rate)
        
        for row in response.data:
            fc = row['from_currency'].upper()
            tc = row['to_currency'].upper()
            ts = row['timestamp']
            r = float(row['rate'])
            
            key = (fc, tc)
            if key not in latest_rates or ts > latest_rates[key][0]:
                latest_rates[key] = (ts, r)
                
        # Build result dict
        result = {}
        target = target_currency.upper()
        
        for curr in unique_currencies:
            curr = curr.upper()
            rate = None
            
            # Try direct: curr -> target
            if (curr, target) in latest_rates:
                rate = latest_rates[(curr, target)][1]
            
            # Try inverse: target -> curr
            elif (target, curr) in latest_rates:
                inv_rate = latest_rates[(target, curr)][1]
                if inv_rate != 0:
                    rate = 1.0 / inv_rate
            
            # Defaults
            if rate is None:
                if curr == 'USD' and target == 'CAD':
                    result[curr] = 1.35
                elif curr == 'CAD' and target == 'USD':
                    result[curr] = 1.0 / 1.35
                else:
                    result[curr] = 1.0
            else:
                result[curr] = rate
                
        return result

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error in fetch_latest_rates_bulk: {e}")
        # Return defaults
        res = {}
        for c in unique_currencies:
            if c == 'USD' and target_currency == 'CAD': res[c] = 1.35
            elif c == 'CAD' and target_currency == 'USD': res[c] = 1.0 / 1.35
            else: res[c] = 1.0
        return res


def get_cache_ttl() -> int:
    """Get cache TTL based on market hours.
    
    Returns:
        Cache TTL in seconds:
        - 300s (5 min) during market hours (9:30 AM - 4:00 PM EST, Mon-Fri)
        - 3600s (1 hour) after market close
    """
    from datetime import datetime
    try:
        import pytz
        est = pytz.timezone('America/New_York')
        now = datetime.now(est)
    except ImportError:
        # Fallback if pytz not available - use zoneinfo (Python 3.9+)
        from zoneinfo import ZoneInfo
        est = ZoneInfo('America/New_York')
        now = datetime.now(est)
    
    # Weekend: cache for 1 hour
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return 3600
    
    # Market hours: 9:30 AM - 4:00 PM EST
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    
    if market_open <= now <= market_close:
        return 300  # 5 minutes during market hours
    else:
        return 3600  # 1 hour outside market hours


def get_supabase_client(user_token: Optional[str] = None) -> Optional[SupabaseClient]:
    """Get Supabase client instance with user authentication
    
    Args:
        user_token: Optional JWT token from authenticated user. If None, tries to get from session.
                   Uses publishable key as fallback (may not work with RLS enabled).
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Check if SupabaseClient class is available
    if SupabaseClient is None:
        logger.error("SupabaseClient class is not available - import failed")
        print("ERROR: SupabaseClient import failed. Check that supabase_client.py exists and dependencies are installed.")
        return None
    
    try:
        # 1. Try to get user token if not provided
        refresh_token = None
        if user_token is None:
            # A. Try Flask context (cookies)
            try:
                from flask import request
                if request:
                    from flask_auth_utils import get_auth_token, get_refresh_token
                    user_token = get_auth_token()
                    # refresh_token = get_refresh_token() # DISABLED to prevent auto-refresh loops in Flask
                    if user_token:
                        logger.debug(f"[AUTH] Found token in Flask context (length: {len(user_token)})")
            except (ImportError, RuntimeError):
                # RuntimeError occurs if we're not in a Flask context (no request)
                pass
            
            # B. Try Streamlit context (via get_user_token)
            if not user_token and get_user_token:
                user_token = get_user_token()
                if user_token:
                    logger.debug(f"[AUTH] Found token in Streamlit context (length: {len(user_token)})")
        
        # Use tokens if available (respects RLS)
        client = SupabaseClient(user_token=user_token, refresh_token=refresh_token)
        
        # Validate client was created successfully
        if client is None:
            logger.error("SupabaseClient() returned None")
            print("ERROR: SupabaseClient initialization returned None")
            return None
        
        # Validate required attributes
        if not hasattr(client, 'supabase') or client.supabase is None:
            logger.error("SupabaseClient created but 'supabase' attribute is None")
            print("ERROR: SupabaseClient.supabase is None after initialization")
            return None
        
        return client
        
    except Exception as e:
        logger.error(f"Exception initializing Supabase client: {e}", exc_info=True)
        print(f"ERROR: Failed to initialize Supabase client: {e}")
        print("Check that SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY environment variables are set.")
        return None


@log_execution_time()
def render_sidebar_fund_selector(label: str = "Select Fund", key: str = "fund_selector", help_text: Optional[str] = None) -> Optional[str]:
    """Render a standardized fund selector in the sidebar.
    
    This function provides a consistent fund selector across all pages that:
    - Uses the user's saved fund preference
    - Automatically saves the preference when changed
    - Falls back to first available fund if preference doesn't exist
    
    Args:
        label: Label for the selectbox (default: "Select Fund")
        key: Unique key for the selectbox widget (default: "fund_selector")
        help_text: Optional help text to display
        
    Returns:
        Selected fund name, or None if no funds available
    """
    if st is None:
        return None
    
    try:
        from user_preferences import get_user_selected_fund, set_user_selected_fund
        
        funds = get_available_funds()
        if not funds:
            st.sidebar.warning("⚠️ No funds found in database")
            return None
        
        # Load saved fund preference
        saved_fund = get_user_selected_fund()
        
        # Determine initial fund index
        # Prefer saved fund if it exists in the list, otherwise default to first fund
        if saved_fund and saved_fund in funds:
            initial_index = funds.index(saved_fund)
        else:
            initial_index = 0
        
        selected_fund = st.sidebar.selectbox(
            label,
            funds,
            index=initial_index,
            key=key,
            help=help_text
        )
        
        # Save fund preference when it changes
        if selected_fund != saved_fund:
            set_user_selected_fund(selected_fund)
        
        return selected_fund
        
    except Exception as e:
        st.sidebar.error(f"❌ Error loading funds: {e}")
        return None


def get_available_funds() -> List[str]:
    """Get list of available funds from Supabase
    
    Queries user_funds table to get funds assigned to the authenticated user.
    Returns a sorted list of unique fund names.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    client = get_supabase_client()
    if not client:
        logger.warning("get_available_funds(): Failed to initialize Supabase client")
        return []
    
    # Get user ID for querying user_funds table
    try:
        from auth_utils import get_user_id
        user_id = get_user_id()
        if not user_id:
            logger.debug("get_available_funds(): No user_id available in session")
            return []
    except Exception as e:
        logger.warning(f"get_available_funds(): Could not get user ID: {e}")
        return []
    
    try:
        # WE MUST PAGINATE - Supabase has a hard limit of 1000 rows per request
        all_rows = []
        batch_size = 1000
        offset = 0
        
        while True:
            query = client.supabase.table("user_funds").select("fund_name").eq("user_id", user_id)
            
            result = query.range(offset, offset + batch_size - 1).execute()
            
            if not result or not result.data:
                break
            
            all_rows.extend(result.data)
            
            # If we got fewer rows than batch_size, we're done
            if len(result.data) < batch_size:
                break
            
            offset += batch_size
            
            # Safety break to prevent infinite loops
            if offset > 50000:
                print("Warning: Reached 50,000 row safety limit in get_available_funds pagination")
                break
        
        if not all_rows:
            logger.debug(f"get_available_funds(): Query returned no data for user_id: {user_id}")
            return []
        
        funds = [row.get('fund_name') for row in all_rows if row.get('fund_name')]
        sorted_funds = sorted(funds)
        logger.debug(f"get_available_funds(): Found {len(sorted_funds)} funds for user_id: {user_id}")
        return sorted_funds
    except Exception as e:
        logger.error(f"get_available_funds(): Error querying user_funds: {e}", exc_info=True)
        return []


@log_execution_time()
@st.cache_data(ttl=300)
def get_current_positions(fund: Optional[str] = None, _cache_version: str = CACHE_VERSION) -> pd.DataFrame:
    """Get current portfolio positions as DataFrame.
    
    CACHED: 5 min TTL. Bump CACHE_VERSION to force immediate invalidation.
    """
    import logging
    logger = logging.getLogger(__name__)
    if fund:
        logger.info(f"Loading current positions for fund: {fund}")
    
    client = get_supabase_client()
    if not client:
        return pd.DataFrame()
    
    try:
        # WE MUST PAGINATE - Supabase has a hard limit of 1000 rows per request
        all_rows = []
        batch_size = 1000
        offset = 0
        
        while True:
            # Join with securities table to get sector, industry, market_cap, country for filtering
            query = client.supabase.table("latest_positions").select(
                "*, securities(company_name, sector, industry, market_cap, country, trailing_pe, dividend_yield, fifty_two_week_high, fifty_two_week_low, last_updated)"
            )
            if fund:
                query = query.eq("fund", fund)
            
            result = query.range(offset, offset + batch_size - 1).execute()
            
            if not result.data:
                break
            
            all_rows.extend(result.data)
            
            # If we got fewer rows than batch_size, we're done
            if len(result.data) < batch_size:
                break
            
            offset += batch_size
            
            # Safety break to prevent infinite loops
            if offset > 50000:
                print("Warning: Reached 50,000 row safety limit in get_current_positions pagination")
                break
        
        if all_rows:
            return pd.DataFrame(all_rows)
        return pd.DataFrame()
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting positions: {e}", exc_info=True)
        return pd.DataFrame()


@log_execution_time()
@st.cache_data(ttl=None)  # Cache forever - historical trades don't change
def get_trade_log(limit: int = 1000, fund: Optional[str] = None, _cache_version: str = CACHE_VERSION) -> pd.DataFrame:
    """Get trade log entries as DataFrame with company names from securities table.
    
    CACHED: Permanently. Bump CACHE_VERSION to invalidate after bug fixes.
    """
    import logging
    logger = logging.getLogger(__name__)
    if fund:
        logger.info(f"Loading trade log for fund: {fund}")
    
    client = get_supabase_client()
    if not client:
        return pd.DataFrame()
    
    try:
        # Use client.get_trade_log() which joins with securities table for company names
        result = client.get_trade_log(limit=limit, fund=fund)
        
        if result:
            df = pd.DataFrame(result)
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
            return df
        return pd.DataFrame()
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting trade log: {e}", exc_info=True)
        return pd.DataFrame()



@log_execution_time()
@st.cache_data(ttl=300)
def get_realized_pnl(fund: Optional[str] = None, display_currency: Optional[str] = None, _cache_version: str = CACHE_VERSION) -> Dict[str, Any]:
    """Calculate realized P&L from closed positions (SELL trades).
    
    Args:
        fund: Optional fund name to filter by
        display_currency: Optional display currency (defaults to user preference)
        _cache_version: Cache version for invalidation
        
    Returns:
        Dictionary with (matching console app's get_realized_pnl_summary() structure):
        - total_realized_pnl: Total realized P&L in display currency
        - total_shares_sold: Total shares sold across all closed positions
        - total_proceeds: Total proceeds from all sales in display currency
        - average_sell_price: Average sell price per share in display currency
        - num_closed_trades: Number of closed trades (sell transactions)
        - winning_trades: Number of winning trades (positive P&L)
        - losing_trades: Number of losing trades (negative P&L)
        - trades_by_ticker: Dictionary with ticker breakdown (realized_pnl, shares_sold, proceeds)
    """
    if display_currency is None:
        display_currency = get_user_display_currency()
    
    client = get_supabase_client()
    if not client:
        return {
            'total_realized_pnl': 0.0,
            'total_shares_sold': 0.0,
            'total_proceeds': 0.0,
            'average_sell_price': 0.0,
            'num_closed_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'trades_by_ticker': {}
        }
    
    try:
        import logging
        logger = logging.getLogger(__name__)
        
        # Get all trades, filter for SELL trades
        trades_df = get_trade_log(limit=10000, fund=fund, _cache_version=_cache_version)
        
        logger.debug(f"get_realized_pnl: Retrieved {len(trades_df)} total trades")
        
        if trades_df.empty:
            logger.debug("get_realized_pnl: No trades found in trade_log")
            return {
                'total_realized_pnl': 0.0,
                'total_shares_sold': 0.0,
                'total_proceeds': 0.0,
                'average_sell_price': 0.0,
                'num_closed_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'trades_by_ticker': {}
            }
        
        # Debug: Log available columns
        logger.debug(f"get_realized_pnl: Available columns: {list(trades_df.columns)}")
        
        # Filter for SELL trades - infer from reason column
        sell_trades = pd.DataFrame()
        if 'reason' in trades_df.columns:
            # Infer from reason field (case-insensitive)
            # Check for 'sell', 'limit sell', or 'market sell' in reason
            reason_lower = trades_df['reason'].astype(str).str.lower()
            sell_mask = reason_lower.str.contains('sell', na=False) | \
                       reason_lower.str.contains('limit sell', na=False) | \
                       reason_lower.str.contains('market sell', na=False)
            sell_trades = trades_df[sell_mask].copy()
            logger.debug(f"get_realized_pnl: Found {len(sell_trades)} SELL trades using 'reason' column")
        
        # If still empty, return empty result
        if sell_trades.empty:
            logger.debug("get_realized_pnl: No SELL trades found after checking 'reason' column")
            return {
                'total_realized_pnl': 0.0,
                'total_shares_sold': 0.0,
                'total_proceeds': 0.0,
                'average_sell_price': 0.0,
                'num_closed_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'trades_by_ticker': {}
            }
        
        # Calculate realized P&L with currency conversion
        # Match console app's get_realized_pnl_summary() structure
        total_realized_pnl = 0.0
        total_shares_sold = 0.0
        total_proceeds = 0.0
        trades_by_ticker = {}
        winning_trades = 0
        losing_trades = 0
        
        # Only process trades that have P&L (realized P&L should be non-zero for closed positions)
        # Filter out trades with None or zero P&L if they shouldn't be counted
        for _, trade in sell_trades.iterrows():
            pnl_val = trade.get('pnl', 0)
            pnl = 0.0 if pd.isna(pnl_val) else float(pnl_val)
            
            shares = float(trade.get('shares', 0) or 0)
            price = float(trade.get('price', 0) or 0)
            proceeds = shares * price
            
            # Skip trades with zero shares (invalid data)
            if shares == 0:
                logger.debug(f"get_realized_pnl: Skipping trade with zero shares: {trade.get('ticker', 'UNKNOWN')}")
                continue
            
            # Get currency and convert to display currency
            currency = str(trade.get('currency', 'CAD')).upper() if pd.notna(trade.get('currency')) else 'CAD'
            
            # Get trade date for historical rate lookup
            trade_date = None
            if 'date' in trade and pd.notna(trade.get('date')):
                try:
                    trade_date = pd.to_datetime(trade.get('date'))
                except:
                    trade_date = None
            
            # Convert to display currency
            pnl_display = convert_to_display_currency(pnl, currency, trade_date, display_currency)
            proceeds_display = convert_to_display_currency(proceeds, currency, trade_date, display_currency)
            
            total_realized_pnl += pnl_display
            total_shares_sold += shares
            total_proceeds += proceeds_display
            
            # Track by ticker
            ticker = str(trade.get('ticker', 'UNKNOWN'))
            if ticker not in trades_by_ticker:
                trades_by_ticker[ticker] = {
                    'realized_pnl': 0.0,
                    'shares_sold': 0.0,
                    'proceeds': 0.0
                }
            trades_by_ticker[ticker]['realized_pnl'] += pnl_display
            trades_by_ticker[ticker]['shares_sold'] += shares
            trades_by_ticker[ticker]['proceeds'] += proceeds_display
            
            # Count winning/losing trades (only count if P&L is non-zero)
            if pnl_display > 0:
                winning_trades += 1
            elif pnl_display < 0:
                losing_trades += 1
        
        logger.debug(f"get_realized_pnl: Processed {len(sell_trades)} SELL trades, total_realized_pnl={total_realized_pnl:.2f}, total_shares_sold={total_shares_sold:.2f}")
        
        # Calculate average sell price (matching console app)
        average_sell_price = total_proceeds / total_shares_sold if total_shares_sold > 0 else 0.0
        
        return {
            'total_realized_pnl': total_realized_pnl,
            'total_shares_sold': total_shares_sold,
            'total_proceeds': total_proceeds,
            'average_sell_price': average_sell_price,
            'num_closed_trades': len(sell_trades),
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'trades_by_ticker': trades_by_ticker
        }
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error calculating realized P&L: {e}", exc_info=True)
        return {
            'total_realized_pnl': 0.0,
            'total_shares_sold': 0.0,
            'total_proceeds': 0.0,
            'average_sell_price': 0.0,
            'num_closed_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'trades_by_ticker': {}
        }


@log_execution_time()
@st.cache_data(ttl=300)
def get_first_trade_dates(fund: Optional[str] = None) -> Dict[str, datetime]:
    """Get the first trade date for each ticker.
    
    Approximation: Uses MIN(date) from portfolio_positions for each ticker.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    client = get_supabase_client()
    if not client:
        return {}
    
    try:
        query = client.supabase.table("portfolio_positions").select("ticker, date")
        if fund:
            query = query.eq("fund", fund)
            
        # We need all history -> this could be large. 
        # Optimization: Only select min date directly via group by if Supabase supported it easily.
        # Since we can't easily do efficient group-by aggregation in postgrest without rpc, 
        # and checking all rows is heavy...
        # BETTER APPROXIMATION: Use trade_log which represents transactions.
        # Find first BUY for each ticker.
        
        # ACTUALLY: Let's use a simpler approach for now to avoid fetching 50k rows.
        # Check if we can use the `trade_log` which is smaller? No, trade_log grows too.
        # Let's try to fetch just unique (ticker, min_date).
        # We can use an RPC call if one existed, but let's stick to standard queries.
        # Let's try fetching from trade_log ordered by date asc, distinct on ticker? 
        # PostgREST 9+ supports distinct.
        
        # Try finding first 'BUY' in trade_log
        # This is reasonably safe for "Opened" date
        today = datetime.now().date()
        
        # We have to be careful about pagination if there are many trades.
        # For now, let's limit to finding dates for CURRENT holdings only?
        # That requires knowing current holdings.
        
        # Let's revert to a "best effort" via trade_log with a reasonable limit
        # or use a dedicated RPC function if we had one.
        # Given constraints, let's look at `portfolio_positions`.
        # Taking MIN(date) from portfolio_positions is actually "when did we first have a record".
        
        # Let's ignore the perfect "gaps" logic and just get min date per ticker from trade_log
        # Fetch all trades (lightweight: just ticker and date)
        
        all_dates = {}
        batch_size = 1000
        offset = 0
        
        while True:
            # Get earliest trades first
            q = client.supabase.table("trade_log").select("ticker, date").order("date", desc=False).range(offset, offset + batch_size - 1)
            if fund:
                q = q.eq("fund", fund)
            
            res = q.execute()
            if not res.data:
                break
                
            for row in res.data:
                ticker = row['ticker']
                if ticker not in all_dates:
                    try:
                        all_dates[ticker] = pd.to_datetime(row['date']).date()
                    except:
                        pass
            
            # Optimization: If we have dates for "enough" tickers, maybe stop? 
            # But we don't know which ones are active. 
            # Given we fetch earliest first, the FIRST time we see a ticker is its start date.
            # So we just need to iterate until we've seen all tickers? No, we might miss new tickers if we stop.
            # But wait! If we order by date ASC, the first time we see a ticker IS the min date.
            # So `if ticker not in all_dates: all_dates[ticker] = date` is correct.
            # Do we need to fetch ALL trades? Yes, to find the first date for late-blooming tickers.
            # This might be slow.
            
            if len(res.data) < batch_size:
                break
            offset += batch_size
            
            if offset > 10000: # Safety cap
                break
                
        return all_dates

    except Exception as e:
        logger.error(f"Error getting trade dates: {e}")
        return {}


@log_execution_time()
@st.cache_data(ttl=300)
def get_cash_balances(fund: Optional[str] = None) -> Dict[str, float]:
    """Get cash balances by currency"""
    import logging
    logger = logging.getLogger(__name__)
    if fund:
        logger.info(f"Loading cash balances for fund: {fund}")
    
    client = get_supabase_client()
    if not client:
        return {"CAD": 0.0, "USD": 0.0}
    
    try:
        # WE MUST PAGINATE - Supabase has a hard limit of 1000 rows per request
        all_rows = []
        batch_size = 1000
        offset = 0
        
        while True:
            query = client.supabase.table("cash_balances").select("*")
            if fund:
                query = query.eq("fund", fund)
            
            result = query.range(offset, offset + batch_size - 1).execute()
            
            if not result.data:
                break
            
            all_rows.extend(result.data)
            
            # If we got fewer rows than batch_size, we're done
            if len(result.data) < batch_size:
                break
            
            offset += batch_size
            
            # Safety break to prevent infinite loops
            if offset > 50000:
                print("Warning: Reached 50,000 row safety limit in get_cash_balances pagination")
                break
        
        balances = {"CAD": 0.0, "USD": 0.0}
        if all_rows:
            for row in all_rows:
                currency = row.get('currency', 'CAD')
                amount = float(row.get('balance', 0))
                balances[currency] = balances.get(currency, 0) + amount
        
        return balances
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting cash balances: {e}", exc_info=True)
        return {"CAD": 0.0, "USD": 0.0}


@log_execution_time()
@st.cache_data(ttl=300)
def calculate_portfolio_value_over_time(fund: str, days: Optional[int] = None, display_currency: Optional[str] = None) -> pd.DataFrame:
    """Calculate portfolio value over time from portfolio_positions table.
    
    This queries the portfolio_positions table to get daily snapshots of
    actual market values (shares * price), with proper normalization,
    currency conversion to display currency, and continuous timeline handling.
    
    CACHED: Results are cached for 5 minutes to improve performance.
    
    Args:
        fund: Fund name (REQUIRED - we always filter by fund for performance)
        days: Optional number of days to look back. None = all time (default)
        display_currency: Optional display currency (defaults to user preference)
    
    Returns DataFrame with columns:
    - date: datetime
    - value: total market value (in display currency)
    - cost_basis: total cost basis (in display currency)
    - pnl: unrealized P&L (in display currency)
    - performance_pct: P&L as percentage of cost basis
    - performance_index: Normalized to start at 100 (for charting)
    """
    import logging
    logger = logging.getLogger(__name__)

    if display_currency is None:
        display_currency = get_user_display_currency()
    from decimal import Decimal
    from datetime import datetime, timedelta, timezone
    
    # Fund is optional - if not provided or 'all', load aggregate data
    if not fund or (isinstance(fund, str) and fund.lower() == 'all'):
        logger.info("📊 calculate_portfolio_value_over_time - Calculating for ALL funds")
        fund = None
    else:
        logger.info(f"📊 calculate_portfolio_value_over_time - Calculating for fund: {fund}")
    
    logger.info(f"Loading portfolio value over time for fund: {fund}")
    
    client = get_supabase_client()
    if not client:
        return pd.DataFrame()
    
    try:
        import time
        start_time = time.time()
        
        # Calculate date cutoff if days parameter provided
        cutoff_date = None
        if days is not None and days > 0:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Query portfolio_positions to get daily snapshots with actual market values
        # Include currency for proper USD→CAD conversion
        
        # WE MUST PAGINATE - Supabase has a hard limit of 1000 rows per request
        all_rows = []
        batch_size = 1000
        offset = 0
        query_start = time.time()
        
        while True:
            # Build query for this batch
            # Include base currency columns for pre-converted values (performance optimization)
            query = client.supabase.table("portfolio_positions").select(
                "date, total_value, cost_basis, pnl, fund, currency, "
                "total_value_base, cost_basis_base, pnl_base, base_currency"
            )
            
            if fund:
                query = query.eq("fund", fund)
            
            # Apply date filter if specified (for performance with large datasets)
            if cutoff_date:
                query = query.gte("date", cutoff_date.strftime('%Y-%m-%dT%H:%M:%SZ'))
            
            # Order by date AND id to ensure consistent pagination (stable sort)
            # Use range() for pagination
            # Note: range is 0-indexed and inclusive for start, inclusive for end in PostgREST logic usually,
            # but supabase-py .range(start, end) handles it.
            result = query.order("date").order("id").range(offset, offset + batch_size - 1).execute()
            
            rows = result.data
            if not rows:
                break
                
            all_rows.extend(rows)
            
            # If we got fewer rows than batch_size, we're done
            if len(rows) < batch_size:
                break
                
            offset += batch_size
            
            # Safety break to prevent infinite loops (e.g. max 50k rows = 50 batches)
            if offset > 50000:
                print("Warning: Reached 50,000 row safety limit in pagination")
                break
        
        query_time = time.time() - query_start
        logger.info(f"⏱️ calculate_portfolio_value_over_time - DB queries: {query_time:.2f}s ({len(all_rows)} rows)")
        
        if not all_rows:
            return pd.DataFrame()
        
        df = pd.DataFrame(all_rows)
        logger.debug(f"Loaded {len(df)} total portfolio position rows from Supabase (paginated)")
        
        # Normalize to noon (12:00) for consistent charting with benchmarks
        # Noon is more sensible than midnight for market data
        df['date'] = pd.to_datetime(df['date']).dt.normalize() + pd.Timedelta(hours=12)
        
        # Log date range for debugging
        if not df.empty:
            min_date = df['date'].min()
            max_date = df['date'].max()
            logger.debug(f"Date range: {min_date.date()} to {max_date.date()}")
        
        # Check if we should use pre-converted values or runtime conversion
        has_preconverted = False
        if 'total_value_base' in df.columns and 'base_currency' in df.columns:
            # FIX: Require that MOST records (>80%) have pre-converted values, not just "any"
            # Otherwise adding new data with values to a dataset with NULL values corrupts the graph
            preconverted_pct = df['total_value_base'].notna().mean()
            has_preconverted = preconverted_pct > 0.8
            if df['total_value_base'].notna().any() and not has_preconverted:
                logger.warning(f"Only {preconverted_pct*100:.1f}% of records have pre-converted values - using fallback")
        
        if has_preconverted:
            # USE PRE-CONVERTED VALUES (FAST PATH) - no exchange rate fetching needed!
            logger.info("⚡ Using pre-converted base currency values (FAST PATH)")
            value_col = 'total_value_base'
            cost_col = 'cost_basis_base'
            pnl_col = 'pnl_base'
        else:
            # FALLBACK: Runtime currency conversion for old data without base columns
            logger.warning("⚠️ Using runtime currency conversion (SLOW PATH - data not pre-converted)")
            
            # Check if we have positions in currencies other than display currency
            needs_conversion = False
            if 'currency' in df.columns:
                currencies = df['currency'].str.upper().fillna('CAD').unique()
                needs_conversion = any(c != display_currency.upper() for c in currencies)
            
            if needs_conversion:
                # Apply currency conversion to positions
                convert_start = time.time()
                
                # OPTIMIZATION: Get unique date-currency pairs to minimize rate lookups
                df['date_normalized'] = pd.to_datetime(df['date']).dt.normalize()
                df['currency_normalized'] = df['currency'].str.upper().fillna('CAD')
                
                # Get unique combinations
                unique_combos = df[['date_normalized', 'currency_normalized']].drop_duplicates()
                
                # BULK FETCH all needed rates in one query instead of 170+ individual queries
                rate_list = []
                unique_dates = unique_combos['date_normalized'].unique()
                unique_currencies = unique_combos['currency_normalized'].unique()
                
                # Build SQL to fetch all rates at once
                try:
                    client = get_supabase_client()
                    if client and len(unique_dates) > 0:
                        # Query for all rates matching our date range and currencies
                        min_date = pd.to_datetime(unique_dates.min()).strftime('%Y-%m-%d')
                        max_date = pd.to_datetime(unique_dates.max()).strftime('%Y-%m-%d')
                        
                        # Fetch rates for both USD<->CAD directions
                        rates_response = client.supabase.table('exchange_rates').select('*') \
                            .gte('timestamp', min_date) \
                            .lte('timestamp', max_date) \
                            .execute()
                        
                        # Build lookup dictionary from bulk results
                        rates_dict = {}
                        if rates_response.data:
                            for row in rates_response.data:
                                date_key = pd.to_datetime(row['timestamp']).normalize()
                                from_curr = row.get('from_currency', '').upper()
                                to_curr = row.get('to_currency', '').upper()
                                rate_val = float(row.get('rate', 1.0))
                                rates_dict[(date_key, from_curr, to_curr)] = rate_val
                        
                        # Now build rate_list using the bulk-fetched data
                        for _, row in unique_combos.iterrows():
                            date_val = row['date_normalized']
                            curr_val = row['currency_normalized']
                            
                            if curr_val == display_currency.upper():
                                rate_list.append({'date_normalized': date_val, 'currency_normalized': curr_val, 'conversion_rate': 1.0})
                            else:
                                # Try direct rate from bulk data
                                rate = rates_dict.get((date_val, curr_val, display_currency.upper()))
                                
                                # Try inverse rate
                                if rate is None:
                                    inverse_rate = rates_dict.get((date_val, display_currency.upper(), curr_val))
                                    if inverse_rate and inverse_rate != 0:
                                        rate = 1.0 / inverse_rate
                                
                                # Fallback to default rates if not found
                                if rate is None:
                                    if curr_val == 'USD' and display_currency.upper() == 'CAD':
                                        rate = 1.35
                                    elif curr_val == 'CAD' and display_currency.upper() == 'USD':
                                        rate = 1.0 / 1.35
                                    else:
                                        rate = 1.0
                                
                                rate_list.append({'date_normalized': date_val, 'currency_normalized': curr_val, 'conversion_rate': rate})
                    else:
                        # Fallback if client not available
                        for _, row in unique_combos.iterrows():
                            date_val = row['date_normalized']
                            curr_val = row['currency_normalized']
                            if curr_val == display_currency.upper():
                                rate = 1.0
                            elif curr_val == 'USD' and display_currency.upper() == 'CAD':
                                rate = 1.35
                            elif curr_val == 'CAD' and display_currency.upper() == 'USD':
                                rate = 1.0 / 1.35
                            else:
                                rate = 1.0
                            rate_list.append({'date_normalized': date_val, 'currency_normalized': curr_val, 'conversion_rate': rate})
                
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Error bulk fetching exchange rates: {e}")
                    # Fallback to defaults
                    for _, row in unique_combos.iterrows():
                        date_val = row['date_normalized']
                        curr_val = row['currency_normalized']
                        if curr_val == display_currency.upper():
                            rate = 1.0
                        elif curr_val == 'USD' and display_currency.upper() == 'CAD':
                            rate = 1.35
                        elif curr_val == 'CAD' and display_currency.upper() == 'USD':
                            rate = 1.0 / 1.35
                        else:
                            rate = 1.0
                        rate_list.append({'date_normalized': date_val, 'currency_normalized': curr_val, 'conversion_rate': rate})
                
                # Create rate lookup df and merge (FULLY VECTORIZED - no apply!)
                rate_df = pd.DataFrame(rate_list)
                df = df.merge(rate_df, on=['date_normalized', 'currency_normalized'], how='left')
                df['conversion_rate'] = df['conversion_rate'].fillna(1.0)
                
                # Vectorized conversion (no loops!)
                df['total_value_display'] = df['total_value'].astype(float) * df['conversion_rate']
                df['cost_basis_display'] = df['cost_basis'].astype(float) * df['conversion_rate']
                df['pnl_display'] = df['pnl'].astype(float) * df['conversion_rate']
                
                convert_time = time.time() - convert_start
                logger.info(f"⏱️ calculate_portfolio_value_over_time - Currency conversion: {convert_time:.2f}s ({len(unique_combos)} unique date-currency pairs)")
                
                value_col = 'total_value_display'
                cost_col = 'cost_basis_display'
                pnl_col = 'pnl_display'
            else:
                # All positions already in display currency, use values as-is
                value_col = 'total_value'
                cost_col = 'cost_basis'
                pnl_col = 'pnl'
        
        # Aggregate by date to get daily portfolio totals
        agg_start = time.time()
        # Sum all positions' values for each day
        daily_totals = df.groupby(df['date'].dt.date).agg({
            value_col: 'sum',
            cost_col: 'sum',
            pnl_col: 'sum'
        }).reset_index()
        
        daily_totals.columns = ['date', 'value', 'cost_basis', 'pnl']
        daily_totals['date'] = pd.to_datetime(daily_totals['date'])
        daily_totals = daily_totals.sort_values('date').reset_index(drop=True)
        
        if daily_totals.empty:
            return pd.DataFrame()
        
        # Calculate performance percentage (P&L / cost_basis * 100)
        # This shows how much the current value exceeds the original purchase price
        # Vectorized calculation (avoid apply!)
        daily_totals['performance_pct'] = np.where(
            daily_totals['cost_basis'] > 0,
            (daily_totals['pnl'] / daily_totals['cost_basis'] * 100),
            0.0
        )
        
        # Normalize performance to start at 100 on first trading day
        # This matches the console app's approach for fair benchmark comparison
        first_day_with_investment = daily_totals[daily_totals['cost_basis'] > 0]
        if not first_day_with_investment.empty:
            first_day_performance = first_day_with_investment.iloc[0]['performance_pct']
            # Adjust performance ONLY for days with investment (cost_basis > 0)
            # Days with cost_basis = 0 should remain at 0% (will become 100 in index)
            mask = daily_totals['cost_basis'] > 0
            daily_totals.loc[mask, 'performance_pct'] = daily_totals.loc[mask, 'performance_pct'] - first_day_performance
        
        # Create Performance Index (baseline 100 + performance %)
        # Days with cost_basis = 0 will have performance_pct = 0, so index = 100
        # Days with investment will have adjusted performance_pct, so first day = 0%, index = 100
        daily_totals['performance_index'] = 100 + daily_totals['performance_pct']
        
        
        # Filter to trading days only (remove weekends for performance)
        # Weekend shading is still shown in charts via _add_weekend_shading()
        filter_start = time.time()
        daily_totals = _filter_trading_days(daily_totals, 'date')
        filter_time = time.time() - filter_start
        logger.info(f"⏱️ calculate_portfolio_value_over_time - Weekend filtering: {filter_time:.2f}s")
        
        total_time = time.time() - start_time
        logger.info(f"⏱️ calculate_portfolio_value_over_time - TOTAL: {total_time:.2f}s")
        
        return daily_totals
        
    except Exception as e:
        logger.error(f"Error calculating portfolio value: {e}", exc_info=True)
        
        # Show error in UI for debugging
        try:
            import streamlit as st
            st.error(f"⚠️ Error loading chart: {str(e)}")
        except:
            pass
        
        return pd.DataFrame()


# Import _filter_trading_days from chart_utils to avoid duplication
from chart_utils import _filter_trading_days



def calculate_performance_metrics(fund: Optional[str] = None) -> Dict[str, Any]:
    """Calculate key performance metrics like the console app.
    
    Returns dict with:
    - peak_date: Date of peak performance
    - peak_gain_pct: Peak gain percentage 
    - max_drawdown_pct: Maximum drawdown percentage
    - max_drawdown_date: Date of max drawdown
    - total_return_pct: Current total return
    - current_value: Current portfolio value
    - total_invested: Total cost basis
    """
    df = calculate_portfolio_value_over_time(fund)
    
    if df.empty or 'performance_index' not in df.columns:
        return {
            'peak_date': None,
            'peak_gain_pct': 0.0,
            'max_drawdown_pct': 0.0,
            'max_drawdown_date': None,
            'total_return_pct': 0.0,
            'current_value': 0.0,
            'total_invested': 0.0
        }
    
    try:
        # Peak performance
        peak_idx = df['performance_index'].idxmax()
        peak_date = df.loc[peak_idx, 'date']
        peak_gain_pct = float(df.loc[peak_idx, 'performance_index']) - 100.0
        
        # Max drawdown calculation
        df_sorted = df.sort_values('date').copy()
        df_sorted['running_max'] = df_sorted['performance_index'].cummax()
        df_sorted['drawdown_pct'] = (df_sorted['performance_index'] / df_sorted['running_max'] - 1.0) * 100.0
        
        dd_idx = df_sorted['drawdown_pct'].idxmin()
        max_drawdown_pct = float(df_sorted.loc[dd_idx, 'drawdown_pct'])
        max_drawdown_date = df_sorted.loc[dd_idx, 'date']
        
        # Current stats (last row)
        last_row = df.iloc[-1]
        total_return_pct = float(last_row['performance_pct'])
        current_value = float(last_row['value'])
        total_invested = float(last_row['cost_basis'])
        
        return {
            'peak_date': peak_date,
            'peak_gain_pct': peak_gain_pct,
            'max_drawdown_pct': max_drawdown_pct,
            'max_drawdown_date': max_drawdown_date,
            'total_return_pct': total_return_pct,
            'current_value': current_value,
            'total_invested': total_invested
        }
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error calculating metrics: {e}", exc_info=True)
        return {
            'peak_date': None,
            'peak_gain_pct': 0.0,
            'max_drawdown_pct': 0.0,
            'max_drawdown_date': None,
            'total_return_pct': 0.0,
            'current_value': 0.0,
            'total_invested': 0.0
        }





def get_individual_holdings_performance(fund: str, days: int = 7) -> pd.DataFrame:
    """Get performance data for individual holdings in a fund.
    
    Args:
        fund: Fund name (required)
        days: Number of days to fetch (7, 30, or 0 for all)
        
    Returns:
        DataFrame with columns: ticker, date, shares, price, total_value, performance_index
    """
    from decimal import Decimal
    from datetime import datetime, timedelta, timezone
    
    if not fund:
        raise ValueError("Fund name is required")
    
    client = get_supabase_client()
    if not client:
        return pd.DataFrame()
    
    try:
        # Calculate date cutoff
        # Query for more days than requested to account for weekends and missing days
        # This ensures we get enough data points even when weekends/holidays are present
        if days > 0:
            # Query for at least 50% more days, or +3 days minimum (whichever is larger)
            query_days = max(int(days * 1.5), days + 3)
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=query_days)
            cutoff_str = cutoff_date.strftime('%Y-%m-%d')
        else:
            cutoff_str = None  # All time
        
        # Fetch position data with pagination - join with securities for sector/industry/currency
        all_rows = []
        batch_size = 1000
        offset = 0
        
        while True:
            # Join with securities table to get sector, industry, currency
            query = client.supabase.table("portfolio_positions").select(
                "ticker, date, shares, price, total_value, currency, securities(sector, industry, currency)"
            )
            
            query = query.eq("fund", fund)
            
            if cutoff_str:
                query = query.gte("date", f"{cutoff_str}T00:00:00")
            
            result = query.order("date").range(offset, offset + batch_size - 1).execute()
            
            rows = result.data
            if not rows:
                break
            
            all_rows.extend(rows)
            
            if len(rows) < batch_size:
                break
            
            offset += batch_size
            
            # Safety break
            if offset > 50000:
                print("Warning: Reached 50,000 row safety limit")
                break
        
        if not all_rows:
            return pd.DataFrame()
        
        df = pd.DataFrame(all_rows)
        
        # Flatten nested securities data
        if 'securities' in df.columns:
            securities_df = pd.json_normalize(df['securities'])
            if not securities_df.empty:
                # Merge sector and industry from securities, prefer securities currency if available
                if 'sector' in securities_df.columns:
                    df['sector'] = securities_df['sector']
                if 'industry' in securities_df.columns:
                    df['industry'] = securities_df['industry']
                if 'currency' in securities_df.columns:
                    # Use securities currency if available, otherwise use position currency
                    df['currency'] = securities_df['currency'].fillna(df.get('currency', 'USD'))
            df = df.drop(columns=['securities'], errors='ignore')
        
        # Normalize to date-only (midnight) for consistent charting
        df['date'] = pd.to_datetime(df['date']).dt.normalize()
        
        # Calculate performance index per ticker (baseline 100) and return percentages
        holdings_performance = []
        
        for ticker in df['ticker'].unique():
            ticker_df = df[df['ticker'] == ticker].copy()
            ticker_df = ticker_df.sort_values('date')
            
            if len(ticker_df) < 1:
                continue
            
            # Use first date's total_value as baseline
            baseline_value = float(ticker_df['total_value'].iloc[0])
            
            if baseline_value == 0:
                continue  # Skip if no valid baseline
            
            # Calculate performance index
            ticker_df['performance_index'] = (ticker_df['total_value'].astype(float) / baseline_value) * 100
            
            # Calculate total return percentage (from baseline to last value) - same for all rows of this ticker
            last_value = float(ticker_df['total_value'].iloc[-1])
            return_pct = ((last_value / baseline_value) - 1) * 100
            ticker_df['return_pct'] = return_pct
            
            # Calculate daily P&L percentage (change from previous day)
            ticker_df['daily_pnl_pct'] = ticker_df['performance_index'].diff()
            
            # Get metadata (sector, industry, currency) - use first non-null value and propagate
            if 'sector' in ticker_df.columns:
                sector_val = ticker_df['sector'].dropna().iloc[0] if not ticker_df['sector'].dropna().empty else None
                ticker_df['sector'] = sector_val
            else:
                ticker_df['sector'] = None
                
            if 'industry' in ticker_df.columns:
                industry_val = ticker_df['industry'].dropna().iloc[0] if not ticker_df['industry'].dropna().empty else None
                ticker_df['industry'] = industry_val
            else:
                ticker_df['industry'] = None
                
            if 'currency' in ticker_df.columns:
                currency_val = ticker_df['currency'].dropna().iloc[0] if not ticker_df['currency'].dropna().empty else 'USD'
                ticker_df['currency'] = currency_val
            else:
                ticker_df['currency'] = 'USD'
            
            # Keep only needed columns for charting and filtering
            cols_to_keep = ['ticker', 'date', 'performance_index', 'return_pct', 'daily_pnl_pct', 'sector', 'industry', 'currency']
            holdings_performance.append(ticker_df[cols_to_keep])
        
        if not holdings_performance:
            return pd.DataFrame()
        
        result_df = pd.concat(holdings_performance, ignore_index=True)
        
        # If days > 0, filter to the last N unique dates (not calendar days)
        # This ensures we get exactly N data points even when weekends/missing days are present
        if days > 0:
            # Get unique dates, sort descending, take first N
            unique_dates = sorted(result_df['date'].unique(), reverse=True)[:days]
            # Filter DataFrame to only include these dates
            result_df = result_df[result_df['date'].isin(unique_dates)]
            # Sort by date ascending for proper chart display
        
        return result_df
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error fetching individual holdings: {e}", exc_info=True)
        return pd.DataFrame()


def get_investor_count(fund: str) -> int:
    """Get count of contributors/investors for a fund
    
    Args:
        fund: Fund name
    
    Returns:
        Integer count of contributors
    """
    client = get_supabase_client()
    if not client:
        return 0
    
    try:
        # Query fund_contributor_summary view for total contributor count
        result = client.supabase.table("fund_contributor_summary").select(
            "total_contributors"
        ).eq("fund", fund).execute()
        
        if result.data and len(result.data) > 0:
            return int(result.data[0].get('total_contributors', 0))
        return 0
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting investor count: {e}", exc_info=True)
        return 0


@st.cache_data(ttl=3600)  # 1 hour - contributor list changes infrequently
def get_investor_allocations(fund: str, user_email: Optional[str] = None, is_admin: bool = False, _cache_version: str = CACHE_VERSION) -> pd.DataFrame:
    """Get investor allocation data with privacy masking
    
    Args:
        fund: Fund name
        user_email: Current user's email (to show their own name)
        is_admin: Whether current user is admin (admins see all names)
    
    Returns:
        DataFrame with columns: contributor_display, net_contribution, ownership_pct
        - If admin: Shows all real contributor names
        - If regular user: Shows only their name, others masked as "Investor 1", "Investor 2", etc.
        - ownership_pct is now NAV-based (units owned), not dollar-based
    """
    client = get_supabase_client()
    if not client:
        return pd.DataFrame()
    
    try:
        # Get all contributions with timestamps for NAV calculation
        all_contributions = []
        batch_size = 1000
        offset = 0
        
        while True:
            query = client.supabase.table("fund_contributions").select(
                "contributor, email, amount, contribution_type, timestamp"
            ).eq("fund", fund)
            
            result = query.range(offset, offset + batch_size - 1).execute()
            
            if not result.data:
                break
            
            all_contributions.extend(result.data)
            
            if len(result.data) < batch_size:
                break
            
            offset += batch_size
            
            if offset > 50000:
                print("Warning: Reached 50,000 row safety limit in get_investor_allocations pagination")
                break
        
        if not all_contributions:
            return pd.DataFrame()
        
        # Parse and sort contributions chronologically
        from datetime import datetime
        contributions = []
        for record in all_contributions:
            timestamp_raw = record.get('timestamp', '')
            timestamp = None
            if timestamp_raw:
                try:
                    if isinstance(timestamp_raw, datetime):
                        timestamp = timestamp_raw
                    elif isinstance(timestamp_raw, str):
                        try:
                            from data.repositories.field_mapper import TypeTransformers
                            timestamp = TypeTransformers.iso_to_datetime(timestamp_raw)
                        except ImportError:
                            from datetime import datetime as dt
                            try:
                                timestamp = dt.fromisoformat(timestamp_raw.replace('Z', '+00:00'))
                            except (ValueError, AttributeError):
                                for fmt in ['%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
                                    try:
                                        timestamp = dt.strptime(timestamp_raw.split('+')[0].split('.')[0], fmt)
                                        break
                                    except ValueError:
                                        continue
                except Exception:
                    pass
            
            contributions.append({
                'contributor': record.get('contributor', 'Unknown'),
                'email': record.get('email', ''),
                'amount': float(record.get('amount', 0)),
                'type': record.get('contribution_type', 'CONTRIBUTION').lower(),
                'timestamp': timestamp
            })
        
        contributions.sort(key=lambda x: x['timestamp'] or datetime.min)
        
        # Get contribution dates for historical fund value lookup
        contrib_dates = [c['timestamp'] for c in contributions if c['timestamp']]
        
        # Fetch historical fund values AND cost basis (for uninvested cash calculation)
        # Returns: (stock_values_dict, cost_basis_dict)
        historical_values, historical_cost_basis = get_historical_fund_values(fund, contrib_dates)
        
        # Calculate NAV-based ownership using same logic as get_user_investment_metrics
        contributor_units = {}
        contributor_data = {}
        total_units = 0.0
        running_contributions = 0.0  # Track total contributions for uninvested cash
        
        # Track state at start of each day for same-day contribution NAV calculation
        units_at_start_of_day = 0.0
        contributions_at_start_of_day = 0.0
        last_contribution_date = None
        
        for contrib in contributions:
            contributor = contrib['contributor']
            amount = contrib['amount']
            contrib_type = contrib['type']
            timestamp = contrib['timestamp']
            
            # Same-day NAV fix - calculate date_str BEFORE withdrawal/contribution logic
            date_str = timestamp.strftime('%Y-%m-%d') if timestamp else None
            if date_str != last_contribution_date:
                units_at_start_of_day = total_units
                contributions_at_start_of_day = running_contributions
                last_contribution_date = date_str
            
            if contributor not in contributor_units:
                contributor_units[contributor] = 0.0
                contributor_data[contributor] = {
                    'email': contrib['email'],
                    'net_contribution': 0.0
                }
            
            if contrib_type == 'withdrawal':
                contributor_data[contributor]['net_contribution'] -= amount
                running_contributions -= amount  # Track for uninvested cash calculation
                
                # Redeem units
                if total_units > 0 and contributor_units[contributor] > 0:
                    # date_str already calculated above
                    if date_str and date_str in historical_values:
                        fund_value_at_date = historical_values[date_str]
                        nav_at_withdrawal = fund_value_at_date / total_units if total_units > 0 else 1.0
                    else:
                        nav_at_withdrawal = 1.0
                    
                    units_to_redeem = amount / nav_at_withdrawal if nav_at_withdrawal > 0 else amount
                    actual_units_redeemed = min(units_to_redeem, contributor_units[contributor])
                    contributor_units[contributor] -= actual_units_redeemed
                    total_units -= actual_units_redeemed
            else:
                contributor_data[contributor]['net_contribution'] += amount
                
                # Calculate NAV
                # date_str already calculated above
                
                if total_units == 0:
                    # First contribution to the fund - NAV starts at 1.0
                    nav_at_contribution = 1.0
                    last_valid_nav = 1.0  # Initialize for future sanity checks
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.info(f"NAV calculation: First contribution to fund, using inception NAV = 1.0")
                elif date_str and date_str in historical_values:
                    stock_value_at_date = historical_values[date_str]
                    cost_basis_at_date = historical_cost_basis.get(date_str, 0.0)
                    
                    unit_price_source = "stock_plus_net_cash"
                    
                    # PROPER NAV FIX: Fund Value = Stock Value + Net Cash
                    # Net Cash = Contributions - Cost Basis.
                    # Crucially, we allow this to be NEGATIVE.
                    # Why? If we bought stock ($8k) but contributions are delayed/missing in DB ($5k),
                    # we have a temporary "liability" of -$3k. 
                    # Fund Equity = $8k (Asset) - $3k (Liability) = $5k.
                    # This prevents NAV inflation (and dilution) when records lag trades.
                    
                    net_cash = contributions_at_start_of_day - cost_basis_at_date
                    fund_value_at_date = stock_value_at_date + net_cash
                    
                    nav_at_contribution = fund_value_at_date / units_for_nav if units_for_nav > 0 else 1.0
                    
                    # Use units_at_start_of_day for same-day contributions
                    units_for_nav = units_at_start_of_day if units_at_start_of_day > 0 else total_units
                    nav_at_contribution = fund_value_at_date / units_for_nav if units_for_nav > 0 else 1.0
                else:
                    # Date not found (e.g., weekend/holiday contribution)
                    # Look backwards up to 7 days for the closest prior trading day
                    nav_at_contribution = 1.0  # Default fallback
                    units_for_nav = units_at_start_of_day if units_at_start_of_day > 0 else total_units
                    if date_str and units_for_nav > 0:
                        from datetime import datetime, timedelta
                        contribution_date = datetime.strptime(date_str, '%Y-%m-%d')
                        
                        for days_back in range(1, 8):  # Check up to 7 days prior
                            prior_date = contribution_date - timedelta(days=days_back)
                            prior_date_str = prior_date.strftime('%Y-%m-%d')
                            
                            if prior_date_str in historical_values:
                                fund_value_at_prior_date = historical_values[prior_date_str]
                                nav_at_contribution = fund_value_at_prior_date / units_for_nav
                                
                                # Log the fallback for transparency
                                import logging
                                logger = logging.getLogger(__name__)
                                logger.warning(f"NAV fallback: {date_str} (weekend/holiday) -> using {prior_date_str} NAV = {nav_at_contribution:.4f}")
                                break
                        
                        # If still 1.0 after search, log as potential issue
                        if nav_at_contribution == 1.0:
                            import logging
                            logger = logging.getLogger(__name__)
                            logger.error(f"NAV calculation: No historical data found within 7 days of {date_str}, falling back to NAV=1.0")
                
                if nav_at_contribution <= 0:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"NAV calculation: Calculated NAV <= 0 ({nav_at_contribution}) for {date_str}, falling back to NAV=1.0 - THIS MAY CORRUPT DATA!")
                    nav_at_contribution = 1.0
                
                units_purchased = amount / nav_at_contribution
                contributor_units[contributor] += units_purchased
                total_units += units_purchased
                running_contributions += amount  # Track for uninvested cash calculation
        
        # Build result DataFrame
        result_data = []
        for contributor, data in contributor_data.items():
            result_data.append({
                'contributor': contributor,
                'email': data['email'],
                'net_contribution': data['net_contribution'],
                'units': contributor_units.get(contributor, 0.0)
            })
        
        df = pd.DataFrame(result_data)
        
        # Calculate ownership percentages based on UNITS (NAV-based), not dollars
        if total_units > 0:
            df['ownership_pct'] = (df['units'] / total_units) * 100
        else:
            df['ownership_pct'] = 0.0
        
        # Sort by ownership percentage (descending) for consistent masking
        df = df.sort_values('ownership_pct', ascending=False).reset_index(drop=True)
        
        # Apply privacy masking
        def mask_name(row, idx):
            if is_admin:
                return row['contributor']
            else:
                contributor_email = row.get('email', '').lower() if pd.notna(row.get('email')) else ''
                user_email_lower = user_email.lower() if user_email else ''
                
                if contributor_email and user_email_lower and contributor_email == user_email_lower:
                    return row['contributor']
                else:
                    return f"Investor {idx + 1}"
        
        df['contributor_display'] = df.apply(lambda row: mask_name(row, row.name), axis=1)
        
        # Return only necessary columns
        return df[['contributor_display', 'net_contribution', 'ownership_pct']]
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting investor allocations: {e}", exc_info=True)
        return pd.DataFrame()


@st.cache_data(ttl=None)  # Cache forever - historical data doesn't change
def get_historical_fund_values(fund: str, dates: List[datetime], _cache_version: str = CACHE_VERSION) -> Dict[str, float]:
    """Get historical fund values for specific dates.
    
    Queries portfolio_positions to calculate total fund value at each date.
    Returns the closest available date if exact date not found.
    
    CACHED: Permanently cached. Bump CACHE_VERSION in streamlit_utils.py to invalidate after bug fixes.
    
    Args:
        fund: Fund name
        dates: List of dates to get fund values for
        _cache_version: Cache key version (auto-set from CACHE_VERSION constant)
        
    Returns:
        Dict mapping date string (YYYY-MM-DD) to fund value
    """
    from datetime import datetime
    
    client = get_supabase_client()
    if not client or not dates:
        return {}, {}
    
    try:
        # Get all unique dates we need
        date_strs = sorted(set(d.strftime('%Y-%m-%d') for d in dates if d))
        if not date_strs:
            return {}, {}
        
        min_date = min(date_strs)
        
        # Query portfolio_positions for this fund, from earliest contribution date onwards
        # WE MUST PAGINATE - Supabase has a hard limit of 1000 rows per request
        all_rows = []
        batch_size = 1000
        offset = 0
        
        while True:
            query = client.supabase.table("portfolio_positions").select(
                "id, date, ticker, shares, price, currency, cost_basis"
            ).eq("fund", fund).gte("date", min_date).order("date").order("id")
            
            result = query.range(offset, offset + batch_size - 1).execute()
            
            if not result.data:
                break
            
            all_rows.extend(result.data)
            
            # If we got fewer rows than batch_size, we're done
            if len(result.data) < batch_size:
                break
            
            offset += batch_size
            
            # Safety break to prevent infinite loops (e.g. max 50k rows = 50 batches)
            if offset > 50000:
                print("Warning: Reached 50,000 row safety limit in get_historical_fund_values pagination")
                break
        
        if not all_rows:
            return {}, {}
        
        # CHECK FOR DUPLICATES - this could inflate NAV calculations!
        import logging
        logger = logging.getLogger(__name__)
        from log_handler import log_message
        
        # Convert to DataFrame for duplicate checking
        import pandas as pd
        df_check = pd.DataFrame(all_rows)
        df_check['date_key'] = df_check['date'].str[:10]  # Just YYYY-MM-DD
        
        # Check if we need ticker column (older data might not have it)
        if 'ticker' in df_check.columns:
            # Group by date and ticker to find duplicates
            duplicate_check = df_check.groupby(['date_key', 'ticker']).size().reset_index(name='count')
            duplicates = duplicate_check[duplicate_check['count'] > 1]
            
            if len(duplicates) > 0:
                logger.error(f"DUPLICATE DATA DETECTED in portfolio_positions for {fund}! {len(duplicates)} duplicate date+ticker pairs found. This will inflate NAV calculations!")
                log_message(f"CRITICAL: {len(duplicates)} duplicate portfolio positions found for {fund}. NAV calculations will be incorrect!", level='ERROR')
                print(f"🚨 CRITICAL: {len(duplicates)} duplicate portfolio positions detected for {fund}!")
                print(f"   This will cause incorrect NAV and return calculations.")
                print(f"   Run debug/clean_duplicate_positions_v2.py to fix.")
                
                # Show first few duplicates
                for _, dup in duplicates.head(5).iterrows():
                    print(f"   - {dup['date_key']} | {dup['ticker']}: {dup['count']} records")
        
        # Get exchange rates for each date we need (use historical rates for accuracy)
        # First, get unique dates from portfolio positions
        position_dates = sorted(set(row['date'][:10] for row in all_rows))
        
        # Fetch historical exchange rates for these dates using batched query
        exchange_rates_by_date = {}
        fallback_rate = 1.42  # Default fallback
        try:
            # Get latest rate as fallback
            rate_result = client.get_latest_exchange_rate('USD', 'CAD')
            if rate_result:
                fallback_rate = float(rate_result)
            
            # Batch fetch all historical rates in a single query
            if position_dates:
                from datetime import datetime as dt
                min_date = dt.strptime(min(position_dates), '%Y-%m-%d')
                max_date = dt.strptime(max(position_dates), '%Y-%m-%d')
                
                # Get all rates in the date range with one query
                rates_list = client.get_exchange_rates(min_date, max_date, 'USD', 'CAD')
                
                # Build a lookup dictionary from the results
                rates_by_date = {}
                for rate_entry in rates_list:
                    timestamp = rate_entry.get('timestamp', '')
                    rate_value = rate_entry.get('rate')
                    if timestamp and rate_value:
                        # Extract date portion (YYYY-MM-DD)
                        date_str = timestamp[:10] if isinstance(timestamp, str) else str(timestamp)[:10]
                        rates_by_date[date_str] = float(rate_value)
                
                # Match each position date to the closest available exchange rate
                for date_str in position_dates:
                    if date_str in rates_by_date:
                        exchange_rates_by_date[date_str] = rates_by_date[date_str]
                    else:
                        # Find closest date on or before this date
                        available_dates = sorted([d for d in rates_by_date.keys() if d <= date_str])
                        if available_dates:
                            closest_date = available_dates[-1]
                            exchange_rates_by_date[date_str] = rates_by_date[closest_date]
                        else:
                            exchange_rates_by_date[date_str] = fallback_rate
        except Exception as e:
            # If we can't get any rates, use fallback for all dates
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to fetch batched exchange rates: {e}, using fallback")
            for date_str in position_dates:
                exchange_rates_by_date[date_str] = fallback_rate
        
        # Calculate total value AND cost basis for each date using date-specific exchange rates
        values_by_date = {}
        cost_basis_by_date = {}  # Track cost basis for uninvested cash calculation
        for row in all_rows:
            date_str = row['date'][:10]  # Get just YYYY-MM-DD
            shares = float(row.get('shares', 0))
            price = float(row.get('price', 0))
            currency = row.get('currency', 'USD')
            cost_basis = float(row.get('cost_basis', 0))
            
            # Convert to CAD using date-specific exchange rate
            value = shares * price
            if currency == 'USD':
                usd_to_cad = exchange_rates_by_date.get(date_str, fallback_rate)
                value *= usd_to_cad
                cost_basis *= usd_to_cad  # Cost basis also needs conversion
            
            if date_str not in values_by_date:
                values_by_date[date_str] = 0.0
                cost_basis_by_date[date_str] = 0.0
            values_by_date[date_str] += value
            cost_basis_by_date[date_str] += cost_basis
        
        # For each requested date, find closest available date
        result_values = {}
        result_cost_basis = {}
        available_dates = sorted(values_by_date.keys())
        
        for date_str in date_strs:
            if date_str in values_by_date:
                result_values[date_str] = values_by_date[date_str]
                result_cost_basis[date_str] = cost_basis_by_date.get(date_str, 0.0)
            else:
                # Find closest date before or on this date
                closest = None
                for avail_date in available_dates:
                    if avail_date <= date_str:
                        closest = avail_date
                    else:
                        break
                if closest:
                    result_values[date_str] = values_by_date[closest]
                    result_cost_basis[date_str] = cost_basis_by_date.get(closest, 0.0)
        
        # Return both stock values and cost basis for proper NAV calculation
        # Fund Value = Stock Value + max(0, Contributions - Cost Basis)
        return result_values, result_cost_basis
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting historical fund values: {e}", exc_info=True)
        return {}, {}


@st.cache_data(ttl=300)
def get_user_investment_metrics(fund: str, total_portfolio_value: float, include_cash: bool = True, session_id: str = "unknown", display_currency: Optional[str] = None, _cache_version: str = CACHE_VERSION) -> Optional[Dict[str, Any]]:
    """Get investment metrics for the currently logged-in user using NAV-based calculation.
    
    This calculates the user's investment performance using a unit-based system 
    (similar to mutual fund NAV). Investors who join when the fund is worth more 
    get fewer units per dollar, resulting in accurate per-investor returns.
    
    CACHED: Results are cached with market-aware TTL (5min during market hours, 
    1hr outside market hours) to improve performance.
    
    Args:
        fund: Fund name
        total_portfolio_value: Total portfolio value (positions only, before cash) in display currency
        include_cash: Whether to include cash in total fund value (default True)
        session_id: Session ID for log tracking (default "unknown")
        display_currency: Optional display currency (defaults to user preference)
    
    Returns:
        Dict with keys:
        - net_contribution: User's net contribution amount (in display currency)
        - current_value: Current value of their investment (NAV-based, in display currency)
        - gain_loss: Absolute gain/loss amount (in display currency)
        - gain_loss_pct: Gain/loss percentage (accurate per-user return)
        - ownership_pct: Ownership percentage (based on units)
        - contributor_name: Their name (for display)
        
        Returns None if:
        - User not logged in
        - No contributor record found matching user's email
        - User has no contributions in the fund
    """
    if display_currency is None:
        display_currency = get_user_display_currency()
    from auth_utils import get_user_email
    from datetime import datetime, timezone, timedelta
    
    # Get user email
    user_email = get_user_email()
    if not user_email:
        return None
    
    client = get_supabase_client()
    if not client:
        return None
    
    try:
        import time
        from log_handler import log_message
        func_start = time.time()
        log_message(f"[{session_id}] PERF: get_user_investment_metrics - Starting", level='DEBUG')
        
        # Get ALL contributions with timestamps (not just the summary view)
        # WE MUST PAGINATE - Supabase has a hard limit of 1000 rows per request
        all_contributions = []
        batch_size = 1000
        offset = 0
        
        t0 = time.time()
        while True:
            query = client.supabase.table("fund_contributions").select(
                "contributor, email, amount, contribution_type, timestamp"
            ).eq("fund", fund)
            
            result = query.range(offset, offset + batch_size - 1).execute()
            
            if not result.data:
                break
            
            all_contributions.extend(result.data)
            
            # If we got fewer rows than batch_size, we're done
            if len(result.data) < batch_size:
                break
            
            offset += batch_size
            
            # Safety break to prevent infinite loops (e.g. max 50k rows = 50 batches)
            if offset > 50000:
                print("Warning: Reached 50,000 row safety limit in get_user_investment_metrics pagination")
                break
        
        log_message(f"[{session_id}] PERF: get_user_investment_metrics - Contributions query: {time.time() - t0:.2f}s ({len(all_contributions)} rows)", level='DEBUG')
        
        if not all_contributions:
            log_message(f"[{session_id}] PERF: get_user_investment_metrics - No contributions found, returning None (total: {time.time() - func_start:.2f}s)", level='DEBUG')
            return None
        
        # Get cash balances for total fund value
        t0 = time.time()
        cash_balances = get_cash_balances(fund)
        
        # Convert cash balances to display currency
        total_cash_display = 0.0
        for currency, amount in cash_balances.items():
            if amount > 0:
                cash_display = convert_to_display_currency(amount, currency, None, display_currency)
                total_cash_display += cash_display
        
        fund_total_value = total_portfolio_value + total_cash_display if include_cash else total_portfolio_value
        log_message(f"[{session_id}] PERF: get_user_investment_metrics - Cash/exchange rate: {time.time() - t0:.2f}s", level='DEBUG')
        
        if fund_total_value <= 0:
            log_message(f"[{session_id}] PERF: get_user_investment_metrics - Fund value <= 0, returning None (total: {time.time() - func_start:.2f}s)", level='DEBUG')
            return None
        
        # Parse and sort contributions chronologically
        t0 = time.time()
        contributions = []
        for record in all_contributions:
            timestamp_raw = record.get('timestamp', '')
            timestamp = None
            if timestamp_raw:
                try:
                    if isinstance(timestamp_raw, datetime):
                        timestamp = timestamp_raw
                    elif isinstance(timestamp_raw, str):
                        # Use the same ISO parser that the repository uses for database timestamps
                        try:
                            from data.repositories.field_mapper import TypeTransformers
                            timestamp = TypeTransformers.iso_to_datetime(timestamp_raw)
                        except ImportError:
                            # Fallback to manual parsing if import fails
                            from datetime import datetime as dt
                            try:
                                timestamp = dt.fromisoformat(timestamp_raw.replace('Z', '+00:00'))
                            except (ValueError, AttributeError):
                                # Last resort: try basic formats
                                for fmt in ['%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
                                    try:
                                        timestamp = dt.strptime(timestamp_raw.split('+')[0].split('.')[0], fmt)
                                        break
                                    except ValueError:
                                        continue
                    else:
                        # Use print for streamlit utilities (logger may not be available)
                        print(f"⚠️  Unexpected timestamp type '{type(timestamp_raw)}' for contributor {record.get('contributor', 'Unknown')}")
                except Exception as e:
                    print(f"⚠️  Could not parse timestamp '{timestamp_raw}' for contributor {record.get('contributor', 'Unknown')}: {e}")
            
            contributions.append({
                'contributor': record.get('contributor', 'Unknown'),
                'email': record.get('email', ''),
                'amount': float(record.get('amount', 0)),
                'type': record.get('contribution_type', 'CONTRIBUTION').lower(),
                'timestamp': timestamp
            })
        
        contributions.sort(key=lambda x: x['timestamp'] or datetime.min)
        log_message(f"[{session_id}] PERF: get_user_investment_metrics - Parse contributions: {time.time() - t0:.2f}s", level='DEBUG')
        
        # Get all contribution dates AND previous dates (for NAV lookup)
        # We need previous day's value to calculate NAV *before* the new capital affects value
        contrib_dates = []
        for c in contributions:
            if c['timestamp']:
                ts = c['timestamp']
                contrib_dates.append(ts)
                # Add previous day
                contrib_dates.append(ts - timedelta(days=1))
        
        # Fetch ACTUAL historical fund values AND cost basis from portfolio_positions
        t0 = time.time()
        try:
            result = get_historical_fund_values(fund, contrib_dates)
            # Handle case where function returns empty result (e.g., during rebuild when no data exists)
            if not result or len(result) != 2:
                historical_values = {}
                historical_cost_basis = {}
            else:
                historical_values, historical_cost_basis = result
        except (ValueError, TypeError) as e:
            # Gracefully handle unpacking errors when no data exists
            log_message(f"[{session_id}] No portfolio data available (rebuild in progress?): {e}", level='WARNING')
            historical_values = {}
            historical_cost_basis = {}
        
        log_message(f"[{session_id}] PERF: get_user_investment_metrics - get_historical_fund_values: {time.time() - t0:.2f}s ({len(historical_values)} dates)", level='DEBUG')
        
        # Check if we have sufficient historical data
        use_historical = bool(historical_values)
        if not historical_values:
            log_message(f"[{session_id}] NAV WARNING: No historical fund values found for {fund}. Using time-weighted estimation.", level='WARNING')
            print(f"⚠️  NAV WARNING: No historical fund values found for {fund}. Using time-weighted estimation.")
        elif len(historical_values) < len(set(d.strftime('%Y-%m-%d') for d in contrib_dates if d)):
            log_message(f"[{session_id}] NAV WARNING: Only {len(historical_values)} historical dates found for {len(set(d.strftime('%Y-%m-%d') for d in contrib_dates if d))} contribution dates. Some will use fallback.", level='WARNING')
            print(f"⚠️  NAV WARNING: Only {len(historical_values)} historical dates found, some contributions will use fallback estimation.")
        
        # Calculate time-weighted estimation parameters for fallback
        # This matches the logic in position_calculator.py
        total_net_contributions = sum(
            -c['amount'] if c['type'] == 'withdrawal' else c['amount'] 
            for c in contributions
        )
        growth_rate = fund_total_value / total_net_contributions if total_net_contributions > 0 else 1.0
        
        timestamps = [c['timestamp'] for c in contributions if c['timestamp']]
        if timestamps:
            first_timestamp = min(timestamps)
            # Ensure now is timezone aware (UTC) to match database timestamps
            now = datetime.now(timezone.utc)
            total_days = max((now - first_timestamp).days, 1)
        else:
            first_timestamp = None
            total_days = 1
        
        # Calculate NAV-based ownership using actual historical data
        t0 = time.time()
        contributor_units = {}
        contributor_data = {}
        total_units = 0.0
        running_total_contributions = 0.0  # Total contributions up to this point
        
        # Track state at start of each day for same-day NAV calculation
        units_at_start_of_day = 0.0
        contributions_at_start_of_day = 0.0
        last_contribution_date = None
        
        for contrib in contributions:
            contributor = contrib['contributor']
            amount = contrib['amount']
            contrib_type = contrib['type']
            timestamp = contrib['timestamp']
            
            # Same-day NAV fix - capture state at START of each new day
            date_str = timestamp.strftime('%Y-%m-%d') if timestamp else None
            if date_str != last_contribution_date:
                units_at_start_of_day = total_units
                contributions_at_start_of_day = running_total_contributions
                last_contribution_date = date_str
            
            if contributor not in contributor_units:
                contributor_units[contributor] = 0.0
                contributor_data[contributor] = {
                    'email': contrib['email'],
                    'contributions': 0.0,
                    'withdrawals': 0.0,
                    'net_contribution': 0.0
                }
            
            # Determine NAV for this transaction
            # CRITICAL: Use PREVIOUS DAY'S Closing NAV to avoid self-referential inflation
            # For same-day contributions, use start-of-day units to ensure fairness
            nav_at_transaction = 1.0  # Default to inception NAV
            nav_source = "inception"
            
            # Use start-of-day units for same-day fairness
            # All contributors on the same day should get the same NAV
            units_for_nav = units_at_start_of_day if units_at_start_of_day > 0 else total_units
            
            if units_for_nav > 0:
                # Try to find historical fund value, looking back up to 7 days
                # This handles weekends, holidays, gaps in trading, and infrequent position updates
                found_nav = False
                
                for days_back in range(1, 8):
                    check_date = (timestamp - timedelta(days=days_back)).strftime('%Y-%m-%d') if timestamp else None
                    
                    if check_date and check_date in historical_values and historical_values[check_date] > 0:
                        stock_value_at_date = historical_values[check_date]
                        cost_basis_at_date = historical_cost_basis.get(check_date, 0.0)
                        
                        # Apply same Logic as get_investor_allocations
                        # Fund Value = Stock + (Contribs - Cost)
                        # Allow negative cash flow to handle unrecorded capital injection
                        net_cash = contributions_at_start_of_day - cost_basis_at_date
                        fund_value_at_date = stock_value_at_date + net_cash
                        
                        nav_at_transaction = fund_value_at_date / units_for_nav
                        nav_source = f"lookback_{days_back}d ({check_date})"
                        found_nav = True
                        break
                
                # If no historical data found in past 7 days, use fallback strategies
                if not found_nav:
                    # Try time-weighted estimation if we have timestamp info
                    if first_timestamp and timestamp:
                        elapsed_days = (timestamp - first_timestamp).days
                        time_fraction = elapsed_days / total_days
                        nav_at_transaction = 1.0 + (growth_rate - 1.0) * time_fraction
                        nav_source = "time_weighted"
                    # Last resort: average cost NAV
                    elif units_for_nav > 0:
                        nav_at_transaction = (running_total_contributions / units_for_nav)
                        nav_source = "average_cost"
            
            if contrib_type == 'withdrawal':
                contributor_data[contributor]['withdrawals'] += amount
                contributor_data[contributor]['net_contribution'] -= amount
                
                if total_units > 0 and contributor_units[contributor] > 0:
                    units_to_redeem = amount / nav_at_transaction if nav_at_transaction > 0 else amount
                    # Cap redemption
                    actual_units_redeemed = min(units_to_redeem, contributor_units[contributor])
                    contributor_units[contributor] -= actual_units_redeemed
                    total_units -= actual_units_redeemed
                elif contributor_units[contributor] <= 0 and amount > 0:
                    log_message(f"[{session_id}] NAV WARNING: Withdrawal of ${amount} from {contributor} skipped - no units to redeem", level='WARNING')
                    print(f"⚠️  Withdrawal of ${amount} from {contributor} skipped - no units to redeem")
                
                running_total_contributions -= amount
            else:
                contributor_data[contributor]['contributions'] += amount
                contributor_data[contributor]['net_contribution'] += amount
                
                units_issued = amount / nav_at_transaction
                contributor_units[contributor] += units_issued
                total_units += units_issued
                running_total_contributions += amount
                
                # Log unit issuance for debugging
                if nav_at_transaction != 10.0:
                    log_message(f"[{session_id}] NAV DEBUG: {contributor} added ${amount} at NAV ${nav_at_transaction:.4f} ({nav_source}) -> {units_issued:.2f} units", level='DEBUG')
        
        log_message(f"[{session_id}] PERF: get_user_investment_metrics - NAV calculations: {time.time() - t0:.2f}s ({len(contributions)} contributions)", level='DEBUG')
        
        if total_units <= 0:
            log_message(f"[{session_id}] PERF: get_user_investment_metrics - Total units <= 0, returning None (total: {time.time() - func_start:.2f}s)", level='DEBUG')
            return None
        
        # Find the current user's data
        user_email_lower = user_email.lower()
        user_contributor = None
        user_units = 0.0
        
        for contributor, data in contributor_data.items():
            contrib_email = data.get('email', '')
            if contrib_email and contrib_email.lower() == user_email_lower:
                user_contributor = contributor
                user_units = contributor_units.get(contributor, 0.0)
                break
        
        if user_contributor is None or user_units <= 0:
            log_message(f"[{session_id}] PERF: get_user_investment_metrics - User not found or no units, returning None (total: {time.time() - func_start:.2f}s)", level='DEBUG')
            return None
        
        user_data = contributor_data[user_contributor]
        user_net_contribution = user_data['net_contribution']
        
        if user_net_contribution <= 0:
            log_message(f"[{session_id}] PERF: get_user_investment_metrics - User net contribution <= 0, returning None (total: {time.time() - func_start:.2f}s)", level='DEBUG')
            return None
        
        # Calculate current NAV and user's value
        current_nav = fund_total_value / total_units
        current_value = user_units * current_nav
        ownership_pct = (user_units / total_units) * 100
        gain_loss = current_value - user_net_contribution
        gain_loss_pct = (gain_loss / user_net_contribution) * 100 if user_net_contribution > 0 else 0.0
        
        log_message(f"[{session_id}] PERF: get_user_investment_metrics - SUCCESS, total time: {time.time() - func_start:.2f}s", level='DEBUG')
        
        return {
            'net_contribution': user_net_contribution,
            'current_value': current_value,
            'gain_loss': gain_loss,
            'gain_loss_pct': gain_loss_pct,
            'ownership_pct': ownership_pct,
            'contributor_name': user_contributor,
            # Additional NAV transparency fields
            'units': user_units,
            'unit_price': current_nav
        }
        
    except Exception as e:
        import logging
        import traceback
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting user investment metrics: {e}", exc_info=True)
        # error_msg logic removed as logger handles it better, but keeping st.error for UI
        
        # Also show in UI if possible
        try:
            import streamlit as st
            st.error(f"⚠️ Error calculating your investment: {str(e)}")
        except:
            pass
        
        # Re-raise in development to surface the actual issue
        if os.environ.get('STREAMLIT_ENV') != 'production':
            raise
            
        return None


@log_execution_time()
@st.cache_data(ttl=3600)  # Cache for 1 hour - thesis doesn't change frequently
def get_fund_thesis_data(fund_name: str) -> Optional[Dict[str, Any]]:
    """Get thesis data for a fund from the database view.
    
    Args:
        fund_name: Name of the fund
        
    Returns:
        Dictionary with thesis data structure:
        {
            'fund': str,
            'title': str,
            'overview': str,
            'pillars': [
                {
                    'name': str,
                    'allocation': str,
                    'thesis': str,
                    'pillar_order': int
                },
                ...
            ]
        }
        Returns None if no thesis exists or on error.
    """
    client = get_supabase_client()
    if not client:
        return None
    
    try:
        # Query the view - get all rows for this fund
        result = client.supabase.table("fund_thesis_with_pillars")\
            .select("*")\
            .eq("fund", fund_name)\
            .execute()
        
        if not result.data:
            return None
        
        # First row has the thesis info (all rows have same thesis fields)
        first_row = result.data[0]
        
        # Build pillars list from all rows (filter out NULL pillars)
        pillars = []
        for row in result.data:
            if row.get('pillar_id') is not None:
                pillars.append({
                    'name': row.get('pillar_name', ''),
                    'allocation': row.get('allocation', ''),
                    'thesis': row.get('pillar_thesis', ''),
                    'pillar_order': row.get('pillar_order', 0)
                })
        
        # Sort pillars by order
        pillars.sort(key=lambda x: x.get('pillar_order', 0))
        
        return {
            'fund': first_row.get('fund', fund_name),
            'title': first_row.get('title', ''),
            'overview': first_row.get('overview', ''),
            'pillars': pillars
        }
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting thesis data for {fund_name}: {e}", exc_info=True)
        return None


@log_execution_time()
def get_biggest_movers(positions_df: pd.DataFrame, display_currency: str, limit: int = 10) -> Dict[str, pd.DataFrame]:
    """Get biggest gainers and losers from positions.
    
    Args:
        positions_df: DataFrame with positions data
        display_currency: Currency to display values in
        limit: Number of top movers to return (default 10)
        
    Returns:
        Dictionary with 'gainers' and 'losers' DataFrames
    """
    if positions_df.empty:
        return {'gainers': pd.DataFrame(), 'losers': pd.DataFrame()}
    
    # Get exchange rates for currency conversion
    all_currencies = set()
    if 'currency' in positions_df.columns:
        all_currencies.update(positions_df['currency'].fillna('CAD').astype(str).str.upper().unique().tolist())
    
    rate_map = fetch_latest_rates_bulk(list(all_currencies), display_currency) if all_currencies else {}
    
    def get_rate_safe(curr):
        return rate_map.get(str(curr).upper(), 1.0)
    
    # Create a copy to avoid modifying original
    df = positions_df.copy()
    
    # Ensure we have required columns
    required_cols = ['ticker']
    if not all(col in df.columns for col in required_cols):
        return {'gainers': pd.DataFrame(), 'losers': pd.DataFrame()}
    
    # Determine which P&L column to use (prefer daily_pnl_pct, fallback to daily_pnl or return_pct)
    pnl_pct_col = None
    pnl_dollar_col = None
    
    if 'daily_pnl_pct' in df.columns:
        pnl_pct_col = 'daily_pnl_pct'
    elif 'return_pct' in df.columns:
        pnl_pct_col = 'return_pct'
    
    if 'daily_pnl' in df.columns:
        pnl_dollar_col = 'daily_pnl'
    elif 'unrealized_pnl' in df.columns:
        pnl_dollar_col = 'unrealized_pnl'
    
    if not pnl_pct_col and not pnl_dollar_col:
        return {'gainers': pd.DataFrame(), 'losers': pd.DataFrame()}
    
    # Filter out positions with zero or missing P&L
    if pnl_pct_col:
        df = df[df[pnl_pct_col].notna() & (df[pnl_pct_col] != 0)]
        sort_col = pnl_pct_col
    else:
        df = df[df[pnl_dollar_col].notna() & (df[pnl_dollar_col] != 0)]
        sort_col = pnl_dollar_col
    
    if df.empty:
        return {'gainers': pd.DataFrame(), 'losers': pd.DataFrame()}
    
    # Convert currency if needed
    if 'currency' in df.columns and pnl_dollar_col:
        rates = df['currency'].fillna('CAD').astype(str).str.upper().map(get_rate_safe)
        df['pnl_display'] = df[pnl_dollar_col] * rates
    elif pnl_dollar_col:
        df['pnl_display'] = df[pnl_dollar_col]
    
    # Handle 5-day P&L currency conversion
    if 'five_day_pnl' in df.columns:
        if 'currency' in df.columns:
            rates = df['currency'].fillna('CAD').astype(str).str.upper().map(get_rate_safe)
            df['five_day_pnl_display'] = df['five_day_pnl'] * rates
        else:
            df['five_day_pnl_display'] = df['five_day_pnl']
    
    # Handle total P&L (unrealized_pnl) currency conversion
    if 'unrealized_pnl' in df.columns:
        if 'currency' in df.columns:
            rates = df['currency'].fillna('CAD').astype(str).str.upper().map(get_rate_safe)
            df['total_pnl_display'] = df['unrealized_pnl'] * rates
        else:
            df['total_pnl_display'] = df['unrealized_pnl']
    
    # Get company names if available
    company_col = None
    if 'securities' in df.columns:
        # Handle nested securities data
        try:
            df['company_name'] = df['securities'].apply(
                lambda x: x.get('company_name', '') if isinstance(x, dict) else ''
            )
            company_col = 'company_name'
        except:
            pass
    elif 'company_name' in df.columns:
        company_col = 'company_name'
    
    # Build result columns (only include columns that exist)
    result_cols = ['ticker']
    if company_col and company_col in df.columns:
        result_cols.append(company_col)
    if pnl_pct_col and pnl_pct_col in df.columns:
        result_cols.append(pnl_pct_col)
    if pnl_dollar_col and 'pnl_display' in df.columns:
        result_cols.append('pnl_display')
    if 'five_day_pnl_pct' in df.columns:
        result_cols.append('five_day_pnl_pct')
    if 'five_day_pnl_display' in df.columns:
        result_cols.append('five_day_pnl_display')
    # Add total return % only if it's different from the daily P&L column
    if 'return_pct' in df.columns and (not pnl_pct_col or pnl_pct_col != 'return_pct'):
        result_cols.append('return_pct')
    if 'total_pnl_display' in df.columns:
        result_cols.append('total_pnl_display')
    if 'current_price' in df.columns:
        result_cols.append('current_price')
    if 'market_value' in df.columns:
        result_cols.append('market_value')
    
    # Filter to only columns that exist
    result_cols = [col for col in result_cols if col in df.columns]
    
    if not result_cols:
        return {'gainers': pd.DataFrame(), 'losers': pd.DataFrame()}
    
    # Get gainers (positive P&L)
    if pnl_pct_col:
        gainers_df = df[df[pnl_pct_col] > 0].nlargest(limit, pnl_pct_col)
    else:
        gainers_df = df[df['pnl_display'] > 0].nlargest(limit, 'pnl_display')
    
    # Get losers (negative P&L)
    if pnl_pct_col:
        losers_df = df[df[pnl_pct_col] < 0].nsmallest(limit, pnl_pct_col)
    else:
        losers_df = df[df['pnl_display'] < 0].nsmallest(limit, 'pnl_display')
    
    # Select only available columns
    if not gainers_df.empty:
        gainers = gainers_df[result_cols].copy()
    else:
        gainers = pd.DataFrame()
    
    if not losers_df.empty:
        losers = losers_df[result_cols].copy()
    else:
        losers = pd.DataFrame()
    
    return {'gainers': gainers, 'losers': losers}


def display_dataframe_with_copy(
    df: pd.DataFrame,
    label: str = "table",
    key_suffix: str = "",
    **dataframe_kwargs
):
    """Display a dataframe with a copy-to-clipboard button.
    
    Exports the complete dataframe as TSV (tab-separated values) for easy copying
    to spreadsheets or sharing for debugging purposes. Includes all column headers.
    
    Args:
        df: DataFrame or Styler object to display
        label: Label for the copy button (e.g., "Trades", "Positions")
        key_suffix: Unique suffix for the button key to avoid conflicts
        **dataframe_kwargs: Additional arguments to pass to st.dataframe()
    
    Example:
        display_dataframe_with_copy(trades_df, label="Trades", key_suffix="recent_trades")
    """
    import streamlit as st
    
    # Check if this is a Styler object (from df.style.format())
    is_styler = hasattr(df, 'data')
    underlying_df = df.data if is_styler else df
    
    # Display the dataframe (styled or not)
    result = st.dataframe(df, **dataframe_kwargs)
    
    # Add copy to clipboard functionality
    # Use underlying DataFrame for export (without styling)
    if not underlying_df.empty:
        # Convert to TSV format with headers
        tsv_data = underlying_df.to_csv(index=False, sep='\t')
        
        # Use an expander to keep the UI clean
        with st.expander(f"📋 Copy {label} to Clipboard", expanded=False):
            st.caption("Click the copy icon in the top-right corner of the box below to copy to clipboard")
            # st.code automatically adds a copy button
            st.code(tsv_data, language=None, line_numbers=False)
            
    return result