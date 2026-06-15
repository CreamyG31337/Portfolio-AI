#!/usr/bin/env python3
"""
Recalculate Portfolio Data from Trade Log

This script updates existing portfolio rows with correct data from the trade log.
It preserves ALL historical price tracking rows and only updates the latest entry for each ticker.
It also adds truly missing trades from the trade log.

Usage:
    python debug/recalculate_portfolio_data.py
    python debug/recalculate_portfolio_data.py test_data
"""

import pandas as pd
from pathlib import Path
from collections import defaultdict
import sys
from datetime import datetime

# Import emoji handling
from display.console_output import _safe_emoji

def get_company_name(ticker: str) -> str:
    """Get company name for ticker using yfinance lookup"""
    try:
        from utils.ticker_utils import get_company_name as lookup_company_name
        return lookup_company_name(ticker)
    except Exception as e:
        print(f"Warning: Could not lookup company name for {ticker}: {e}")
        return 'Unknown'

def get_currency(ticker: str) -> str:
    """Get currency for ticker"""
    if '.TO' in ticker or '.V' in ticker:
        return 'CAD'
    return 'USD'

def recalculate_portfolio_data(data_dir: str = "trading_data/funds/TEST"):
    """Update existing portfolio rows with correct data from trade log - preserves all historical price tracking"""
    
    data_path = Path(data_dir)
    trade_log_file = data_path / "llm_trade_log.csv"
    portfolio_file = data_path / "llm_portfolio_update.csv"
    
    if not trade_log_file.exists():
        print(f"{_safe_emoji('❌')} Trade log not found: {trade_log_file}")
        return False
    
    if not portfolio_file.exists():
        print(f"{_safe_emoji('❌')} Portfolio file not found: {portfolio_file}")
        return False
    
    try:
        # BACKUP THE FILE FIRST
        backup_dir = portfolio_file.parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_dir / f"{portfolio_file.stem}.backup_{timestamp}.csv"
        portfolio_df = pd.read_csv(portfolio_file)
        portfolio_df.to_csv(backup_file, index=False)
        print(f"{_safe_emoji('💾')} Backed up portfolio to: {backup_file}")
        
        # Read trade log
        trade_df = pd.read_csv(trade_log_file)
        print(f"{_safe_emoji('📊')} Loaded {len(trade_df)} trades from trade log")
        
        # Read existing portfolio - KEEP ALL ROWS
        print(f"{_safe_emoji('📊')} Loaded {len(portfolio_df)} portfolio entries")
        
        # Calculate correct positions from trade log
        ticker_data = defaultdict(lambda: {'total_shares': 0, 'total_cost': 0, 'last_action': 'BUY', 'last_price': 0, 'sell_shares': 0, 'sell_price': 0, 'sell_pnl': 0})
        
        print(f"\n📈 Processing trades from trade log:")
        
        for trade in trade_df.to_dict('records'):
            ticker = trade['Ticker']
            shares = float(trade['Shares'])
            price = float(trade['Price'])
            cost = float(trade['Cost Basis'])
            pnl = float(trade['PnL'])
            reason = trade['Reason']
            
            # Determine if this is a buy or sell
            is_sell = 'SELL' in reason.upper() or 'sell' in reason.lower()
            
            print(f"   {ticker} | {shares:.4f} @ ${price:.2f} | ${cost:.2f} | PnL: ${pnl:.2f} | {reason}")
            
            if is_sell:
                # Track sell information
                ticker_data[ticker]['sell_shares'] = shares
                ticker_data[ticker]['sell_price'] = price
                ticker_data[ticker]['sell_pnl'] = pnl
                ticker_data[ticker]['last_action'] = 'SELL'
                ticker_data[ticker]['last_price'] = price
            else:
                # For buys, add shares and cost
                ticker_data[ticker]['total_shares'] += shares
                ticker_data[ticker]['total_cost'] += cost
                ticker_data[ticker]['last_action'] = 'BUY'
                ticker_data[ticker]['last_price'] = price
        
        # Check for missing trades and add them
        missing_trades = []
        
        print(f"\n🔍 Checking for missing trades...")
        
        # Process each trade to see if we need to add missing entries
        running_positions = defaultdict(lambda: {'shares': 0, 'cost': 0, 'trades': []})
        
        for trade in trade_df.to_dict('records'):
            ticker = trade['Ticker']
            date = trade['Date']
            shares = float(trade['Shares'])
            price = float(trade['Price'])
            cost = float(trade['Cost Basis'])
            pnl = float(trade['PnL'])
            reason = trade['Reason']
            
            # Determine if this is a buy or sell
            is_sell = 'SELL' in reason.upper() or 'sell' in reason.lower()
            
            if is_sell:
                # Check if we have this sell entry by date and ticker
                sell_exists = False
                for row in portfolio_df.to_dict('records'):
                    if (row['Ticker'] == ticker and 
                        row['Date'] == date and
                        row['Action'] == 'SELL'):
                        sell_exists = True
                        break
                
                if not sell_exists:
                    # Get company/currency info
                    company = get_company_name(ticker)
                    currency = get_currency(ticker)
                    for row in portfolio_df.to_dict('records'):
                        if row['Ticker'] == ticker:
                            currency = row.get('Currency', get_currency(ticker))
                            break
                    
                    missing_trades.append({
                        'Date': date,
                        'Ticker': ticker,
                        'Shares': 0.0,
                        'Average Price': 0.0,
                        'Cost Basis': 0.0,
                        'Stop Loss': 0.0,
                        'Current Price': price,
                        'Total Value': 0.0,
                        'PnL': pnl,
                        'Action': 'SELL',
                        'Company': company,
                        'Currency': currency
                    })
                    print(f"   Missing SELL: {ticker} on {date}")
                
                # Reset position after sell
                running_positions[ticker] = {'shares': 0, 'cost': 0, 'trades': []}
            else:
                # For buys, update running position
                running_positions[ticker]['shares'] += shares
                running_positions[ticker]['cost'] += cost
                running_positions[ticker]['trades'].append({'shares': shares, 'price': price, 'cost': cost})
                
                # Check if we have this buy entry by date and ticker
                buy_exists = False
                for row in portfolio_df.to_dict('records'):
                    if (row['Ticker'] == ticker and 
                        row['Date'] == date and
                        row['Action'] == 'BUY'):
                        buy_exists = True
                        break
                
                if not buy_exists:
                    # Get company/currency info
                    company = get_company_name(ticker)
                    currency = get_currency(ticker)
                    for row in portfolio_df.to_dict('records'):
                        if row['Ticker'] == ticker:
                            currency = row.get('Currency', get_currency(ticker))
                            break
                    
                    # Calculate values
                    total_shares = running_positions[ticker]['shares']
                    total_cost = running_positions[ticker]['cost']
                    avg_price = total_cost / total_shares if total_shares > 0 else 0
                    current_price = price
                    total_value = total_shares * current_price
                    unrealized_pnl = (current_price - avg_price) * total_shares
                    
                    missing_trades.append({
                        'Date': date,
                        'Ticker': ticker,
                        'Shares': round(total_shares, 2),
                        'Average Price': round(avg_price, 2),
                        'Cost Basis': round(total_cost, 2),
                        'Stop Loss': 0.0,
                        'Current Price': round(current_price, 2),
                        'Total Value': round(total_value, 2),
                        'PnL': round(unrealized_pnl, 2),
                        'Action': 'BUY',
                        'Company': company,
                        'Currency': currency
                    })
                    print(f"   Missing BUY: {ticker} on {date}")
        
        # Add missing trades to portfolio
        if missing_trades:
            print(f"\n➕ Adding {len(missing_trades)} missing trades...")
            missing_df = pd.DataFrame(missing_trades)
            portfolio_df = pd.concat([portfolio_df, missing_df], ignore_index=True)
            portfolio_df = portfolio_df.sort_values(['Date', 'Ticker']).reset_index(drop=True)
            print(f"   Portfolio now has {len(portfolio_df)} entries")
        else:
            print(f"   No missing trades found")
        
        # Update ONLY the latest entry for each ticker in the existing portfolio
        updated_count = 0
        changes_made = []
        
        # Group portfolio by ticker and find the latest entry for each
        latest_entries = {}
        # itertuples preserves the index label stored in 'idx' (used by iloc/.at below).
        for row in portfolio_df.itertuples():
            ticker = row.Ticker
            if ticker not in latest_entries or row.Date > latest_entries[ticker]['Date']:
                latest_entries[ticker] = {'idx': row.Index, 'Date': row.Date}
        
        # Update only the latest entry for each ticker
        for ticker, entry_info in latest_entries.items():
            if ticker in ticker_data:
                idx = entry_info['idx']
                row = portfolio_df.iloc[idx]
                
                # Get current values
                old_shares = float(row['Shares'])
                old_avg_price = float(row['Average Price'])
                old_cost_basis = float(row['Cost Basis'])
                old_action = row['Action']
                old_pnl = float(row['PnL'])
                
                # Calculate correct values from trade log
                if ticker_data[ticker]['last_action'] == 'SELL':
                    # For sell transactions, show 0 shares and sell details
                    new_shares = 0.0
                    new_avg_price = 0.0
                    new_cost_basis = 0.0
                    new_action = 'SELL'
                    new_current_price = ticker_data[ticker]['sell_price']
                    new_total_value = 0.0
                    new_pnl = ticker_data[ticker]['sell_pnl']  # Use actual PnL from trade log
                else:
                    # For buy transactions, show normal position
                    new_shares = ticker_data[ticker]['total_shares']
                    new_avg_price = ticker_data[ticker]['total_cost'] / ticker_data[ticker]['total_shares'] if ticker_data[ticker]['total_shares'] > 0 else 0
                    new_cost_basis = ticker_data[ticker]['total_cost']
                    new_action = 'BUY'
                    new_current_price = ticker_data[ticker]['last_price']
                    new_total_value = round(new_shares * new_current_price, 2)
                    new_pnl = round((new_current_price - new_avg_price) * new_shares, 2)
                
                # Update values with proper rounding
                portfolio_df.at[idx, 'Shares'] = round(new_shares, 2)
                portfolio_df.at[idx, 'Average Price'] = round(new_avg_price, 2)
                portfolio_df.at[idx, 'Cost Basis'] = round(new_cost_basis, 2)
                portfolio_df.at[idx, 'Action'] = new_action
                portfolio_df.at[idx, 'Current Price'] = round(new_current_price, 2)
                portfolio_df.at[idx, 'Total Value'] = round(new_total_value, 2)
                portfolio_df.at[idx, 'PnL'] = round(new_pnl, 2)
                
                # Track changes
                shares_diff = abs(old_shares - new_shares)
                price_diff = abs(old_avg_price - new_avg_price)
                cost_diff = abs(old_cost_basis - new_cost_basis)
                action_changed = old_action != new_action
                pnl_diff = abs(old_pnl - new_pnl)
                
                if shares_diff > 0.001 or price_diff > 0.01 or cost_diff > 0.01 or action_changed or pnl_diff > 0.01:
                    changes_made.append({
                        'ticker': ticker,
                        'old_shares': old_shares,
                        'new_shares': new_shares,
                        'old_price': old_avg_price,
                        'new_price': new_avg_price,
                        'old_cost': old_cost_basis,
                        'new_cost': new_cost_basis,
                        'old_action': old_action,
                        'new_action': new_action,
                        'old_pnl': old_pnl,
                        'new_pnl': new_pnl,
                        'shares_diff': shares_diff,
                        'price_diff': price_diff,
                        'cost_diff': cost_diff,
                        'action_changed': action_changed,
                        'pnl_diff': pnl_diff
                    })
                    updated_count += 1
        
        # Show detailed changes
        if changes_made:
            print(f"\n{_safe_emoji('🔄')} Updated {updated_count} latest entries:")
            for change in changes_made:
                print(f"   {change['ticker']}:")
                print(f"     Shares: {change['old_shares']:.4f} → {change['new_shares']:.4f} ({change['shares_diff']:.4f} diff)")
                print(f"     Price:  ${change['old_price']:.2f} → ${change['new_price']:.2f} (${change['price_diff']:.2f} diff)")
                print(f"     Cost:   ${change['old_cost']:.2f} → ${change['new_cost']:.2f} (${change['cost_diff']:.2f} diff)")
                print(f"     PnL:    ${change['old_pnl']:.2f} → ${change['new_pnl']:.2f} (${change['pnl_diff']:.2f} diff)")
                if change['action_changed']:
                    print(f"     Action: {change['old_action']} → {change['new_action']}")
        else:
            print(f"\n{_safe_emoji('✅')} No changes needed - all data is already accurate")
        
        # Round all numeric columns to 2 decimal places before saving
        numeric_columns = ['Shares', 'Average Price', 'Cost Basis', 'Stop Loss', 'Current Price', 'Total Value', 'PnL']
        for col in numeric_columns:
            if col in portfolio_df.columns:
                portfolio_df[col] = portfolio_df[col].round(2)
        
        # Save updated portfolio (preserves all historical rows)
        portfolio_df.to_csv(portfolio_file, index=False)
        
        print(f"\n{_safe_emoji('✅')} Portfolio updated with trade log data: {portfolio_file}")
        print(f"   Preserved ALL {len(portfolio_df)} historical price tracking rows")
        print(f"   Updated only the latest entry for each ticker with correct data")
        print(f"   Used actual PnL from trade log for sell transactions")
        print(f"   Backup created at: {backup_file}")
        
        return True
        
    except Exception as e:
        print(f"{_safe_emoji('❌')} Error recalculating portfolio data: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main function to recalculate portfolio data"""
    print(f"{_safe_emoji('🔄')} Recalculating Portfolio Data from Trade Log")
    print("=" * 50)
    
    # Check if data directory argument provided
    data_dir = "trading_data/funds/TEST"
    if len(sys.argv) > 1:
        data_dir = sys.argv[1]
    
    # Show environment banner
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from display.console_output import print_environment_banner
    print_environment_banner(data_dir)
    
    print(f"📁 Using data directory: {data_dir}")
    
    success = recalculate_portfolio_data(data_dir)
    
    if success:
        print("\n🎉 Portfolio data recalculated successfully!")
        print("   All shares, prices, and cost basis are now accurate based on the trade log")
    else:
        print(f"\n{_safe_emoji('❌')} Failed to recalculate portfolio data")
        sys.exit(1)

if __name__ == "__main__":
    main()