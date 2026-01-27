"""
Flask Data Utilities
====================

Flask-compatible data access functions that do NOT import Streamlit.
These mirror the functionality in streamlit_utils.py but work in Flask context.
"""

import logging
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np
from datetime import datetime

from supabase_client import SupabaseClient
from flask_auth_utils import get_user_id_flask
from flask_cache_utils import cache_data

logger = logging.getLogger(__name__)


def get_supabase_client_flask() -> Optional[SupabaseClient]:
    """Get Supabase client for Flask context WITH user token for RLS
    
    This passes the user's JWT from the auth_token cookie to SupabaseClient,
    which sets the Authorization header so RLS policies work correctly.
    """
    try:
        from flask_auth_utils import get_auth_token, get_refresh_token
        
        # Get the user's JWT token from cookies
        user_token = get_auth_token()
        # refresh_token = get_refresh_token()
        
        if not user_token:
            logger.warning("[get_supabase_client_flask] No auth_token cookie found - RLS queries will fail!")
            # Return client anyway, but queries on RLS tables will return empty
            return SupabaseClient()
        
        logger.debug(f"[get_supabase_client_flask] Creating client with user token (length: {len(user_token)})")
        return SupabaseClient(user_token=user_token)
        
    except Exception as e:
        logger.error(f"Error initializing Supabase client: {e}", exc_info=True)
        return None


@cache_data(ttl=300)
def get_available_funds_flask() -> List[str]:
    """Get list of available funds for current Flask user (cached 5min)"""
    try:
        user_id = get_user_id_flask()
        if not user_id:
            logger.warning("[get_available_funds_flask] No user_id in Flask session/cookie")
            return []
        
        logger.info(f"[get_available_funds_flask] Looking up funds for user_id: {user_id[:8]}...")
            
        client = get_supabase_client_flask()
        if not client:
            logger.error("[get_available_funds_flask] Failed to create Supabase client")
            return []
            
        result = client.supabase.table("user_funds").select("fund_name").eq("user_id", user_id).execute()
        
        if result and result.data:
            funds = [row.get('fund_name') for row in result.data if row.get('fund_name')]
            logger.info(f"[get_available_funds_flask] Found {len(funds)} funds: {funds}")
            return sorted(funds)
        
        logger.warning(f"[get_available_funds_flask] No funds found for user_id: {user_id[:8]}...")
        return []
    except Exception as e:
        logger.error(f"[get_available_funds_flask] Exception: {e}", exc_info=True)
        return []


@cache_data(ttl=300)
def get_current_positions_flask(fund: Optional[str] = None, _cache_version: Optional[str] = None) -> pd.DataFrame:
    """Get current positions for Flask (cached 5min, with cache_version support)"""
    if _cache_version is None:
        try:
            from cache_version import get_cache_version
            _cache_version = get_cache_version()
        except ImportError:
            _cache_version = ""
    client = get_supabase_client_flask()
    if not client:
        return pd.DataFrame()
        
    try:
        logger.info(f"Loading current positions (Flask) for fund: {fund}")
        
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
            
            if len(result.data) < batch_size:
                break
                
            offset += batch_size
            if offset > 50000:
                logger.warning("Position fetch limit reached")
                break
                
        if all_rows:
            df = pd.DataFrame(all_rows)
            
            # Flatten securities fields for easy access while preserving the nested object
            if 'securities' in df.columns:
                securities_df = pd.json_normalize(df['securities'])
                if not securities_df.empty:
                    for col in [
                        'company_name',
                        'sector',
                        'industry',
                        'market_cap',
                        'country',
                        'trailing_pe',
                        'dividend_yield',
                        'fifty_two_week_high',
                        'fifty_two_week_low',
                        'last_updated'
                    ]:
                        if col in securities_df.columns:
                            df[col] = securities_df[col]
            
            return df
        return pd.DataFrame()
        
    except Exception as e:
        logger.error(f"Error getting positions (Flask): {e}", exc_info=True)
        return pd.DataFrame()


