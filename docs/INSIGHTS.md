# Insights — human thesis threads

Org-wide, fund-agnostic thesis threads for tickers. Separate from automated signals,
`stance_history`, and fund-level philosophy (`fund_thesis` / `thesis_update_job`).

**UI:** `/insights` (sidebar after Ideas). Dossier also loads `/api/ticker/<ticker>/insights`.

## Tables (Research DB)

| Table | Role |
|-------|------|
| `ticker_theses` | Header: ticker, title, disposition, intent, status, `last_reviewed_at` |
| `thesis_entries` | Flat thread: `opening`, `comment`, `review`, `llm_reply` |
| `thesis_evidence` | Links to user URLs, articles, meta, stance rows, etc. |

Schema: `database/schema/research/tables/ticker_theses.sql` (+ entries/evidence).
Migration: `database/migrations/2026-07_add_ticker_theses.sql`.

## Axes

- **Disposition:** `bullish` | `bearish` | `neutral`
- **Intent:** `seek_entry` | `seek_exit` | `monitor`
- **Status:** `active` | `archived` | `superseded` (soft archive = recycle bin; admin hard-delete)

## Entry kinds

| Kind | Who writes | Notes |
|------|------------|--------|
| `opening` | User (on create) | First post |
| `comment` | User | Does not change disposition/intent |
| `review` | User | May change disposition/intent; bumps `last_reviewed_at` |
| `llm_reply` | System / eval job | Advisory only; does **not** bump `last_reviewed_at` |

User API (`add_entry`) rejects `opening` and `llm_reply`. Jobs use `add_llm_reply`.

## Freshness / due-for-review

`reviewed_at = COALESCE(last_reviewed_at, created_at)`

| Status | Age |
|--------|-----|
| `due_for_review` | ≥ 14 days |
| `stale` | ≥ 30 days |

Weak moat drafts (`[WEAK CONTEXT]` in title/body, or `weak_context` tag) sort first in the due queue.

**API:** `GET /api/insights/due`

Only a human `review` clears due/stale — an `llm_reply` is advisory context.

## AI evaluation job

- **Job id:** `insights_thesis_evaluation` (not `thesis_update_job` — that updates fund philosophy)
- **Schedule:** Tue/Thu 18:30 America/New_York (respects global AI lock via `AI_JOB_NAMES`)
- **Pick:** active theses due/stale (and weak drafts), up to 8 per run
- **Context:** thesis header + recent entries + stored `ticker_meta_analysis` narrative/stance +
  latest `ticker_analysis` summary (read-only; does not re-run meta)
- **Write:** `add_llm_reply` with verdict `HOLDS` | `TENSION` | `STALE_THESIS` |
  `INSUFFICIENT_DATA`, optional suggested disposition/intent (advisory), optional evidence
  link to meta row
- Does **not** auto-flip disposition/intent, bump `last_reviewed_at`, or write `stance_history`

Prompt: `INSIGHTS_THESIS_EVALUATION_PROMPT` in `web_dashboard/ai_prompts.py`.

## Bootstrap (one-off)

`web_dashboard/scripts/probe_moat_theses.py` drafts positive/moat theses from Research DB + SearXNG.
Treat drafts with `weak_context` as noise until a human reviews them.

**Lessons (2026-07):** never use title/summary `ILIKE` for article lookup — `COST`→costs,
`RAIL`→Trail, `FAST`→Faster polluted drafts. Use ticker-array matches only + company-first
SearXNG. Moat framing is a poor fit for index/sector ETFs — `--stocks-only` skips them;
archive weak ETF bootstrap drafts rather than rewriting.

Smoke eval one ticker: `python scripts/smoke_thesis_eval.py COST`

## Overlap — do not confuse

| Feature | What it is |
|---------|------------|
| Sector Insights `/sector_insights` | ETF/sector meta surface |
| `thesis_update_job` / `fund_thesis` | Fund-level philosophy in Supabase |
| `action_queue_ai_review` | Queue row vs research; different table/prompt |
| `stance_history` | Automated stance ledger — Insights does not write it in v1 |

## Related

- Roadmap Decide layer + backlog (meta injection, Today/Ideas surfacing): [`docs/ROADMAP.md`](ROADMAP.md)
- Research loop screen map: [`docs/DASHBOARD_RESEARCH_LOOP.md`](DASHBOARD_RESEARCH_LOOP.md)
