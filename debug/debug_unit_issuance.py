import os
import sys
import pandas as pd
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web_dashboard.supabase_client import SupabaseClient

client = SupabaseClient()
fund_name = 'Project Chimera'

def get_historical_fund_values_local(fund, dates):
    """Local version without Streamlit dependencies"""
    if not dates:
        return {}, {}
        
    date_strs = sorted(set(d.strftime('%Y-%m-%d') for d in dates if d))
    if not date_strs:
        return {}, {}
        
    min_date = min(date_strs)
    
    # Query portfolio_positions
    all_rows = []
    batch_size = 1000
    offset = 0
    
    while True:
        result = client.supabase.table("portfolio_positions").select(
            "date, shares, price, currency, cost_basis, total_value_base"
        ).eq("fund", fund).gte("date", min_date).order("date").range(offset, offset + batch_size - 1).execute()
        
        if not result.data:
            break
            
        all_rows.extend(result.data)
        if len(result.data) < batch_size:
            break
        offset += batch_size

    if not all_rows:
        return {}, {}

    # Calculate daily values
    values_by_date = {}
    
    for row in all_rows:
        date_str = row['date'][:10]
        # Use pre-converted value if available, else calculate
        if row.get('total_value_base'):
            value = float(row['total_value_base'])
        else:
            # Simple approximation for debug - ignore currency conversion for now
            # Assume 1.40 for USD if no base value (rough check)
            val = float(row.get('shares',0)) * float(row.get('price',0))
            if row.get('currency') == 'USD':
                val *= 1.40
            value = val
            
        if date_str not in values_by_date:
            values_by_date[date_str] = 0.0
        values_by_date[date_str] += value
        
    # Map requested dates to values
    result_values = {}
    available_dates = sorted(values_by_date.keys())
    
    for date_str in date_strs:
        if date_str in values_by_date:
            result_values[date_str] = values_by_date[date_str]
        else:
            # Find closest previous
            closest = None
            for avail in available_dates:
                if avail <= date_str:
                    closest = avail
                else:
                    break
            if closest:
                result_values[date_str] = values_by_date[closest]
                
    return result_values, {}

# 1. Fetch contributions
print("Fetching contributions...")
contribs = client.supabase.table('fund_contributions') \
    .select('*') \
    .eq('fund', fund_name) \
    .order('timestamp') \
    .execute()

df_contribs = pd.DataFrame(contribs.data)
df_contribs['timestamp'] = pd.to_datetime(df_contribs['timestamp'])
df_contribs['date'] = df_contribs['timestamp'].dt.date

# 2. Fetch historical fund values
print("\nFetching historical fund values...")
dates_to_check = df_contribs['timestamp'].tolist()
historical_values, _ = get_historical_fund_values_local(fund_name, dates_to_check)

print(f"Found {len(historical_values)} historical value points")

# 3. Simulate Unit Calculation
print("\n--- Simulating Unit Issuance ---")
STARTING_NAV = 10.0
total_units = 0.0
investor_units = {}

running_cash = 0.0

for row in df_contribs.to_dict('records'):
    date_str = row['timestamp'].strftime('%Y-%m-%d')
    email = row['email']
    amount = float(row['amount'])
    
    # Get portfolio value (assets)
    portfolio_value = historical_values.get(date_str, 0.0)
    
    # Fund Value = Portfolio Assets + Cash form previous contributions
    # NOTE: This is a simplification. The actual dashboard does this differently 
    # depending on if "portfolio_value" includes the cash deployed or not.
    # Usually Portfolio Value = Market Value of Stocks.
    # Total Fund Value = Market Value of Stocks + Cash on Hand.
    
    total_fund_value = portfolio_value + running_cash
    
    # Calculate NAV
    if total_units == 0:
        nav = STARTING_NAV
    else:
        if total_fund_value == 0:
             print(f"⚠️  WARNING: Fund Value is 0 on {date_str} but units exist!")
             nav = 10.0
        else:
            nav = total_fund_value / total_units
            
    units_issued = amount / nav
    
    if email not in investor_units:
        investor_units[email] = 0.0
    investor_units[email] += units_issued
    total_units += units_issued
    running_cash += amount
    
    user_display = email.split('@')[0] if email else "UNKNOWN"
    print(f"Date: {date_str} | User: {user_display} | Amt: ${amount:,.2f} | PortVal: ${portfolio_value:,.2f} | NAV: ${nav:.2f} -> Units: {units_issued:.2f}")

print("\n--- Final Ownership ---")
df_units = pd.DataFrame([{'email': k, 'units': v} for k, v in investor_units.items()])
df_units['pct'] = (df_units['units'] / total_units) * 100
df_units['contrib'] = df_units['email'].map(df_contribs.groupby('email')['amount'].sum())
print(df_units.sort_values('pct', ascending=False))
