from flask import Blueprint, render_template, request, jsonify, current_app
from datetime import datetime, date, timedelta
import pandas as pd
import logging
from typing import Optional, Dict, Any, List
from collections import Counter

# Import utilities
from flask_auth_utils import get_user_email_flask
from user_preferences import get_user_timezone
from streamlit_utils import get_supabase_client
from flask_data_utils import get_available_funds_flask
from auth import require_auth
# Better to use the one from app context or creating a fresh one
from supabase_client import SupabaseClient

etf_bp = Blueprint('etf_bp', __name__)
logger = logging.getLogger(__name__)

# Change detection thresholds (matching jobs_etf_watchtower.py)
MIN_SHARE_CHANGE = 1000  # Minimum absolute share change to show
MIN_PERCENT_CHANGE = 0.5  # Minimum % change relative to previous holdings

# --- Helper Functions (Migrated from Streamlit) ---


def get_latest_date(db_client) -> Optional[date]:
    """Get latest available date from etf_holdings_log"""
    if db_client is None:
        return None
    try:
        result = db_client.supabase.table("etf_holdings_log").select("date").order("date", desc=True).limit(1).execute()
        if result.data and result.data[0].get('date'):
            return datetime.strptime(result.data[0]['date'], '%Y-%m-%d').date()
        return None
    except Exception as e:
        logger.error(f"Error fetching latest date: {e}")
        return None

def get_available_dates(db_client, etf_ticker: Optional[str] = None) -> List[date]:
    """Get all available dates from etf_holdings_log (for date navigation)"""
    if db_client is None:
        return []
    try:
        query = db_client.supabase.table("etf_holdings_log").select("date")
        if etf_ticker and etf_ticker != "All ETFs":
            query = query.eq("etf_ticker", etf_ticker)
        
        result = query.order("date", desc=True).execute()
        if not result.data:
            return []
        
        # Get unique dates and sort descending
        dates = sorted(list(set([datetime.strptime(row['date'], '%Y-%m-%d').date() for row in result.data])), reverse=True)
        return dates
    except Exception as e:
        logger.error(f"Error fetching available dates: {e}")
        return []


def get_as_of_date(db_client, target_date: date, etf_ticker: Optional[str] = None) -> Optional[date]:
    """Get the most recent date <= target_date (As Of logic)"""
    if db_client is None:
        return None
    try:
        target_date_str = target_date.isoformat()
        query = db_client.supabase.table("etf_holdings_log").select("date").lte("date", target_date_str)
        
        if etf_ticker:
            query = query.eq("etf_ticker", etf_ticker)
        
        result = query.order("date", desc=True).limit(1).execute()
        
        if result.data and result.data[0].get('date'):
            return datetime.strptime(result.data[0]['date'], '%Y-%m-%d').date()
        return None
    except Exception as e:
        logger.error(f"Error fetching As Of date: {e}")
        return None

def check_etf_ownership(db_client, etf_ticker: str) -> Optional[Dict[str, Any]]:
    """Check if user owns shares of the ETF itself"""
    if db_client is None or not etf_ticker:
        return None
    try:
        # Use latest_positions view
        result = db_client.supabase.table("latest_positions").select("shares, fund").eq("ticker", etf_ticker).gt("shares", 0).execute()
        
        if result.data:
            total_shares = sum(row['shares'] for row in result.data)
            funds = ", ".join(set(row['fund'] for row in result.data))
            return {
                'total_shares': total_shares,
                'funds': funds
            }
        return None
    except Exception as e:
        logger.error(f"Error checking ETF ownership for {etf_ticker}: {e}")
        return None

def get_available_etfs(db_client) -> List[Dict[str, str]]:
    """Get all available ETF tickers with names from Supabase"""
    if db_client is None:
        return []
    try:
        holdings_res = db_client.supabase.table("etf_holdings_log").select("etf_ticker").execute()
        if not holdings_res.data:
            return []
        
        tickers = sorted(list(set(row['etf_ticker'] for row in holdings_res.data)))
        
        securities_res = db_client.supabase.table("securities").select("ticker, company_name").in_("ticker", tickers).execute()
        names_map = {row['ticker']: row['company_name'] for row in securities_res.data}
        
        return [{'ticker': t, 'name': names_map.get(t, t)} for t in tickers]
    except Exception as e:
        logger.error(f"Error fetching available ETFs: {e}")
        return []

