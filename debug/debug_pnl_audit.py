#!/usr/bin/env python3
"""
Audit P&L calculation to identify discrepancies with Webull.
"""

import pandas as pd
import sys
from decimal import Decimal
from pathlib import Path
import json

def audit_pnl_calculation():
    """Audit P&L calculation to identify bugs or discrepancies."""

    print("🔍 P&L CALCULATION AUDIT")
    print("=" * 60)

    # Load portfolio data
    portfolio_file = 'trading_data/funds/RRSP Lance Webull/llm_portfolio_update.csv'
    df = pd.read_csv(portfolio_file)

    # Get latest entries for each ticker
    latest_entries = df.sort_values('Date').groupby('Ticker').tail(1)
    hold_positions = latest_entries[latest_entries['Action'] == 'HOLD']

    print(f"📊 Analyzing {len(hold_positions)} HOLD positions")

    # Calculate P&L for each position using the same logic as the bot
    total_bot_pnl = Decimal('0')
    position_details = []

    for row in hold_positions.to_dict('records'):
        ticker = row['Ticker']
        shares = Decimal(str(row['Shares']))
        avg_price = Decimal(str(row['Average Price']))
        current_price = Decimal(str(row['Current Price']))

        # Calculate P&L using bot's method
        bot_pnl = (current_price - avg_price) * shares
        bot_pnl = bot_pnl.quantize(Decimal('0.01'))

        total_bot_pnl += bot_pnl

        position_details.append({
            'ticker': ticker,
            'shares': float(shares),
            'avg_price': float(avg_price),
            'current_price': float(current_price),
            'bot_pnl': float(bot_pnl),
            'total_value': float(current_price * shares)
        })

    print("\n🏦 BOT P&L CALCULATION BREAKDOWN:")
    print(f"Total positions: {len(position_details)}")
    print(f"Bot total P&L: ${total_bot_pnl:,.2f}")

    # Show top gainers and losers
    position_details.sort(key=lambda x: x['bot_pnl'], reverse=True)

    print("\n📈 TOP 5 GAINERS:")
    for pos in position_details[:5]:
        print(f"  {pos['ticker']:8s}: ${pos['bot_pnl']:+8.2f} ({pos['shares']:.0f} shares @ ${pos['current_price']:.2f})")

    print("\n📉 TOP 5 LOSERS:")    for pos in position_details[-5:]:
        print(f"  {pos['ticker']:8s}: ${pos['bot_pnl']:+8.2f} ({pos['shares']:.0f} shares @ ${pos['current_price']:.2f})")

    # Calculate totals
    total_current_value = sum(pos['total_value'] for pos in position_details)
    total_cost_basis = sum(pos['shares'] * pos['avg_price'] for pos in position_details)

    print("\n💰 PORTFOLIO SUMMARY:")    print(f"  Total current value: ${total_current_value:,.2f}")
    print(f"  Total cost basis: ${total_cost_basis:,.2f}")
    print(f"  Total P&L: ${total_current_value - total_cost_basis:,.2f}")

    # Compare with Webull
    webull_pnl = Decimal('11690.81')
    webull_positions = 72

    print("\n📱 WEBULL COMPARISON:")    print(f"  Webull P&L: ${webull_pnl:,.2f}")
    print(f"  Webull positions: {webull_positions}")
    print(f"  Bot P&L: ${total_bot_pnl:,.2f}")
    print(f"  Bot positions: {len(position_details)}")

    difference = webull_pnl - total_bot_pnl
    print(f"  P&L difference: ${difference:+.2f}")

    # Calculate commission impact
    trades_count = 73  # From earlier analysis
    commission_per_trade = Decimal('2.99')
    total_commissions = trades_count * commission_per_trade
    remaining_difference = difference - total_commissions

    print("\n🔍 COMMISSION ANALYSIS:")    print(f"  Total trades: {trades_count}")
    print(f"  Commission per trade: ${commission_per_trade}")
    print(f"  Total commissions: ${total_commissions:,.2f}")
    print(f"  Remaining unexplained difference: ${remaining_difference:+.2f}")

    # Look for potential issues
    print("\n🔎 POTENTIAL ISSUES TO INVESTIGATE:")    if len(position_details) != webull_positions:
        print(f"  ⚠️  Position count mismatch: {len(position_details)} vs {webull_positions}")

    if abs(remaining_difference) > Decimal('100'):
        print("  ❌ Major unexplained difference - investigate cost basis calculation")
    elif abs(remaining_difference) > Decimal('10'):
        print("  ⚠️  Moderate difference - check price sources or rounding")
    else:
        print("  ✅ Small difference - likely due to timing or minor calculation differences")

    # Check for data quality issues
    positions_with_zero_avg_price = sum(1 for pos in position_details if pos['avg_price'] == 0)
    positions_with_zero_current_price = sum(1 for pos in position_details if pos['current_price'] == 0)

    if positions_with_zero_avg_price > 0:
        print(f"  ⚠️  {positions_with_zero_avg_price} positions have zero average price")

    if positions_with_zero_current_price > 0:
        print(f"  ⚠️  {positions_with_zero_current_price} positions have zero current price")

    print("\n📝 RECOMMENDATIONS:")    print("  1. Verify cost basis calculation method (FIFO vs average price)")
    print("  2. Compare current prices between bot and Webull")
    print("  3. Check if Webull uses different baseline date for P&L")
    print("  4. Verify all positions have valid prices and average prices")
    print("  5. Consider if Webull includes/excludes certain positions in P&L calculation")

if __name__ == "__main__":
    audit_pnl_calculation()
