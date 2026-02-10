# LLM Handoff: Watchlist Backfill, Cutover, and Pipeline Next Steps

## Context

The migration from the global `watched_tickers` table to fund-scoped `watched_tickers_v2` is code-complete. All application code now routes through a shared accessor with automatic v2-first / legacy-fallback behavior. What remains is operational: running the backfill, verifying data, enabling strict mode, and then moving on to the broader Automated Intelligence Pipeline.

## Environment

- **OS:** Windows 11 / PowerShell
- **Python:** 3.13+ with venv at `.\venv\Scripts\activate`
- **Repo root:** `c:\Users\cream\OneDrive\Documents\LLM-Micro-Cap-trading-bot`
- **This is a Windows environment** — use PowerShell syntax, not bash.

## What Is Already Done (Do NOT Redo)

### Schema & Policies
- `watched_tickers_v2` table exists in Supabase with FK constraints (`fund -> funds(name)`, `ticker -> securities(ticker)`, PK `(fund, ticker)`).
- RLS policies applied (user view + service role manage).
- Registered in `database/schema/supabase/_init_schema.sql`.

### Shared Accessor
- `web_dashboard/watchlist_access.py` — single entry point for all watchlist reads.
- Tries `watched_tickers_v2` first, falls back to legacy `watched_tickers` if v2 is empty/missing.
- Supports `fund` filter, `fallback_if_empty` flag, and `WATCHLIST_STRICT=1` env var.
- Fallback hits are logged at INFO level: `"watchlist fallback: v2 returned 0 rows for fund=..."`.

### All Call Sites Migrated
Every production Flask and Streamlit path now uses the shared accessor. Zero direct `watched_tickers` table queries remain in `web_dashboard/` (only the accessor itself references the legacy table for fallback). Migrated files:

| File | Function |
|------|----------|
| `web_dashboard/scheduler/jobs_signals.py` | signal generation |
| `web_dashboard/routes/dashboard_routes.py` | dashboard API |
| `web_dashboard/routes/signals_routes.py` | `get_cached_watchlist_signals()` |
| `web_dashboard/routes/social_sentiment_routes.py` | `get_cached_dynamic_watchlist()` |
| `web_dashboard/social_service.py` | social sentiment |
| `web_dashboard/ticker_analysis_service.py` | ticker analysis |
| `web_dashboard/ticker_utils.py` | `_fetch_watchlist_status()` |
| `web_dashboard/utils/db_utils.py` | `get_all_unique_tickers()` |
| `web_dashboard/pages/social_sentiment.py` | Streamlit watchlist + dynamic watchlist |

### Backfill Script
- `scripts/backfill_watched_tickers_v2.py` — ready to run.
- Supports `--dry-run`, `--funds FUND1 FUND2`, `--force`.
- Idempotent (upsert on `(fund, ticker)`), validates tickers against `securities` FK.

### Strict Mode
- `WATCHLIST_STRICT=1` disables legacy fallback entirely.
- Default is fallback-enabled.

### Tests
- `tests/test_watchlist_access.py` — 8 tests covering v2 preference, fallback, strict mode, sorting, multi-fund.
- All 53 Flask tests pass. All 8 watchlist tests pass.

## YOUR TASK: Remaining Steps (In Order)

### Step 1: Run Backfill (Dry Run First)

```powershell
.\venv\Scripts\activate
.\venv\Scripts\python.exe scripts/backfill_watched_tickers_v2.py --dry-run
```

