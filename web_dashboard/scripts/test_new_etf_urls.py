#!/usr/bin/env python3
"""
Test script to validate new ETF CSV/Excel URLs before adding to ETF Watchtower.

Tests URLs from:
- iShares (SOXX, ICLN, IBB)
- Global X (BUG, FINX)
- VanEck (SMH, TAN, DAPP)
- Direxion (MOON)

Run: python web_dashboard/scripts/test_new_etf_urls.py
"""

import requests
import pandas as pd
from io import StringIO, BytesIO
from datetime import datetime
import logging
import sys

# Force UTF-8 output on Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Check for required dependencies
try:
    import openpyxl
    OPENPYXL_AVAILABLE = True
    logger.info("[OK] openpyxl is installed (required for Excel files)")
except ImportError:
    OPENPYXL_AVAILABLE = False
    logger.warning("[FAIL] openpyxl is NOT installed - Excel files will fail")
    logger.warning("   Install with: pip install openpyxl")

print()

# Standard headers for requests
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}


def test_ishares(ticker: str, product_id: str, slug: str):
    """Test iShares AJAX CSV endpoint."""
    url = f"https://www.ishares.com/us/products/{product_id}/{slug}/1467271812596.ajax?fileType=csv&fileName={ticker}_holdings&dataType=fund"
    
    print(f"\n{'='*60}")
    print(f"Testing {ticker} (iShares)")
    print(f"URL: {url}")
    print('='*60)
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        
        if response.status_code != 200:
            print(f"[FAIL] HTTP {response.status_code}")
            return False
            
        print(f"[OK] HTTP 200 OK | Content-Type: {response.headers.get('Content-Type', 'unknown')}")
        
        # Parse CSV - iShares has metadata rows at top
        content = response.text
        lines = content.split('\n')
        header_row = 0
        for i, line in enumerate(lines[:25]):
            if 'Ticker' in line and ('Name' in line or 'Security Name' in line):
                header_row = i
                break
        
        df = pd.read_csv(StringIO(content), skiprows=header_row)
        df.columns = df.columns.str.strip()
        
        print(f"[OK] Parsed {len(df)} rows")
        print(f"   Columns: {df.columns.tolist()}")
        
        # Check for required columns
        has_ticker = 'Ticker' in df.columns
        has_shares = 'Shares' in df.columns or 'Quantity' in df.columns
        
        if has_ticker and has_shares:
            print(f"[OK] Has required columns (Ticker, Shares/Quantity)")
            # Show sample
            print(f"\n   Sample data:")
            print(df.head(3).to_string(index=False))
            return True
        else:
            print(f"[FAIL] Missing required columns")
            return False
            
    except Exception as e:
        print(f"[FAIL] Error: {e}")
        return False


def test_globalx(ticker: str):
    """Test Global X date-based CSV endpoint."""
    today = datetime.now()
    date_str = today.strftime('%Y%m%d')
    url = f"https://assets.globalxetfs.com/funds/holdings/{ticker.lower()}_full-holdings_{date_str}.csv"
    
    print(f"\n{'='*60}")
    print(f"Testing {ticker} (Global X)")
    print(f"URL: {url}")
    print('='*60)
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        
        if response.status_code != 200:
            print(f"[FAIL] HTTP {response.status_code}")
            # Try yesterday's date
            from datetime import timedelta
            yesterday = (today - timedelta(days=1)).strftime('%Y%m%d')
            url_yesterday = f"https://assets.globalxetfs.com/funds/holdings/{ticker.lower()}_full-holdings_{yesterday}.csv"
            print(f"   Trying yesterday: {url_yesterday}")
            response = requests.get(url_yesterday, headers=HEADERS, timeout=30)
            if response.status_code != 200:
                print(f"[FAIL] HTTP {response.status_code} for yesterday too")
                return False
            
        print(f"[OK] HTTP 200 OK | Content-Type: {response.headers.get('Content-Type', 'unknown')}")
        
        # Global X CSVs have 2 header rows
        df = pd.read_csv(StringIO(response.text), skiprows=2)
        df.columns = df.columns.str.strip()
        
        print(f"[OK] Parsed {len(df)} rows")
        print(f"   Columns: {df.columns.tolist()}")
        
        # Check for required columns
        has_ticker = 'Ticker' in df.columns
        has_shares = 'Shares Held' in df.columns
        
        if has_ticker and has_shares:
            print(f"[OK] Has required columns (Ticker, Shares Held)")
            print(f"\n   Sample data:")
            print(df.head(3).to_string(index=False))
            return True
        else:
            print(f"[FAIL] Missing required columns")
            return False
            
    except Exception as e:
        print(f"[FAIL] Error: {e}")
        return False


