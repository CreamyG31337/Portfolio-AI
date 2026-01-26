# Congress Trades Data Collection - Field Mapping

## Two Data Sources

### 1. Congress Trades Scraper (Manual - `seed_congress_trades.py`)
**Source**: External website (uses FlareSolverr to bypass Cloudflare)
**Frequency**: Manual runs only
**Reliability**: ⚠️ May break if website changes

#### Fields Captured:
- ✅ `ticker` - Stock symbol
- ✅ `company_name` - Full company name
- ✅ `politician` - Full name
- ✅ `chamber` - House/Senate
- ✅ `party` - Democratic/Republican/Independent
- ✅ `state` - 2-letter state code (looked up from database)
- ✅ `owner` - Self/Spouse/Dependent/Joint
- ✅ `owner` - "Self", "Spouse", "Child"
- ✅ `transaction_date` - Trade date
- ✅ `disclosure_date` - Disclosure date
- ✅ `type` - Purchase/Sale/Exchange/Transfer
- ✅ `amount` - Range (e.g., "$1,001 - $15,000")
- ✅ `price` - Transaction price if available
- ✅ `asset_type` - Stock/Crypto
- ✅ **`notes`** - **Tooltip/description** (e.g., "Exchange", "Transfer", other trade details)

---

### 2. FMP API Job (Automated - `fetch_congress_trades_job()`)
**Source**: Financial Modeling Prep API
**Frequency**: Every 12 minutes (scheduler job)
**Reliability**: ✅ Stable API, unlikely to break

#### Fields Captured (Updated 2025-12-27):
- ✅ `ticker` - From `symbol` field
- ✅ `politician` - From `firstName` + `lastName`
- ✅ `chamber` - House/Senate (from endpoint)
- ✅ **`party`** - **NEW**: Extracted from `office` field pattern (D-CA, R-TX, etc.)
- ✅ **`state`** - **NEW**: Extracted from `office` field pattern
- ✅ **`owner`** - **NEW**: From `owner`/`assetOwner`/`ownerType` if available
- ✅ `transaction_date` - From `transactionDate`
- ✅ `disclosure_date` - From `disclosureDate`
- ✅ `type` - Purchase/Sale (from `type`/`transactionType`)
- ✅ `amount` - From `amount`/`value`/`range`
- ✅ **`price`** - **NEW**: From `pricePerShare`/`price_per_share`/`price`
- ✅ `asset_type` - Stock/Crypto (from `assetType`)
- ✅ **`notes`** - **NEW**: Combined from:
  - `description`/`comment`/`notes`/`memo` fields
  - `capitalGains` flag if set
  - `link`/`disclosureUrl` to original disclosure

---

## Comparison

| Field | Scraper | FMP API | Notes |
|-------|---------|---------|-------|
| ticker | ✅ | ✅ | Both sources |
| politician | ✅ | ✅ | Both sources |
| chamber | ✅ | ✅ | Both sources |
| **party** | ✅ | ✅ | Scraper: direct field, API: extracted from office |
| **state** | ✅ | ✅ | Scraper: DB lookup, API: extracted from office |
| **owner** | ✅ | ✅ | May be null in API |
| owner | ✅ | ✅ | FMP via `owner` (fallback to Text) |
| transaction_date | ✅ | ✅ | Both sources |
| disclosure_date | ✅ | ✅ | Both sources |
| type | ✅ | ✅ | Both sources |
| amount | ✅ | ✅ | Both sources |
| price | ✅ | ✅ | Both sources (API: pricePerShare) |
| asset_type | ✅ | ✅ | Both sources |
| **notes** | ✅ | ✅ | Scraper: tooltip, API: description+links |
| company_name | ✅ | ❌ | Scraper only |

---

## Recommendations

1. **Use FMP API as primary source** (automated, stable)
2. **Use scraper for backfill** (more complete data, but may break)
3. **Both now capture all critical metadata** for AI analysis
4. **Notes field preserved** for tooltip/description text from both sources

---

## What Changed (2025-12-27)

### Before:
- FMP API was missing: party, state, owner, price, notes
- Only scraper had complete metadata

### After:
- ✅ FMP API now extracts **all available fields**
- ✅ Party & state extracted from `office` field patterns
- ✅ Owner extracted if available
- ✅ Price per share captured
- ✅ Notes built from description, capital gains, disclosure links
- ✅ Both sources now provide sufficient data for AI analysis

---

## AI Analysis Requirements

For effective conflict-of-interest analysis, we need:
- ✅ politician name
- ✅ party (for industry-relevance scoring)
- ✅ state (for state-interest scoring)
- ✅ committee assignments (from separate table)
- ✅ ticker & company
- ✅ trade type & amount
- ✅ owner (Self vs Spouse matters)
- ✅ date (for timing analysis)

**Both sources now provide sufficient data for AI analysis!** ✅
