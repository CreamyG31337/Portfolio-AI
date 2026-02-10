# LLM Handoff: Remaining Watchlist Migration Work

## Purpose
Continue and finish the migration from global `watched_tickers` to fund-scoped `watched_tickers_v2` with minimal re-discovery and low Supabase footprint.

## What Is Already Done

- Added fund-scoped table + FKs:
  - `database/schema/supabase/tables/watched_tickers_v2.sql`
  - FK: `fund -> funds(name)`
  - FK: `ticker -> securities(ticker)`
- Added policies:
  - `database/schema/supabase/policies/watched_tickers_v2_Users can view watchlist for their funds.sql`
  - `database/schema/supabase/policies/watched_tickers_v2_Service role can manage watched_tickers_v2.sql`
- Added to init schema:
  - `database/schema/supabase/_init_schema.sql`
- Added shared accessor with fallback:
  - `web_dashboard/watchlist_access.py`
  - Reads `watched_tickers_v2` first, falls back to legacy `watched_tickers` if v2 missing/empty.
- Switched core consumers:
  - `web_dashboard/scheduler/jobs_signals.py`
  - `web_dashboard/routes/dashboard_routes.py`
  - `web_dashboard/social_service.py`
  - `web_dashboard/ticker_analysis_service.py`
- Added tests:
  - `tests/test_watchlist_access.py`

## Completed Work

### Phase 1: Migrate Remaining Call Sites ✅

All direct `supabase.table("watched_tickers")` queries in production Flask/Streamlit backend paths have been replaced with calls to the shared accessor (`web_dashboard/watchlist_access.py`):

- `web_dashboard/routes/signals_routes.py` — `get_cached_watchlist_signals()` now uses `get_active_watchlist_rows()`
- `web_dashboard/routes/social_sentiment_routes.py` — `get_cached_dynamic_watchlist()` now uses `get_active_watchlist_rows()`
- `web_dashboard/ticker_utils.py` — `_fetch_watchlist_status()` now uses `get_active_watchlist_rows()`
- `web_dashboard/utils/db_utils.py` — `get_all_unique_tickers()` now uses `get_active_watchlist_tickers()`
- `web_dashboard/pages/social_sentiment.py` — both `get_watchlist_tickers()` and `get_dynamic_watchlist_tickers()` now use `get_active_watchlist_rows()`

**Verification:** `rg "table(\"watched_tickers\")" web_dashboard` returns zero results. Only `watchlist_access.py` itself references the legacy table (for fallback).

### Phase 2: Backfill Script ✅

- Created `scripts/backfill_watched_tickers_v2.py`
- Features:
  - `--dry-run` prints counts and sample rows without writing.
  - `--funds TEST TFSA` limits to specific funds.
  - `--force` re-upserts even if rows already exist in v2.
  - Idempotent: uses `ON CONFLICT (fund, ticker) DO UPDATE`.
  - Validates tickers against `securities` table (FK constraint safety).
  - Batch upserts (50 rows per batch) with error handling.
  - Logs row counts and sample spot checks.

### Phase 3: Strict Mode Switch ✅

- Added `WATCHLIST_STRICT=1` environment variable support in `web_dashboard/watchlist_access.py`.
- When strict mode is active:
  - Legacy `watched_tickers` is never consulted.
  - If v2 query fails, returns empty list (no fallback).
  - Logs a warning on v2 failure in strict mode.
- Default remains fallback-enabled until migration verification is complete.
- Documented switch criteria in module docstring.
- Fallback hits are now logged at INFO level for monitoring.

### Phase 4: Tests ✅

Extended `tests/test_watchlist_access.py` from 2 to 8 tests:
- `test_watchlist_access_uses_v2_when_available` — v2 preferred over legacy
- `test_watchlist_access_falls_back_to_legacy_when_v2_missing` — fallback on v2 failure
- `test_fallback_when_v2_empty` — fallback when v2 returns empty
- `test_no_fallback_when_fallback_disabled` — `fallback_if_empty=False` honored
- `test_strict_mode_disables_fallback` — `WATCHLIST_STRICT=1` prevents fallback
- `test_strict_mode_returns_empty_on_v2_failure` — strict mode + v2 failure = empty
- `test_get_active_watchlist_tickers_sorted` — tickers sorted alphabetically
- `test_no_fund_filter_returns_all_funds` — no fund filter returns all funds

All 8 watchlist tests + all 53 Flask tests pass.

## Remaining Work (Operational)

### Run Backfill
```powershell
.\venv\Scripts\python.exe scripts/backfill_watched_tickers_v2.py --dry-run
.\venv\Scripts\python.exe scripts/backfill_watched_tickers_v2.py --funds TEST TFSA
```

### Enable Strict Mode (when ready)
1. Confirm v2 is populated for all required funds.
2. Monitor logs for `"watchlist fallback"` messages — ensure zero hits over 1+ week.
3. Test all key endpoints with v2-only data.
4. Set `WATCHLIST_STRICT=1` in environment.

### Legacy Table Deprecation (future)
- Do not remove `watched_tickers` yet.
- After strict mode has been active for 2+ weeks with no issues, plan explicit deprecation.

## Constraints and Design Rules

- Use FK constraints whenever possible (already applied for v2).
- Keep high-volume text/embeddings in Research DB; avoid unnecessary Supabase growth.
- Do not remove legacy `watched_tickers` yet; keep as fallback/rollback path.
- If a view/table is not actively used, document it; do not overbuild.
- Preserve `verification/` directory.

## Suggested Quick Commands

```powershell
# Verify no remaining legacy direct reads
rg -n "table\(\"watched_tickers\"\)" web_dashboard

# Run targeted watchlist tests
.\venv\Scripts\python.exe -m pytest tests/test_watchlist_access.py -v

# Run Flask test suite
.\venv\Scripts\python.exe -m pytest tests/ -k "flask" -v

# Run backfill dry-run
.\venv\Scripts\python.exe scripts/backfill_watched_tickers_v2.py --dry-run
```

## Completion Definition

- ✅ All primary Flask/API watchlist reads go through `web_dashboard/watchlist_access.py`.
- ✅ Backfill script exists and is documented.
- ✅ Fallback can be monitored and optionally disabled via strict mode.
- ✅ Tests covering v2 + fallback pass.
- ✅ Legacy table remains present until explicit deprecation decision.
