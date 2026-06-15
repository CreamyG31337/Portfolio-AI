#!/usr/bin/env python3
"""Debug ownership percentage discrepancy between sidebar and pie chart"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

from supabase_client import SupabaseClient
from streamlit_utils import get_user_investment_metrics, get_investor_allocations
import pandas as pd

client = SupabaseClient(use_service_role=True)
fund = 'Project Chimera'
user_email = 'lance@lancecolt.com'  # Update this to your email

# Get total portfolio value
result = client.supabase.table('portfolio_positions').select(
    'shares, price'
).eq('fund', fund).order('date', desc=True).limit(100).execute()

df = pd.DataFrame(result.data)
if not df.empty:
    df['date'] = pd.to_datetime([r['date'] for r in result.data])
    latest_date = df['date'].max()
    latest = df[df['date'] == latest_date]
    portfolio_value = (latest['shares'].astype(float) * latest['price'].astype(float)).sum()
else:
    portfolio_value = 0

print("="*80)
print("DEBUGGING OWNERSHIP PERCENTAGE DISCREPANCY")
print("="*80)
print(f"\nPortfolio value: ${portfolio_value:,.2f}\n")

# Method 1: get_user_investment_metrics (sidebar)
print("Method 1: get_user_investment_metrics (SIDEBAR)")
try:
    # Note: This function needs user email from session, let's mock it
    import streamlit as st
    st.session_state.user_email = user_email
    
    user_metrics = get_user_investment_metrics(fund, portfolio_value, include_cash=True, session_id='debug')
    if user_metrics:
        ownership_sidebar = user_metrics.get('ownership_pct', 0)
        print(f"  Your units: {user_metrics.get('units', 'N/A')}")
        print(f"  Total units: {user_metrics.get('total_units', 'N/A')}")
        print(f"  Ownership: {ownership_sidebar:.2f}%")
    else:
        print("  No data returned")
        ownership_sidebar = None
except Exception as e:
    print(f"  Error: {e}")
    ownership_sidebar = None

# Method 2: get_investor_allocations (pie chart)
print("\nMethod 2: get_investor_allocations (PIE CHART)")
try:
    allocations = get_investor_allocations(fund, portfolio_value, user_email=user_email, is_admin=True, session_id='debug')
    if not allocations.empty:
        your_row = allocations[allocations['contributor_display'].str.contains('Lance Colton', case=False, na=False)]
        if not your_row.empty:
            ownership_pie = your_row.iloc[0]['ownership_pct']
            print(f"  Your ownership: {ownership_pie:.2f}%")
            print(f"\n  All investors:")
            for row in allocations.to_dict('records'):
                print(f"    {row['contributor_display']}: {row['ownership_pct']:.2f}%")
        else:
            print("  You not found in allocations")
            ownership_pie = None
    else:
        print("  No data returned")
        ownership_pie = None
except Exception as e:
    print(f"  Error: {e}")
    import traceback
    traceback.print_exc()
    ownership_pie = None

# Compare
print("\n" + "="*80)
if ownership_sidebar is not None and ownership_pie is not None:
    diff = abs(ownership_sidebar - ownership_pie)
    print(f"SIDEBAR:   {ownership_sidebar:.2f}%")
    print(f"PIE CHART: {ownership_pie:.2f}%")
    print(f"DIFFERENCE: {diff:.2f}%")
    if diff > 0.1:
        print("\n⚠️  DISCREPANCY DETECTED - Need to investigate!")
else:
    print("Could not compare - one or both methods failed")
