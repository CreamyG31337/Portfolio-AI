#!/usr/bin/env python3
"""
Debug company name lookup to understand why it's not working
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

def debug_company_names():
    """Debug company name lookup step by step."""
    
    import pandas as pd
    import glob
    import yfinance as yf
    import logging
    
    # Suppress yfinance logging
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    
    problematic_tickers = ['KEY', 'DOL', 'NXTG']
    
    # Load currency cache
    portfolio_files = glob.glob('trading_data/funds/*/llm_portfolio_update.csv')
    currency_cache = {}
    
    for file_path in portfolio_files:
        try:
            df = pd.read_csv(file_path)
            if 'Ticker' in df.columns and 'Currency' in df.columns:
                latest_entries = df.groupby('Ticker').last()
                for row in latest_entries.itertuples():
                    currency_cache[row.Index] = row.Currency
        except Exception:
            continue
    
    print('Debugging company name lookup:')
    print('=' * 50)
    
    for ticker in problematic_tickers:
        print(f'\n{ticker}:')
        currency = currency_cache.get(ticker, 'NOT_FOUND')
        print(f'  Currency: {currency}')
        
        # Determine variants to try
        is_likely_canadian = currency == 'CAD'
        print(f'  Likely Canadian: {is_likely_canadian}')
        
        if is_likely_canadian:
            variants_to_try = [f"{ticker}.TO", f"{ticker}.V", ticker]
        else:
            variants_to_try = [ticker, f"{ticker}.TO", f"{ticker}.V"]
        
        print(f'  Variants to try: {variants_to_try}')
        
        # Try each variant
        for variant in variants_to_try:
            try:
                stock = yf.Ticker(variant)
                info = stock.info
                company_name = info.get('longName', info.get('shortName', 'Unknown'))
                
                if company_name and company_name != 'Unknown' and len(company_name) > 3:
                    print(f'    {variant}: {company_name}')
                    break
                else:
                    print(f'    {variant}: No valid name found')
            except Exception as e:
                print(f'    {variant}: Error - {e}')

if __name__ == "__main__":
    debug_company_names()
