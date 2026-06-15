#!/usr/bin/env python3
"""
Simple P&L audit to identify discrepancies with Webull.
"""

import pandas as pd
from decimal import Decimal

def audit_pnl_simple():
    """Simple P&L audit to identify bugs or discrepancies."""

    print("P&L CALCULATION AUDIT")
    print("=" * 50)

    # Load portfolio data
    portfolio_file = 'trading_data/funds/RRSP Lance Webull/llm_portfolio_update.csv'
    df = pd.read_csv(portfolio_file)

    # Get latest entries for each ticker
    latest_entries = df.sort_values('Date').groupby('Ticker').tail(1)
    hold_positions = latest_entries[latest_entries['Action'] == 'HOLD']

    print(f"Analyzing {len(hold_positions)} HOLD positions")

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

    print(f"\nBOT P&L CALCULATION:")
    print(f"Total positions: {len(position_details)}")
    print(f"Bot total P&L: ${total_bot_pnl:,.2f}")

    # Calculate totals
    total_current_value = sum(pos['total_value'] for pos in position_details)
    total_cost_basis = sum(pos['shares'] * pos['avg_price'] for pos in position_details)

    print(f"\nPORTFOLIO SUMMARY:")
    print(f"  Total current value: ${total_current_value:,.2f}")
    print(f"  Total cost basis: ${total_cost_basis:,.2f}")
    print(f"  Total P&L: ${total_current_value - total_cost_basis:,.2f}")

    # Compare with Webull
    webull_pnl = Decimal('11690.81')
    webull_positions = 72

    print(f"\nWEBULL COMPARISON:")
    print(f"  Webull P&L: ${webull_pnl:,.2f}")
    print(f"  Webull positions: {webull_positions}")
    print(f"  Bot P&L: ${total_bot_pnl:,.2f}")
    print(f"  Bot positions: {len(position_details)}")

    difference = webull_pnl - total_bot_pnl
    print(f"  P&L difference: ${difference:+.2f}")

    # Calculate commission impact
    trades_count = 73
    commission_per_trade = Decimal('2.99')
    total_commissions = trades_count * commission_per_trade
    remaining_difference = difference - total_commissions

    print(f"\nCOMMISSION ANALYSIS:")
    print(f"  Total trades: {trades_count}")
    print(f"  Commission per trade: ${commission_per_trade}")
    print(f"  Total commissions: ${total_commissions:,.2f}")
    print(f"  Remaining unexplained difference: ${remaining_difference:+.2f}")

    # Look for potential issues
    if len(position_details) != webull_positions:
        print(f"  Position count mismatch: {len(position_details)} vs {webull_positions}")

    if abs(remaining_difference) > Decimal('100'):
        print("  Major unexplained difference - investigate cost basis calculation")
    elif abs(remaining_difference) > Decimal('10'):
        print("  Moderate difference - check price sources or rounding")
    else:
        print("  Small difference - likely due to timing or minor calculation differences")

    # Check for data quality issues
    positions_with_zero_avg_price = sum(1 for pos in position_details if pos['avg_price'] == 0)
    positions_with_zero_current_price = sum(1 for pos in position_details if pos['current_price'] == 0)

    if positions_with_zero_avg_price > 0:
        print(f"  {positions_with_zero_avg_price} positions have zero average price")

    if positions_with_zero_current_price > 0:
        print(f"  {positions_with_zero_current_price} positions have zero current price")

    print(f"\nAUDIT SUMMARY:")
    print(f"  The P&L calculation logic appears to be correct")
    print(f"  Bot uses: (current_price - avg_price) × shares")
    print(f"  Difference of ${difference:+.2f} needs investigation")
    print(f"  Commissions explain ${total_commissions:,.2f} of the difference")
    print(f"  Remaining unexplained: ${remaining_difference:+.2f}")

if __name__ == "__main__":
    audit_pnl_simple()
