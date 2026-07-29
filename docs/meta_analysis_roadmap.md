# Meta Analysis Roadmap

This document tracks the multi-layer meta-analysis program and keeps the next phases explicit.

> **⭐ Start here instead:** [`docs/ROADMAP.md`](ROADMAP.md) is the **master plan**. As of
> **2026-07-29**, Phase H is closed; Ideas quality P1–P4 and measurement rig M1–M5 shipped.
> Active backlog: **Phase I** (prefer I1 story dedup), then **Phase J** / **Phase K** (K1
> PoC done). This doc remains the deep reference for the meta-analysis layers (Phases 1–3,
> all shipped); its "Later phases" section is superseded by `ROADMAP.md`.

**Related docs (keep in sync when the pipeline changes):**

| Doc | Purpose |
|-----|---------|
| [`docs/ROADMAP.md`](ROADMAP.md) | **Master plan** — prioritized pillars, decision surfaces, sequencing |
| [`docs/PHASE_JK_PLAN.md`](PHASE_JK_PLAN.md) | Event catalyst backtest + YouTube captions → articles (pipeline integration) |
| [`docs/INSIGHTS.md`](INSIGHTS.md) | Human theses + **Decide-layer job map** (meta vs thesis eval vs queue review — table + mermaid) |
| [`docs/ETF_SECTOR_META_OPS.md`](ETF_SECTOR_META_OPS.md) | Ops cheat sheet: catch-up after outage, one-command backfill |
| [`docs/ETF_AI_ANALYSIS_SYSTEM.md`](ETF_AI_ANALYSIS_SYSTEM.md) | ETF group + ticker analysis jobs, prompts, storage |
| [`docs/ETF_WATCHTOWER.md`](ETF_WATCHTOWER.md) | Holdings ingestion into Research |

## Program goals (stable intent)

The program is **incremental by design**: we add one layer of structure, measure quality in production, then wire the next consumer. Prompt-only leaps are avoided when SQL invariants or job metrics can catch silent failure.

**Long-term north star (moving target):** help answer *what to buy or sell* (or lean long/short/avoid) using:

- **Market** regime (risk on/off, breadth, vol)
- **Sector** rotation (ETF flow themes, sector stance)
- **Ticker** evidence (signals, congress, insider, fundamentals, research, social)
- **Portfolio** constraints (positions, fund rules, cash) — mostly **not** wired yet

We are **not** building autonomous execution. Outputs should be **inspectable** (stance, drivers, contradictions, freshness) so a human can agree or override. The exact contract evolves as we learn what the data actually supports.

## What exists today vs north star

| Capability | Today | North star |
|------------|-------|------------|
| Market regime prior | Shipped (`market_daily_brief` → ticker meta) | Same |
| Sector rotation view | Shipped (`sector_meta_analysis`, Sector Insights UI) | Fed into ticker meta (3c) |
| Human ticker theses | Shipped as **Insights** (`/insights`, `ticker_theses`) — not Sector Insights; see [`INSIGHTS.md`](INSIGHTS.md). Injected into ticker meta (R1) and Today/Ideas attention (R2); thesis advice → ledger (R3). | Widen scope / trust calibration via Phase H source-ROI |
| Per-ticker conviction | Shipped (`ticker_meta_analysis` + Phase 1 signal fusion) | Sector prior + ETF flow context (3c+); **Phase H2** adds clusters / dilution / filings / confluence / prior stance (Today-only as of 2026-07-15) |
| Action queue | **Rules-based** from technical `signal_analysis`; meta attached as context | Ranked ideas aligned with meta + portfolio |
| Explicit BUY/SELL/HOLD with size | **Ticker analysis** JSON has stance fields; **not** portfolio-level picks | Fund-aware recommendation list with explainability |
| Outcome feedback | Ledger + scoring + track-record + **source-ROI (H1) + baselines (M5)** shipped; fund primary benchmark (M6) still open | Calibrate which inputs predict good trades; down-weight noisy collectors |

## Phase status (2026-05-23)

