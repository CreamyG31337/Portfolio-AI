#!/usr/bin/env python3
"""
Comprehensive NAV calculation diagnostic - trace user return step-by-step
and check for any data issues that could inflate returns
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "web_dashboard"))

from supabase_client import SupabaseClient
import pandas as pd
from datetime import datetime

def check_table_duplicates(client, table_name, key_columns):
    """Check for duplicates in a table"""
    print(f"\n{'='*80}")
    print(f"Checking {table_name} for duplicates...")
    print(f"{'='*80}")
    
    res = client.supabase.table(table_name).select('*').execute()
    if not res.data:
        print(f"No data in {table_name}")
        return
    
    df = pd.DataFrame(res.data)
    print(f"Total records: {len(df)}")
    
    # Check for duplicates based on key columns
    duplicates = df[df.duplicated(subset=key_columns, keep=False)]
    
    if len(duplicates) > 0:
        print(f"\n[!] DUPLICATES FOUND: {len(duplicates)} records")
        print("\nDuplicate groups:")
        for key_vals, group in duplicates.groupby(key_columns):
            print(f"\n  Key: {key_vals}")
            print(f"  Count: {len(group)}")
            for row in group.to_dict('records'):
                print(f"    ID: {row.get('id', 'N/A')[:8]}... Created: {row.get('created_at', 'N/A')}")
    else:
        print(f"[OK] No duplicates found")

def trace_user_return_calculation(client, user_email, fund_name="Project Chimera"):
    """Trace the complete NAV calculation for a specific user"""
    print(f"\n{'='*80}")
    print(f"TRACING USER RETURN CALCULATION")
    print(f"User: {user_email}")
    print(f"Fund: {fund_name}")
    print(f"{'='*80}\n")
    
    # Step 1: Get user contributions
    print("STEP 1: User Contributions")
    print("-" * 80)
    contrib_res = client.supabase.table('fund_contributions')\
        .select('*')\
        .eq('fund', fund_name)\
        .eq('email', user_email)\
        .order('timestamp')\
        .execute()
    
    if not contrib_res.data:
        print(f"No contributions found for {user_email}")
        return
    
    contrib_df = pd.DataFrame(contrib_res.data)
    contrib_df['timestamp'] = pd.to_datetime(contrib_df['timestamp'])
    
    total_contributed = contrib_df[contrib_df['contribution_type'] == 'CONTRIBUTION']['amount'].sum()
    total_withdrawn = contrib_df[contrib_df['contribution_type'] == 'WITHDRAWAL']['amount'].sum()
    net_contributed = total_contributed - total_withdrawn
    
    print(f"Total Contributions: ${total_contributed:,.2f}")
    print(f"Total Withdrawals: ${total_withdrawn:,.2f}")
    print(f"Net Contributed: ${net_contributed:,.2f}")
    print(f"\nContribution History:")
    for row in contrib_df.to_dict('records'):
        sign = "+" if row['contribution_type'] == 'CONTRIBUTION' else "-"
        print(f"  {row['timestamp'].strftime('%Y-%m-%d')}: {sign}${row['amount']:,.2f}")
    
    # Step 2: Calculate historical NAV from portfolio positions
    print(f"\n\nSTEP 2: Calculate Historical NAV from Portfolio Positions")
    print("-" * 80)
    
    pos_res = client.supabase.table('portfolio_positions')\
        .select('*')\
        .eq('fund', fund_name)\
        .order('date')\
        .execute()
    
    if not pos_res.data:
        print(f"No portfolio positions found for {fund_name}")
        return
    
    pos_df = pd.DataFrame(pos_res.data)
    pos_df['date'] = pd.to_datetime(pos_df['date'])
    
    # Calculate total fund value by date
    # Group by date and sum total_value
    daily_values = pos_df.groupby('date')['total_value'].sum().reset_index()
    daily_values.columns = ['date', 'total_value']
    daily_values = daily_values.sort_values('date')
    
    # Calculate NAV (set first day as 1.0, then scale from there)
    if len(daily_values) > 0:
        first_value = daily_values.iloc[0]['total_value']
        daily_values['nav'] = daily_values['total_value'] / first_value
    
    print(f"Portfolio position records: {len(pos_df)}")
    print(f"Unique dates: {len(daily_values)}")
    print(f"Date range: {daily_values['date'].min().strftime('%Y-%m-%d')} to {daily_values['date'].max().strftime('%Y-%m-%d')}")
    print(f"\nFirst Value: ${daily_values.iloc[0]['total_value']:,.2f} (NAV: {daily_values.iloc[0]['nav']:.4f})")
    print(f"Latest Value: ${daily_values.iloc[-1]['total_value']:,.2f} (NAV: {daily_values.iloc[-1]['nav']:.4f})")
    print(f"Fund total return: {((daily_values.iloc[-1]['nav'] / daily_values.iloc[0]['nav']) - 1) * 100:.2f}%")
    
    nav_df = daily_values  # Use this for NAV lookups
    
    # Step 3: Calculate units purchased at each contribution
    print(f"\n\nSTEP 3: Units Calculation")
    print("-" * 80)
    
    total_units = 0
    unit_transactions = []
    
    for contrib in contrib_df.to_dict('records'):
        contrib_date = contrib['timestamp']
        # Find NAV on or before contribution date
        nav_at_contrib = nav_df[nav_df['date'] <= contrib_date]
        
        if len(nav_at_contrib) == 0:
            print(f"  WARNING: No NAV found before {contrib_date.strftime('%Y-%m-%d')}")
            continue
        
        nav_value = nav_at_contrib.iloc[-1]['nav']
        nav_date = nav_at_contrib.iloc[-1]['date']
        
        if contrib['contribution_type'] == 'CONTRIBUTION':
            units = contrib['amount'] / nav_value
            total_units += units
            unit_transactions.append({
                'date': contrib['timestamp'],
                'type': 'BUY',
                'amount': contrib['amount'],
                'nav': nav_value,
                'nav_date': nav_date,
                'units': units,
                'running_total_units': total_units
            })
            print(f"  {contrib_date.strftime('%Y-%m-%d')}: CONTRIBUTION ${contrib['amount']:,.2f}")
            print(f"    NAV @ {nav_date.strftime('%Y-%m-%d')}: ${nav_value:.4f}")
            print(f"    Units purchased: {units:.4f}")
            print(f"    Total units: {total_units:.4f}\n")
        else:
            units = contrib['amount'] / nav_value
            total_units -= units
            unit_transactions.append({
                'date': contrib['timestamp'],
                'type': 'SELL',
                'amount': contrib['amount'],
                'nav': nav_value,
                'nav_date': nav_date,
                'units': units,
                'running_total_units': total_units
            })
            print(f"  {contrib_date.strftime('%Y-%m-%d')}: WITHDRAWAL ${contrib['amount']:,.2f}")
            print(f"    NAV @ {nav_date.strftime('%Y-%m-%d')}: ${nav_value:.4f}")
            print(f"    Units sold: {units:.4f}")
            print(f"    Total units: {total_units:.4f}\n")
    
    # Step 4: Calculate current value
    print(f"\n\nSTEP 4: Current Value Calculation")
    print("-" * 80)
    
    current_nav = nav_df.iloc[-1]['nav']
    current_value = total_units * current_nav
    profit = current_value - net_contributed
    return_pct = (profit / net_contributed * 100) if net_contributed > 0 else 0
    
    print(f"Total Units Owned: {total_units:.4f}")
    print(f"Current NAV: ${current_nav:.4f}")
    print(f"Current Value: ${current_value:,.2f}")
    print(f"\nNet Contributed: ${net_contributed:,.2f}")
    print(f"Current Value: ${current_value:,.2f}")
    print(f"Profit: ${profit:,.2f}")
    print(f"Return: {return_pct:.2f}%")
    
    # Step 5: Sanity checks
    print(f"\n\nSTEP 5: Sanity Checks")
    print("-" * 80)
    
    # Check if return exceeds fund return significantly
    fund_return = ((nav_df.iloc[-1]['nav'] / nav_df.iloc[0]['nav']) - 1) * 100
    if return_pct > fund_return + 5:  # More than 5% higher
        print(f"[!] WARNING: User return ({return_pct:.2f}%) significantly exceeds fund return ({fund_return:.2f}%)")
        print(f"    This might indicate:")
        print(f"    - Timing of contributions (buying at different NAVs)")
        print(f"    - Data quality issues")
        print(f"    - Calculation errors")
    else:
        print(f"[OK] User return ({return_pct:.2f}%) vs Fund return ({fund_return:.2f}%) seems reasonable")
    
    # Summary
    print(f"\n\n{'='*80}")
    print(f"SUMMARY")
    print(f"{'='*80}")
    print(f"User: {user_email}")
    print(f"Fund: {fund_name}")
    print(f"Net Contributed: ${net_contributed:,.2f}")
    print(f"Current Value: ${current_value:,.2f}")
    print(f"Return: ${profit:,.2f} ({return_pct:.2f}%)")
    print(f"Fund Total Return: {fund_return:.2f}%")
    print(f"{'='*80}\n")

def main():
    client = SupabaseClient(use_service_role=True)
    
    # Check all relevant tables for duplicates
    print("\n" + "="*80)
    print("CHECKING ALL TABLES FOR DUPLICATES")
    print("="*80)
    
    check_table_duplicates(client, 'portfolio_positions', ['date', 'ticker', 'fund'])
    check_table_duplicates(client, 'fund_contributions', ['timestamp', 'fund', 'contributor', 'amount'])
    
    # Get user email from first contribution
    print("\n\n" + "="*80)
    print("GETTING USER EMAIL")
    print("="*80)
    
    # Find the user's email from their contributions
    contrib_res = client.supabase.table('fund_contributions')\
        .select('email, contributor')\
        .eq('fund', 'Project Chimera')\
        .limit(1)\
        .execute()
    
    if contrib_res.data:
        user_email = contrib_res.data[0].get('email')
        contributor_name = contrib_res.data[0].get('contributor')
        print(f"Found user: {contributor_name} ({user_email})")
        
        # Trace the calculation
        trace_user_return_calculation(client, user_email, 'Project Chimera')
    else:
        print("No contributions found for Project Chimera")

if __name__ == "__main__":
    main()