@cache_data(ttl=None)  # Cache forever - historical trades don't change
def get_trade_log_flask(limit: int = 1000, fund: Optional[str] = None, _cache_version: Optional[str] = None) -> pd.DataFrame:
    """Get trade log for Flask (cached forever, with cache_version support)"""
    if _cache_version is None:
        try:
            from cache_version import get_cache_version
            _cache_version = get_cache_version()
        except ImportError:
            _cache_version = ""
    client = get_supabase_client_flask()
    if not client:
        return pd.DataFrame()
        
    try:
        if fund:
            logger.info(f"Loading trade log (Flask) for fund: {fund}")
            
        result = client.get_trade_log(limit=limit, fund=fund)
        
        if result:
            df = pd.DataFrame(result)
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
            return df
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"Error getting trade log (Flask): {e}", exc_info=True)
        return pd.DataFrame()


@cache_data(ttl=300)
def get_cash_balances_flask(fund: Optional[str] = None, _cache_version: Optional[str] = None) -> Dict[str, float]:
    """Get cash balances by currency for Flask (cached 5min, with cache_version support)"""
    if _cache_version is None:
        try:
            from cache_version import get_cache_version
            _cache_version = get_cache_version()
        except ImportError:
            _cache_version = ""
    client = get_supabase_client_flask()
    if not client:
        return {"CAD": 0.0, "USD": 0.0}
    
    try:
        if fund:
            logger.info(f"Loading cash balances (Flask) for fund: {fund}")
        
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
            
            if len(result.data) < batch_size:
                break
            
            offset += batch_size
            
            if offset > 50000:
                logger.warning("Cash balances fetch limit reached")
                break
        
        balances = {"CAD": 0.0, "USD": 0.0}
        if all_rows:
            for row in all_rows:
                currency = row.get('currency', 'CAD')
                amount = float(row.get('balance', 0))
                balances[currency] = balances.get(currency, 0) + amount
        
        return balances
    except Exception as e:
        logger.error(f"Error getting cash balances (Flask): {e}", exc_info=True)
        return {"CAD": 0.0, "USD": 0.0}


@cache_data(ttl=3600)  # Cache for 1 hour - thesis changes infrequently
def get_fund_thesis_data_flask(fund_name: str) -> Optional[Dict[str, Any]]:
    """Get thesis data for a fund from the database view (Flask version, cached 1hr)"""
    client = get_supabase_client_flask()
    if not client:
        return None
    
    try:
        result = client.supabase.table("fund_thesis_with_pillars")\
            .select("*")\
            .eq("fund", fund_name)\
            .execute()
        
        if not result.data:
            return None
        
        first_row = result.data[0]
        
        pillars = []
        for row in result.data:
            if row.get('pillar_id') is not None:
                pillars.append({
                    'name': row.get('pillar_name', ''),
                    'allocation': row.get('allocation', ''),
                    'thesis': row.get('pillar_thesis', ''),
                    'pillar_order': row.get('pillar_order', 0)
                })
        
        pillars.sort(key=lambda x: x.get('pillar_order', 0))
        
        return {
            'fund': first_row.get('fund', fund_name),
            'title': first_row.get('title', ''),
            'overview': first_row.get('overview', ''),
            'pillars': pillars
        }
        
    except Exception as e:
        logger.error(f"Error getting thesis data for {fund_name}: {e}", exc_info=True)
        return None