- Phase 1 (Signal + News Fusion into Ticker Meta): **shipped** — see [Ticker analysis recovery](#ticker-analysis-pipeline-recovery-2026-05-20) for the May 2026 unblock
- Phase 2 (Market Meta Regime): **2a + 2b shipped** — Phase 2c (digests/newsletters) deferred
- Phase 3 (Sector Meta Layer): **3a + 3b + 3c shipped** — ETF holdings on Research only; ticker meta bundle includes sector prior when `META_ANALYSIS_PHASE3_SECTOR` on; verified end-to-end 2026-05-21 / 2026-05-22; **3d not started**
- Phase 4–6 (feedback, scheduling, explainability): **planned**
- Phase 7 (portfolio-aware recommendations): **aspirational** — see [Later phases](#later-phases-iterative)

### See also: AI Task Queue ([`docs/AI_TASK_QUEUE_DESIGN.md`](AI_TASK_QUEUE_DESIGN.md))

The queue and meta roadmaps share infrastructure even though they cover different concerns:

- **Queue Q2** (`ticker_analysis` migration, ✅) is what now feeds fresh `ticker_analysis` rows into the meta bundle on a reliable nightly cadence — without it, Phase 3c had no consumer (see the May 2026 unblock note below).
- **Queue Q3** (retire global mutex for queue-managed jobs, ⏳) is the real fix for "an unrelated AI job hung and `ticker_meta_analysis` skipped its cron" failures.
- **Queue Q4** (migrate `ticker_meta_analysis`, `sector_meta_analysis`, `etf_group_analysis`, `market_daily_brief`, `ui_ai_summaries`, `action_queue_ai_review`, ⏳) is the queue-side framing of what this doc later calls "lock-aware scheduling" under Later phases.

When in doubt, treat the queue doc as **infra status** for the meta program; treat this doc as the **product layers** the AI is actually for.

### Ticker analysis pipeline recovery (2026-05-20)

While verifying Phase 3c we discovered the entire ticker pipeline had been **silently dead since 2026-01-23**:

- A single `NoneType.__format__` crash in the ticker analysis save path failed once for every holding in one nightly run.
- The old `AISkipListManager.record_failure` insert path left `skip_until` NULL on the first failure, and `should_skip` treated NULL as **permanent ban**. Result: **84 holdings were permanently banned after one failure each**, despite `MAX_FAILURES_BEFORE_SKIP = 3`.
- A second silent bug: `get_tickers_to_analyze` called `supabase.table('portfolio_positions').select('ticker').execute()` without pagination, capping at the Supabase Python client's default 1000 rows. Even without the skip list, only a tiny subset of holdings was ever considered.
- Net effect for 4 months: `ticker_analysis` cron ran but processed **zero tickers**, so `ticker_analysis` and `ticker_meta_analysis` tables stayed at 0 rows. Phase 3c was shipped but had no consumer.

**Fixes (commit landing 2026-05-20):**

1. `AISkipListManager.record_failure` now inserts a finite `skip_until` (~1h) on first failure; only permanent markers (`delisted`, `no such ticker`, etc.) ever set `skip_until=NULL` after `MAX_FAILURES_BEFORE_SKIP`.
2. Transient failures (format crashes, timeouts, JSON errors) now get exponential 24h/48h/96h backoff, capped at 7 days.
3. `get_tickers_to_analyze` paginates `portfolio_positions` explicitly and reports a structured `last_selection_stats` breakdown.
4. `jobs_ticker_analysis` now surfaces the breakdown (manual/holdings/watchlist counts vs. skipped/recently_analyzed) when the picker returns 0 — so a polluted skip list cannot ever again look like a healthy quiet day.
5. New helper `web_dashboard/scripts/clear_format_polluted_skip_list.py` cleared the 84 historical rows in one shot (kept the 11 legitimate skip entries).
6. New tests: `tests/test_ai_skip_list_manager.py` and pagination/breakdown coverage in `tests/test_ticker_analysis_service.py`.

**Verification next step:** wait one nightly cycle (`ticker_analysis` 4 AM UTC, `ticker_meta_analysis` 6:45 AM UTC), then run `python web_dashboard/scripts/verify_sector_prior.py` to confirm the Phase 3c sector prior block lands in real bundles.

---

## ETF holdings data layer (2026-05 migration)

**Source of truth:** Research Postgres `etf_holdings_log` + view `etf_holdings_changes`.

| Store | Role |
|-------|------|
| **Research** | Watchtower writes here; Flask ETF Holdings UI reads here; `etf_group_analysis` reads changes here |
| **Supabase** `etf_holdings_log` | **Removed** (legacy Jan 2026 snapshot only). Migration: `database/schema/supabase/migrations/drop_legacy_etf_holdings_supabase.sql` |

If Sector Insights or ETF articles look months old while holdings look current, the gap is almost always **missing ETF Analysis articles**, not missing holdings. See [`docs/ETF_SECTOR_META_OPS.md`](ETF_SECTOR_META_OPS.md).

**Auto catch-up:** `etf_group_analysis` queues missing (ETF, date) pairs for **14 days**, expanding to **30** when behind (`web_dashboard/etf_meta_pipeline.py`). **Manual catch-up:** `web_dashboard/scripts/backfill_etf_sector_meta.py`.

---

## Phase 1: Signal + News Fusion into Ticker Meta

### Scope

- Extend artifact bundle construction in `web_dashboard/meta_analysis_service.py`.
- Keep scheduler shape intact in `web_dashboard/scheduler/jobs_ticker_meta_analysis.py`.
- Reuse existing signal and research outputs from current stores.

### Implemented in this phase

1. Artifact bundle now includes:
   - Latest technical signal snapshot (`overall_signal`, confidence, trend/timing/fear, momentum/fundamental bias).
   - Latest market regime brief context (`headline`, `risk_tone`, leadership/caveats, narrative).
2. Ticker meta prompt now requests stable output contract fields:
   - `stance`, `confidence`, `horizon`, `key_drivers`, `contradictions`, `risk_flags`, `actionability_score`.
3. Persistence compatibility:
   - `ticker_meta_analysis.unified_conviction` now accepts fallback from `stance`.
   - `ticker_meta_analysis.confidence_adjusted` now accepts fallback from `confidence`.
4. Basic instrumentation:
   - Per-run meta logs include stance/confidence and contradiction/risk-flag counts.
5. **Shared LLM workflow:** `TickerMetaAnalysisService` calls `OllamaClient.collect_with_summary_model_chain()` (`web_dashboard/ollama_client.py`) so meta synthesis uses the same multi-model order, per-model host list, second-Ollama-host fallback, and GLM path as other production AI jobs. Avoid ad-hoc `query_ollama` in new meta-related code unless there is a strong reason.
6. **Host-aware Ollama routing:** Defaults live in `web_dashboard/model_config.json` (per-model `base_url_env` / `fallback_base_url_env`). Prefer semantic env vars `OLLAMA_BASE_URL_AMD` and `OLLAMA_BASE_URL_NVIDIA` in production mappings; legacy `OLLAMA_BASE_URL` and `OLLAMA_BASE_URL_2` still resolve when semantic vars are unset (see `_resolve_ollama_host_env` in `ollama_client.py`). Deployment: host-side optional env (e.g. `trading-dashboard-optional.env`) and Docker env pass-through (see `.woodpecker.yml` comments)—not committed repo `.env` files.
7. **Provenance:** Successful runs should persist `model_used` (and related fields where tables support them) so stale UI and 404-on-wrong-host incidents are diagnosable from the DB.

### Rollout checklist (Phase 1)

#### Feature flag

- **Env:** `META_ANALYSIS_PHASE1_SIGNAL_FUSION` (default: on)
  - **On:** Artifact bundle includes technical signal snapshot + latest `market_daily_brief` context; prompt asks the model to treat signals as first-class (see `TICKER_META_ANALYSIS_PROMPT` in `web_dashboard/ai_prompts.py`).
  - **Off:** Set to `false`, `0`, `no`, or `off` to use the legacy bundle (no signal/brief blocks) and `TICKER_META_ANALYSIS_PROMPT_LEGACY` — instant rollback without code changes.
- **Docker / compose:** Add or change the variable on the web/scheduler service, then recreate the container(s) so the process picks up the new value.

#### Pre-deploy baseline (optional but useful)

Run against **research** DB (where `ticker_meta_analysis` lives) and **Supabase** (where `job_executions` lives), adjusting the time window as needed.

```sql
-- Research DB: how fresh is meta today?
SELECT count(*) AS meta_rows,
       count(*) FILTER (WHERE updated_at > now() - interval '24 hours') AS updated_last_24h
FROM ticker_meta_analysis;

-- Research DB: distribution of contradiction list lengths (full_result is optional if contradictions column is populated)
SELECT percentile_cont(0.5) WITHIN GROUP (
  ORDER BY jsonb_array_length(coalesce(contradictions, '[]'::jsonb))
) AS p50_contradiction_count
FROM ticker_meta_analysis;
```

```sql
-- Supabase: recent ticker_meta_analysis job outcomes (schema uses error_message for failure text)
SELECT status, count(*)
FROM job_executions
WHERE job_name = 'ticker_meta_analysis'
  AND started_at > now() - interval '48 hours'
GROUP BY status
ORDER BY status;
```

#### Post-deploy verification (first 2–6 hours)

1. Confirm env: `META_ANALYSIS_PHASE1_SIGNAL_FUSION` unset or `true` in the running container if you intend Phase 1 on.
2. After the next `ticker_meta_analysis` run, spot-check **logs** for lines like `Meta synthesis for TICKER: stance=... contradictions=N risk_flags=M` (see `web_dashboard/meta_analysis_service.py`).
3. Re-run the SQL snippets above; expect `updated_last_24h` to increase after the job succeeds.
4. If outputs look wrong or job latency spikes, set `META_ANALYSIS_PHASE1_SIGNAL_FUSION=false`, redeploy/restart, and compare the next run.

#### 24-hour acceptance metrics

| Metric | Where | Acceptable initial target |
|--------|--------|---------------------------|
| Job success rate | `job_executions` for `ticker_meta_analysis` | No sustained increase in `failed` vs the prior 7-day baseline; no rows stuck `running` > 2× usual max duration |
| Throughput | Same table + logs | At least as many successful completions per day as before rollout (allow one off day if AI lock contention) |
| Output shape | `ticker_meta_analysis.full_result` | Most rows include `stance` / `confidence` (or mapped into `unified_conviction` / `confidence_adjusted`); `contradictions` and `risk_flags` are arrays, not null-heavy breakage |
| Qualitative | UI / API | Narratives remain readable; no systematic “everything INSUFFICIENT_DATA” unless upstream analyses are empty |
| Rollback drill | Env only | Team can turn flag off and get a clean legacy bundle + prompt within one container restart |

#### Remaining validation steps

- Evaluate real outputs over 1–2 nightly runs for consistency and sparse-data behavior.
- Confirm contradiction/risk-flag frequencies are useful and not over-triggering.

---

## Shared infrastructure (feeds meta and dashboard AI)

Meta-analysis freshness depends on the same stack as other cached LLM artifacts (market brief, portfolio snapshot AI, fund digest, ticker analysis).

| Concern | Where it lives | Notes |
|--------|----------------|-------|
| Standard LLM entry | `collect_with_summary_model_chain` in `web_dashboard/ollama_client.py` | Prefer this for any new scheduler job or service that summarizes with the “summary model” chain. |
| Model/host config | `web_dashboard/model_config.json` | Single place to bind a model name to AMD vs NVIDIA host env vars and fallbacks. |
| Feature flag (Phase 1 bundle) | `META_ANALYSIS_PHASE1_SIGNAL_FUSION` | `web_dashboard/settings.py` → `is_meta_analysis_phase1_signal_fusion_enabled()`. |
| Global AI lock | `utils/job_tracking.py` | One AI-heavy job at a time **for legacy (non-queue) jobs**. `ticker_analysis` already runs on the [`AI task queue`](AI_TASK_QUEUE_DESIGN.md) (Q2 ✅ 2026-05-20). Meta jobs (`ticker_meta_analysis`, `sector_meta_analysis`, `etf_group_analysis`, etc.) still respect this lock and are tracked under queue Q4. Stale `running` rows are cleaned by watchdog / lock helpers until those jobs migrate. |
| Embedded scheduler | `web_dashboard/app.py` + `web_dashboard/scheduler/scheduler_core.py` | Scheduler must start with the Flask process unless `DISABLE_SCHEDULER=true` or a separate scheduler mode is intentionally used. Duplicate starts are suppressed via locks/heartbeat inside `start_scheduler()`, not by skipping startup on `WERKZEUG_RUN_MAIN`. |
| Admin “Next run” | `get_all_jobs_status_batched()` in `scheduler_core.py` | When the web worker has no in-process scheduler, next run times are read from the `apscheduler_jobs` table so the Jobs UI stays truthful under multi-worker Gunicorn. |
| Heavy job staggering | `web_dashboard/scheduler/jobs.py` | Example nightly PT order: **ticker_analysis** ~21:00 → **alpha_research** 23:15 → **ticker_meta_analysis** 23:45 — reduces collisions with the global AI lock. **market_daily_brief** runs weekdays 17:45 ET after benchmark refresh cadence. |

### Manual verification

- `web_dashboard/scripts/run_scheduler_job_once.py` can trigger `ticker_meta_analysis`, `market_daily_brief`, `sector_meta_analysis`, `etf_group_analysis`, etc., without waiting for cron.
- **ETF + sector catch-up:** `web_dashboard/scripts/backfill_etf_sector_meta.py` (see [`docs/ETF_SECTOR_META_OPS.md`](ETF_SECTOR_META_OPS.md)).

---

## Phase 2: Market Meta Regime Normalization

### Goal

Convert market brief output into a reusable regime prior consumed by ticker synthesis.

### Phase 2a (implemented)

- **`MARKET_DAILY_BRIEF_PROMPT`** now asks the brief LLM for the full regime object (`risk_regime`, `regime_confidence`, `breadth_proxy`, `volatility_state`, `macro_themes`, `leadership_note`, `caveats`).
- **`web_dashboard/market_regime_normalization.py`** merges LLM output with canonical keys before UPSERT (`merge_regime_for_storage`) and normalizes on read for ticker meta bundles (`normalize_market_regime`). Legacy rows that only had `risk_tone` still work; **`as_of`** prefers row `updated_at` (UTC ISO), otherwise **16:00 America/New_York** on `brief_date` converted to UTC.
- **`market_brief_service.run_market_daily_brief`** persists merged `regime_json`; **`TickerMetaAnalysisService`** Phase 1 market block emits all canonical regime lines into the artifact bundle.

### Phase 2b (implemented)

- **`GET /api/dashboard/market-brief`** adds **`regime_canonical`**: same stable contract as `normalize_market_regime` so TypeScript and other clients do not duplicate normalization. **`regime_json`** remains the stored row (merged raw + canonical from 2a) for debugging.
- **Dashboard** market brief card: collapsible **Regime (structured)** section fed from `regime_canonical`.
- **Validation:** `invalid_regime_enum_fields` in `market_regime_normalization.py`; `run_market_daily_brief` logs **`logger.warning`** when the LLM returns out-of-set `risk_regime` / `risk_tone` / `breadth_proxy` / `volatility_state` before UPSERT (normalization still clamps; the job does not fail on drift alone).

### Phase 2c — **explicitly deferred** (newsletters and digest rollups later)

**Not in scope until Phase 2c is scheduled for implementation:** wiring **fund digests**, **email digests**, **newsletters**, and similar rollup surfaces so they **read and embed `regime_canonical`** (or otherwise depend on the normalized regime as a single source of truth). The dashboard and **`GET /api/dashboard/market-brief`** already expose `regime_canonical` for interactive use; batch narrative products stay on legacy paths until we intentionally ship 2c.

**Rationale:** keep Phase 2b stable in production, avoid duplicate normalization in long-form generators, and **defer newsletter work** to a dedicated pass (copy, truncation, and send-time freshness differ from the dashboard card).

**Still deferred after 2c ships (Phase 2c+):** contrast model-reported `volatility_state` with realized vol from benchmark series when we want fewer `UNKNOWN`s; any other rollup not listed in the Phase 2c bullet above remains out of scope until called out in a future checklist.

### Structured object contract

Proposed normalized market regime object:

```json
{
  "risk_regime": "RISK_ON|RISK_OFF|NEUTRAL|MIXED",
  "regime_confidence": 0.0,
  "breadth_proxy": "LEADERSHIP_BROAD|LEADERSHIP_NARROW|UNCLEAR",
  "volatility_state": "CALM|ELEVATED|STRESSED|UNKNOWN",
  "macro_themes": ["string"],
  "leadership_note": "string",
  "caveats": ["string"],
  "as_of": "ISO-8601 timestamp"
}
```

### Data sources

- `market_daily_brief` in research DB (`regime_json`, `headline`, `narrative`, `updated_at`).
- Existing benchmark statistics currently used by market brief job.

### Integration points

- Primary read path: `meta_analysis_service` bundle builder.
- Secondary use: UI summaries and cross-screen rollups where available.

### Exit criteria

- Ticker meta runs deterministically with or without regime object.
- Regime object is queryable with explicit freshness metadata.

---

## Phase 3: Sector Meta Layer

### Status (as of 2026-05-19)

| Sub-phase | What | Status |
|-----------|------|--------|
| **3a** | `/sector_insights` Flask page | **Shipped.** Lists ETF Analysis articles; when `sector_meta_analysis` rows exist, UI prefers synthesized sector cards (see `etf_routes.py`). |
| **3b** | `sector_meta_analysis` job + Research table | **Shipped.** Service, scheduler, prompt, `sector_meta_normalization.py`, ETF article sector tagging (`etf_article_sector_infer.py`). |
| **3b-data** | Holdings → articles pipeline on Research | **Shipped (2026-05).** `etf_group_analysis` reads Research `etf_holdings_changes`; Supabase holdings table dropped. Ops: [`docs/ETF_SECTOR_META_OPS.md`](ETF_SECTOR_META_OPS.md). |
| **3c** | Ticker meta consumes sector prior | **Shipped (2026-05-19).** `meta_analysis_service._append_sector_prior_block`, `TICKER_META_ANALYSIS_PROMPT` item 7; gated by `META_ANALYSIS_PHASE3_SECTOR`. |
| **3d** | Richer sector inputs + UI polish | **Not started.** Optional after 3c. |

> **Fresh agent:** Phase 3c is shipped — prioritize **3d** UI polish, ETF article freshness ops, or **Phase 7** recommendation slice. Do not reintroduce Supabase `etf_holdings_log` reads.

### End-to-end pipeline (target mental model)

```text
etf_watchtower          →  Research.etf_holdings_log
etf_group_analysis      →  research_articles ("ETF Analysis", sector-tagged)
sector_meta_analysis    →  sector_meta_analysis (sector stance, rotation_rank, …)
ticker_meta_analysis    →  ticker_meta_analysis (unified_conviction + sector prior when 3c on)
action_queue (signals)  →  human-facing queue; meta as context today
```

**Theoretical link to buy/sell:** ETF flows → sector rotation → ticker stance is the intended reasoning chain. After backfill, all three layers can be fresh; **3c** passes sector prior into ticker meta LLM input (deploy + run `ticker_meta_analysis` to refresh rows).
>
> **Anti-pattern to avoid:** the 3a deploy bug was misdiagnosed by an earlier agent as a Python/template bug, which led to three commits (`b4c2f04d`, `9e179e14`, `a1dcd644`) adding defensive band-aids (`ensure_flask_sidebar_navigation_links`, sector-specific `show=True` overrides, template `url_for` hacks). The real fault was one missing `COPY` line. Root-cause first; do not stack workarounds.

### Goal

Add sector-level rotation context that conditions ticker conviction.

### Sector output contract (locked target shape — do not rename or add fields in 3b)

```json
{
  "sector": "string",
  "sector_stance": "BULLISH|NEUTRAL|BEARISH|MIXED|INSUFFICIENT_DATA",
  "momentum_state": "ACCELERATING|STABLE|DECELERATING|UNKNOWN",
  "news_pressure": "POSITIVE|NEUTRAL|NEGATIVE|MIXED|UNKNOWN",
  "rotation_rank": 0,
  "confidence": 0.0,
  "key_drivers": ["string"],
  "risk_flags": ["string"],
  "as_of": "ISO-8601 timestamp"
}
```

### Candidate data sources

- Existing ETF holdings/analysis outputs (`etf_watchtower`, `etf_group_analysis`).
- Research article sentiment/conclusions grouped by sector.
- Sector ETF return/relative-strength snapshots (if available from benchmark/market data stores).

### Scheduler sequencing (target)

Nightly AI sequencing target:

1. `market_daily_brief`
2. `sector_meta_analysis` (new — 3b)
3. `ticker_analysis`
4. `ticker_meta_analysis`

This ordering ensures ticker synthesis consumes both global and sector priors. The global AI lock (`utils/job_tracking.py`) serializes anyway; pick a slot that does not collide with the existing 21:00 / 23:15 / 23:45 PT chain in the heavy-job staggering table at the top of this doc.

### Overall exit criteria for Phase 3

- Ticker meta prompt/input includes a sector prior when fresh rows exist; runs deterministically when they don't.
- Sector output is inspectable in research DB (and eventually, via 3d, in `/sector_insights` UI) for debugging and QA.

### Data foundation (ETF Analysis → sector meta) — incremental, noisy inputs

Meta layers only work if **upstream artifacts are consistently tagged and identifiable** without ad-hoc archaeology. We are building this **slowly on purpose**: each phase adds signal, measures quality, then tightens—not “vibe code” the whole stack in one pass.

**What broke in practice (2026-05):**

- **Split database:** `etf_group_analysis` read Supabase `etf_holdings_changes` (frozen ~Jan 2026) while Watchtower wrote Research (through May 2026) → no new ETF articles → sector meta summarized stale January content. **Fixed:** all production readers/writers use Research; Supabase holdings dropped.
- `research_articles.sector` was often **empty** for `article_type = 'ETF Analysis'` because `etf_group_analysis` did not set it and **`securities.sector` is frequently null for ETF tickers**. **Mitigated:** `etf_article_sector_infer.py` on save + backfill script.
- Downstream **`sector_meta_analysis`** groups articles by `sector`; empty tags → **`__UNTAGGED__`**, which weakens prompts.

**What we standardized:**

1. **`resolve_sector_for_etf_analysis_article`** in `web_dashboard/etf_article_sector_infer.py`: holdings (mode of `securities` sectors) → ETF from canonical **`etf-analysis://{TICKER}/{date}` URL** → **`KNOWN_ETF_IMPUTED_SECTOR`** for known watchlist ETFs + **`Multi-sector`** for broad index ETFs. **Same resolver** on **new saves** (`etf_group_analysis`) and **backfill** (`scripts/backfill_etf_analysis_article_sectors.py`).
2. **Operational check** (research DB): count rows that should never accumulate if the daily save path stays healthy:

```sql
SELECT count(*) AS etf_analysis_missing_sector
FROM research_articles
WHERE article_type = 'ETF Analysis'
  AND (sector IS NULL OR TRIM(sector) = '');
```

Target: **0** in steady state after `etf_group_analysis` runs with the resolver. If this grows, fix **securities coverage**, extend the **imputation map**, or add structured fields—**not** more LLM prompt text alone.

**What to do when scaling (new ETFs, new jobs):**

- When adding symbols to the ETF watchtower / `ETF_NAMES` list, **update `KNOWN_ETF_IMPUTED_SECTOR`** in the same change (or accept `Multi-sector` / unresolved until securities has a sector).
- Prefer **small, observable increments** (new column, new job metric, SQL invariant) over prompt-only “summarize everything” leaps—the latter hides missing structure.

**Known ceiling:** article-only sector meta cannot replace **time series**, **cross-sectional ranks**, or **ticker-level trends**; Phase 3d and benchmark inputs exist to widen the foundation. Until then, treat outputs as **rotation-flavored context**, not omniscient rollup.

---

### Phase 3a — Read-only preview UI (shipped)

What exists today:

- Route: `web_dashboard/routes/etf_routes.py::sector_insights` (`/sector_insights`).
- Template: `web_dashboard/templates/sector_insights.html`.
- Behavior: queries `ResearchRepository.get_recent_articles(limit=48, days=730, article_type="ETF Analysis")` and renders cards.
- Sidebar link: emitted via `get_navigation_links()` in `web_dashboard/shared_navigation.py`; `get_navigation_context()` in `web_dashboard/app.py` forces `show=True` for `sector_insights`.
- When `sector_meta_analysis` rows exist for the latest `run_date`, the page shows synthesized sector cards; article list remains as drill-down. Banner may still note that **ticker meta does not consume sector prior until 3c**.

What 3a is **not**:

- Not a synthesis. The page does no LLM work, no sector grouping, no rotation ranking. It is a different lens onto `etf_group_analysis` output that already existed under `/research`.

**Operational note:** the Dockerfile.frontend fix from 2026-05-14 must ship via a frontend image rebuild before the navigation link and any template changes appear in production. Trigger the rebuild as part of any Phase 3b deploy.

---

### Phase 3b — Build `sector_meta_analysis` (start here)

**Implemented in repo (2026-05-14).** The checklist below is the **contract reference** for behavior and rollout; change code and this section together.

Treat this as one self-contained chunk. Acceptance is binary: either the job runs nightly and persists conformant rows, or it doesn't.

**Scope (must do):**

1. **New service:** `web_dashboard/sector_meta_analysis_service.py`.
   - Mirror `web_dashboard/meta_analysis_service.py` (`TickerMetaAnalysisService`) patterns: artifact bundle → prompt → `collect_with_summary_model_chain` → parse → persist.
   - Output **must** match the "Sector output contract" above. No renames, no extra fields.
   - Sparse/empty input: persist a row with `sector_stance: "INSUFFICIENT_DATA"`; downstream consumers must accept this without crashing.

2. **New scheduler job module:** `web_dashboard/scheduler/jobs_sector_meta_analysis.py`.
   - Mirror `web_dashboard/scheduler/jobs_ticker_meta_analysis.py` (shape, lock usage, error handling).
   - Register in `web_dashboard/scheduler/jobs.py`. Time slot: between `market_daily_brief` (17:45 ET weekdays) and `ticker_meta_analysis` (23:45 PT). Suggested ~23:30 PT, but confirm against the staggering table at the top of this doc and current `apscheduler_jobs` so you don't collide with `alpha_research` at 23:15 PT.

3. **Persistence:** new research DB table `sector_meta_analysis`.
   - Suggested columns: `id (uuid)`, `sector (text)`, `sector_stance`, `momentum_state`, `news_pressure`, `rotation_rank (int)`, `confidence (float)`, `key_drivers (jsonb)`, `risk_flags (jsonb)`, `as_of (timestamptz)`, `full_result (jsonb)`, `model_used (text)`, `created_at`, `updated_at`.
   - One row per sector per run. UPSERT on `(sector, as_of::date)` is acceptable; do not dedupe more aggressively than the contract's `as_of`.
   - Match the migration pattern used by `ticker_meta_analysis` (find that table's migration and copy the structure / index choices).

4. **Feature flag:** `META_ANALYSIS_PHASE3_SECTOR`.
   - Accessor: `web_dashboard/settings.py` → `is_meta_analysis_phase3_sector_enabled()`. Default **on**.
   - Emergency off: set env var `META_ANALYSIS_PHASE3_SECTOR=false` on the container and restart — no code change needed.
   - When off: job is a no-op, table stays empty, `/sector_insights` falls back to ETF Analysis articles, ticker meta skips sector block.

5. **Prompt:** add `SECTOR_META_ANALYSIS_PROMPT` to `web_dashboard/ai_prompts.py`. Ask explicitly for every field in the contract. Reuse the `INSUFFICIENT_DATA` / `UNKNOWN` enum vocabulary the market regime prompt already uses.

6. **Provenance:** persist `model_used` on every successful row (mirrors Phase 1 item 7 / Phase 2a). Diagnosing stale UI and wrong-host incidents from the DB matters more than another nice-to-have output field.

7. **Enum-drift validation:** mirror `invalid_regime_enum_fields` in `web_dashboard/market_regime_normalization.py`. `logger.warning` on out-of-set enums before UPSERT, clamp to `UNKNOWN` / `MIXED` / `INSUFFICIENT_DATA`, do **not** crash the job on drift alone.

**Inputs (read-only — do not mutate these stores):**

- `etf_group_analysis` articles from research DB (same source `/sector_insights` already reads).
- If available: sector ETF return / relative-strength snapshots from benchmark stores. If absent, degrade to article-only input, not a crash.

**Out of scope for 3b (these are 3c/3d):**

- Wiring `sector_meta_analysis` rows into the ticker meta bundle (3c).
- Replacing `/sector_insights` UI to render rows (3d).
- New input sources beyond ETF group AI + benchmark snapshots (3d).

**Exit criteria for 3b:**

- `job_executions` rows for `sector_meta_analysis` show `succeeded` 3 consecutive nights.
- Every successful row has non-null `sector_stance`, `confidence`, `as_of`, `model_used`.
- Sparse-input rows carry `INSUFFICIENT_DATA` without crashing the job.
- No regression in `ticker_meta_analysis` success rate or runtime (AI lock not starved).
- `web_dashboard/scripts/run_scheduler_job_once.py sector_meta_analysis` triggers a manual run end-to-end.
- Rollback drill: setting `META_ANALYSIS_PHASE3_SECTOR=false` and restarting the container produces a clean no-op next run.

---

### Phase 3c — Ticker meta consumes the sector prior (shipped 2026-05-19)

**Implemented:**

1. `TickerMetaAnalysisService._append_sector_prior_block` — maps ticker → `securities.sector`, loads latest `sector_meta_analysis` row for that sector.
2. `TICKER_META_ANALYSIS_PROMPT` — item 7 instructs the model to reconcile sector prior vs ticker evidence.
3. Gated by `META_ANALYSIS_PHASE3_SECTOR` (same flag as sector meta job).

**After deploy:** run `ticker_meta_analysis` (nightly or `run_scheduler_job_once.py ticker_meta_analysis`) so existing meta rows pick up the new bundle digest.

**Exit criteria (verify in prod):**

- Ticker meta runs when sector row missing (bundle notes MISSING; no crash).
- Tickers with sector + fresh sector meta show prior lines in logs/bundle digest refresh.
- No regression in `ticker_meta_analysis` job success rate.

---

### Phase 3d — Optional polish (after 3c)

Optional; do these only when 3b + 3c are producing useful output:

- Sector-tagged research aggregation (research DB sector tags) as an additional input to `sector_meta_analysis`.
- Benchmark-relative ETF snapshots as a structured input vs. extracting them from articles.
- Replace `/sector_insights` UI to render `sector_meta_analysis` rows (with the existing article list as a fallback when rows are missing); drop the "stepping stone" banner once rows are the primary source.

---

## Later phases (iterative)

Near term (recommended order):

1. **ETF article freshness:** Keep gap at zero via nightly queue + occasional `backfill_etf_sector_meta.py` after outages ([`docs/ETF_SECTOR_META_OPS.md`](ETF_SECTOR_META_OPS.md)).
3. **Phase 2c (when scheduled):** Newsletters / digests consuming **`regime_canonical`** — deferred; see Phase 2c above.
4. **Quality loop:** 10–20 ticker eval set; regression on `stance`, `contradictions`, `risk_flags` after prompt/model changes.
5. **Lock-aware scheduling:** Batch or stagger meta jobs if AI lock wait grows (global lock serializes anyway).
6. **Event/news catalyst backtesting:** See master plan **Phase J** in [`ROADMAP.md`](ROADMAP.md#phase-j--event--news-catalyst-backtesting) (after Phase I story dedup).
7. **YouTube captions as articles:** See master plan **Phase K** in [`ROADMAP.md`](ROADMAP.md#phase-k--youtube-captions--research-articles) (allowlisted channels → `research_articles`).

### Phase 4 — Outcome feedback

> **Now planned concretely in [`docs/ROADMAP.md`](ROADMAP.md) Pillar 1** (stance ledger +
> outcome scoring). Key blocker discovered 2026-06-09: `ticker_meta_analysis` has
> `UNIQUE (ticker)` with `ON CONFLICT (ticker) DO UPDATE`, so stance history is destroyed on
> every run — Phase 4 requires the **append-only `stance_history` table** before any scoring
> is possible. Time-sensitive: history not captured is unrecoverable.

- Compare `ticker_meta_analysis` / `ticker_analysis` stances to realized P&amp;L and trade outcomes.
- Down-weight sources that add noise; document in this roadmap when weights change.

### Phase 5 — Adaptive scheduling

- Schedule by backlog (missing ETF articles, stale meta age) not only wall-clock cron.
- Partially addressed for ETF group queue lookback auto-expansion (`etf_meta_pipeline.py`).

### Phase 6 — Explainability in UI

- Surfaces show *why* this stance: which inputs agreed, which conflicted (`contradictions`, `risk_flags`, `key_drivers`).
- Sector Insights and ticker details already expose structured fields; unify copy and freshness badges.

### Phase 7 — Portfolio-aware recommendations (north star slice)

**Not started.** Prerequisites: 3c stable, fresh ETF articles, trustworthy sector tags.

| Piece | Description |
|-------|-------------|
| **Contract** | e.g. `recommendation: BUY\|SELL\|HOLD\|AVOID`, `horizon`, `confidence`, `rationale[]`, `invalidation` — aligned with existing `ticker_analysis` JSON where possible |
| **Inputs** | Ticker meta + signal queue + positions + fund policy (`settings` / fund profiles) |
| **Output surface** | Extend action queue or new “Ideas” panel — **human approves**; no auto-trade |
| **Mapping gap** | ETF holdings are mostly large-cap/index names; micro-cap book may need explicit “similar theme” or watchlist overlap, not raw ETF constituents |

Treat Phase 7 as a **product slice** once 3c proves sector prior improves ticker meta in spot checks — not a single prompt change.

---

## Exploratory — LLM-driven research selection

**Status:** parked, not on the numbered phase track. Captured here so the brainstorm isn't lost while we focus on Q3/Q4 + Phase 4.

### Gap this would fill

Today every "research" job uses **static selection** — a fixed query list, a fixed domain list, or round-robin through the watchlist. None of them use LLM judgment to pick *what* to research, and none of them read `ticker_meta_analysis` / `sector_meta_analysis` outputs to decide where a second pass is warranted. So the meta layer's signals (`contradictions`, `confidence`, `risk_flags`, `rotation_rank`) are produced but never consumed by a follow-up research step.

### Candidate shapes

Five distinct flavors. They are **not** interchangeable — different inputs, different outputs, different evaluation methods.

| ID | Shape | Picks | Output | Builds on |
|----|-------|-------|--------|-----------|
| A | **Smart Prioritizer** | A ticker | Ranked next-to-research queue + per-pick rationale | Q2 queue + `ticker_meta_analysis` + `signal_analysis` |
| B | **Topic / Theme Research** | A theme (e.g. "AI capex sustainability") | Topic memo + `theme` artifact + exposed-tickers list | New artifact; feeds `ticker_meta_analysis` bundle like sector prior |
| C | **Contradiction Drill-Down** | A ticker where `contradictions ≥ N` or `confidence < 0.5` | Deeper "why is this confusing" memo + updated stance | Closes the meta loop; second pass over richer inputs |
| D | **Hypothesis Loop** | A testable claim ("if X, then Y by Z") | `hypothesis` rows with falsification criteria | Foundation for Phase 4 outcome calibration |
| E | **Discovery Scout** | Tickers *outside* the watchlist that fit current themes | "Consider adding" candidates with rationale | Different from `opportunity_discovery` (static queries) — uses live regime + rotation rankings |

A and C are the lowest novelty / fastest to ship. B and D are the highest novelty but depend on input quality the most. E is the most product-facing.

### Why this is parked: input-data-quality is the actual gate

We can't pick a shape responsibly until we know whether the input corpus is rich enough to support it. **What we already know:**

- **Structured inputs are good.** `signal_analysis` (11k rows), `congress_trades` (29k), `insider_trades` (130k), Research `etf_holdings_log`, `social_metrics` / `social_posts`, plus the meta tables — these are well-typed, fresh, and reliable. Any shape that synthesizes from structured inputs (A, C, parts of D, E) starts on solid ground.
- **Text inputs are mixed.** `research_articles` is fed by SearXNG + RSS + scraping + email ingest. SearXNG result diversity is bounded by the engines it queries; scraping is bounded by `research_domain_health` auto-blacklisting; email is bounded by which newsletters subscribe. Article *coverage* of any specific theme/ticker on a given day can range from rich (mega-caps, hot themes) to empty (micro-caps, off-cycle weeks).
- **Existing AI synthesis works on this.** `ticker_meta_analysis` and `sector_meta_analysis` already consume this corpus and produce stances. So the corpus is "good enough" for synthesis-style jobs (C, A) — the open question is whether it's good enough for **theme tracking** (B), **discovery** (E), and **hypothesis verification** (D).

### Cheap learns before committing to a shape

These are SQL/log-only investigations, no new code. None should take more than ~30 minutes. **Do these before picking A–E**, not as part of building it:

1. **Article supply audit:** `research_articles` by `article_type`, `source domain`, and age — how many distinct domains per day, what's the age distribution, what fraction of `ETF Analysis` rows have null `sector`, what's the median articles-per-ticker over 30 days.
2. **Domain health snapshot:** `research_domain_health` — which domains are auto-blacklisted, which are flaky. Indicates what extra work scraping reliability needs before themes can rely on broad domain coverage.
3. **Theme-coverage stress test:** pick 5 *known* themes (rate cuts, AI capex, lithium, geopolitics, retail consumer) and grep `research_articles.title + content` for each over the last 30 days. If any theme returns < ~20 distinct articles from < ~5 distinct domains, shape B is premature.
4. **Contradiction supply check:** count `ticker_meta_analysis` rows where `contradictions ≥ 2` and `confidence < 0.5` over the last 14 days. If that bucket is consistently < ~10/day, shape C runs out of inputs fast and may not justify a dedicated job.
5. **Hypothesis-evaluable check:** for D, sample 10 hypotheses we *would* write today ("if Fed cuts 50bp, regional banks outperform XLF by 3% in 30d"). Do we have the data — benchmark series, rate decision dates — to actually score them in 30 days? If not, D is a writing exercise, not a feedback loop.
6. **Discovery target check:** for E, the Watchtower ETFs hold mostly large-caps; check how many holdings are *not* in our watchlist already. If the answer is "all the interesting ones already are," E becomes a watchlist-rotation feature, not a discovery feature.

### Decision rule

After the cheap learns:

- If structured inputs alone suffice → start with **A (Smart Prioritizer)** — lowest risk, immediate feedback loop with the queue.
- If theme-coverage stress test (#3) passes → **B (Theme Research)** is the bigger leverage; output also feeds the existing `ticker_meta_analysis` bundle.
- If contradiction supply (#4) is healthy → **C (Contradiction Drill-Down)** is the cleanest "closes the loop with what meta produces."
- D and E require additional infra investment beyond the picker job itself; defer until A/B/C produce real wins.

### Anti-patterns to avoid

- **Shipping a "smarter research" job whose output is another article corpus.** That's already what `market_research` / `alpha_research` do. The new value has to be a *new artifact type* (theme rows, hypothesis rows, drill-down memos) or a *queue rerouting decision*, not "more articles."
- **Promising LLM-driven discovery on text inputs we know are thin.** If the cheap learns show theme coverage is sparse for half our themes of interest, B will hallucinate confidently — worse than no job.
- **Building D before Phase 4.** Phase 4 (outcome calibration) is the natural home for hypothesis scoring; D without Phase 4 is hypotheses-with-no-grader.

## Operating guardrails

- **ETF holdings:** Research only — never read Supabase `etf_holdings_log` in production (dropped).
- **ETF Analysis sector invariant:** keep `research_articles.sector` populated for `article_type = 'ETF Analysis'`; see **Data foundation** under Phase 3.
- **Freshness:** after deploy/outage, run `backfill_etf_sector_meta.py` before judging Sector Insights quality.
- Keep additions additive with fallback defaults (`INSUFFICIENT_DATA`, empty bundles).
- Avoid increasing lock contention while introducing new jobs.
- Prefer phased rollout with observable metrics (SQL invariants, `job_executions`, gap scripts) at each layer.
- **New AI call sites:** route through `collect_with_summary_model_chain` unless documented otherwise.
- **Doc hygiene:** when changing pipeline stores or job order, update this file + [`docs/ETF_SECTOR_META_OPS.md`](ETF_SECTOR_META_OPS.md) + [`docs/ETF_AI_ANALYSIS_SYSTEM.md`](ETF_AI_ANALYSIS_SYSTEM.md) in the same PR when practical.
