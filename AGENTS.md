# Agent Guidelines for LLM Micro-Cap Trading Bot

## ⚠️ CRITICAL: Windows/PowerShell Environment

**USE POWERSHELL SYNTAX — NOT BASH**

- Use `Get-ChildItem`/`dir`, `Get-Content`/`type`, `Select-String` (not `ls`, `cat`, `grep`)
- Use `$env:VAR` (not `$VAR` or `export VAR=`)
- Use `;` to chain commands (not `&&`)
- Use `C:\path\to\file` and `.\venv\Scripts\activate` (not `/path/` or `source venv/bin/activate`)
- Avoid multi-line Python strings in terminal commands — use a `.py` file instead (they trigger `>>` prompts; `Ctrl+C` to escape)

## Environment Setup

- **Repo path (local, not OneDrive):** `C:\Projects\LLM-Micro-Cap-trading-bot`
- **Migrate from OneDrive:** `.\scripts\migrate_off_onedrive.ps1 -SetupDeps`
- **Always activate venv first**: `.\venv\Scripts\activate`
- **Use TEST fund for development**: `trading_data/funds/TEST` (NOT `trading_data/funds/Project Chimera` — that's production)
- Copy CSVs from Project Chimera → TEST anytime for testing

## Build/Lint/Test Commands

```powershell
mypy trading_script.py
ruff check trading_script.py
ruff check --fix trading_script.py
python -m pytest tests/ -v
python -m pytest tests/ --cov=.
python dev_run.py --data-dir "trading_data/funds/TEST"
```

## Committing Code

1. Run unit tests: `python -m pytest tests/ -v`
2. Run lint + types: `ruff check trading_script.py; mypy trading_script.py`
3. All tests must pass before committing
4. Descriptive commit messages explaining the "why"
5. **One PR at a time** — review diff, then merge. Never batch-merge.
6. Code review docs (CODE_REVIEW_*.md): implement suggestions in code, then merge code. Do NOT merge the review doc.

## Test Selection (CRITICAL)

Run the right test suite based on what you're changing (both suites use the root venv):

| Code location | Test command |
|---|---|
| `web_dashboard/` (Flask, routes, templates, TS) | `python -m pytest tests/test_flask_*.py -v` |
| Root-level Python (trading_script, portfolio/, financial/, utils/) | `python -m pytest tests/ -v -k "not flask"` |
| Both changed | Run both |

## Code Style

- Python 3.11+, `decimal.Decimal` for all financial values (convert to float only at Supabase boundary), timezone-aware datetimes
- Strict mypy, full type annotations, no `Any` except when necessary
- Line length 100, double quotes, PEP 8
- Absolute imports, grouped: stdlib → third-party → local (`known-first-party = ["trading_script"]`)
- Specific exception types, meaningful error messages, handle None/empty gracefully (`or 0` pattern in P&L)
- Never log/expose secrets; validate user inputs

### TypeScript / Frontend

- **Edit `web_dashboard/src/js/*.ts`** — never edit `web_dashboard/static/js/*.js` (auto-generated, overwritten)
- **Package manager is pnpm** (not npm). Lockfiles `pnpm-lock.yaml` committed at repo root AND `web_dashboard/` (two Node projects). CI/Docker use `pnpm install --frozen-lockfile`. See `docs/frontend_dependencies.md`.
- Build: `pnpm run build:ts` (TS), `pnpm run build:css` (Tailwind), `pnpm run build` (both), `pnpm run watch:css` (watch)
- **Use Tailwind CSS** (v4) for all styling. **Use Flowbite** (v4) for UI components (modals, dropdowns, drawers, etc.)
- **Buttons:** use shared classes from `web_dashboard/static/css/input.css` — `btn-outline` (default) or `btn-outline-sm` (dense). Avoid solid `bg-accent text-white` fills for page actions (harsh in both themes). Secondary/cancel: muted `border border-border`. Settings page is the reference.
- **Use Font Awesome** (v6) for icons (`fas fa-...`)
- Page-specific: AG Grid (complex tables), Plotly (interactive charts), Chart.js (simple charts), Marked + DOMPurify (markdown)
- Only write custom CSS for: webkit scrollbars, complex keyframe animations, CSS variables for theming, third-party overrides (AG Grid, Plotly dark mode). Document why Tailwind can't be used.

## Repository Pattern (CRITICAL — common source of bugs)

| Repository | Reads from | Used by |
|---|---|---|
| `CSVRepository` | CSV files | Console app (local) |
| `SupabaseRepository` | Supabase DB | Web dashboard (Flask) |
| `DualWriteRepository` | **CSV files** | Console app (dual backup) |

**Rules:**
1. Flask **must** use `SupabaseRepository` directly — the web server has no CSV files, `DualWriteRepository` silently returns empty reads
2. Always use named parameters: `RepositoryFactory.create_dual_write_repository(fund_name=..., data_directory=...)` (swapped args = Supabase queries match nothing)
3. `DualWriteRepository.get_trade_history()` reads from CSV, not Supabase
4. `CSVRepository.__init__` silently `mkdir`s — wrong paths create empty dirs instead of erroring

## Verification Folder (DO NOT DELETE)

`verification/` contains Playwright/UI scripts and screenshots. **Never delete it** — multiple PRs have accidentally removed it.

## Social Sentiment AI System

- Uses Ollama `granite4.1:8b` for AI analysis of StockTwits/Reddit posts
- Pipeline: extract posts → group into 4h sessions → AI analysis → validate tickers → store in research DB
- Supabase: `social_metrics`, `social_posts`, `sentiment_sessions`. Research DB: `social_sentiment_analysis`, `extracted_tickers`, `post_summaries`
- Run job: `cd web_dashboard; python scheduler/social_sentiment_ai_job.py`
- Retention: raw posts 14d, AI results 90d, metrics 60d

## Daily Critical Data Backup

- `daily_critical_data_backup_job` in `web_dashboard/scheduler/jobs_daily_backup.py`, runs daily 12:00 UTC
- Snapshots irreplaceable Supabase data → host volume (`/home/lance/trading-dashboard-backups`) + Supabase Storage bucket `daily-backups`
- Scope: per-fund `trade_log` CSVs + critical tables (user_profiles, user_funds, funds, fund_thesis*, fund_contributions, system_settings, watched_tickers_v2, ai_analysis_skip_list, contributors, contributor_access)
- New irreplaceable table? Append to `CRITICAL_APP_TABLES` and update `tests/test_jobs_daily_backup.py`
- One-time bucket setup: `python web_dashboard\scripts\setup_daily_backup_bucket.py` (MCP can't create Storage buckets)
- Runbook: `docs/DAILY_BACKUP_RESTORE_RUNBOOK.md`

## Meta Analysis (market → sector → ticker)

- **North star:** human-in-the-loop buy/sell *ideas* from layered evidence (not auto-trading). Phased — see `docs/meta_analysis_roadmap.md`
- **Human theses:** Insights (`/insights`, Research `ticker_theses`) — see `docs/INSIGHTS.md` (Decide-layer job map: meta vs thesis eval vs queue review). Do not confuse with Sector Insights (`/sector_insights`) or fund `fund_thesis`.
- **Watchlist:** `/watchlist` + ticker Add/Remove write `watched_tickers_v2` (service role after fund ACL). Ideas Accept adds discovery tickers only — do not stuff friend tips into Ideas.
- Pipeline: `etf_watchtower → etf_holdings_log (Research)` → `etf_group_analysis → research_articles` → `sector_meta_analysis → /sector_insights` → `ticker_meta_analysis`
- **Do not** read Supabase `etf_holdings_log` (dropped May 2026 — holdings live in Research DB)
- Catch-up after outage: `python web_dashboard/scripts/backfill_etf_sector_meta.py` — see `docs/ETF_SECTOR_META_OPS.md`
- ETF job details: `docs/ETF_AI_ANALYSIS_SYSTEM.md`

## Database Schema

- **Source of truth:** SQL files at `database/schema/supabase/` and `database/schema/research/` (`_init_schema.sql` ties each together). `database/archive/` is historical context only.
- Docs (markdown + JSON) at `docs/database/` — Supabase prod (~40 tables) and Research/AI DB (~30 tables, includes Insights `ticker_theses` / `thesis_entries` / `thesis_evidence`). Regenerate after DB changes.
- Generate docs: `.\web_dashboard\venv\Scripts\python.exe scripts\generate_schema_docs.py`
- Export SQL: `.\web_dashboard\venv\Scripts\python.exe scripts\export_clean_schema.py` — **always run after production DB changes**

## Test Database (for Cloud Agents / Safe Dev)

```powershell
docker-compose -f docker-compose.test.yml up -d
cp .env.test.template .env
```

- Ports: Supabase test → 5433, Research test → 5434. Seed files (`database/test_seed_*.sql`) are pre-committed and auto-load.
- **Do not** run `generate_test_seed.py` (needs production credentials). Only TEST/TFSA funds, all PII scrubbed, synthetic AI data.
- Test users: `admin@test.com`, `contributor@test.com`, `viewer@test.com`. Switch in psql: `SELECT set_current_test_user('admin@test.com');`

## Mandrel MCP Server (Persistent AI Memory)

Shared memory across agents/sessions (not a code graph — use Graphify for that).

- Runs on Ubuntu server, MCP HTTP Bridge at port **8082** (not 8081 = direct REST API)
- Configure URL in `mcps/mandrel/SERVER_METADATA.json` (gitignored; copy from `.example`)
- **Session start (light)**: `project_current` once if unsure of project; `context_get_recent` or `task_list` only when continuing prior work
- **Before repeating known pain**: `context_search` (semantic) — older bug/architecture notes live here, not in `context_get_recent`
- **During / end of work**: `context_store` handoffs agents can pick up; `task_create` / `task_update` for multi-agent coordination; `decision_record` for durable architecture choices
- `context_store` type must be one of: code, decision, error, discussion, planning, completion, reflections, handoff (NOTE: `milestone` is documented but rejected by the DB constraint — use `completion`)
- Prefer targeted search/store over dumping `mandrel_help` every session

## Supabase MCP Server

- Runs locally via `npx @supabase/mcp-server-supabase@latest` (configured in `C:\Users\cream\.cursor\mcp.json` with PAT)
- Use for: schema queries, SQL execution (`execute_sql`), migrations (`apply_migration`), TS type generation, logs (`get_logs`), advisors (`get_advisors`)
- Workflow: `list_tables` → `execute_sql` / `apply_migration` for DB work
- **Never use for production data access** — development/test projects only. Does NOT expose Storage admin tools.

## Graphify (code graph MCP)

- **MCP reads from a fixed path outside OneDrive** — never point MCP at `graphify-out/` inside the synced repo (OneDrive conflicts + agents overwrite it).
- Install path: `%USERPROFILE%\graphify\LLM-Micro-Cap-trading-bot\graph.json`
- Build locally: `graphify update .` (writes to repo `graphify-out/` only)
- **Share between PCs:** `.\scripts\graphify_export.ps1` → transfer zip (USB/email) → `.\scripts\graphify_import.ps1 -ZipPath ...`
- **Do NOT** run `graphify extract` on the receiving PC unless explicitly rebuilding the graph.
- Check: `.\scripts\graphify_status.ps1`

## Test Accounts

Credentials in `web_dashboard/test_credentials.json` (gitignored). Regenerate: `cd web_dashboard; python setup_test_accounts.py`

## Cursor Cloud specific instructions

The guidance above is written for a **Windows/PowerShell** workstation. Cursor Cloud VMs are **Linux/bash** — translate accordingly (`source venv/bin/activate` or call `./venv/bin/python`; `$VAR`/`export`; `/` paths). The update script already installs all dependencies on VM startup, so the notes below are startup/run caveats, not install steps.

- **Python env:** a single root `venv` holds BOTH `requirements.txt` (CLI engine) and `web_dashboard/requirements.txt` (Flask app), plus `ruff` + `mypy`. `psycopg2-binary` needs `libpq-dev`/`build-essential` (baked into the VM image, not the update script). `pandas` resolves to 2.3.x (the `>=2.2` pin also allows 3.x; test behavior is identical).
- **Node:** two pnpm projects — repo root and `web_dashboard/` (each with its own committed `pnpm-lock.yaml`). Build the frontend with `pnpm run build` (Tailwind CSS + `tsc`); it emits generated JS into `web_dashboard/static/js` (never edit those by hand).
- **CLI engine — must switch to CSV first (non-obvious):** the committed `repository_config.json` points the CLI at **production Supabase ("Project Chimera")**, which is unreachable/unsafe from a cloud VM — `python trading_script.py` will fail with `Connection refused`. For local CLI work run `./venv/bin/python simple_repository_switch.py csv "trading_data/funds/TEST"` first (writes `repository_config.json`; restore it / don't commit that change). Then use the `TEST` fund only.
- **CLI run/output caveat:** prefer running `trading_script.py` / `update_cash.py` **directly**, not `dev_run.py`, when output is piped/non-TTY — `dev_run.py` wraps `sys.stdout` and crashes with `I/O operation on closed file` under a pipe. `trading_script.py --non-interactive` skips the menu; its interactive menu only appears once portfolio data exists. `update_cash.py --data-dir "trading_data/funds/TEST"` is a reliable offline action entry point (adds/sets fund cash → persists JSON in the fund dir).
- **Flask web dashboard:** `cd web_dashboard && DISABLE_SCHEDULER=true FLASK_PORT=5001 ../venv/bin/python app.py` serves on `http://localhost:5001` (login page at `/auth`). Always set `DISABLE_SCHEDULER=true` for local dev (avoids APScheduler needing `SUPABASE_DATABASE_URL`). `cp .env.test.template .env` gives a working test config. **Full login + portfolio pages require REAL Supabase credentials** (`SUPABASE_URL` + publishable/secret keys); the app talks to Supabase over HTTP/PostgREST, which the Docker `docker-compose.test.yml` Postgres (`:5433`/`:5434`) does **not** provide — those DBs are only for scheduler persistence, the Research DB, and SQL/RLS-level testing. `TEST_MODE`/`ENVIRONMENT` in the template are documentation-only (not read by code).
- **Tests:** `python -m pytest tests/test_flask_*.py` (Flask; mocks Supabase + disables scheduler, needs no DB) and `python -m pytest tests/ -k "not flask" -m "not bench and not live_fetch and not live_reddit"` (~1626 pass). Frontend: `pnpm run test:ts` (root, `tsc --noEmit`) and `cd web_dashboard && pnpm test` (vitest). A handful of tests fail **pre-existing / offline-expected**, unrelated to setup: 4 Flask tests (`test_flask_dashboard_research`, `test_flask_digest_email`, 2× `test_flask_performance_gap_fill`) and several non-Flask suites that need live Supabase HTTP (`test_pnl_calculation_consistency`, `test_csv_vs_supabase_consistency`, `test_real_data_pnl_consistency`, dual-write), live Ollama (`test_ollama_multi_server`), or special env vars (`test_symbol_article_scraper` needs `SYMBOL_ARTICLE_BASE_URL`).
- **Docker is not installed by default** and is not needed for the CLI, the Flask test suite, or booting the dashboard. Install it only if you need the `docker-compose.test.yml` databases (see the "Test Database" section above).
