# Meta Analysis Roadmap

This document tracks the multi-layer meta-analysis program and keeps the next phases explicit.

## Program Goals

- Build a coherent stack across market, sector, and ticker layers.
- Treat technical signals and curated research/news as first-class synthesis inputs.
- Standardize outputs for downstream UI, scheduling, and evaluation loops.

## Phase Status

- Phase 1 (Signal + News Fusion into Ticker Meta): `code complete — rollout / validation`
- Phase 2 (Market Meta Regime Normalization): `planned`
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

## Phase 2: Market Meta Regime Normalization

### Goal

Convert market brief output into a reusable regime prior consumed by ticker synthesis.

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

- Phase 4: Outcome feedback loop and per-source weighting calibration.
- Phase 5: Adaptive scheduling by backlog/runtime/lock pressure.
- Phase 6: Layered explainability in UI surfaces.

## Operating Guardrails

- Keep additions additive with fallback defaults.
- Avoid increasing lock contention while introducing new jobs.
- Prefer phased rollout with observable metrics at each layer.
