#!/usr/bin/env python3
"""
Debug script to analyze currency distribution in Webull portfolio.
"""

import pandas as pd
import sys
from decimal import Decimal

def analyze_currency_distribution():
    """Analyze currency distribution to identify conversion issues."""

    print("🔍 ANALYZING CURRENCY DISTRIBUTION")
    print("=" * 50)

    # Load portfolio data
    portfolio_file = 'trading_data/funds/RRSP Lance Webull/llm_portfolio_update.csv'
    df = pd.read_csv(portfolio_file)

    # Get latest entries for each ticker
    latest_entries = df.sort_values('Date').groupby('Ticker').tail(1)
    hold_positions = latest_entries[latest_entries['Action'] == 'HOLD']

    print(f"Total positions: {len(hold_positions)}")

    # Analyze currency distribution
    cad_positions = hold_positions[hold_positions['Currency'] == 'CAD']
    usd_positions = hold_positions[hold_positions['Currency'] == 'USD']

    print(f"\n💰 CAD Positions: {len(cad_positions)}")
    print(f"💵 USD Positions: {len(usd_positions)}")

    # Calculate values by currency
    cad_total = Decimal('0')
    usd_total = Decimal('0')

    print("\n📊 CAD POSITIONS:")
    for row in cad_positions.to_dict('records'):
        current_price = Decimal(str(row['Current Price']))
        shares = Decimal(str(row['Shares']))
        value = current_price * shares
        cad_total += value
        ticker = str(row['Ticker'])
        print(f"  {ticker:8s}: ${value",.2f"}")

    print("\n📈 USD POSITIONS:")
    for row in usd_positions.to_dict('records'):
        current_price = Decimal(str(row['Current Price']))
        shares = Decimal(str(row['Shares']))
        value = current_price * shares
        usd_total += value
        ticker = str(row['Ticker'])
        print(f"  {ticker:8s}: ${value",.2f"}")

    print("\n🏦 CURRENCY SUMMARY:")
    print(f"  CAD Total: ${cad_total",.2f"}")
    print(f"  USD Total: ${usd_total",.2f"}")
    print(f"  Combined: ${cad_total + usd_total",.2f"}")

    # Check exchange rate and CAD equivalent
    usd_to_cad_rate = Decimal('1.35')  # Current approximate rate
    usd_total_cad = usd_total * usd_to_cad_rate
    total_cad_equiv = cad_total + usd_total_cad

    print("\n💱 CAD EQUIVALENT:")
    print(f"  USD -> CAD Rate: {usd_to_cad_rate}")
    print(f"  USD Value in CAD: ${usd_total_cad",.2f"}")
    print(f"  Total CAD Equivalent: ${total_cad_equiv",.2f"}")

    # Check if this matches Webull's ~$74k total
    webull_target = Decimal('74000')
    difference = abs(total_cad_equiv - webull_target)

    print("\n🎯 COMPARISON TO WEBULL:")
    print(f"  Our CAD Total: ${total_cad_equiv",.2f"}")
    print(f"  Webull Total: ~${webull_target",.2f"}")
    print(f"  Difference: ${difference",.2f"}")

    if difference > Decimal('5000'):
        print("  ❌ Large discrepancy detected - possible currency conversion issue")
    elif difference > Decimal('1000'):
        print("  ⚠️  Moderate discrepancy - check exchange rates or missing positions")
    else:
        print("  ✅ Values are reasonably close")

if __name__ == "__main__":
    analyze_currency_distribution()
