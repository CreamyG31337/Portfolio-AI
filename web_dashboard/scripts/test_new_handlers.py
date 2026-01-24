#!/usr/bin/env python3
"""Quick test of newly implemented ETF handlers."""

import sys
sys.path.insert(0, 'web_dashboard')

from scheduler.jobs_etf_watchtower import (
    fetch_ishares_holdings, fetch_globalx_holdings, fetch_direxion_holdings,
    fetch_vaneck_holdings, ETF_CONFIGS, ETF_NAMES
)

new_etfs = [
    # iShares
    'SOXX', 'ICLN', 'IBB',
    # Global X
    'BUG', 'FINX',
    # Direxion
    'MOON',
    # VanEck (11 total)
    'SMH', 'DAPP', 'BBH', 'BUZZ', 'IBOT', 'MOAT', 'PPH', 'RTH', 'SMHX', 'SMOT', 'OIH',
]

print("=" * 60)
print("Testing New ETF Handlers")
print("=" * 60)

results = {}

for ticker in new_etfs:
    config = ETF_CONFIGS.get(ticker)
    if not config:
        print(f'{ticker}: NOT FOUND IN CONFIG')
        results[ticker] = False
        continue
    
    print(f'\n{ticker} - {ETF_NAMES.get(ticker, "Unknown")}')
    print(f'  Provider: {config["provider"]}')
    
    try:
        if config['provider'] == 'iShares':
            df = fetch_ishares_holdings(ticker, config['url'])
        elif config['provider'] == 'Global X':
            df = fetch_globalx_holdings(ticker, config['url'])
        elif config['provider'] == 'Direxion':
            df = fetch_direxion_holdings(ticker, config['url'])
        elif config['provider'] == 'VanEck':
            df = fetch_vaneck_holdings(ticker, config['url'])
        else:
            print(f'  [SKIP] Unknown provider')
            results[ticker] = False
            continue
        
        if df is not None and len(df) > 0:
            print(f'  [OK] {len(df)} holdings')
            if 'ticker' in df.columns:
                sample = df['ticker'].head(5).tolist()
                print(f'  Sample: {sample}')
            results[ticker] = True
        else:
            print('  [FAIL] No data returned')
            results[ticker] = False
    except Exception as e:
        print(f'  [ERROR] {e}')
        results[ticker] = False

# Summary
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
passed = sum(1 for v in results.values() if v)
for ticker, success in results.items():
    status = "[OK]" if success else "[FAIL]"
    print(f"  {ticker}: {status}")
print(f"\nTotal: {passed}/{len(results)} passed")
