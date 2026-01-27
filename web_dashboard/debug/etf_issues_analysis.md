# ETF Tracking Issues Analysis

## Issue 1: Query Not Returning Data Properly

### Current Implementation
- **Location**: `web_dashboard/routes/etf_routes.py` - `get_holdings_changes()` function
- **NOT using a view**: The function queries `etf_holdings_log` table directly, NOT the `etf_holdings_changes` view
- **There IS a view**: `etf_holdings_changes` exists in the database but is unused by the Flask route

### The Problem
1. **Line 259**: `get_as_of_date()` returns the **global latest date** across ALL ETFs (2026-01-27)
2. **Line 276**: Query uses `WHERE date = '2026-01-27'` (exact match)
3. **Result**: ETFs without data on 2026-01-27 are completely excluded from results

### Why This Is Wrong
- "As of today" should mean "show me the latest available data for each ETF"
- If an ETF's latest data is from 2026-01-25, it should still appear in results
- Things shouldn't disappear just because there's no new data today
- The query should use **each ETF's own latest date**, not a global latest date

### What Should Happen
- For each ETF, find its own latest date <= target_date
- Query holdings using each ETF's latest date
- Compare each ETF's latest holdings to its previous holdings
- This way, ETFs with data from different dates all appear

---

## Issue 2: Job Failing for New ETFs

### Current Implementation
- **Location**: `web_dashboard/scheduler/jobs_etf_watchtower.py` - `etf_watchtower_job()`
- **Line 1093-1154**: Loops through all ETFs in `ETF_CONFIGS`

### The Problem
1. **Line 1116-1118**: If fetch returns `None` or empty, it just logs warning and `continue`s
2. **Line 1151-1154**: If exception occurs, it logs error and `continue`s
3. **Result**: Job "succeeds" even if many ETFs fail silently
4. **New ETFs**: Only have data from 2026-01-25, meaning they've been failing since then

### Why New ETFs Are Failing
Possible reasons:
- Download errors (network, 403, timeout)
- Parsing errors (CSV format changed, Excel format different)
- Provider-specific issues (URL changed, authentication required)
- Date-based URL issues (Global X uses date in filename)

### What Should Happen
- Job should log which ETFs failed and why
- Failed ETFs should be retried or investigated
- Job should not silently skip failures
- Need to check job logs to see specific error messages

---

## Database View (Unused)

### View Exists But Not Used
- **View**: `etf_holdings_changes` in Research DB
- **Location**: `database/schema/research/views/etf_holdings_changes.sql`
- **What it does**: Calculates changes using SQL window functions (LAG)
- **Why unused**: Flask route calculates changes in Python instead

### View Logic
- Uses `LAG()` window function to get previous shares
- Calculates share_change, percent_change, action (BUY/SELL/HOLD)
- Filters to significant changes only (>= 1000 shares OR >= 0.5%)

### Could Use View Instead
- The view already does the change calculation
- Could query view instead of calculating in Python
- But still need to fix the date filtering issue

---

## Summary

### Two Separate Issues

1. **Query Logic Issue**: 
   - Uses global latest date instead of per-ETF latest dates
   - ETFs disappear if they don't have data on the global latest date
   - Fix: Query each ETF's own latest date

2. **Job Failure Issue**:
   - New ETFs are failing to download/parse
   - Failures are silent (job still "succeeds")
   - Need to check job logs to see specific errors
   - Fix: Investigate why new ETFs are failing, improve error handling

### Root Cause
- Both issues stem from assuming all ETFs have data on the same date
- Reality: ETFs can have data on different dates (job failures, weekends, holidays)
- Solution: Handle per-ETF dates gracefully