def test_vaneck(ticker: str, slug: str):
    """Test VanEck Excel endpoint."""
    url = f"https://www.vaneck.com/us/en/investments/{slug}/holdings/{ticker.lower()}-holdings.xlsx"
    
    print(f"\n{'='*60}")
    print(f"Testing {ticker} (VanEck)")
    print(f"URL: {url}")
    print('='*60)
    
    if not OPENPYXL_AVAILABLE:
        print("[FAIL] Skipping - openpyxl not installed")
        return False
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        
        if response.status_code != 200:
            print(f"[FAIL] HTTP {response.status_code}")
            return False
            
        print(f"[OK] HTTP 200 OK | Content-Type: {response.headers.get('Content-Type', 'unknown')}")
        
        # Parse Excel
        df = pd.read_excel(BytesIO(response.content), engine='openpyxl')
        df.columns = df.columns.str.strip()
        
        print(f"[OK] Parsed {len(df)} rows")
        print(f"   Columns: {df.columns.tolist()}")
        
        # Show sample
        print(f"\n   Sample data:")
        print(df.head(3).to_string(index=False))
        return True
            
    except Exception as e:
        print(f"[FAIL] Error: {e}")
        return False


def test_direxion(ticker: str):
    """Test Direxion CSV endpoint."""
    url = f"https://www.direxion.com/holdings/{ticker}.csv"
    
    print(f"\n{'='*60}")
    print(f"Testing {ticker} (Direxion)")
    print(f"URL: {url}")
    print('='*60)
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        
        if response.status_code != 200:
            print(f"[FAIL] HTTP {response.status_code}")
            return False
            
        print(f"[OK] HTTP 200 OK | Content-Type: {response.headers.get('Content-Type', 'unknown')}")
        
        # Parse CSV - Direxion has 5 header rows before the data
        df = pd.read_csv(StringIO(response.text), skiprows=5)
        df.columns = df.columns.str.strip()
        
        print(f"[OK] Parsed {len(df)} rows")
        print(f"   Columns: {df.columns.tolist()}")
        
        # Check for required columns
        has_ticker = 'StockTicker' in df.columns
        has_shares = 'Shares' in df.columns
        
        if has_ticker and has_shares:
            print(f"[OK] Has required columns (StockTicker, Shares)")
            print(f"\n   Sample data:")
            print(df.head(3).to_string(index=False))
            return True
        else:
            print(f"[FAIL] Missing required columns")
            return False
            
    except Exception as e:
        print(f"[FAIL] Error: {e}")
        return False


def main():
    print("=" * 60)
    print("ETF URL Validation Test")
    print("=" * 60)
    
    results = {}
    
    # Test iShares ETFs
    results['SOXX'] = test_ishares('SOXX', '239705', 'ishares-phlx-semiconductor-sector-index-fund')
    results['ICLN'] = test_ishares('ICLN', '239738', 'ishares-global-clean-energy-etf')
    results['IBB'] = test_ishares('IBB', '239699', 'ishares-nasdaq-biotechnology-etf')
    
    # Test Global X ETFs
    results['BUG'] = test_globalx('BUG')
    results['FINX'] = test_globalx('FINX')
    
    # VanEck ETFs - SKIPPED: URLs return HTML pages, not direct downloads
    # These would require JavaScript/browser automation to download
    print("\n" + "=" * 60)
    print("SKIPPED: VanEck ETFs (SMH, TAN, DAPP)")
    print("  Reason: URLs return HTML pages, not direct file downloads")
    print("=" * 60)
    
    # Test Direxion ETFs
    results['MOON'] = test_direxion('MOON')
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for ticker, success in results.items():
        status = "[OK] PASS" if success else "[FAIL] FAIL"
        print(f"  {ticker}: {status}")
    
    print(f"\nTotal: {passed}/{total} passed")
    
    if passed < total:
        print("\n[WARN]  Some URLs failed. Check the output above for details.")
        print("   Failed URLs may need different patterns or manual verification.")


if __name__ == '__main__':
    main()
