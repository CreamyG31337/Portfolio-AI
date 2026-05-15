# Meta Analysis Roadmap

This document tracks the multi-layer meta-analysis program and keeps the next phases explicit.

## Program Goals

- Build a coherent stack across market, sector, and ticker layers.
- Treat technical signals and curated research/news as first-class synthesis inputs.
- Standardize outputs for downstream UI, scheduling, and evaluation loops.

## Phase Status

- Phase 1 (Signal + News Fusion into Ticker Meta): `shipped — monitor output quality and lock/runtime behavior`
- Phase 2 (Market Meta Regime Normalization): `Phase 2a + 2b shipped — regime_json, regime_canonical API, dashboard panel, enum drift warnings — Phase 2c deferred (see below)`
- Phase 3 (Sector Meta Layer): `3a shipped (deploy fix landed 2026-05-14, awaiting frontend image rebuild); 3b sector_meta_analysis job is next; 3c/3d not started`
- Phase 4+ (Adaptive weights, scheduling, and UI explainability): `planned`

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
| Global AI lock | `utils/job_tracking.py` | One AI-heavy job at a time; stale `running` rows are cleaned by watchdog / lock helpers. |
| Embedded scheduler | `web_dashboard/app.py` + `web_dashboard/scheduler/scheduler_core.py` | Scheduler must start with the Flask process unless `DISABLE_SCHEDULER=true` or a separate scheduler mode is intentionally used. Duplicate starts are suppressed via locks/heartbeat inside `start_scheduler()`, not by skipping startup on `WERKZEUG_RUN_MAIN`. |
| Admin “Next run” | `get_all_jobs_status_batched()` in `scheduler_core.py` | When the web worker has no in-process scheduler, next run times are read from the `apscheduler_jobs` table so the Jobs UI stays truthful under multi-worker Gunicorn. |
| Heavy job staggering | `web_dashboard/scheduler/jobs.py` | Example nightly PT order: **ticker_analysis** ~21:00 → **alpha_research** 23:15 → **ticker_meta_analysis** 23:45 — reduces collisions with the global AI lock. **market_daily_brief** runs weekdays 17:45 ET after benchmark refresh cadence. |

### Manual verification

- `web_dashboard/scripts/run_scheduler_job_once.py` can trigger `ticker_meta_analysis`, `market_daily_brief`, `ui_ai_summaries`, etc., without waiting for cron.

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

### Status (as of 2026-05-14)

| Sub-phase | What | Status |
|-----------|------|--------|
| **3a** | Read-only `/sector_insights` Flask page listing recent ETF Analysis articles | **Shipped.** Deploy was silently broken 2026-05-12 → 2026-05-14: `web_dashboard/Dockerfile.frontend` dropped `COPY web_dashboard/tsconfig.json` during the npm→pnpm refactor (commit `4b6d9ad5`), so the frontend image build failed with `TS5058: The specified path does not exist: 'web_dashboard/tsconfig.json'` and stale assets shipped. Fixed in this session; the next frontend rebuild ships the page and sidebar link. |
| **3b** | `sector_meta_analysis` service + scheduler job + persistence + prompt (the actual sector synthesis) | **Shipped (2026-05-14).** Code: `web_dashboard/sector_meta_analysis_service.py`, `scheduler/jobs_sector_meta_analysis.py`, `sector_meta_normalization.py`, `ai_prompts.py` (`SECTOR_META_ANALYSIS_PROMPT`), research table `sector_meta_analysis`. ETF article **sector tagging** + backfill: `etf_article_sector_infer.py`, `scripts/backfill_etf_analysis_article_sectors.py`, `etf_group_analysis` save path. |
| **3c** | Ticker meta bundle and prompt consume the sector prior when rows exist | **Not started.** Depends on 3b. |
| **3d** | Optional polish: sector-tagged research aggregation, benchmark-relative ETF snapshots, swap `/sector_insights` UI to render rows from 3b | **Not started.** Optional after 3c. |

> **Fresh agent: start at Phase 3c** (ticker meta consumes sector prior) unless fixing 3b regressions. Phase 3a/3b code paths are live; extend deliberately.
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