def get_all_holdings(
    db_client,
    target_date: date,
    etf_ticker: str,
    fund_filter: Optional[str] = None
) -> tuple[pd.DataFrame, Optional[date]]:
    """Get ALL current holdings for a specific ETF using As Of date logic.
    
    Returns:
        tuple: (DataFrame with holdings, actual date used (As Of date))
    """
    if db_client is None:
        return pd.DataFrame(), None
    
    try:
        # Find the most recent date <= target_date (As Of logic)
        as_of_date = get_as_of_date(db_client, target_date, etf_ticker)
        if not as_of_date:
            return pd.DataFrame(), None
        
        as_of_date_str = as_of_date.isoformat()
        holdings_res = db_client.supabase.table("etf_holdings_log").select(
            "date, etf_ticker, holding_ticker, holding_name, shares_held, weight_percent"
        ).eq("date", as_of_date_str).eq("etf_ticker", etf_ticker).gt("shares_held", 0).execute()
        
        if not holdings_res.data:
            return pd.DataFrame(), as_of_date
        
        holdings_df = pd.DataFrame(holdings_res.data)
        holdings_df = holdings_df.rename(columns={'shares_held': 'current_shares'})
        
        # User portfolio overlap
        user_pos_query = db_client.supabase.table("latest_positions").select("ticker, shares, fund").gt("shares", 0)
        
        if fund_filter and fund_filter != "All Funds":
            # Handle multi-select
            if ',' in fund_filter:
                fund_list = fund_filter.split(',')
                user_pos_query = user_pos_query.in_("fund", fund_list)
            else:
                user_pos_query = user_pos_query.eq("fund", fund_filter)
            
        user_pos_res = user_pos_query.execute()
        
        if user_pos_res.data:
            user_df = pd.DataFrame(user_pos_res.data)
            user_agg = user_df.groupby('ticker')['shares'].sum().reset_index()
            user_agg = user_agg.rename(columns={'shares': 'user_shares'})
            
            holdings_df = holdings_df.merge(user_agg, left_on='holding_ticker', right_on='ticker', how='left').drop(columns=['ticker'])
            holdings_df['user_shares'] = holdings_df['user_shares'].fillna(0)
        else:
            holdings_df['user_shares'] = 0
            
        return holdings_df.sort_values(by=['weight_percent', 'current_shares'], ascending=[False, False]), as_of_date
        
    except Exception as e:
        logger.error(f"Error fetching all holdings: {e}", exc_info=True)
        return pd.DataFrame(), None

