"""
Add NAV-based performance calculation to the graph

Strategy:
1. Get portfolio values over time (already have this)
2. Get contributions over time to calculate total_units at each date
3. Calculate NAV = portfolio_value / total_units
4. Show NAV indexed to 100 at start

This shows TRUE fund performance independent of new money coming in.
"""

# Add to streamlit_utils.py after calculate_portfolio_value_over_time

@log_execution_time()
@st.cache_data(ttl=300)
def calculate_nav_over_time(fund: str, days: Optional[int] = None) -> pd.DataFrame:
    """Calculate NAV (Net Asset Value) over time for proper fund performance tracking.
    
    NAV represents the per-unit value of the fund, allowing proper performance
    comparison over time regardless of when contributions were made.
    
    Args:
        fund: Fund name
        days: Optional number of days to look back
        
    Returns DataFrame with columns:
    - date: datetime
    - nav: Net Asset Value (portfolio value / total units)
    - nav_index: NAV indexed to 100 at start date (for charting)
    """
    from datetime import datetime, timedelta
    import pandas as pd
    
    # Get portfolio values over time
    portfolio_df = calculate_portfolio_value_over_time(fund, days)
    if portfolio_df.empty:
        return pd.DataFrame()
    
    # Get all contributions to calculate total units at each date
    # Use same logic as get_user_investment_metrics
    client = get_supabase_client()
    if not client:
        return pd.DataFrame()
    
    # Fetch ALL contributions for this fund
    all_contributions = []
    batch_size = 1000
    offset = 0
    
    while True:
        result = client.supabase.table("fund_contributions").select(
            "timestamp, amount, contribution_type"
        ).eq("fund", fund).order("timestamp").range(offset, offset + batch_size - 1).execute()
        
        if not result.data:
            break
        all_contributions.extend(result.data)
        if len(result.data) < batch_size:
            break
        offset += batch_size
    
    if not all_contributions:
        return pd.DataFrame()
    
    # Parse contributions
    contributions = []
    for record in all_contributions:
        timestamp_raw = record.get('timestamp', '')
        timestamp = pd.to_datetime(timestamp_raw) if timestamp_raw else None
        
        contributions.append({
            'timestamp': timestamp,
            'amount': float(record.get('amount', 0)),
            'type': record.get('contribution_type', 'CONTRIBUTION').lower()
        })
    
    contributions.sort(key=lambda x: x['timestamp'] or datetime.min)
    
    # Get historical fund values for NAV calculation
    contrib_dates = [c['timestamp'] for c in contributions if c['timestamp']]
    historical_values = get_historical_fund_values(fund, contrib_dates)
    
    # Calculate total_units at each date
    # Use same NAV logic from get_user_investment_metrics
    total_units = 0.0
    units_at_start_of_day = 0.0
    last_contribution_date = None
    
    date_to_units = {}  # Map of date -> total_units
    
    for contrib in contributions:
        amount = contrib['amount']
        timestamp = contrib['timestamp']
        contrib_type = contrib['type']
        
        if not timestamp:
            continue
        
        date_str = timestamp.strftime('%Y-%m-%d')
        
        # Same-day NAV fix
        if date_str != last_contribution_date:
            units_at_start_of_day = total_units
            last_contribution_date = date_str
        
        if contrib_type == 'withdrawal':
            # Redeem units (simplified - just use NAV)
            if date_str in historical_values and units_at_start_of_day > 0:
                nav = historical_values[date_str] / units_at_start_of_day
                units_to_redeem = amount / nav if nav > 0 else 0
                total_units = max(0, total_units - units_to_redeem)
        else:
            # Calculate NAV
            if total_units == 0:
                nav = 1.0
            elif date_str in historical_values:
                units_for_nav = units_at_start_of_day if units_at_start_of_day > 0 else total_units
                nav = historical_values[date_str] / units_for_nav if units_for_nav > 0 else 1.0
            else:
                # Weekend fallback
                nav = 1.0
                contribution_date = datetime.strptime(date_str, '%Y-%m-%d')
                units_for_nav = units_at_start_of_day if units_at_start_of_day > 0 else total_units
                
                for days_back in range(1, 8):
                    prior_date = contribution_date - timedelta(days=days_back)
                    prior_date_str = prior_date.strftime('%Y-%m-%d')
                    
                    if prior_date_str in historical_values and units_for_nav > 0:
                        nav = historical_values[prior_date_str] / units_for_nav
                        break
            
            units = amount / nav if nav > 0 else 0
            total_units += units
        
        # Store units at this date
        date_obj = timestamp.date()
        date_to_units[date_obj] = total_units
    
    # Now calculate NAV for each date in portfolio_df
    nav_data = []
    
    for row in portfolio_df.to_dict('records'):
        date_obj = row['date'].date() if hasattr(row['date'], 'date') else row['date']
        portfolio_value = row['value']
        
        # Find total_units at this date (use last known value if date not in map)
        units = 0.0
        for contrib_date in sorted([d for d in date_to_units.keys() if d <= date_obj], reverse=True):
            units = date_to_units[contrib_date]
            break
        
        if units > 0:
            nav = portfolio_value / units
        else:
            nav = 1.0  # Inception NAV
        
        nav_data.append({
            'date': row['date'],
            'nav': nav,
            'portfolio_value': portfolio_value,
            'total_units': units
        })
    
    if not nav_data:
        return pd.DataFrame()
    
    df = pd.DataFrame(nav_data)
    
    # Calculate NAV index (start at 100)
    if not df.empty and df.iloc[0]['nav'] > 0:
        df['nav_index'] = (df['nav'] / df.iloc[0]['nav']) * 100
    else:
        df['nav_index'] = 100
    
    return df