- `research_articles.sector` was often **empty** for `article_type = 'ETF Analysis'` because `etf_group_analysis` did not set it and **`securities.sector` is frequently null for ETF tickers** (and sometimes the saved `tickers` list collapsed to a single symbol with no sector).
- Downstream **`sector_meta_analysis`** groups articles by `sector`; empty tags → everything lands in **`__UNTAGGED__`**, which weakens prompts and hides silent degradation.

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
- Sidebar link: emitted via `get_navigation_links()` in `web_dashboard/shared_navigation.py`; `get_navigation_context()` in `web_dashboard/app.py` forces `show=True` for `sector_insights` regardless of `v2_enabled` (Flask-only page, no Streamlit fallback).
- UI is **intentionally honest**: a banner labels the page a "Phase 3 stepping stone" and explicitly states this is *not* the `sector_meta` contract and *not* fed into ticker meta yet.

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
   - Add accessor in `web_dashboard/settings.py`: `is_meta_analysis_phase3_sector_enabled()` (mirror `is_meta_analysis_phase1_signal_fusion_enabled`).
   - Default **off** until 3 successful nightly runs prove stability in prod. Flip default to on in a follow-up commit only.
   - When off: job is a no-op, table stays empty, 3c sees no rows and skips the sector block — ticker meta must remain deterministic.

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

### Phase 3c — Ticker meta consumes the sector prior (after 3b)

**Scope:**

1. Extend the artifact bundle in `web_dashboard/meta_analysis_service.py` with a sector block, parallel to the existing market regime block, when a fresh `sector_meta_analysis` row exists for the ticker's primary sector.
2. Resolve ticker → sector via the same mapping `etf_group_analysis` / the ticker UI already use; do not invent a new mapping.
3. Update `TICKER_META_ANALYSIS_PROMPT` in `web_dashboard/ai_prompts.py` to treat `sector_stance` / `rotation_rank` / `news_pressure` as a first-class prior alongside the existing market regime block.
4. Reuse the `META_ANALYSIS_PHASE3_SECTOR` flag so 3b and 3c roll out and roll back together.

**Exit criteria for 3c:**

- Ticker meta still runs deterministically when no sector row is available (Phase 1 contract preserved).
- When rows exist, spot-check 5–10 QA tickers show the sector prior surfacing in `key_drivers` or `contradictions` where appropriate.
- No regression in `ticker_meta_analysis` success rate over 3 nights.

---

### Phase 3d — Optional polish (after 3c)

Optional; do these only when 3b + 3c are producing useful output:

- Sector-tagged research aggregation (research DB sector tags) as an additional input to `sector_meta_analysis`.
- Benchmark-relative ETF snapshots as a structured input vs. extracting them from articles.
- Replace `/sector_insights` UI to render `sector_meta_analysis` rows (with the existing article list as a fallback when rows are missing); drop the "stepping stone" banner once rows are the primary source.

---

## Later Phases (Iterative)

Near term (recommended order):

1. **Phase 2c (when scheduled):** Newsletters, fund digests, and email digests consuming **`regime_canonical`** — see **Phase 2c — explicitly deferred** above. **Phase 2c+** remains realized-vol enrichment and other items called out there.
2. **Phase 3:** Add `sector_meta_analysis` job and sector prior block in the ticker meta prompt; keep ETF/sentiment sources read-only until the contract is stable.
3. **Quality loop:** Light-weight eval set (10–20 tickers) with expected fields (`stance`, `contradictions`, `risk_flags`) and regression checks after prompt or model changes.
4. **Lock-aware scheduling:** If meta runtime grows, consider splitting meta by fund or batching with backoff instead of parallel AI jobs (global lock will serialize anyway).

Longer horizon:

- Phase 4: Outcome feedback loop and per-source weighting calibration (trades/outcomes ↔ meta stance).
- Phase 5: Adaptive scheduling by backlog, runtime telemetry, and lock wait time (not only wall-clock cron).
- Phase 6: Layered explainability in UI surfaces (why this stance, which inputs conflicted).

## Operating Guardrails

- **ETF Analysis sector invariant:** keep `research_articles.sector` populated for `article_type = 'ETF Analysis'` (resolver + optional backfill); see **Data foundation (ETF Analysis → sector meta)** under Phase 3. Nightly `sector_meta_analysis` quality tracks this.
- Keep additions additive with fallback defaults.
- Avoid increasing lock contention while introducing new jobs.
- Prefer phased rollout with observable metrics at each layer.
- **New AI call sites:** route through `collect_with_summary_model_chain` (or a thin wrapper with a documented exception) so host failover and model ordering stay consistent with meta and dashboard jobs.