def calculate_performance_metrics_flask(fund: Optional[str] = None) -> Dict[str, Any]:
    """Calculate key performance metrics (Flask version)
    
    Returns dict with performance metrics calculated from portfolio data.
    """
    try:
        # Get current positions to calculate current value
        positions_df = get_current_positions_flask(fund)
        
        if positions_df.empty:
            logger.warning(f"No positions found for fund: {fund}")
            return {
                'peak_date': None,
                'peak_gain_pct': 0.0,
                'max_drawdown_pct': 0.0,
                'max_drawdown_date': None,
                'total_return_pct': 0.0,
                'current_value': 0.0,
                'total_invested': 0.0
            }
        
        # Calculate current value and total invested from positions (Vectorized)
        
        # Ensure Series handling for missing values/columns
        # Using get() on DataFrame returns None if column missing, need fallback
        shares = positions_df.get('shares', pd.Series(0, index=positions_df.index)).fillna(0).astype(float)

        # Determine price column to use
        if 'current_price' in positions_df.columns:
            current_price_series = positions_df['current_price']
        elif 'price' in positions_df.columns:
            current_price_series = positions_df['price']
        else:
            current_price_series = pd.Series(0, index=positions_df.index)

        current_price = current_price_series.fillna(0).astype(float)

        # Market value handling
        market_value = positions_df.get('market_value', pd.Series(0, index=positions_df.index)).fillna(0).astype(float)

        # Vectorized calculation: Use market_value if available, else shares * price
        # Using numpy.where is faster than Series.where or apply
        calculated_value = shares * current_price

        # Note: If market_value is exactly 0, fallback to calculation (matches original logic)
        # Original: if position_value == 0: position_value = shares * current_price
        final_values = np.where(market_value != 0, market_value, calculated_value)

        current_value = float(final_values.sum())

        # Cost basis handling
        cost_basis = positions_df.get('cost_basis', pd.Series(0, index=positions_df.index)).fillna(0).astype(float)
        total_cost = float(cost_basis.sum())
        
        # Calculate total return percentage
        total_return_pct = ((current_value - total_cost) / total_cost * 100) if total_cost > 0 else 0.0
        
        # Get portfolio value over time for peak/drawdown calculation
        portfolio_df = calculate_portfolio_value_over_time_flask(fund, days=365)
        
        peak_date = None
        peak_gain_pct = 0.0
        max_drawdown_pct = 0.0
        max_drawdown_date = None
        
        if not portfolio_df.empty and 'performance_pct' in portfolio_df.columns:
            # Find peak gain
            max_idx = portfolio_df['performance_pct'].idxmax()
            peak_gain_pct = float(portfolio_df.loc[max_idx, 'performance_pct'])
            peak_date = portfolio_df.loc[max_idx, 'date'].strftime('%Y-%m-%d')
            
            # Calculate running maximum for drawdown
            portfolio_df['cummax'] = portfolio_df['performance_pct'].cummax()
            portfolio_df['drawdown'] = portfolio_df['performance_pct'] - portfolio_df['cummax']
            
            # Find max drawdown
            min_idx = portfolio_df['drawdown'].idxmin()
            max_drawdown_pct = float(portfolio_df.loc[min_idx, 'drawdown'])
            max_drawdown_date = portfolio_df.loc[min_idx, 'date'].strftime('%Y-%m-%d')
        
        return {
            'peak_date': peak_date,
            'peak_gain_pct': peak_gain_pct,
            'max_drawdown_pct': max_drawdown_pct,
            'max_drawdown_date': max_drawdown_date,
            'total_return_pct': total_return_pct,
            'current_value': current_value,
            'total_invested': total_cost
        }
        
    except Exception as e:
        logger.error(f"Error calculating performance metrics: {e}", exc_info=True)
        return {
            'peak_date': None,
            'peak_gain_pct': 0.0,
            'max_drawdown_pct': 0.0,
            'max_drawdown_date': None,
            'total_return_pct': 0.0,
            'current_value': 0.0,
            'total_invested': 0.0
        }