def get_holdings_changes(
    db_client,
    target_date: date,
    etf_ticker: Optional[str] = None,
    fund_filter: Optional[str] = None
) -> tuple[pd.DataFrame, Optional[date]]:
    """Calculate holdings changes using As Of date logic.
    
    Returns:
        tuple: (DataFrame with changes, actual date used (As Of date))
    """
    if db_client is None:
        return pd.DataFrame(), None
    
    try:
        # For changes view, we need to find the most recent date <= target_date
        # But we need to handle multiple ETFs, so we'll find the date per ETF or use a common date
        # For simplicity, use the latest date <= target_date across all ETFs
        as_of_date = get_as_of_date(db_client, target_date, None)
        if not as_of_date:
            return pd.DataFrame(), None
        
        as_of_date_str = as_of_date.isoformat()
        
        # Fetch current holdings with pagination (for "All ETFs" view or large ETFs)
        curr_holdings_list = []
        page_size = 1000
        offset = 0
        
        while True:
            curr_query = db_client.supabase.table("etf_holdings_log").select(
                "date, etf_ticker, holding_ticker, holding_name, shares_held"
            ).eq("date", as_of_date_str)
            
            if etf_ticker and etf_ticker != "All ETFs":
                curr_query = curr_query.eq("etf_ticker", etf_ticker)
            
            curr_res = curr_query.range(offset, offset + page_size - 1).execute()
            
            if not curr_res.data:
                break
            
            curr_holdings_list.extend(curr_res.data)
            
            # If we got fewer than page_size, we've reached the end
            if len(curr_res.data) < page_size:
                break
            
            offset += page_size
        
        if not curr_holdings_list:
            return pd.DataFrame(), as_of_date
        
        curr_df = pd.DataFrame(curr_holdings_list)
        
        tickers_to_check = curr_df['etf_ticker'].unique().tolist()
        
        # Find latest previous date for each ETF
        hist_res = db_client.supabase.table("etf_holdings_log").select("etf_ticker, date").lt("date", as_of_date_str).in_("etf_ticker", tickers_to_check).order("date", desc=True).execute()
        
        if not hist_res.data:
            # No previous data - all holdings are "new" (first time seeing them)
            # Mark as BUY (new positions) instead of HOLD so they show up in changes view
            curr_df['previous_shares'] = 0
            curr_df['share_change'] = curr_df['shares_held']  # All shares are "new"
            curr_df['percent_change'] = 100.0  # 100% change (new position)
            curr_df['action'] = 'BUY'  # Mark as BUY so they appear in changes view
        else:
            hist_df = pd.DataFrame(hist_res.data)
            latest_prev = hist_df.groupby('etf_ticker')['date'].max().reset_index()
            
            date_groups = latest_prev.groupby('date')['etf_ticker'].apply(list).reset_index()
            
            prev_holdings_list = []
            for _, date_row in date_groups.iterrows():
                batch_date = date_row['date']
                batch_etfs = date_row['etf_ticker']
                
                # Use pagination to fetch all holdings (for ETFs with >1000 holdings like IWM)
                page_size = 1000
                offset = 0
                while True:
                    p_res = db_client.supabase.table("etf_holdings_log").select(
                        "etf_ticker, holding_ticker, shares_held"
                    ).eq("date", batch_date).in_("etf_ticker", batch_etfs).range(offset, offset + page_size - 1).execute()
                    
                    if not p_res.data:
                        break
                    
                    prev_holdings_list.extend(p_res.data)
                    
                    # If we got fewer than page_size, we've reached the end
                    if len(p_res.data) < page_size:
                        break
                    
                    offset += page_size
            
            if prev_holdings_list:
                prev_df = pd.DataFrame(prev_holdings_list)
                prev_df = prev_df.rename(columns={'shares_held': 'previous_shares'})
                
                merged_df = curr_df.merge(
                    prev_df, 
                    on=['etf_ticker', 'holding_ticker'], 
                    how='outer'
                )
                
                merged_df['shares_held'] = merged_df['shares_held'].fillna(0)
                merged_df['previous_shares'] = merged_df['previous_shares'].fillna(0)
                
                merged_df['share_change'] = merged_df['shares_held'] - merged_df['previous_shares']
                
                def calc_pct(row):
                    if row['previous_shares'] > 0:
                        return (row['share_change'] / row['previous_shares']) * 100
                    return 0
                
                merged_df['percent_change'] = merged_df.apply(calc_pct, axis=1)
                
                def determine_action(row):
                    if row['previous_shares'] == 0 and row['shares_held'] > 0: return 'BUY'
                    if row['shares_held'] > row['previous_shares']: return 'BUY'
                    if row['shares_held'] < row['previous_shares']: return 'SELL'
                    return 'HOLD'
                
                merged_df['action'] = merged_df.apply(determine_action, axis=1)
                curr_df = merged_df
            else:
                # No previous holdings found (even though hist_res had data, no actual holdings)
                # Mark all as new positions (BUY)
                curr_df['previous_shares'] = 0
                curr_df['share_change'] = curr_df['shares_held']  # All shares are "new"
                curr_df['percent_change'] = 100.0  # 100% change (new position)
                curr_df['action'] = 'BUY'  # Mark as BUY so they appear in changes view
        
        curr_df = curr_df.rename(columns={'shares_held': 'current_shares'})
        
        # Note: We show ALL changes on the web page (not just "significant" ones)
        # The MIN_SHARE_CHANGE and MIN_PERCENT_CHANGE thresholds are used by the job
        # to generate articles, but for the web UI we want to show all changes so users
        # can see everything that's happening. Users can filter if needed.
        # 
        # Mark significant changes for potential future use (e.g., highlighting)
        if not curr_df.empty:
            significant_mask = (
                (curr_df['share_change'].abs() >= MIN_SHARE_CHANGE) |
                (curr_df['percent_change'].abs() >= MIN_PERCENT_CHANGE)
            )
            curr_df['is_significant'] = significant_mask
        
        # Filter systematic adjustments (same logic as job)
        # Only filter if we have enough data to make a determination
        if not curr_df.empty and len(curr_df) > 5:
            # Group by ETF for systematic adjustment detection
            etfs_to_remove = []
            for etf in curr_df['etf_ticker'].unique():
                etf_changes = curr_df[
                    (curr_df['etf_ticker'] == etf) & 
                    (curr_df['action'] != 'HOLD') &
                    (curr_df['share_change'] != 0)
                ]
                
                if len(etf_changes) > 5:
                    # Check for systematic adjustment pattern
                    percent_changes = [abs(p) for p in etf_changes['percent_change'] if pd.notna(p)]
                    if len(percent_changes) > 5:
                        rounded_pcts = [round(p, 1) for p in percent_changes]
                        pct_counts = Counter(rounded_pcts)
                        most_common_pct, most_common_count = pct_counts.most_common(1)[0]
                        
                        # If 80%+ cluster around same percentage ≤2%, and all same direction
                        if (most_common_count >= len(etf_changes) * 0.8 and 
                            most_common_pct <= 2.0):
                            # Check if all changes are in the same direction
                            etf_change_indices = etf_changes.index
                            share_changes = curr_df.loc[etf_change_indices, 'share_change']
                            all_same_dir = (
                                all(share_changes > 0) or
                                all(share_changes < 0)
                            )
                            
                            if all_same_dir:
                                # Mark this ETF for removal (systematic adjustment)
                                logger.debug(f"Filtering systematic adjustment for {etf}: {most_common_count}/{len(etf_changes)} changes at ~{most_common_pct:.1f}%")
                                etfs_to_remove.append(etf)
            
            # Remove all ETFs that were flagged as systematic adjustments
            if etfs_to_remove:
                curr_df = curr_df[~curr_df['etf_ticker'].isin(etfs_to_remove)].copy()
        
        # User overlap
        max_date_res = db_client.supabase.table("portfolio_positions").select("date").order("date", desc=True).limit(1).execute()
        if max_date_res.data:
            max_date = max_date_res.data[0]['date']
            user_pos_query = db_client.supabase.table("portfolio_positions").select("ticker, quantity, fund").eq("date", max_date).gt("quantity", 0)
            
            if fund_filter and fund_filter != "All Funds":
                # Handle multi-select
                if ',' in fund_filter:
                    fund_list = fund_filter.split(',')
                    user_pos_query = user_pos_query.in_("fund", fund_list)
                else:
                    user_pos_query = user_pos_query.eq("fund", fund_filter)

            user_pos_res = user_pos_query.execute()
            
            if user_pos_res.data:
                user_df = pd.DataFrame(user_pos_res.data)
                user_agg = user_df.groupby('ticker')['quantity'].sum().reset_index()
                user_agg = user_agg.rename(columns={'quantity': 'user_shares'})
                
                curr_df = curr_df.merge(user_agg, left_on='holding_ticker', right_on='ticker', how='left').drop(columns=['ticker'])
                curr_df['user_shares'] = curr_df['user_shares'].fillna(0)
            else:
                curr_df['user_shares'] = 0
        else:
            curr_df['user_shares'] = 0
            
        return curr_df, as_of_date
    except Exception as e:
        logger.error(f"Error fetching holdings changes: {e}", exc_info=True)
        return pd.DataFrame(), None

