#!/usr/bin/env python3
"""
Debug script to investigate Webull portfolio calculation discrepancies.
"""

import pandas as pd
import sys
from decimal import Decimal
from pathlib import Path
import json

def debug_portfolio_calculation():
    """Debug the portfolio calculation to identify discrepancies."""

    print("DEBUGGING WEBULL PORTFOLIO CALCULATION")
    print("=" * 50)

    # Load portfolio data
    portfolio_file = 'trading_data/funds/RRSP Lance Webull/llm_portfolio_update.csv'
    df = pd.read_csv(portfolio_file)

    # Get latest entries for each ticker
    latest_entries = df.sort_values('Date').groupby('Ticker').tail(1)
    print(f"Total unique positions: {len(latest_entries)}")

    # Separate HOLD and SELL positions
    hold_positions = latest_entries[latest_entries['Action'] == 'HOLD']
    sell_positions = latest_entries[latest_entries['Action'] == 'SELL']

    print(f"HOLD positions: {len(hold_positions)}")
    print(f"SELL positions: {len(sell_positions)}")

    if not sell_positions.empty:
        print(f"SELL positions found: {sell_positions['Ticker'].tolist()}")

    # Calculate total portfolio value from positions only
    positions_total = Decimal('0')
    positions_pnl_total = Decimal('0')

    for row in hold_positions.to_dict('records'):
        current_price = Decimal(str(row['Current Price']))
        shares = Decimal(str(row['Shares']))
        avg_price = Decimal(str(row['Average Price']))

        position_value = current_price * shares
        position_cost = avg_price * shares
        position_pnl = position_value - position_cost

        positions_total += position_value
        positions_pnl_total += position_pnl

        ticker = str(row['Ticker'])
        print(f"  {ticker}: Value=${position_value}, PnL=${position_pnl}")

    print(f"\nPositions Total Value: ${positions_total}")
    print(f"Positions Total PnL: ${positions_pnl_total}")

    # Load cash balances
    cash_file = 'trading_data/funds/RRSP Lance Webull/cash_balances.json'
    try:
        with open(cash_file, 'r') as f:
            cash_data = json.load(f)
        cad_cash = Decimal(str(cash_data.get('cad', 0)))
        usd_cash = Decimal(str(cash_data.get('usd', 0)))
        print(f"\nCash Balances: CAD=${cad_cash}, USD=${usd_cash}")
    except Exception as e:
        print(f"\nError loading cash balances: {e}")
        cad_cash = usd_cash = Decimal('0')

    # Calculate total CAD equivalent
    usd_to_cad_rate = Decimal('1.35')  # Default rate
    usd_cash_cad = usd_cash * usd_to_cad_rate
    total_cash_cad = cad_cash + usd_cash_cad
    total_portfolio_cad = positions_total + total_cash_cad

    print("\nTOTAL ACCOUNT SUMMARY:")
    print(f"  Positions Value: ${positions_total}")
    print(f"  Cash (CAD equiv): ${total_cash_cad}")
    print(f"  Total Account: ${total_portfolio_cad}")
    print(f"  Total PnL: ${positions_pnl_total}")

    # Account for Webull commissions ($2.99 per trade)
    commission_per_trade = Decimal('2.99')
    total_commissions = len(hold_positions) * commission_per_trade
    adjusted_pnl = positions_pnl_total - total_commissions
    
    print(f"  Commission per trade: ${commission_per_trade}")
    print(f"  Total commissions: ${total_commissions}")
    print(f"  Adjusted PnL (after commissions): ${adjusted_pnl}")

    # Webull comparison
    webull_pnl = Decimal('11690.81')
    webull_positions = 72
    webull_cad_market_value = Decimal('74395.47')
    webull_usd_market_value = Decimal('111914.91')

    print("\nWEBULL COMPARISON:")
    print(f"  Webull PnL: ${webull_pnl}")
    print(f"  Webull Positions: {webull_positions}")
    print(f"  Webull CAD Market Value: ~${webull_cad_market_value}")
    print(f"  Webull USD Market Value: ~${webull_usd_market_value}")

    print("\nDISCREPANCIES:")
    if abs(positions_pnl_total - webull_pnl) > Decimal('1'):
        print(f"  PnL difference (before commissions): ${abs(positions_pnl_total - webull_pnl)}")
    
    if abs(adjusted_pnl - webull_pnl) > Decimal('1'):
        print(f"  PnL difference (after commissions): ${abs(adjusted_pnl - webull_pnl)}")

    if len(hold_positions) != webull_positions:
        print(f"  Position count difference: {len(hold_positions)} vs {webull_positions}")

    if abs(total_portfolio_cad) < Decimal('1000'):
        print(f"  Total account suspiciously low: ${total_portfolio_cad} (should be ~${webull_cad_market_value})")

if __name__ == "__main__":
    debug_portfolio_calculation()
