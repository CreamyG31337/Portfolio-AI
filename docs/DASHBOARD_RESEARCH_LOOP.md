# Dashboard research loop

This document ties together **dashboard mechanics** (rules-based alerts) and **AI research artifacts** (interpretation aids). Nothing here is investment advice; all AI output is for research and must be verified before acting.

## Action Queue (rules-based, not LLM)

The **Action Queue** ranks watchlist tickers using the latest `signal_analysis` row per symbol, **fund holdings**, and configurable alert policy thresholds.

**Authoritative rules** live in the docstring of `get_action_queue()` in [`web_dashboard/routes/dashboard_routes.py`](../web_dashboard/routes/dashboard_routes.py):

| Action | When it appears |
|--------|-----------------|
| **SELL** | `overall_signal == SELL`, fund **holds** the position, confidence ≥ fund policy |
| **BUY** | `overall_signal == BUY`, fund does **not** hold, confidence ≥ policy |
| **RISK** | Fear level in policy set (e.g. HIGH/EXTREME), fund **holds** |
| **WATCH** | `overall_signal == WATCH`, fund does **not** hold, confidence floor |

**API:** `GET /api/dashboard/action-queue?fund=...&limit=10`

**Query params:**

- `enrich` — default `1`. When `1`, each row may include `research_context` (latest saved `ticker_analysis` / `ticker_meta_analysis` from the research DB). Set `enrich=0` to skip extra Postgres reads.

## Market daily brief (LLM, cached once per day)

A short **market backdrop** (indices, risk tone, caveats) generated from recent **`benchmark_data`** closes in Supabase (^GSPC, QQQ, ^RUT, VTI, etc.) plus one LLM pass. It is **not** a trade list and does not replace the Action Queue.

**Storage:** Research Postgres table `market_daily_brief` (one row per `brief_date`).

**API:** `GET /api/dashboard/market-brief` — latest brief or 404 if not generated yet.

**Job:** `market_daily_brief` scheduler job (after benchmark data is refreshed; see `AVAILABLE_JOBS` in `web_dashboard/scheduler/jobs.py`).

## Queue intelligence

### Deterministic enrichment (`research_context`)

For each queue row, the API can attach the latest **standard** `ticker_analysis` stance/sentiment and **meta** `unified_conviction` when available, plus ages in hours. This helps answer: *does saved research align with the mechanical signal?* at a glance.

### Cached AI review (`action_queue_ai_review`)

Optional nightly (or on-demand) LLM pass that stores a compact **verdict** (e.g. ALIGNED, TENSION, STALE, INSUFFICIENT_DATA) and a one-line note per `(fund, ticker, signal analysis date)`. The dashboard **reads** these rows only—no LLM on every refresh.

**API:** Reviews are merged into action queue items as `ai_review` when present.

## Screen map

| Screen | Purpose | Key APIs / routes |
|--------|---------|-------------------|
| Dashboard | Portfolio summary, Action Queue, Market brief card | `/api/dashboard/summary`, `/api/dashboard/action-queue`, `/api/dashboard/market-brief` |
| Today | Regime + **Advise pack** (ranked buy/sell) + flips + queue + Insights attention | `/api/today/briefing` (`advise_pack`) |
| Watchlist | Fund-scoped watched tickers: list, bulk paste, soft-remove, tier | `/watchlist`, `GET/POST /api/watchlist`, `PATCH /api/watchlist/item`. Ticker page Add/Remove. Ideas Accept still adds discovery tickers (`source=ideas_inbox`). |
| Ticker detail | Full ticker AI analysis + meta synthesis | `/api/v2/ticker/<t>/analysis`, `/api/v2/ticker/<t>/meta-analysis` |
| Insights | Human thesis threads (org-wide); due-for-review queue | `/insights`, `/api/insights`, `/api/insights/due`, `/api/ticker/<t>/insights` |
| Research | Articles, semantic search | Research routes / `research_articles` |
| Jobs admin | Schedule / run jobs | Scheduler UI / `jobs.py` |

Insights (`/insights`) is **not** Sector Insights (`/sector_insights`). Thesis eval job
(`insights_thesis_evaluation`) posts advisory `llm_reply` entries; it does not update
Action Queue review rows. See [`docs/INSIGHTS.md`](INSIGHTS.md).

For the full Decide-layer comparison (what each LLM pass is *for*, data-flow mermaid,
circularity guards): [`INSIGHTS.md` → Analysis layers](INSIGHTS.md#analysis-layers--what-each-pass-is-for).

## Related docs

- [Insights / analysis layers](INSIGHTS.md#analysis-layers--what-each-pass-is-for)
- [ETF / ticker AI](../docs/ETF_AI_ANALYSIS_SYSTEM.md)
- [AI research system](../web_dashboard/AI_RESEARCH_SYSTEM.md)
- [AGENTS.md](../AGENTS.md) — testing and conventions