# --- Route ---

@etf_bp.route('/etf_holdings', methods=['GET'])
@require_auth
def etf_holdings():
    from app import get_navigation_context
    
    # 1. Navigation & Context
    nav_context = get_navigation_context(current_page='etf_holdings')
    user_email = get_user_email_flask()
    # Use service role to bypass RLS - this is server-side and already protected by @require_auth
    db_client = SupabaseClient(use_service_role=True)
    
    if not db_client:
         return render_template('etf_holdings.html', 
                               error="Database Unavailable", 
                               error_message="Could not connect to Supabase.",
                               **nav_context)

    # 2. Parameters
    # Note: refresh_key is no longer used, kept for backwards compatibility
    refresh_key = request.args.get('refresh_key', 0)
    selected_etf = request.args.get('etf', 'All ETFs')  # Default to "All ETFs" to show changes view
    selected_date_str = request.args.get('date')
    selected_fund = request.args.get('fund', 'All Funds')
    change_type_filter = request.args.get('change_type', 'ALL')  # NEW, SOLD, BUY, SELL, ALL
    # Default to True (show changes only, hide HOLD) if not specified
    # Hidden input always sends a value ('true' or 'false'), so we can default to 'true'
    changes_only_param = request.args.get('changes_only', 'true')  # Default to 'true' (checked)
    changes_only = changes_only_param == 'true'  # Show changes only when 'true'
    
    latest_date = get_latest_date(db_client)
    
    # Default to latest available date if no date specified
    if selected_date_str:
        try:
            selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
        except ValueError:
            selected_date = latest_date or date.today()
    else:
        # No date specified - use latest available date to show most recent changes
        selected_date = latest_date or date.today()

    # 3. Available ETFs & Funds
    available_etfs_list = get_available_etfs(db_client)
    available_funds_list = get_available_funds_flask()
    
    # Initialize for later use
    as_of_date = None
    prev_date = None
    next_date = None
    
    # 4. View Mode & Data Fetching
    # Default to "changes" view (show all ETF changes) when no ETF is selected
    view_mode = "changes"
    etf_ownership = None
    
    if selected_etf and selected_etf != "All ETFs":
        # Single ETF selected - show holdings view
        view_mode = "holdings"
        changes_df, as_of_date = get_all_holdings(db_client, selected_date, selected_etf, selected_fund)
        etf_ownership = check_etf_ownership(db_client, selected_etf)
    else:
        # "All ETFs" or no selection - show changes view (default behavior)
        view_mode = "changes"
        changes_df, as_of_date = get_holdings_changes(db_client, selected_date, None, selected_fund)
        
        # Log for debugging
        if changes_df.empty:
            logger.warning(f"No changes found for date {selected_date}, as_of_date={as_of_date}")
        else:
            logger.info(f"Found {len(changes_df)} changes before filtering (date={selected_date}, as_of_date={as_of_date})")
        
        # Filter out HOLD actions by default in changes view (only show actual changes)
        # The checkbox "Show changes only" is checked by default - hide HOLD unless user unchecks it
        if not changes_df.empty and changes_only:
            # Hide HOLD actions (show only actual changes)
            before_filter = len(changes_df)
            changes_df = changes_df[changes_df['action'] != 'HOLD'].copy()
            after_filter = len(changes_df)
            if before_filter != after_filter:
                logger.debug(f"Filtered out {before_filter - after_filter} HOLD actions, {after_filter} changes remaining")
        
        # Apply change type filter for changes view
        if not changes_df.empty and change_type_filter != 'ALL':
            if change_type_filter == 'NEW':
                # New positions: BUY where previous_shares = 0
                changes_df = changes_df[(changes_df['action'] == 'BUY') & (changes_df['previous_shares'] == 0)]
            elif change_type_filter == 'SOLD':
                # Sold positions: current_shares = 0 (completely sold)
                changes_df = changes_df[changes_df['current_shares'] == 0]
            elif change_type_filter == 'BUY':
                # All buy actions (including new)
                changes_df = changes_df[changes_df['action'] == 'BUY']
            elif change_type_filter == 'SELL':
                # All sell actions (including fully sold)
                changes_df = changes_df[changes_df['action'] == 'SELL']
    
    # Get all available dates for navigation AFTER we have as_of_date
    # For "All ETFs", we want all dates across all ETFs (pass None)
    # For specific ETF, we want dates for that ETF only
    available_dates = get_available_dates(db_client, selected_etf if selected_etf != "All ETFs" else None)
    
    # Calculate previous and next dates AFTER we have as_of_date from data fetching
    if as_of_date and available_dates:
        # Convert available_dates to date objects if they're strings
        available_dates_clean = []
        for d in available_dates:
            if isinstance(d, str):
                try:
                    available_dates_clean.append(datetime.strptime(d, '%Y-%m-%d').date())
                except ValueError:
                    continue
            elif isinstance(d, date):
                available_dates_clean.append(d)
        
        if available_dates_clean:
            # Find current position in available dates
            try:
                current_idx = available_dates_clean.index(as_of_date)
                # Next date is earlier (dates are sorted descending)
                if current_idx < len(available_dates_clean) - 1:
                    next_date = available_dates_clean[current_idx + 1]
                # Prev date is later
                if current_idx > 0:
                    prev_date = available_dates_clean[current_idx - 1]
            except ValueError:
                # as_of_date not in list, find closest
                # This can happen if as_of_date is calculated differently than available_dates
                # Find the closest date in available_dates_clean
                closest_idx = None
                min_diff = None
                for i, d in enumerate(available_dates_clean):
                    diff = abs((d - as_of_date).days)
                    if min_diff is None or diff < min_diff:
                        min_diff = diff
                        closest_idx = i
                
                if closest_idx is not None:
                    # Use closest date as current position
                    if closest_idx < len(available_dates_clean) - 1:
                        next_date = available_dates_clean[closest_idx + 1]
                    if closest_idx > 0:
                        prev_date = available_dates_clean[closest_idx - 1]
                else:
                    # Fallback: find dates around as_of_date
                    for i, d in enumerate(available_dates_clean):
                        if d <= as_of_date:
                            if i > 0:
                                prev_date = available_dates_clean[i - 1]
                            if i < len(available_dates_clean) - 1:
                                next_date = available_dates_clean[i + 1]
                            break

    
    # 5. Process Data for Frontend (JSON)
    if not changes_df.empty:
        # Fill NaNs for JSON serialization
        changes_df = changes_df.fillna({
            'user_shares': 0,
            'current_shares': 0,
            'weight_percent': 0,
            'previous_shares': 0,
            'share_change': 0,
            'percent_change': 0
        })
        
        # Add formatted columns for easier JS display? 
        # Actually AgGrid can handle formatting, but pre-formatting in Python is sometimes easier 
        # equivalent to Streamlit's `apply`. 
        # Let's send raw data and format in JS (better for sorting).
        
        # Ensure we have all expected columns
        if 'action' not in changes_df.columns:
            changes_df['action'] = 'HOLD' # For holdings view
        
        # Batch fetch logo URLs for all tickers (caching-friendly pattern)
        # Get unique tickers from both holding_ticker and etf_ticker columns
        unique_tickers = set()
        if 'holding_ticker' in changes_df.columns:
            unique_tickers.update(changes_df['holding_ticker'].dropna().unique())
        if 'etf_ticker' in changes_df.columns:
            unique_tickers.update(changes_df['etf_ticker'].dropna().unique())
        
        logo_urls_map = {}
        if unique_tickers:
            try:
                from web_dashboard.utils.logo_utils import get_ticker_logo_urls
                logo_urls_map = get_ticker_logo_urls(list(unique_tickers))
            except Exception as e:
                logger.warning(f"Error fetching logo URLs: {e}")
        
        # Add logo URLs to DataFrame
        if 'holding_ticker' in changes_df.columns:
            changes_df['_holding_logo_url'] = changes_df['holding_ticker'].map(lambda x: logo_urls_map.get(x) if x else None)
        if 'etf_ticker' in changes_df.columns:
            changes_df['_etf_logo_url'] = changes_df['etf_ticker'].map(lambda x: logo_urls_map.get(x) if x else None)
            
        data_json = changes_df.to_dict(orient='records')
    else:
        data_json = []

    # 6. Summary Stats (for Changes View)
    stats = {}
    if view_mode == "changes" and not changes_df.empty:
        significant = changes_df[changes_df['action'] != 'HOLD']
        bullish = significant[significant['action'] == 'BUY']
        bearish = significant[significant['action'] == 'SELL']
        
        stats = {
            'total_changes': len(significant),
            'bullish_count': len(bullish),
            'bearish_count': len(bearish),
            'total_etfs': changes_df['etf_ticker'].nunique() if 'etf_ticker' in changes_df.columns else 0
        }
        
        # Identify largest moves
        if not bullish.empty:
             largest_buy_row = bullish.loc[bullish['share_change'].idxmax()]
             stats['largest_buy'] = {
                 'ticker': largest_buy_row['holding_ticker'],
                 'etf': largest_buy_row['etf_ticker'],
                 'change': largest_buy_row['share_change']
             }
             
        if not bearish.empty:
             largest_sell_row = bearish.loc[bearish['share_change'].idxmin()]
             stats['largest_sell'] = {
                 'ticker': largest_sell_row['holding_ticker'],
                 'etf': largest_sell_row['etf_ticker'],
                 'change': largest_sell_row['share_change']
             }

    # Remove available_funds from nav_context to avoid duplicate when we pass it explicitly
    nav_context_clean = {k: v for k, v in nav_context.items() if k != 'available_funds'}
    
    return render_template(
        'etf_holdings.html',
        nav_context=nav_context,
        user_email=user_email,
        
        # Params
        current_etf=selected_etf,
        current_date=selected_date.strftime('%Y-%m-%d'),
        as_of_date=as_of_date.strftime('%Y-%m-%d') if as_of_date else None,
        date_has_data=as_of_date == selected_date if as_of_date else False,
        current_fund=selected_fund,
        current_change_type=change_type_filter,
        current_changes_only=changes_only,
        latest_date=latest_date.strftime('%Y-%m-%d') if latest_date else date.today().strftime('%Y-%m-%d'),
        prev_date=prev_date.strftime('%Y-%m-%d') if prev_date else None,
        next_date=next_date.strftime('%Y-%m-%d') if next_date else None,
        available_etfs=available_etfs_list,
        available_funds=available_funds_list,
        
        # Data
        view_mode=view_mode,
        holdings_data=data_json,
        etf_ownership=etf_ownership,
        stats=stats,
        
        **nav_context_clean # Explode nav_context (without available_funds) for template
    )
