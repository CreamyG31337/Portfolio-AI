#!/usr/bin/env python3
"""
Script to populate securities table with data from fundamentals_overrides.json.

This script reads the override file and updates the securities table in Supabase
with sector, industry, and country data for tickers that have overrides.
Overrides take precedence over yfinance data (which may be NULL or incorrect for ETFs).
"""

import json
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
import sys
sys.path.insert(0, str(project_root))

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv(project_root / '.env')

from supabase import create_client


def load_overrides(config_path: Path) -> dict:
    """Load fundamentals overrides from JSON file."""
    with open(config_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Filter out meta keys (starting with _)
    overrides = {k: v for k, v in data.items() if not k.startswith('_')}
    return overrides


def main():
    """Update securities table with overrides data."""
    
    # Get Supabase credentials - use secret key to bypass RLS for admin operations
    supabase_url = os.environ.get('SUPABASE_URL')
    # Prefer secret key (bypasses RLS), fall back to service key or publishable key
    supabase_key = (
        os.environ.get('SUPABASE_SECRET_KEY') or
        os.environ.get('SUPABASE_SERVICE_KEY') or
        os.environ.get('SUPABASE_PUBLISHABLE_KEY')
    )

    if not supabase_url or not supabase_key:
        print("[ERROR] SUPABASE_URL and SUPABASE_SECRET_KEY environment variables required")
        return
    
    # Connect to Supabase
    supabase = create_client(supabase_url, supabase_key)
    print(f"[OK] Connected to Supabase")
    
    # Load overrides
    config_path = project_root / 'config' / 'fundamentals_overrides.json'
    overrides = load_overrides(config_path)
    print(f"[INFO] Loaded {len(overrides)} overrides from {config_path}")
    
    # Get existing tickers in securities table (paginate to get all)
    existing_tickers = set()
    page_size = 1000
    offset = 0
    while True:
        result = supabase.table('securities').select('ticker').range(offset, offset + page_size - 1).execute()
        if not result.data:
            break
        existing_tickers.update(row['ticker'] for row in result.data)
        if len(result.data) < page_size:
            break
        offset += page_size
    print(f"[INFO] Found {len(existing_tickers)} tickers in securities table")
    
    # Update each ticker with override data
    updated = 0
    inserted = 0
    skipped = 0
    
    for ticker, override_data in overrides.items():
        # Build update object with only relevant fields
        update_obj = {}
        
        if 'sector' in override_data:
            update_obj['sector'] = override_data['sector']
        if 'industry' in override_data:
            update_obj['industry'] = override_data['industry']
        if 'country' in override_data:
            update_obj['country'] = override_data['country']
        
        # Note: description_note is NOT used for company_name - it's just a note
        # Company names should be fetched from yfinance or provided explicitly
        
        if not update_obj:
            skipped += 1
            continue
        
        if ticker in existing_tickers:
            # Update existing ticker
            try:
                supabase.table('securities').update(update_obj).eq('ticker', ticker).execute()
                print(f"  [+] Updated {ticker}: sector={update_obj.get('sector')}, industry={update_obj.get('industry')}")
                updated += 1
            except Exception as e:
                print(f"  [!] Failed to update {ticker}: {e}")
        else:
            # Insert new ticker (if it's in our portfolio)
            try:
                update_obj['ticker'] = ticker
                supabase.table('securities').insert(update_obj).execute()
                print(f"  [NEW] Inserted {ticker}: sector={update_obj.get('sector')}, industry={update_obj.get('industry')}")
                inserted += 1
            except Exception as e:
                print(f"  [!] Failed to insert {ticker}: {e}")
    
    print(f"\n=== Summary ===")
    print(f"  Updated: {updated}")
    print(f"  Inserted: {inserted}")
    print(f"  Skipped: {skipped}")


if __name__ == '__main__':
    main()
