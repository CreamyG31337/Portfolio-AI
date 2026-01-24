#!/usr/bin/env python3
"""Quick test for new ETF fetch functions"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import logging
logging.basicConfig(level=logging.INFO, format='%(message)s')

from scheduler.jobs_etf_watchtower import (
    fetch_spdr_holdings,
    fetch_globalx_holdings,
    ETF_CONFIGS
)

# Test XBI
print("\n" + "="*60)
print("Testing XBI (SPDR)")
print("="*60)
xbi_config = ETF_CONFIGS['XBI']
xbi_df = fetch_spdr_holdings('XBI', xbi_config['url'])
if xbi_df is not None:
    print(f"✅ SUCCESS: Got {len(xbi_df)} holdings")
    print(f"Columns: {xbi_df.columns.tolist()}")
    print("\nFirst 3 holdings:")
    print(xbi_df[['ticker', 'name', 'shares']].head(3))
else:
    print("❌ FAILED")

# Test BOTZ
print("\n" + "="*60)
print("Testing BOTZ (Global X)")
print("="*60)
botz_config = ETF_CONFIGS['BOTZ']
botz_df = fetch_globalx_holdings('BOTZ', botz_config['url'])
if botz_df is not None:
    print(f"✅ SUCCESS: Got {len(botz_df)} holdings")
    print(f"Columns: {botz_df.columns.tolist()}")
    print("\nFirst 3 holdings:")
    print(botz_df[['ticker', 'name', 'shares']].head(3))
else:
    print("❌ FAILED")

# Test LIT
print("\n" + "="*60)
print("Testing LIT (Global X)")
print("="*60)
lit_config = ETF_CONFIGS['LIT']
lit_df = fetch_globalx_holdings('LIT', lit_config['url'])
if lit_df is not None:
    print(f"✅ SUCCESS: Got {len(lit_df)} holdings")
    print(f"Columns: {lit_df.columns.tolist()}")
    print("\nFirst 3 holdings:")
    print(lit_df[['ticker', 'name', 'shares']].head(3))
else:
    print("❌ FAILED")
