import pandas as pd
import sys
from pathlib import Path

# Load the data and analyze cash flows vs performance
df = pd.read_csv('trading_data/funds/Project Chimera/llm_portfolio_update.csv')
print('📊 Analyzing Portfolio Cash Flows vs Returns')
print('=' * 50)

df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
df['Date_Only'] = df['Date'].dt.date
df['Total Value'] = pd.to_numeric(df['Total Value'], errors='coerce')
df['Cost Basis'] = pd.to_numeric(df['Cost Basis'], errors='coerce')

# Group by date and analyze what happened each day
for date_only, date_group in df.groupby('Date_Only'):
    if pd.isna(date_only):
        continue
    
    print(f"\n📅 {date_only}")
    
    # Separate BUY vs HOLD actions
    buys = date_group[date_group['Action'] == 'BUY']
    holds = date_group[date_group['Action'] == 'HOLD']
    sells = date_group[date_group['Action'] == 'SELL']
    
    if len(buys) > 0:
        total_new_investment = buys['Cost Basis'].sum()
        print(f"   💰 New Investments: ${total_new_investment:,.2f}")
        for buy in buys.to_dict('records'):
            print(f"      - {buy['Ticker']}: ${buy['Cost Basis']:.2f}")
    
    if len(sells) > 0:
        print(f"   📤 Sales:")
        for sell in sells.to_dict('records'):
            print(f"      - {sell['Ticker']}: SOLD")
    
    # Calculate end-of-day portfolio value and cost basis
    final_positions = []
    for ticker, ticker_group in date_group.groupby('Ticker'):
        latest_entry = ticker_group.loc[ticker_group['Date'].idxmax()]
        if latest_entry['Total Value'] > 0:  # Still holding
            final_positions.append({
                'ticker': ticker,
                'cost_basis': latest_entry['Cost Basis'],
                'market_value': latest_entry['Total Value'],
                'unrealized_pnl': latest_entry['PnL']
            })
    
    total_cost_basis = sum(pos['cost_basis'] for pos in final_positions)
    total_market_value = sum(pos['market_value'] for pos in final_positions)
    total_unrealized_pnl = sum(pos['unrealized_pnl'] for pos in final_positions)
    
    print(f"   📊 End of Day:")
    print(f"      Total Cost Basis: ${total_cost_basis:,.2f}")
    print(f"      Total Market Value: ${total_market_value:,.2f}")
    print(f"      Unrealized P&L: ${total_unrealized_pnl:+,.2f} ({total_unrealized_pnl/total_cost_basis*100:+.2f}%)")

print("\n" + "=" * 50)
print("🎯 KEY INSIGHT:")
print("The portfolio 'growth' from $1,009 to $6,417 includes:")
print("- New cash invested during the period")
print("- Actual market performance of holdings")
print("\nTo show TRUE performance, we need to:")
print("1. Track cumulative cost basis (money invested)")
print("2. Track market value of all holdings")
print("3. Show the DIFFERENCE as actual gains/losses")