#!/usr/bin/env python3
"""Debug: Check what get_user_investment_metrics returns vs what trace script calculates"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

from supabase_client import SupabaseClient
from streamlit_utils import get_user_investment_metrics, get_cash_balances
import pandas as pd

client = SupabaseClient(use_service_role=True)

# Get current portfolio positions for Project Chimera
print("="*80)
print("Getting current portfolio value...")
print("="*80)

pos_res = client.supabase.table('latest_positions').select('*').eq('fund', 'Project Chimera').execute()
if pos_res.data:
    df = pd.DataFrame(pos_res.data)
    print(f"Found {len(df)} positions")
    
    # Calculate portfolio value (no cash)
    portfolio_value = 0.0
    for row in df.to_dict('records'):
        market_value = float(row.get('market_value', 0) or 0)
        currency = str(row.get('currency', 'CAD')).upper() if pd.notna(row.get('currency')) else 'CAD'
        if currency == 'USD':
            portfolio_value += market_value * 1.42  # Use approximate rate
        else:
            portfolio_value += market_value
    
    print(f"Portfolio value (no cash): ${portfolio_value:,.2f}")
    
    # Get cash
    cash = get_cash_balances('Project Chimera')
    total_cash = cash.get('CAD', 0) + (cash.get('USD', 0) * 1.42)
    print(f"Cash: ${total_cash:,.2f}")
    print(f"Total fund value: ${portfolio_value + total_cash:,.2f}")
    
    # Call get_user_investment_metrics for Lance
    print("\n" + "="*80)
    print("Calling get_user_investment_metrics...")
    print("="*80)
    
    # Need to mock streamlit session
    class MockStreamlit:
        class cache_data:
            @staticmethod
            def __call__(*args, **kwargs):
                def decorator(func):
                    return func
                return decorator
    
    import streamlit_utils
    import sys
    sys.modules['streamlit'] = type(sys)('streamlit')
    sys.modules['streamlit'].cache_data = MockStreamlit.cache_data
    
    # Mock auth to return Lance's email
    import auth_utils
    auth_utils.get_user_email = lambda: 'lance.colton@gmail.com'
    
    result = get_user_investment_metrics('Project Chimera', portfolio_value, include_cash=True, session_id='debug')
    
    if result:
        print(f"\nRESULT:")
        print(f"  Net Contribution: ${result['net_contribution']:,.2f}")
        print(f"  Current Value: ${result['current_value']:,.2f}")
        print(f"  Gain/Loss: ${result['gain_loss']:,.2f}")
        print(f"  Return %: {result['gain_loss_pct']:.2f}%")
        print(f"  Ownership %: {result['ownership_pct']:.2f}%")
    else:
        print("No result returned!")
else:
    print("No positions found!")
