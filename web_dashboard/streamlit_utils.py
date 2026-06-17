#!/usr/bin/env python3
# NOTE: Historical name—Streamlit pages still import this module. Shared constants,
# currency helpers, and NAV metrics live in dashboard_constants.py, currency_display_utils.py,
# and portfolio_metrics.py; Flask production should import those directly.

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


def _streamlit_cache_data(ttl: Optional[int] = 3600):
    """Use Streamlit cache when available; no-op decorator when Streamlit is not installed."""
    if st is not None and hasattr(st, "cache_data"):
        return st.cache_data(ttl=ttl)

    def _noop_decorator(func):
        return func

    return _noop_decorator


from dashboard_constants import CACHE_VERSION, SUPPORTED_CURRENCIES, get_cache_ttl, get_supported_currencies
from currency_display_utils import (
    convert_to_display_currency,
    fetch_latest_rates_bulk,
    get_exchange_rate_for_display,
    get_user_display_currency,
)
from portfolio_metrics import get_historical_fund_values, get_user_investment_metrics


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
                    # IMPORTANT: Only use a validated Supabase access token in Flask context.
                    # get_auth_token() may return legacy session_token, which is not a Supabase JWT
                    # and will fail Supabase auth.set_session() signature verification.
                    from flask_auth_utils import get_supabase_access_token
                    user_token = get_supabase_access_token()
                    # refresh_token is intentionally not pulled here to avoid auto-refresh loops in Flask.
                    if user_token:
                        logger.debug(f"[AUTH] Found token in Flask context (length: {len(user_token)})")
                    else:
                        logger.debug("[AUTH] No valid Supabase access token found in Flask cookies")
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
@_streamlit_cache_data(ttl=300)
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
@_streamlit_cache_data(ttl=None)  # Cache forever - historical trades don't change
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
@_streamlit_cache_data(ttl=300)
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
        # OPTIMIZATION: Replaced iterrows() with to_dict('records') for O(1) bulk conversion and faster iteration
        for trade in sell_trades.to_dict('records'):
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
@_streamlit_cache_data(ttl=300)
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
@_streamlit_cache_data(ttl=300)
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
            from routes.fund_cash_balance_utils import cash_amount_from_row

            for row in all_rows:
                currency = str(row.get("currency", "CAD")).upper()
                amount = cash_amount_from_row(row)
                balances[currency] = balances.get(currency, 0) + amount
        
        return balances
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting cash balances: {e}", exc_info=True)
        return {"CAD": 0.0, "USD": 0.0}


@log_execution_time()
@_streamlit_cache_data(ttl=300)
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
                        for row in unique_combos.itertuples(index=False):
                            date_val = getattr(row, "date_normalized")
                            curr_val = getattr(row, "currency_normalized")
                            
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
                        for row in unique_combos.itertuples(index=False):
                            date_val = getattr(row, "date_normalized")
                            curr_val = getattr(row, "currency_normalized")
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
                    for row in unique_combos.itertuples(index=False):
                        date_val = getattr(row, "date_normalized")
                        curr_val = getattr(row, "currency_normalized")
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
            # OPTIMIZATION: Use list comprehension instead of pd.json_normalize which is very slow
            sec_col = df['securities'].tolist()
            for col in ['sector', 'industry', 'currency']:
                df[f'sec_{col}'] = [s.get(col) if isinstance(s, dict) else None for s in sec_col]

            # Merge sector and industry from securities only if present
            if df['sec_sector'].notna().any() or 'sector' not in df.columns:
                df['sector'] = df['sec_sector']
            if df['sec_industry'].notna().any() or 'industry' not in df.columns:
                df['industry'] = df['sec_industry']

            # Use securities currency if available, otherwise use position currency
            if 'currency' in df.columns:
                df['currency'] = df['sec_currency'].fillna(df['currency'])
            else:
                df['currency'] = df['sec_currency'].fillna('USD')

            # Drop temporary columns and original securities column
            df = df.drop(columns=['securities', 'sec_sector', 'sec_industry', 'sec_currency'], errors='ignore')
        
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


@_streamlit_cache_data(ttl=3600)  # 1 hour - contributor list changes infrequently
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

@log_execution_time()
@_streamlit_cache_data(ttl=3600)  # Cache for 1 hour - thesis doesn't change frequently
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
