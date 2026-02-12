# Code Review: Insider Trades Update
**Commit:** `f8e3bce` - Insider trades: SEC Form 4 backfill, date filter, junk ticker fixes

## Summary
The recent changes introduce a robust system for fetching, storing, and displaying insider trading data. The implementation spans the full stack, from a scheduler job (`jobs_insiders.py`) fetching data, to a backend API (`app.py`) serving it, and a frontend (`insider_trades.ts`) displaying it with filters.

Overall, the feature set is well-implemented, but there is a **critical security vulnerability** in the data fetching job that must be addressed immediately.

## Critical Findings

### 🚨 Security Vulnerability: `eval()` usage in `jobs_insiders.py`
**File:** `web_dashboard/scheduler/jobs_insiders.py`
**Line:** ~277 (approximate based on context)

The code uses `eval()` as a fallback to parse the embedded data from the source website:
```python
# Try eval as fallback (safe since it's from the source page)
try:
    trades_data = eval(json_str)
```
**Risk:** While the comment claims it is "safe since it's from the source page", this is a dangerous assumption. If the source website is compromised or serves malicious content, `eval()` will execute arbitrary code on your server.
**Recommendation:** Replace `eval()` with `ast.literal_eval()`. The comment notes that the data is in "Python dict notation", for which `ast.literal_eval()` is the designed, safe parser.

```python
import ast
# ...
try:
    trades_data = ast.literal_eval(json_str)
```

## Major Findings

### ⚠️ Performance: Unbounded Data Fetching
**File:** `web_dashboard/app.py`, function `api_insider_trades_data`
**Issue:** The API fetches *all* trades matching the filter criteria using `get_insider_trades_cached`. While there is an internal safety limit of 100,000 rows in the cached function, sending ~100k rows (each with multiple fields) to the frontend in one JSON response is a heavy payload that will cause latency and high memory usage on both client and server.
**Recommendation:** Implement server-side pagination. The current implementation relies on the frontend (AgGrid) to handle pagination, but it still requires the full dataset to be loaded first.

### ⚠️ Reliability: Flaky Grid Initialization
**File:** `web_dashboard/src/js/insider_trades.ts`, function `initializeInsiderTradesGrid`
**Issue:** The grid relies on `setTimeout` to auto-size columns:
```typescript
setTimeout(() => {
    // ... autoSizeColumns ...
}, 300);
```
This is a race condition waiting to happen. If the grid renders slower than 300ms (e.g., on a slow device with a large dataset), the columns won't resize correctly.
**Recommendation:** Use AgGrid's `onFirstDataRendered` event more robustly or the `autoSizeStrategy` grid option if available in the version you are using.

## Minor Findings & Praise

### ✅ Feature Implementation
-   **Junk Ticker Fixes:** The logic in `insider_trades.ts` (cleaning tickers like `.TO`, `.V`) and `jobs_insiders.py` is solid.
-   **Date Filters:** The backend support for `start_date` and `end_date` in `api_insider_trades_data` is correctly implemented and exposed to the frontend.
-   **Backfill Logic:** The scheduler job correctly handles `INSIDER_TRADES_DAYS=0` for full backfills and has a smart catch-up mechanism (`INSIDER_TRADES_CATCH_UP_DAYS`).

### ℹ️ Code Style
-   **Type Safety:** The TypeScript file uses `any` in several places (`window as any`, `gridApi` casting). While understandable for rapid development, adding proper type definitions for `themeManager` and `Plotly` would improve maintainability.
-   **Duplicate Logic:** Both the scheduler and the backend have logic to normalize/clean tickers. Consider moving shared logic to `web_dashboard/utils/ticker_utils.py` to ensure consistency.

## Action Items
1.  **IMMEDIATE:** Replace `eval()` with `ast.literal_eval()` in `web_dashboard/scheduler/jobs_insiders.py`.
2.  **HIGH:** Add server-side pagination to `api_insider_trades_data` or strictly limit the default date range to prevent massive payloads.
3.  **MEDIUM:** Refactor `setTimeout` in frontend grid initialization.

## Code Review - Thu Feb 12 15:16:19 UTC 2026

### Commit 4d732f7
**Subject:** fix(research): Set ticker_validated_at on manual save and reprocess to protect from junk filter

**Summary:**
The commit introduces a mechanism to protect validated research articles from accidental deletion by the automated junk filter.

**Key Changes:**
1. **Database:** Added `ticker_validated_at` timestamp updates in `research_repository.py` on manual save/reprocess.
2. **Routes:** Updated `research_routes.py` to exempt articles with `ticker_validated_at` from junk filtering unless explicitly confirmed as junk (relevance <= 0.1).
3. **Scheduler:** Added `jobs_article_relevance.py` to automatically validate unvalidated articles using GLM-4.5-air.

**Feedback:**
- **Correctness:** Logic correctly implements the requested feature.
- **Robustness:** Includes failsafe in automation job to prevent stuck retries.
- **Performance:** Batch processing is efficient.
- **Suggestion:** Monitor logs for GLM failures.