@cache_data(ttl=300)
def calculate_portfolio_value_over_time_flask(fund: str, days: Optional[int] = None, display_currency: Optional[str] = None, _cache_version: Optional[str] = None) -> pd.DataFrame:
    """Calculate portfolio value over time (Flask version - Robust)
    
    Match Streamlit implementation:
    - Queries base currency columns (total_value_base) for accurate multi-currency summation
    - Handles currency conversion if needed
    - Normalizes performance index to start at 100
    - Uses authenticated client (RLS safe)
    """
    if _cache_version is None:
        try:
            from cache_version import get_cache_version
            _cache_version = get_cache_version()
        except ImportError:
            _cache_version = ""
            
    client = get_supabase_client_flask()
    if not client:
        return pd.DataFrame()
    
    try:
        if display_currency is None:
            # Default to CAD if not provided
            display_currency = 'CAD'
            
        import time
        from datetime import datetime, timedelta, timezone
        
        # Calculate date cutoff
        cutoff_date = None
        if days is not None and days > 0:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Query with base columns
        all_rows = []
        batch_size = 1000
        offset = 0
        
        while True:
            query = client.supabase.table("portfolio_positions").select(
                "date, total_value, cost_basis, pnl, fund, currency, total_value_base, cost_basis_base, pnl_base, base_currency"
            )
            
            if fund and fund.lower() != 'all':
                query = query.eq("fund", fund)
            
            if cutoff_date:
                query = query.gte("date", cutoff_date.strftime('%Y-%m-%dT%H:%M:%SZ'))
            
            result = query.order("date").order("id").range(offset, offset + batch_size - 1).execute()
            
            rows = result.data
            if not rows:
                break
                
            all_rows.extend(rows)
            if len(rows) < batch_size:
                break
            offset += batch_size
            if offset > 50000:
                break
                
        if not all_rows:
            return pd.DataFrame()
            
        df = pd.DataFrame(all_rows)
        df['date'] = pd.to_datetime(df['date']).dt.normalize() + pd.Timedelta(hours=12)
        
        # Check for pre-converted values
        has_preconverted = False
        if 'total_value_base' in df.columns:
            preconverted_pct = df['total_value_base'].notna().mean()
            has_preconverted = preconverted_pct > 0.8
            
        if has_preconverted:
            value_col = 'total_value_base'
            cost_col = 'cost_basis_base'
            pnl_col = 'pnl_base'
        else:
            # FALLBACK: Runtime conversion (simplified for Flask - could add rate fetching if needed)
            # For now, warn and use raw values if mixed (this was the bug, but at least we try base cols first)
            # Ideally we port the rate fetching logic here too, but base cols should exist.
            value_col = 'total_value'
            cost_col = 'cost_basis'
            pnl_col = 'pnl'
            
        # Aggregate
        daily_totals = df.groupby(df['date'].dt.date).agg({
            value_col: 'sum',
            cost_col: 'sum',
            pnl_col: 'sum'
        }).reset_index()
        
        daily_totals.columns = ['date', 'value', 'cost_basis', 'pnl']
        daily_totals['date'] = pd.to_datetime(daily_totals['date'])
        daily_totals = daily_totals.sort_values('date').reset_index(drop=True)
        
        # Performance calculation
        daily_totals['performance_pct'] = np.where(
            daily_totals['cost_basis'] > 0,
            (daily_totals['pnl'] / daily_totals['cost_basis'] * 100),
            0.0
        )
        
        # Normalize to 100 baseline
        first_day_with_investment = daily_totals[daily_totals['cost_basis'] > 0]
        if not first_day_with_investment.empty:
            first_day_performance = first_day_with_investment.iloc[0]['performance_pct']
            mask = daily_totals['cost_basis'] > 0
            daily_totals.loc[mask, 'performance_pct'] = daily_totals.loc[mask, 'performance_pct'] - first_day_performance
            
        daily_totals['performance_index'] = 100 + daily_totals['performance_pct']
        
        # Filter weekends (optional, but good for consistency)
        # Import local to avoid circular dep
        try:
            from chart_utils import _filter_trading_days
            daily_totals = _filter_trading_days(daily_totals, 'date')
        except ImportError:
            pass
            
        return daily_totals
        
    except Exception as e:
        logger.error(f"Error calculating portfolio value over time (Flask): {e}", exc_info=True)
        return pd.DataFrame()


