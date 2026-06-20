#!/usr/bin/env python3
"""
FINAL PROPER NAV CALCULATION

Key fixes:
1. Fund Value = Stock Value + Uninvested Cash
2. Uninvested Cash = (Contributions at start of day) - (Cost Basis)
3. All same-day contributions use the SAME NAV (start-of-day)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

from supabase_client import SupabaseClient
from datetime import datetime, timedelta
import pandas as pd

client = SupabaseClient(use_service_role=True)
fund = 'Project Chimera'

# Get all contributions
result = client.supabase.table('fund_contributions').select(
    'contributor, email, amount, contribution_type, timestamp'
).eq('fund', fund).order('timestamp').execute()

contributions = []
for r in result.data:
    contributions.append({
        'contributor': r['contributor'],
        'email': r.get('email', ''),
        'amount': float(r['amount']),
        'type': r.get('contribution_type', 'CONTRIBUTION').lower(),
        'timestamp': r.get('timestamp')
    })

# Get historical STOCK values AND cost basis
positions_result = client.supabase.table('portfolio_positions').select(
    'date, shares, price, cost_basis, currency'
).eq('fund', fund).execute()

daily_stock_value = {}
daily_cost_basis = {}

if positions_result.data:
    df = pd.DataFrame(positions_result.data)
    df['date'] = pd.to_datetime(df['date'])
    df['price'] = df['price'].astype(float)
    df['shares'] = df['shares'].astype(float)
    df['cost_basis'] = df['cost_basis'].astype(float)
    df['value_cad'] = df.apply(
        lambda row: row['shares'] * row['price'] * (1.42 if row.get('currency') == 'USD' else 1.0),
        axis=1
    )
    
    daily_stock = df.groupby('date').agg({'value_cad': 'sum', 'cost_basis': 'sum'})
    for row in daily_stock.itertuples():
        date_str = row.Index.strftime('%Y-%m-%d')
        daily_stock_value[date_str] = row.value_cad
        daily_cost_basis[date_str] = row.cost_basis

print("="*130)
print("FINAL NAV CALCULATION: Same-day contributions all use START-OF-DAY NAV")
print("="*130)
print(f"{'Date':<12} {'Contributor':<20} {'Amount':>10} {'SOD Contribs':>12} {'Stock Val':>12} {'Cost Basis':>12} {'Cash':>10} {'Fund Val':>10} {'NAV':>8} {'Units':>10}")
print("-"*130)

total_units = 0.0
contributor_units = {}
running_contributions = 0.0  # All contributions up to now
contributions_at_start_of_day = 0.0  # Contributions at START of this day
units_at_start_of_day = 0.0
last_contribution_date = None

for contrib in contributions:
    contributor = contrib['contributor']
    amount = contrib['amount']
    contrib_type = contrib['type']
    ts = contrib['timestamp']
    
    # Parse date
    date_str = None
    if ts:
        try:
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            date_str = dt.strftime('%Y-%m-%d')
        except:
            pass
    
    # Same-day tracking - capture state at START of each new day
    if date_str != last_contribution_date:
        units_at_start_of_day = total_units
        contributions_at_start_of_day = running_contributions
        last_contribution_date = date_str
    
    if contributor not in contributor_units:
        contributor_units[contributor] = 0.0
    
    if contrib_type == 'withdrawal':
        running_contributions -= amount
        print(f"{date_str:<12} {contributor[:20]:<20} {f'-${amount:,.0f}':>10} {'':>12} {'':>12} {'':>12} {'':>10} {'':>10} {'WTHDRW':>8} {'':>10}")
        continue
    
    # Get stock value and cost basis for this date
    stock_value = daily_stock_value.get(date_str, 0)
    cost_basis = daily_cost_basis.get(date_str, 0)
    
    # Fallback to prior day if no data
    if stock_value == 0 and date_str:
        try:
            check_date = datetime.strptime(date_str, '%Y-%m-%d')
            for days_back in range(1, 8):
                prior = check_date - timedelta(days=days_back)
                prior_str = prior.strftime('%Y-%m-%d')
                if prior_str in daily_stock_value:
                    stock_value = daily_stock_value[prior_str]
                    cost_basis = daily_cost_basis[prior_str]
                    break
        except:
            pass
    
    # KEY FIX: Use contributions at START OF DAY for uninvested cash calculation
    # This ensures all same-day contributions get the same NAV
    uninvested_cash = max(0, contributions_at_start_of_day - cost_basis)
    
    # Total fund value = stock value + uninvested cash (at start of day)
    fund_value = stock_value + uninvested_cash
    
    # Calculate NAV
    if units_at_start_of_day == 0 and total_units == 0:
        nav = 1.0
        units = amount
    else:
        units_for_nav = units_at_start_of_day if units_at_start_of_day > 0 else total_units
        nav = fund_value / units_for_nav if units_for_nav > 0 and fund_value > 0 else 1.0
        units = amount / nav
    
    contributor_units[contributor] += units
    total_units += units
    running_contributions += amount
    
    print(f"{date_str:<12} {contributor[:20]:<20} {f'${amount:,.0f}':>10} {f'${contributions_at_start_of_day:,.0f}':>12} {f'${stock_value:,.0f}':>12} {f'${cost_basis:,.0f}':>12} {f'${uninvested_cash:,.0f}':>10} {f'${fund_value:,.0f}':>10} {f'${nav:.4f}':>8} {f'{units:.1f}':>10}")

# Calculate current fund value
latest_date = max(daily_stock_value.keys())
current_stock_value = daily_stock_value[latest_date]
current_cost_basis = daily_cost_basis[latest_date]
current_uninvested_cash = max(0, running_contributions - current_cost_basis)
current_total_value = current_stock_value + current_uninvested_cash
current_nav = current_total_value / total_units if total_units > 0 else 1.0

print("="*130)
print(f"\nCURRENT STATE (as of {latest_date}):")
print(f"  Stock value (CAD): ${current_stock_value:,.2f}")
print(f"  Cost basis: ${current_cost_basis:,.2f}")
print(f"  Total contributions: ${running_contributions:,.2f}")
print(f"  Uninvested cash: ${current_uninvested_cash:,.2f}")
print(f"  Total fund value: ${current_total_value:,.2f}")
print(f"  Total units: {total_units:,.2f}")
print(f"  Current NAV: ${current_nav:.4f}")

fund_return_pct = ((current_nav - 1.0) / 1.0) * 100
print(f"  Fund Return (NAV-based): +{fund_return_pct:.2f}%")

print("\n" + "="*130)
print("INVESTOR RETURNS:")
print("-"*130)

contributor_net = {}
for contrib in contributions:
    c = contrib['contributor']
    if c not in contributor_net:
        contributor_net[c] = 0.0
    if contrib['type'] == 'withdrawal':
        contributor_net[c] -= contrib['amount']
    else:
        contributor_net[c] += contrib['amount']

for contributor, units in sorted(contributor_units.items(), key=lambda x: -x[1]):
    net = contributor_net.get(contributor, 0)
    value = units * current_nav
    gain = value - net
    pct = (gain / net * 100) if net > 0 else 0
    print(f"{contributor:<25} Net: ${net:>10,.2f}  Units: {units:>10,.2f}  Value: ${value:>10,.2f}  Return: ${gain:>10,.2f} ({pct:+.2f}%)")
