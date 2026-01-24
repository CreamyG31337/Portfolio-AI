# ETF Watchtower Job Documentation

## Overview

The ETF Watchtower job tracks daily changes in ETF holdings by downloading CSV/XLSX files directly from ETF providers (iShares, ARK Invest, Global X, SPDR, Direxion, VanEck) and comparing them to previous snapshots. This enables detection of institutional accumulation/distribution patterns ("The Diff Engine").

## Supported ETFs

**Total: 32 ETFs across 6 providers**

### iShares (BlackRock) - 7 ETFs
- **IVV**: iShares Core S&P 500 ETF (~509 holdings)
- **IWM**: iShares Russell 2000 ETF (~1957 holdings)
- **IWC**: iShares Micro-Cap ETF (~1316 holdings)
- **IWO**: iShares Russell 2000 Growth ETF (~1102 holdings)
- **SOXX**: iShares Semiconductor ETF (~36 holdings) - *Added Jan 2026*
- **ICLN**: iShares Global Clean Energy ETF (~136 holdings) - *Added Jan 2026*
- **IBB**: iShares Biotechnology ETF (~265 holdings) - *Added Jan 2026*

### ARK Invest - 8 ETFs
- **ARKK**: ARK Innovation ETF (~45 holdings)
- **ARKQ**: ARK Autonomous Technology & Robotics ETF (~37 holdings)
- **ARKW**: ARK Next Generation Internet ETF (~45 holdings)
- **ARKG**: ARK Genomic Revolution ETF (~34 holdings)
- **ARKF**: ARK Fintech Innovation ETF (~41 holdings)
- **ARKX**: ARK Space Exploration & Innovation ETF (~33 holdings)
- **IZRL**: ARK Israel Innovative Technology ETF (~64 holdings)
- **PRNT**: The 3D Printing ETF (~44 holdings)

### Global X - 4 ETFs
- **BOTZ**: Global X Robotics & Artificial Intelligence ETF
- **LIT**: Global X Lithium & Battery Tech ETF
- **BUG**: Global X Cybersecurity ETF - *Added Jan 2026*
- **FINX**: Global X FinTech ETF - *Added Jan 2026*

### SPDR (State Street) - 1 ETF
- **XBI**: SPDR S&P Biotech ETF

### Direxion - 1 ETF
- **MOON**: Direxion Moonshot Innovators ETF (~50 holdings) - *Added Jan 2026*

### VanEck - 11 ETFs
- **SMH**: VanEck Semiconductor ETF (~27 holdings) - *Added Jan 2026*
- **DAPP**: VanEck Digital Transformation ETF (~23 holdings) - *Added Jan 2026*
- **BBH**: VanEck Biotech ETF (~27 holdings) - *Added Jan 2026*
- **BUZZ**: VanEck Social Sentiment ETF (~77 holdings) - *Added Jan 2026*
- **IBOT**: VanEck Robotics ETF (~50 holdings) - *Added Jan 2026*
- **MOAT**: VanEck Morningstar Wide Moat ETF (~56 holdings) - *Added Jan 2026*
- **PPH**: VanEck Pharmaceutical ETF (~27 holdings) - *Added Jan 2026*
- **RTH**: VanEck Retail ETF (~27 holdings) - *Added Jan 2026*
- **SMHX**: VanEck Fabless Semiconductor ETF (~24 holdings) - *Added Jan 2026*
- **SMOT**: VanEck Morningstar SMID Moat ETF (~108 holdings) - *Added Jan 2026*
- **OIH**: VanEck Oil Services ETF (~27 holdings) - *Added Jan 2026*

## How It Works

1. **Download Holdings**: Fetches today's holdings CSV from provider
2. **Get Previous Snapshot**: Retrieves yesterday's holdings from database
3. **Calculate Differences**: Compares holdings to detect changes
4. **Filter Changes**: Removes non-stock holdings and systematic adjustments
5. **Generate Article**: Creates research article for significant changes
6. **Save Snapshot**: Stores today's holdings for tomorrow's comparison

## Change Detection Thresholds

- **MIN_SHARE_CHANGE**: 1000 shares (minimum absolute share change)
- **MIN_PERCENT_CHANGE**: 0.5% (minimum percentage change)

A change is considered "significant" if it meets EITHER threshold (OR logic).

## Systematic Adjustment Filtering

### Problem

ETF providers sometimes apply systematic adjustments to all holdings proportionally:
- Expense ratio deductions (~0.5% annually)
- Data normalization/rounding
- Administrative rebalancing calculations

These adjustments affect ALL holdings by the same percentage and are NOT trading activity.

### Detection Criteria

The job automatically filters out systematic adjustments when:

1. **Clustering**: 80%+ of changes cluster around the same percentage (within 0.1%)
2. **Size**: That percentage is ≤2% (small adjustments, not large trades)
3. **Direction**: All changes are in the same direction (all buys OR all sells)

### Example: Systematic Adjustment

```
ARKG on 2026-01-21: 29 changes detected
- All 29 changes: exactly -0.5%
- All are "SELL" actions
- No new positions, no removed positions
→ FILTERED OUT (systematic adjustment, not trading)
```

### Example: Real Trading

```
IWM on 2026-01-21: 3 changes detected
- ADRO: -272,339 shares (-17.1%)
- ADRO: -1,316,575 shares (-82.9%)
- MNMD: -16,632 shares (100.0%)
→ KEPT (legitimate trading activity)
```

## Pagination Fix

### Problem

Supabase has a default limit of 1000 rows per query. For ETFs with >1000 holdings (IWM, IWC, IWO), this caused:
- Only first 1000 holdings fetched from previous day
- Remaining holdings appeared as "new" positions
- False positives: IWM showed 955 changes instead of 3

### Solution

The `get_previous_holdings()` function now uses pagination:
- Fetches holdings in batches of 1000
- Continues until all holdings are retrieved
- Ensures complete comparison data

### Impact

- **Before**: IWM flagged 955 false changes (958 holdings beyond limit)
- **After**: IWM correctly detects 3 real changes

## Data Storage

### Database Tables

- **`etf_holdings_log`** (Supabase): Daily snapshots of all holdings
  - Columns: `date`, `etf_ticker`, `holding_ticker`, `holding_name`, `shares_held`, `weight_percent`
  - Primary key: `(date, etf_ticker, holding_ticker)`
  
- **`research_articles`** (Postgres): Generated articles for significant changes
  - Article type: `ETF Change`
  - Contains summary of top buys/sells

### Data Retention

- Holdings snapshots: Indefinite (used for historical comparison)
- Research articles: Standard retention policy

## Running the Job

### Scheduled Execution

- **Frequency**: Daily at 8:00 PM EST (after ARK publishes holdings)
- **Job ID**: `etf_watchtower`
- **Location**: `web_dashboard/scheduler/jobs_etf_watchtower.py`

### Manual Execution

```bash
cd web_dashboard
.\venv\Scripts\activate
python -c "from scheduler.jobs_etf_watchtower import etf_watchtower_job; etf_watchtower_job()"
```

## Debugging Tools

### Test Holdings Comparison
```bash
python debug/test_iwm_holdings.py
```

### Show Changes for Specific Date
```bash
python debug/show_ark_changes.py --etf ARKG --date 2026-01-21
```

### Verify Fix
```bash
python debug/verify_etf_fix.py
```

### Cleanup Bad Articles
```bash
python debug/cleanup_bad_etf_articles.py --delete
```

### Re-process Today's Data
```bash
python debug/reprocess_today_etf_articles.py
```

## Known Issues & Solutions

### Issue: High Change Counts for Large ETFs

**Symptom**: IWM, IWC, IWO showing hundreds of changes

**Cause**: Pagination bug - only first 1000 holdings fetched

**Solution**: Fixed with pagination in `get_previous_holdings()`

### Issue: Systematic Adjustments Flagged as Changes

**Symptom**: ARKG showing 29 changes, all at exactly -0.5%

**Cause**: Expense ratio deduction affecting all holdings proportionally

**Solution**: Automatic filtering of systematic adjustments

### Issue: Missing Previous Data

**Symptom**: All holdings appear as "new" on first run

**Cause**: No previous snapshot exists

**Solution**: Job saves snapshot but skips article generation (expected behavior)

## Future Improvements

- [ ] Save CSV files for historical re-processing
- [ ] Add VanEck TAN (Solar Energy) - requires FlareSolverr or different URL pattern
- [ ] Improve systematic adjustment detection (ML-based)
- [ ] Add alerts for unusual change patterns
- [ ] Track cumulative changes over time

## Changelog

### January 2026
- Added 17 new ETFs:
  - iShares: SOXX (Semiconductors), ICLN (Clean Energy), IBB (Biotech)
  - Global X: BUG (Cybersecurity), FINX (FinTech)
  - Direxion: MOON (Moonshot Innovators)
  - VanEck (11 ETFs): SMH, DAPP, BBH, BUZZ, IBOT, MOAT, PPH, RTH, SMHX, SMOT, OIH
- Added new `fetch_direxion_holdings()` handler for Direxion CSV format
- Added new `fetch_vaneck_holdings()` handler for VanEck XLSX format
- Modified `fetch_globalx_holdings()` to try up to 5 days back (handles weekends/holidays)
- Total ETFs increased from 15 to 32