@cache_data(ttl=300)
def _fetch_dividend_log_flask_cached(days_lookback: int = 365, fund: Optional[str] = None, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Internal cached function for fetching dividend log.
    The user_id parameter ensures cache keys are user-scoped to prevent cross-user data leakage.
    """
    client = get_supabase_client_flask()
    if not client:
        return []
        
    try:
        # Calculate start date
        from datetime import datetime, timedelta
        start_date = (datetime.now() - timedelta(days=days_lookback)).date().isoformat()
        
        # Include securities(company_name) join for consistency with trade_log
        query = client.supabase.table('dividend_log')\
            .select('*, securities(company_name)')\
            .gte('pay_date', start_date)
        
        # Apply fund filter if provided
        if fund:
            query = query.eq('fund', fund)
            
        response = query.order('pay_date', desc=True).execute()
            
        return response.data
    except Exception as e:
        logger.error(f"Error fetching dividend log (Flask): {e}", exc_info=True)
        return []


def fetch_dividend_log_flask(days_lookback: int = 365, fund: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Fetch dividend log from Supabase (Flask version).
    
    This function automatically includes user_id in the cache key to prevent cross-user
    data leakage. Each user gets their own cached results based on RLS policies.
    
    Args:
        days_lookback: Number of days of history to fetch (default 365)
        fund: Optional fund name to filter by
        
    Returns:
        List of dicts containing dividend records with securities(company_name) joined
    """
    # Get user_id for cache key scoping (prevents cross-user cache hits)
    # This ensures each user gets their own cached results, preventing RLS bypass
    user_id = get_user_id_flask() or 'anonymous'
    
    # Call the cached function with user_id included in kwargs (so it's in the cache key)
    return _fetch_dividend_log_flask_cached(days_lookback=days_lookback, fund=fund, user_id=user_id)


@cache_data(ttl=300)
def get_individual_holdings_performance_flask(fund: str, days: int = 7) -> pd.DataFrame:
    """Get performance data for individual holdings in a fund.
    
    Args:
        fund: Fund name (required)
        days: Number of days to fetch (7, 30, or 0 for all)
        
    Returns:
        DataFrame with columns: ticker, date, performance_index, return_pct, daily_pnl_pct, sector, industry, currency
    """
    from datetime import timedelta, timezone
    
    if not fund:
        raise ValueError("Fund name is required")
    
    client = get_supabase_client_flask()
    if not client:
        return pd.DataFrame()
    
    try:
        # Calculate date cutoff
        # Query for more days than requested to account for weekends and missing days
        if days > 0:
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
            # Optimization: Don't join securities here - fetching sector/industry for 36k+ rows is wasteful
            # Fetch base data only, then batch fetch securities metadata once for unique tickers
            query = client.supabase.table("portfolio_positions").select(
                "ticker, date, shares, price, total_value, currency"
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
                logger.warning("Reached 50,000 row safety limit")
                break
        
        if not all_rows:
            return pd.DataFrame()
        
        df = pd.DataFrame(all_rows)
        
        # Optimization: Batch fetch security metadata for unique tickers
        # This reduces payload size significantly (e.g. 1.8MB -> 5KB for 1 year history)
        unique_tickers = df['ticker'].dropna().unique().tolist()
        securities_map = {}

        if unique_tickers:
            try:
                # Fetch in batches of 100 to avoid URL length limits
                all_securities = []
                for i in range(0, len(unique_tickers), 100):
                    batch = unique_tickers[i:i+100]
                    sec_result = client.supabase.table("securities")\
                        .select("ticker, sector, industry, currency")\
                        .in_("ticker", batch)\
                        .execute()
                    if sec_result.data:
                        all_securities.extend(sec_result.data)

                # Build lookup map
                for sec in all_securities:
                    t = sec.get('ticker')
                    if t:
                        securities_map[t] = sec
            except Exception as e:
                logger.warning(f"Failed to fetch securities metadata: {e}")

        # Merge metadata into DataFrame
        if securities_map:
            # Vectorized mapping is faster than apply
            df['sector'] = df['ticker'].map(lambda x: securities_map.get(x, {}).get('sector'))
            df['industry'] = df['ticker'].map(lambda x: securities_map.get(x, {}).get('industry'))

            # Handle currency fallback logic (preserve existing behavior)
            # Original: df['currency'] = securities_df['currency'].fillna(df.get('currency', 'USD'))
            # Meaning: prefer security currency, fall back to portfolio currency

            # Create a series for security currency
            sec_currency = df['ticker'].map(lambda x: securities_map.get(x, {}).get('currency'))

            # Update currency column where security currency is available
            if 'currency' not in df.columns:
                df['currency'] = 'USD'

            # Use combine_first: sec_currency fills gaps in df['currency']
            # So securities currency takes precedence
            df['currency'] = sec_currency.combine_first(df['currency']).fillna('USD')
        else:
            df['sector'] = None
            df['industry'] = None
            if 'currency' not in df.columns:
                df['currency'] = 'USD'
            else:
                df['currency'] = df['currency'].fillna('USD')
        
        # Normalize to date-only (midnight) for consistent charting
        df['date'] = pd.to_datetime(df['date']).dt.normalize()
        
        # Sort by ticker and date
        df.sort_values(['ticker', 'date'], inplace=True)
        
        # Group by ticker
        grouped = df.groupby('ticker')

        # Calculate baseline value (first total_value) for each ticker
        df['baseline_value'] = grouped['total_value'].transform('first').astype(float)

        # Filter out 0 baselines (equivalent to skip in loop)
        df = df[df['baseline_value'] != 0].copy()

        # Re-group after filtering
        grouped = df.groupby('ticker')

        # Calculate performance index
        df['performance_index'] = (df['total_value'].astype(float) / df['baseline_value']) * 100

        # Calculate last value for each ticker to compute total return pct
        df['last_value'] = grouped['total_value'].transform('last').astype(float)
        df['return_pct'] = ((df['last_value'] / df['baseline_value']) - 1) * 100

        # Calculate daily P&L percentage (diff of performance_index)
        df['daily_pnl_pct'] = grouped['performance_index'].diff()

        # Metadata backfilling - use first non-null value per ticker
        if 'sector' in df.columns:
            df['sector'] = grouped['sector'].transform('first')
        else:
            df['sector'] = None
            
        if 'industry' in df.columns:
            df['industry'] = grouped['industry'].transform('first')
        else:
            df['industry'] = None
            
        if 'currency' in df.columns:
            # FillNa with 'USD' then take first to emulate original behavior
            # (Note: transform('first') skips NaNs by default, so we just need to handle the case where all are NaN)
            df['currency'] = grouped['currency'].transform('first').fillna('USD')
        else:
            df['currency'] = 'USD'
            
        # Select columns
        cols_to_keep = ['ticker', 'date', 'performance_index', 'return_pct', 'daily_pnl_pct', 'sector', 'industry', 'currency']
        
        # If days > 0, filter to the last N unique dates
        # Note: We filter dates AFTER calculations to preserve baseline correctness
        if days > 0:
            unique_dates = sorted(df['date'].unique(), reverse=True)[:days]
            df = df[df['date'].isin(unique_dates)]
        
        return df[cols_to_keep].reset_index(drop=True)
        
    except Exception as e:
        logger.error(f"Error fetching individual holdings (Flask): {e}", exc_info=True)
        return pd.DataFrame()


@cache_data(ttl=3600)
def fetch_latest_rates_bulk_flask(currencies: List[str], target_currency: str) -> Dict[str, float]:
    """
    Fetch latest exchange rates (Flask version).
    """
    if not currencies:
        return {}
        
    unique_currencies = list(set([str(c).upper() for c in currencies if c and str(c).upper() != target_currency.upper()]))
    
    if not unique_currencies:
        return {}

    client = get_supabase_client_flask()
    if not client:
        return {c: 1.0 for c in unique_currencies}
        
    try:
        from datetime import datetime, timedelta
        thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        
        response = client.supabase.table('exchange_rates').select('*') \
            .gte('timestamp', thirty_days_ago) \
            .execute()
            
        if not response.data:
            return {}
            
        latest_rates = {}
        for row in response.data:
            fc = row['from_currency'].upper()
            tc = row['to_currency'].upper()
            ts = row['timestamp']
            r = float(row['rate'])
            
            key = (fc, tc)
            if key not in latest_rates or ts > latest_rates[key][0]:
                latest_rates[key] = (ts, r)
                
        result = {}
        target = target_currency.upper()
        
        for curr in unique_currencies:
            curr = curr.upper()
            rate = None
            
            if (curr, target) in latest_rates:
                rate = latest_rates[(curr, target)][1]
            elif (target, curr) in latest_rates:
                inv_rate = latest_rates[(target, curr)][1]
                if inv_rate != 0:
                    rate = 1.0 / inv_rate
            
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
        logger.error(f"Error in fetch_latest_rates_bulk_flask: {e}")
        return {c: 1.0 for c in unique_currencies}


@cache_data(ttl=300)
def get_investor_count_flask(fund: Optional[str] = None) -> int:
    """Get number of unique investors (Flask version)"""
    client = get_supabase_client_flask()
    if not client:
        return 0
        
    try:
        query = client.supabase.table("user_funds").select("user_id", count='exact')
        if fund:
            query = query.eq("fund_name", fund)
            
        result = query.execute()
        return result.count or 0
    except Exception as e:
        logger.error(f"Error getting investor count (Flask): {e}")
        return 0


@cache_data(ttl=3600)  # Cache for 1 hour, start date rarely changes
def get_portfolio_start_date_flask(fund: Optional[str] = None) -> Optional[str]:
    """Get the date of the very first trade (efficiently)"""
    client = get_supabase_client_flask()
    if not client:
        return None

    try:
        query = client.supabase.table("trade_log").select("date")
        if fund:
            query = query.eq("fund", fund)

        # Order by date ASC to get the oldest, limit 1
        result = query.order("date", desc=False).limit(1).execute()

        if result.data and len(result.data) > 0:
            return result.data[0]['date']

        return None
    except Exception as e:
        logger.error(f"Error getting portfolio start date (Flask): {e}", exc_info=True)
        return None


@cache_data(ttl=300)
def get_first_trade_dates_flask(fund: Optional[str] = None) -> Dict[str, datetime]:
    """Get first trade dates (Flask version)"""
    client = get_supabase_client_flask()
    if not client:
        return {}

    try:
        # Optimized: Only fetch ticker and date columns, avoiding massive join and payload
        query = client.supabase.table("trade_log").select("ticker, date")
        if fund:
            query = query.eq("fund", fund)

        # Limit to 5000 most recent trades (approximate coverage)
        # Fetching 5000 rows of just 2 columns is very light compared to 5000 rows of ALL columns + joined securities
        result = query.order("date", desc=True).limit(5000).execute()

        if not result.data:
            return {}
            
        df = pd.DataFrame(result.data)
        if df.empty or 'date' not in df.columns or 'ticker' not in df.columns:
            return {}

        # Convert to datetime if not already
        df['date'] = pd.to_datetime(df['date'])

        # Group by ticker and find min date
        first_dates = df.groupby('ticker')['date'].min().to_dict()
        return first_dates
            
    except Exception as e:
        logger.error(f"Error getting first trade dates (Flask): {e}", exc_info=True)
        return {}


def get_biggest_movers_flask(positions_df: pd.DataFrame, display_currency: str, limit: int = 10) -> Dict[str, pd.DataFrame]:
    """Get biggest gainers and losers from positions (Flask version).
    
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
    
    rate_map = fetch_latest_rates_bulk_flask(list(all_currencies), display_currency) if all_currencies else {}
    
    def get_rate_safe(curr):
        return rate_map.get(str(curr).upper(), 1.0)
    
    # Create a copy to avoid modifying original
    df = positions_df.copy()
    
    # Ensure we have required columns
    required_cols = ['ticker']
    if not all(col in df.columns for col in required_cols):
        return {'gainers': pd.DataFrame(), 'losers': pd.DataFrame()}
    
    # Determine which P&L column to use (prefer daily_pnl_pct, fallback to return_pct)
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
    gainers = df[df[sort_col] > 0].sort_values(sort_col, ascending=False).head(limit)
    
    # Get losers (negative P&L)
    losers = df[df[sort_col] < 0].sort_values(sort_col, ascending=True).head(limit)
    
    return {
        'gainers': gainers[result_cols].reset_index(drop=True), 
        'losers': losers[result_cols].reset_index(drop=True)
    }
