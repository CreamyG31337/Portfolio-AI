#!/usr/bin/env python3
"""
Data fix script to update trade log CSV to include Webull's $2.99 per trade fees.
"""

import pandas as pd
import shutil
from decimal import Decimal
from datetime import datetime

def fix_trade_log_with_fees():
    """Update trade log to include Webull fees in TEST environment."""
    
    # File paths for TEST environment
    data_dir = 'trading_data/funds/TEST'
    trade_log_file = f'{data_dir}/llm_trade_log.csv'
    backup_file = f'{data_dir}/llm_trade_log_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    
    # Create backup
    shutil.copy2(trade_log_file, backup_file)
    print(f"Backup created: {backup_file}")
    
    # Load data
    df = pd.read_csv(trade_log_file)
    print(f"Loaded {len(df)} trades from TEST environment")
    
    # Webull commission per trade
    commission_per_trade = Decimal('2.99')
    
    # Update prices for all trades (BUY and SELL)
    changes_made = 0
    # itertuples preserves the index label needed by df.at[index, 'Price'].
    for row in df.itertuples():
        if row.Shares > 0: # Ensure shares are positive for a valid trade
            shares = Decimal(str(row.Shares))
            price = Decimal(str(row.Price))
            
            # Add fee per share to price
            fee_per_share = commission_per_trade / shares
            new_price = price + fee_per_share
            new_price = new_price.quantize(Decimal('0.01'))
            
            df.at[row.Index, 'Price'] = float(new_price)
            changes_made += 1
    
    # Save updated CSV
    df.to_csv(trade_log_file, index=False)
    print(f"Updated {changes_made} trades with Webull fees")
    print(f"Updated {trade_log_file}")
    print("Trade log fix complete!")
    print("Now run the recreate to update portfolio with corrected prices")

if __name__ == "__main__":
    fix_trade_log_with_fees()
