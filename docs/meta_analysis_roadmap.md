# Meta Analysis Roadmap

This document tracks the multi-layer meta-analysis program and keeps the next phases explicit.

## Program Goals

- Build a coherent stack across market, sector, and ticker layers.
- Treat technical signals and curated research/news as first-class synthesis inputs.
- Standardize outputs for downstream UI, scheduling, and evaluation loops.

## Phase Status

- Phase 1 (Signal + News Fusion into Ticker Meta): `shipped — monitor output quality and lock/runtime behavior`
- Phase 2 (Market Meta Regime Normalization): `Phase 2a shipped — regime_json + bundle; 2b planned (UI/API rollups)`
- Phase 3 (Sector Meta Layer): `planned`
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

**Deferred (Phase 2b+):** dedicated regime-only API/UI, rollups consuming normalized fields everywhere, deterministic validation against benchmark-derived volatility proxies.

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

### Goal

Add sector-level rotation context that conditions ticker conviction.

### Proposed sector output contract

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
2. `sector_meta_analysis` (new)
3. `ticker_analysis`
4. `ticker_meta_analysis`

This ordering ensures ticker synthesis consumes both global and sector priors.

### Exit criteria

- Ticker meta prompt/input includes sector prior when available.
- Sector output is inspectable independently for debugging and QA.

---

## Later Phases (Iterative)

Near term (recommended order):

1. **Phase 2b:** Extend normalized regime consumption to UI summaries / APIs where helpful; optional tight schema validation for brief LLM output; contrast model-reported volatility with realized vol from benchmark series when we want fewer `UNKNOWN`s.
2. **Phase 3:** Add `sector_meta_analysis` job and sector prior block in the ticker meta prompt; keep ETF/sentiment sources read-only until the contract is stable.
3. **Quality loop:** Light-weight eval set (10–20 tickers) with expected fields (`stance`, `contradictions`, `risk_flags`) and regression checks after prompt or model changes.
4. **Lock-aware scheduling:** If meta runtime grows, consider splitting meta by fund or batching with backoff instead of parallel AI jobs (global lock will serialize anyway).

Longer horizon:

- Phase 4: Outcome feedback loop and per-source weighting calibration (trades/outcomes ↔ meta stance).
- Phase 5: Adaptive scheduling by backlog, runtime telemetry, and lock wait time (not only wall-clock cron).
- Phase 6: Layered explainability in UI surfaces (why this stance, which inputs conflicted).

## Operating Guardrails

- Keep additions additive with fallback defaults.
- Avoid increasing lock contention while introducing new jobs.
- Prefer phased rollout with observable metrics at each layer.
- **New AI call sites:** route through `collect_with_summary_model_chain` (or a thin wrapper with a documented exception) so host failover and model ordering stay consistent with meta and dashboard jobs.
