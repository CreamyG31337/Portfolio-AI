# Agent Guidelines for LLM Micro-Cap Trading Bot

## ⚠️ CRITICAL: Windows/PowerShell Environment

**USE POWERSHELL SYNTAX — NOT BASH**

- Use `Get-ChildItem`/`dir`, `Get-Content`/`type`, `Select-String` (not `ls`, `cat`, `grep`)
- Use `$env:VAR` (not `$VAR` or `export VAR=`)
- Use `;` to chain commands (not `&&`)
- Use `C:\path\to\file` and `.\venv\Scripts\activate` (not `/path/` or `source venv/bin/activate`)
- Avoid multi-line Python strings in terminal commands — use a `.py` file instead (they trigger `>>` prompts; `Ctrl+C` to escape)

## Environment Setup

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

Streamlit (`web_dashboard/pages/*.py`) is a **prototype only** — no tests, maintenance only. Flask is production and gets priority for all new features.

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
- Pipeline: `etf_watchtower → etf_holdings_log (Research)` → `etf_group_analysis → research_articles` → `sector_meta_analysis → /sector_insights` → `ticker_meta_analysis`
- **Do not** read Supabase `etf_holdings_log` (dropped May 2026 — holdings live in Research DB)
- Catch-up after outage: `python web_dashboard/scripts/backfill_etf_sector_meta.py` — see `docs/ETF_SECTOR_META_OPS.md`
- ETF job details: `docs/ETF_AI_ANALYSIS_SYSTEM.md`

## Database Schema

- **Source of truth:** SQL files at `database/schema/supabase/` and `database/schema/research/` (`_init_schema.sql` ties each together). `database/archive/` is historical context only.
- Docs (markdown + JSON) at `docs/database/` — Supabase prod (29 tables) and Research/AI DB (13 tables)
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

- Runs on Ubuntu server, MCP HTTP Bridge at port **8082** (not 8081 = direct REST API)
- Configure URL in `mcps/mandrel/SERVER_METADATA.json` (gitignored; copy from `.example`)
- **Start every session**: `mandrel_ping` → `project_current` → `context_get_recent` → `task_list`
- **During work**: `context_store` for learnings/decisions, `task_update` for progress
- **End session**: `context_store` (type `completion`), update task statuses
- `context_store` type must be one of: code, decision, error, discussion, planning, completion, reflections, handoff (NOTE: `milestone` is documented but rejected by the DB constraint — use `completion`)
- Call `mandrel_help` to discover all tools

## Supabase MCP Server

- Runs locally via `npx @supabase/mcp-server-supabase@latest` (configured in `C:\Users\cream\.cursor\mcp.json` with PAT)
- Use for: schema queries, SQL execution (`execute_sql`), migrations (`apply_migration`), TS type generation, logs (`get_logs`), advisors (`get_advisors`)
- Workflow: `list_tables` → `execute_sql` / `apply_migration` for DB work
- **Never use for production data access** — development/test projects only. Does NOT expose Storage admin tools.

## Test Accounts

Credentials in `web_dashboard/test_credentials.json` (gitignored). Regenerate: `cd web_dashboard; python setup_test_accounts.py`
