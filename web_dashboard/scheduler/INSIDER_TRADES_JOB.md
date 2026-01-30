# Insider Trades Fetch Job

## Overview

- **Job:** `fetch_insider_trades_job`
- **Module:** `web_dashboard/scheduler/jobs_insiders.py`
- **Schedule:** Every 6 hours (see `web_dashboard/scheduler/jobs.py`)

Fetches corporate insider trading data from an external web source. The source page embeds a JavaScript array of recent trades (newest-first); the job parses that array, deduplicates against the DB, and upserts into Supabase. Designed to be polite to the source: when our data is up to date we only process the first N rows; when we are behind we process all to catch up.

---

## Environment Variables

### Source URL (optional)

- **`INSIDER_TRADES_BASE_URL`**  
  Full URL of the insider-trades page to scrape. If set, this is used and no encoded fallback is needed. Prefer setting this in `.env` (gitignored) so the URL is not in the repo.

- **`INSIDER_TRADES_SOURCE_ENCODED`**  
  Base64-encoded fallback URL. Used only when `INSIDER_TRADES_BASE_URL` is not set. Default is provided in code for backward compatibility.

### Date filter

- **`INSIDER_TRADES_DAYS`** (default: `7`)  
  Only ingest trades whose **transaction_date** is within the last N days.  
  - **`0`** = no date filter (one-time backfill: process all trades from the page).

### Row limit (polite scraping)

- **`INSIDER_TRADES_MAX_ROWS`** (optional)  
  - **Unset:** Smart default. If the newest trade in our DB is **within** the catch-up window (see below), we only process the **first 300 rows** from the source (newest-first). If we are **behind** (newest trade older than the catch-up window or DB empty), we process **all** rows to catch up.  
  - **`0`:** Always process all rows (e.g. manual full backfill).  
  - **Positive number (e.g. `200`):** When up to date, cap at that many rows instead of 300.

- **`INSIDER_TRADES_CATCH_UP_DAYS`** (default: `7`)  
  “Behind” threshold in days. If the newest **transaction_date** in our DB is this many days ago or more (or DB is empty), we consider ourselves behind and process all rows from the source. Otherwise we are “up to date” and apply the row limit (default 300 or `INSIDER_TRADES_MAX_ROWS`).

### Other

- **`FLARESOLVERR_URL`** (default: `http://localhost:8191`)  
  When the source is behind Cloudflare, the job can use FlareSolverr to fetch the page. Set this to your FlareSolverr endpoint.

- **`ENABLE_ROBOTS_TXT_CHECKS`**  
  If set, the job checks the source domain’s robots.txt before scraping (see Robots.txt below).

---

## Behavior Summary

| Situation | Date filter | Rows processed |
|-----------|------------|-----------------|
| Normal run (default) | Last 7 days | First 300 (if up to date) or all (if behind) |
| Up to date (newest in DB &lt; 7 days ago) | Last 7 days | First 300 (or `INSIDER_TRADES_MAX_ROWS` if set) |
| Behind (newest in DB ≥ 7 days ago or empty) | Last 7 days | All rows (catch-up) |
| Backfill: `INSIDER_TRADES_DAYS=0` | None | All rows (or first N if `MAX_ROWS` set) |
| Full backfill: `DAYS=0` and `MAX_ROWS=0` | None | All rows |

---

## How to Run

**From repo (uses `.env` in project root / web_dashboard for DB):**

```powershell
.\venv\Scripts\activate
python debug\test_insider_trades_job.py
```

**One-time full backfill (no date filter, no row limit):**

```powershell
$env:INSIDER_TRADES_DAYS = "0"
$env:INSIDER_TRADES_MAX_ROWS = "0"
python debug\test_insider_trades_job.py
```

Then unset both for normal scheduler runs.

---

## Data Source (generic)

- **Method:** Single HTTP GET to the configured URL; parse HTML and extract an embedded JavaScript array from inline `<script>` tags. Variable names looked for: `recentInsiderTransactionsData` or `topMonthlyInsiderTransactionsData`.
- **Bypass:** If the page is behind Cloudflare, set `FLARESOLVERR_URL` and the job will try FlareSolverr first, then fall back to a direct request.

---

## Field Mapping (Source → DB)

| Source key | DB column | Notes |
|------------|-----------|--------|
| `rptOwnerName` | `insider_name` | Fallbacks: `reportingOwnerName`, `ownerName`, `name`. Never stored empty; use "Unknown" if missing. |
| `officerTitle` | `insider_title` | Stored as empty string when source has `-` or missing. |
| `issuerTradingSymbol` | `ticker` | Uppercased. |
| `transactionCode` | `type` | Normalized to "Purchase" / "Sale" / title case. |
| `transactionShares` | `shares` | |
| `transactionPricePerShare` | `price_per_share` | |
| `transactionValue` | `value` | |
| `transactionDate` | `transaction_date` | Parsed (e.g. "Jan 21, 2026"). |
| `fileDate` | `disclosure_date` | Parsed; time portion stripped. |

---

## Debugging

1. **Logs:** The job logs the **keys of the first raw trade** at INFO so you can confirm the source’s field names. It also logs whether it is in “up to date” (first N rows) or “catch-up” (all rows) mode.

2. **Missing names:** If `insider_name` is missing in the UI, check logs for `"Insider name missing for ticker X, raw keys: [...]"` to see which keys the source sent. Ensure fallbacks and "Unknown" handling in the job (see `jobs_insiders.py`).

3. **DB:** Query Supabase `insider_trades` for `insider_name IS NULL OR insider_name = ''` to list rows with missing names.

---

## Database

- **Table:** `insider_trades` (Supabase)
- **Schema:** `database/schema/supabase/tables/insider_trades.sql`
- **Upsert key:** `(ticker, insider_name, transaction_date, type, shares, price_per_share)`

---

## Robots.txt

If `ENABLE_ROBOTS_TXT_CHECKS` is set, the job checks the source domain’s robots.txt before scraping; see `robots_utils` and the job’s robots check block.
