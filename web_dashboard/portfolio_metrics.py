#!/usr/bin/env python3
"""NAV-based per-investor portfolio metrics (Flask + Streamlit; no Streamlit UI dependency)."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from currency_display_utils import convert_to_display_currency, get_user_display_currency
from dashboard_constants import CACHE_VERSION
from dashboard_data_clients import get_user_scoped_supabase_client
from flask_cache_utils import cache_data
from supabase_client import SupabaseClient

logger = logging.getLogger(__name__)


def _get_cash_balances(fund: str) -> Dict[str, float]:
    from flask_data_utils import get_cash_balances_flask

    return get_cash_balances_flask(fund)



@cache_data(ttl=None)  # Cache forever - historical data doesn't change
def get_historical_fund_values(fund: str, dates: List[datetime], _cache_version: str = CACHE_VERSION) -> Dict[str, float]:
    """Get historical fund values for specific dates.
    
    Queries portfolio_positions to calculate total fund value at each date.
    Returns the closest available date if exact date not found.
    TODO(bot-pr-180): If reintroducing performance_metrics fast-path queries, enforce explicit base-currency normalization checks before returning totals.
    
    CACHED: Permanently cached. Bump CACHE_VERSION in dashboard_constants.py to invalidate after bug fixes.
    
    Args:
        fund: Fund name
        dates: List of dates to get fund values for
        _cache_version: Cache key version (auto-set from CACHE_VERSION constant)
        
    Returns:
        Dict mapping date string (YYYY-MM-DD) to fund value
    """
    from datetime import datetime
    
    client = get_user_scoped_supabase_client()
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
                for dup in duplicates.head(5).to_dict('records'):
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


def _nav_normalize_email(value: Optional[str]) -> str:
    """Lowercase + strip for comparing login email to contribution / contributor rows."""
    if not value:
        return ""
    return str(value).strip().lower()


def _get_supabase_client_for_nav_contribution_ledger(session_id: str = "unknown"):
    """Client for loading **all** ``fund_contributions`` rows when computing NAV.

    ``portfolio_positions`` / cash RLS often grants **full-fund** market data to anyone who
    has **any** contribution row for that fund (subquery on ``fund_contributions`` by email).
    But ``fund_contributions`` SELECT can return **only rows whose email matches** the viewer
    unless they are also in ``user_funds``. Mixing a **partial** ledger with **full** fund
    value makes total units too small, NAV too large, and one person appear to own the whole fund.

    When ``SUPABASE_SECRET_KEY`` / ``SUPABASE_SERVICE_ROLE_KEY`` is set (normal on the Flask
    server), use the service role **only** for this paginated read; the API still returns
    only the signed-in user's derived metrics.

    Falls back to the user-scoped client if the service key is missing (e.g. some local dev),
    which may reproduce wrong numbers for email-only fund access.
    """
    import logging

    logger = logging.getLogger(__name__)
    if not SupabaseClient:
        return None
    if os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        try:
            logger.debug(
                "[%s] NAV ledger: using service-role Supabase client for fund_contributions",
                session_id,
            )
            return SupabaseClient(use_service_role=True)
        except Exception as e:
            logger.warning(
                "[%s] NAV ledger: service-role client failed (%s); falling back to user JWT",
                session_id,
                e,
            )
    else:
        logger.warning(
            "[%s] NAV ledger: no service role key in env; fund_contributions use user JWT "
            "(per-user NAV can be wrong for contributors who are not in user_funds for the fund)",
            session_id,
        )
    return get_user_scoped_supabase_client()


@cache_data(ttl=300)
def get_user_investment_metrics(
    fund: str,
    total_portfolio_value: float,
    include_cash: bool = True,
    session_id: str = "unknown",
    display_currency: Optional[str] = None,
    user_email: Optional[str] = None,
    user_id: Optional[str] = None,
    _cache_version: str = CACHE_VERSION,
) -> Optional[Dict[str, Any]]:
    """Get investment metrics for the currently logged-in user using NAV-based calculation.

    This calculates the user's investment performance using a unit-based system
    (similar to mutual fund NAV). Investors who join when the fund is worth more
    get fewer units per dollar, resulting in accurate per-investor returns.

    CACHED: ``@st.cache_data`` keys on all arguments including ``user_email``/``user_id``. From Streamlit,
    pass ``user_email=get_user_email() or ""`` so each user gets a separate cache entry. From
    Flask, pass ``get_user_email_flask()`` (never rely on Streamlit session state).

    Args:
        fund: Fund name
        total_portfolio_value: Total portfolio value (positions only, before cash) in display currency
        include_cash: Whether to include cash in total fund value (default True)
        session_id: Session ID for log tracking (default "unknown")
        display_currency: Optional display currency (defaults to user preference)
        user_email: Optional login email. If None, uses Streamlit ``get_user_email()`` only.
        user_id: Optional auth user id. Used as fallback via contributor_access mapping.

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
    from datetime import datetime, timezone, timedelta

    if user_email is not None:
        resolved_email = user_email.strip()
    else:
        try:
            from flask import has_request_context
            from flask_auth_utils import get_user_email_flask

            if has_request_context():
                resolved_email = (get_user_email_flask() or "").strip()
            else:
                resolved_email = ""
        except (ImportError, RuntimeError):
            resolved_email = ""

    resolved_user_id = (user_id or "").strip()
    if not resolved_user_id:
        try:
            from flask import has_request_context
            from flask_auth_utils import get_user_id_flask

            if has_request_context():
                resolved_user_id = (get_user_id_flask() or "").strip()
            else:
                resolved_user_id = ""
        except (ImportError, RuntimeError):
            resolved_user_id = ""

    # Require at least one identifier for matching.
    if not resolved_email and not resolved_user_id:
        return None

    ledger_client = _get_supabase_client_for_nav_contribution_ledger(session_id)
    if not ledger_client:
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
            query = ledger_client.supabase.table("fund_contributions").select(
                "contributor, contributor_id, email, amount, contribution_type, timestamp"
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
        cash_balances = _get_cash_balances(fund)
        
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
                        # Use print when logger may not be available
                        print(f"⚠️  Unexpected timestamp type '{type(timestamp_raw)}' for contributor {record.get('contributor', 'Unknown')}")
                except Exception as e:
                    print(f"⚠️  Could not parse timestamp '{timestamp_raw}' for contributor {record.get('contributor', 'Unknown')}: {e}")
            
            cid = record.get("contributor_id")
            contributions.append({
                'contributor': record.get('contributor', 'Unknown'),
                'contributor_id': str(cid) if cid is not None else None,
                'email': (record.get('email') or '') if record.get('email') is not None else '',
                'amount': float(record.get('amount', 0)),
                'type': record.get('contribution_type', 'CONTRIBUTION').lower(),
                'timestamp': timestamp
            })
        
        # Build contributor_id -> email map from contributors table (source of truth).
        # Used both to hydrate missing row emails and to resolve user identity even when
        # fund_contributions.email is stale/mismatched.
        contributor_id_to_email: Dict[str, str] = {}
        try:
            unique_ids = list({
                c["contributor_id"]
                for c in contributions
                if c.get("contributor_id")
            })
            if unique_ids and ledger_client:
                chunk_size = 80
                for i in range(0, len(unique_ids), chunk_size):
                    chunk = unique_ids[i : i + chunk_size]
                    res = (
                        ledger_client.supabase.table("contributors")
                        .select("id, email")
                        .in_("id", chunk)
                        .execute()
                    )
                    if res.data:
                        for row in res.data:
                            em = (row.get("email") or "").strip()
                            if em:
                                contributor_id_to_email[str(row["id"])] = em
                for c in contributions:
                    cid = c.get("contributor_id")
                    if cid and not _nav_normalize_email(c.get("email")):
                        filled = contributor_id_to_email.get(str(cid))
                        if filled:
                            c["email"] = filled
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "NAV: could not hydrate contributor emails: %s", e, exc_info=True
            )
        
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
                    'email': contrib.get('email') or '',
                    'contributions': 0.0,
                    'withdrawals': 0.0,
                    'net_contribution': 0.0
                }
            else:
                row_em = _nav_normalize_email(contrib.get('email'))
                if row_em and not _nav_normalize_email(contributor_data[contributor].get('email')):
                    contributor_data[contributor]['email'] = (contrib.get('email') or '').strip()
            
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
        
        # Match login to any ledger row's email (not only first stored per contributor name).
        # If that fails, fall back to contributor_access(user_id -> contributor_id) mapping.
        user_email_norm = _nav_normalize_email(resolved_email)
        user_contributor = None
        user_units = 0.0
        if user_email_norm:
            for c in contributions:
                if _nav_normalize_email(c.get('email')) == user_email_norm:
                    user_contributor = c['contributor']
                    user_units = contributor_units.get(user_contributor, 0.0)
                    break
            # Fallback: contributor_id mapped to contributors.email (authoritative identity).
            if user_contributor is None or user_units <= 0:
                for c in contributions:
                    cid = c.get("contributor_id")
                    if not cid:
                        continue
                    mapped_email = _nav_normalize_email(contributor_id_to_email.get(str(cid)))
                    if mapped_email and mapped_email == user_email_norm:
                        user_contributor = c["contributor"]
                        user_units = contributor_units.get(user_contributor, 0.0)
                        if user_units > 0:
                            break

        if (user_contributor is None or user_units <= 0) and resolved_user_id:
            try:
                access_rows = (
                    ledger_client.supabase.table("contributor_access")
                    .select("contributor_id")
                    .eq("user_id", resolved_user_id)
                    .execute()
                )
                accessible_ids = {
                    str(r.get("contributor_id"))
                    for r in (access_rows.data or [])
                    if r.get("contributor_id")
                }
                if accessible_ids:
                    for c in contributions:
                        cid = c.get("contributor_id")
                        if cid and str(cid) in accessible_ids:
                            user_contributor = c["contributor"]
                            user_units = contributor_units.get(user_contributor, 0.0)
                            if user_units > 0:
                                break
            except Exception as e:
                log_message(
                    f"[{session_id}] contributor_access fallback failed: {e}",
                    level="WARNING",
                )
        
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
        logger.error(f"Error getting user investment metrics: {e}", exc_info=True)
        return None