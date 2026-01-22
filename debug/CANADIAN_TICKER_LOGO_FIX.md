# Canadian Ticker Logo Fix

## Problem
Canadian tickers like `DRX.TO` were not finding logos because the code was stripping the `.TO` suffix before querying the Parqet API.

## Root Cause
The `logo_utils.py` function was removing exchange suffixes (`.TO`, `.V`, etc.) from Canadian tickers, assuming logos would be available for the base ticker. However, **Parqet API requires the full ticker with suffix for Canadian exchanges**.

## Testing Results

### Test Script
Created `debug/test_canadian_ticker_logos_debug.py` to test multiple APIs and formats.

### Key Findings

1. **Parqet API Behavior:**
   - ✅ `DRX.TO` (full ticker) → Returns 200 (works)
   - ❌ `DRX` (base ticker) → Returns 404 (fails)
   - ✅ `AAPL` (US ticker, no suffix) → Returns 200 (works)

2. **Other APIs Tested:**
   - Yahoo Finance: Returns 403 (blocked/requires auth)
   - yfinance: No logo_url in info dict
   - CompaniesLogo.com: Requires API key
   - IEX Cloud: Requires API key
   - Finnhub: Requires API key

3. **Conclusion:**
   - Parqet is the best free option
   - Parqet needs full ticker with suffix for Canadian tickers
   - Parqet works fine with base ticker for US tickers

## Solution

Updated `web_dashboard/utils/logo_utils.py` to:
1. **Keep the full ticker (with suffix) for Parqet API calls**
   - This fixes Canadian tickers like `DRX.TO`
   - Still works for US tickers like `AAPL` (no suffix to remove)

2. **Extract base ticker only for Yahoo Finance fallback**
   - Yahoo Finance typically uses base ticker format
   - This maintains compatibility with existing fallback logic

## Code Changes

**Before:**
```python
# Stripped suffix for all APIs
if '.' in clean_ticker:
    parts = clean_ticker.rsplit('.', 1)
    if len(parts) == 2 and parts[1] in ('TO', 'V', 'CN', ...):
        base_ticker = parts[0]  # Removed suffix
    else:
        base_ticker = clean_ticker
else:
    base_ticker = clean_ticker

parqet_url = f"https://assets.parqet.com/logos/symbol/{base_ticker}?format=png&size=64"
```

**After:**
```python
# Keep full ticker for Parqet (needs suffix for Canadian tickers)
parqet_ticker = clean_ticker  # Keep suffix if present

# Extract base ticker only for Yahoo fallback
if '.' in clean_ticker:
    parts = clean_ticker.rsplit('.', 1)
    if len(parts) == 2 and parts[1] in ('TO', 'V', 'CN', ...):
        base_ticker = parts[0]  # Only for Yahoo fallback
    else:
        base_ticker = clean_ticker
else:
    base_ticker = clean_ticker

parqet_url = f"https://assets.parqet.com/logos/symbol/{parqet_ticker}?format=png&size=64"
```

## Verification

Tested with:
- ✅ `DRX.TO` → `https://assets.parqet.com/logos/symbol/DRX.TO?format=png&size=64` (200 OK)
- ✅ `AAPL` → `https://assets.parqet.com/logos/symbol/AAPL?format=png&size=64` (200 OK)
- ✅ `SHOP.TO` → `https://assets.parqet.com/logos/symbol/SHOP.TO?format=png&size=64` (200 OK)

## Alternative APIs Considered

If Parqet doesn't have a logo for a specific ticker, the following alternatives were researched but require API keys or have limitations:

1. **CompaniesLogo.com** - $49/month, 10,000+ logos
2. **Benzinga** - Explicitly supports TSX, but requires paid API
3. **IEX Cloud** - Free tier available but limited
4. **Yahoo Finance** - Returns 403 (blocked/requires auth)

For now, Parqet remains the best free option with good coverage.

## Future Improvements

1. **Server-side caching**: Download logos to `static/logos/{ticker}.png` and serve locally
2. **Multiple fallback attempts**: Try base ticker if full ticker fails (for edge cases)
3. **Logo validation**: Check if URL returns valid image before returning it
