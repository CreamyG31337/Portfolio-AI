#!/usr/bin/env python3
"""
Fix currency assignments in existing portfolio data.

This script corrects the currency field in the portfolio CSV files
based on ticker suffixes (.TO, .V, etc. for CAD, everything else for USD).
"""

import pandas as pd
import glob
import sys
from pathlib import Path

# Add the project root to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from financial.currency_handler import CurrencyHandler

def fix_currency_assignments(data_dir: str = "trading_data/funds/TEST"):
    """Fix currency assignments in portfolio CSV files."""
    
    print(f"Fixing currency assignments in {data_dir}")
    
    # Initialize currency handler
    currency_handler = CurrencyHandler(Path(data_dir))
    
    # Find all portfolio CSV files
    portfolio_files = glob.glob(f"{data_dir}/llm_portfolio_update.csv")
    
    for file_path in portfolio_files:
        print(f"\nProcessing: {file_path}")
        
        try:
            # Read the CSV file
            df = pd.read_csv(file_path)
            
            if 'Currency' not in df.columns:
                print(f"  No Currency column found in {file_path}")
                continue
            
            # Track changes
            changes_made = 0
            
            # Fix currency assignments based on ticker
            # itertuples preserves the index label needed by df.at[index, ...].
            for row in df.itertuples():
                ticker = row.Ticker
                current_currency = row.Currency
                
                # Get correct currency
                correct_currency = currency_handler.get_ticker_currency(ticker)
                
                if current_currency != correct_currency:
                    print(f"  Fixing {ticker}: {current_currency} -> {correct_currency}")
                    df.at[row.Index, 'Currency'] = correct_currency
                    changes_made += 1
            
            if changes_made > 0:
                # Create backup
                backup_path = file_path.replace('.csv', '_currency_backup.csv')
                df_original = pd.read_csv(file_path)
                df_original.to_csv(backup_path, index=False)
                print(f"  Created backup: {backup_path}")
                
                # Save corrected file
                df.to_csv(file_path, index=False)
                print(f"  Fixed {changes_made} currency assignments")
            else:
                print(f"  No currency corrections needed")
                
        except Exception as e:
            print(f"  Error processing {file_path}: {e}")
    
    print("\nCurrency assignment fix completed!")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        data_dir = sys.argv[1]
    else:
        data_dir = "trading_data/funds/TEST"
    
    fix_currency_assignments(data_dir)
