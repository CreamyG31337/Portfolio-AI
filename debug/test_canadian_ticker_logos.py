"""Test Canadian ticker logo URL generation"""
import sys
from pathlib import Path

# Add web_dashboard to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

from web_dashboard.utils.logo_utils import get_ticker_logo_url, get_ticker_logo_urls

# Test Canadian tickers
test_tickers = [
    'AAPL',           # US ticker
    'XMA.TO',         # Canadian TSX
    'NXT.V',          # Canadian TSXV
    'SHOP.TO',        # Canadian TSX
    'WEED.TO',        # Canadian TSX
    'AC.TO',          # Canadian TSX
    'CNR.TO',         # Canadian TSX
    'TSLA',           # US ticker
    'MSFT',           # US ticker
]

print("Testing Logo URL Generation")
print("=" * 60)

for ticker in test_tickers:
    url = get_ticker_logo_url(ticker)
    print(f"{ticker:12} -> {url}")

print("\n" + "=" * 60)
print("Testing Batch Logo URL Generation")
print("=" * 60)

urls_map = get_ticker_logo_urls(test_tickers)
for ticker, url in urls_map.items():
    print(f"{ticker:12} -> {url}")

print("\n" + "=" * 60)
print("Testing Canadian Ticker Suffix Removal")
print("=" * 60)

canadian_tickers = ['XMA.TO', 'NXT.V', 'SHOP.TO', 'WEED.TO', 'AC.TO', 'CNR.TO']
for ticker in canadian_tickers:
    url = get_ticker_logo_url(ticker)
    # Extract base ticker from URL
    if url:
        # Parqet URL format: https://assets.parqet.com/logos/symbol/{base_ticker}?format=png&size=64
        if 'parqet.com' in url:
            base_from_url = url.split('/symbol/')[1].split('?')[0] if '/symbol/' in url else 'N/A'
        else:
            base_from_url = 'N/A'
    else:
        base_from_url = 'None'
    
    expected_base = ticker.rsplit('.', 1)[0]
    print(f"{ticker:12} -> Base: {expected_base:8} | URL base: {base_from_url:8} | Match: {expected_base == base_from_url}")