Review output. Confirm:
- Row counts look reasonable.
- No FK-skipped tickers that should be present (if tickers are skipped because they're not in `securities`, that may indicate the securities table needs updating first).

Then run for real:
```powershell
.\venv\Scripts\python.exe scripts/backfill_watched_tickers_v2.py
```

Or limit to specific funds:
```powershell
.\venv\Scripts\python.exe scripts/backfill_watched_tickers_v2.py --funds "Project Chimera" TFSA
```

### Step 2: Verify Backfill

After backfill, verify v2 data matches expectations:

```powershell
.\venv\Scripts\python.exe -c "from supabase_client import SupabaseClient; c = SupabaseClient(use_service_role=True); r = c.supabase.table('watched_tickers_v2').select('fund, ticker, priority_tier', count='exact').execute(); print(f'Total rows: {r.count}'); [print(f'  {row[\"fund\"]:20s} {row[\"ticker\"]:10s} {row[\"priority_tier\"]}') for row in (r.data or [])[:20]]"
```

Compare against legacy:
```powershell
.\venv\Scripts\python.exe -c "from supabase_client import SupabaseClient; c = SupabaseClient(use_service_role=True); r = c.supabase.table('watched_tickers').select('ticker', count='exact').eq('is_active', True).execute(); print(f'Legacy active rows: {r.count}')"
```

### Step 3: Run All Tests

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_watchlist_access.py -v
.\venv\Scripts\python.exe -m pytest tests/ -k "flask" -v
```

All must pass.

### Step 4: Monitor Fallback Hits

After deploying, search application logs for:
```
watchlist fallback: v2 returned 0 rows
```

If this message appears, it means some fund/endpoint is still hitting the legacy table. Investigate and ensure v2 is populated for those funds.

Goal: zero fallback hits over at least one week of operation.

### Step 5: Enable Strict Mode

Once zero fallback hits confirmed:

1. Set environment variable: `WATCHLIST_STRICT=1`
2. Restart the application.
3. Monitor for any empty-watchlist issues (would indicate v2 is missing data for a fund).
4. Run tests again to confirm.

### Step 6 (Future): Legacy Table Deprecation

Do NOT do this yet. Only after strict mode has been stable for 2+ weeks:

1. Remove the fallback code path in `web_dashboard/watchlist_access.py`.
2. Remove the `WATCHLIST_STRICT` env var logic (it becomes the only behavior).
3. Drop or archive the `watched_tickers` table.
4. Update `database/schema/supabase/_init_schema.sql` to remove legacy table references.

---

## What Comes Next in the Broader Pipeline

After the watchlist migration is fully operational, the next work items from the Automated Intelligence Pipeline plan (`C:\Users\cream\.cursor\plans\automated_intelligence_pipeline_298e1f2d.plan.md`) are:

### Pipeline Phase 0 (Remaining Items)
- Reconcile init schemas with runtime tables — ensure schema parity.
- Finalize data ownership contract (Supabase vs Research DB) for new entities.
- Decide AI orchestration mode (queue-first via `ai_analysis_queue`).

### Pipeline Phase 1: Securities Bridge + Embeddings
- Add `description_embedding vector(768)`, `description_hash TEXT`, `last_synced_at` to Research DB `securities`.
- Build event-driven ticker upsert + incremental sync job (every 4-6h) + daily reconciliation.
- Re-embed only on description hash change.

### Pipeline Phase 2: Opportunity Pipeline
- Create `opportunity_evidence` (global) and `fund_opportunity_candidates` (fund-scoped) tables in Research DB.
- Build evaluator that fans global evidence into fund-specific candidate rows using fund profiles.
- Queue decisions via `ai_analysis_queue`.

### Pipeline Phase 3: Watchlist Lifecycle + Thesis Tracking
- Add `watchlist_history` and `watchlist_alerts` tables (Supabase).
- Add `watchlist_thesis_snapshots` table (Research DB).
- Build `watchlist_thesis_update_job`.

### Pipeline Phase 4: Advisory Entry/Exit Monitor
- Entry/exit condition evaluation per `(fund, ticker)`.
- Alert deduplication + cooldown.
- Multi-signal confluence scoring.

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `web_dashboard/watchlist_access.py` | Shared accessor (v2 + fallback + strict mode) |
| `scripts/backfill_watched_tickers_v2.py` | One-time backfill script |
| `tests/test_watchlist_access.py` | 8 unit tests for accessor |
| `database/schema/supabase/tables/watched_tickers_v2.sql` | V2 table DDL |
| `database/schema/supabase/_init_schema.sql` | Init schema (includes v2) |
| `C:\Users\cream\.cursor\plans\automated_intelligence_pipeline_298e1f2d.plan.md` | Full pipeline plan |

## Constraints

- **Do NOT remove** the legacy `watched_tickers` table or its schema files yet.
- **Do NOT remove** the `verification/` directory.
- Use FK constraints for all new same-DB tables.
- Keep high-volume text/embeddings in Research DB, not Supabase.
- Run `.\venv\Scripts\python.exe -m pytest tests/test_watchlist_access.py -v` after any changes to watchlist code.
- Run `.\venv\Scripts\python.exe -m pytest tests/ -k "flask" -v` after any Flask changes.
