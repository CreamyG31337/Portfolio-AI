# AI Task Queue Design

Backend-bound AI task queue and worker pool — replaces the coarse global AI lock for AI jobs that opt in via `AI_QUEUE_ENABLED=true` + `AI_QUEUE_JOBS=...`. The legacy inline path remains the default for any job not listed.

## Status (2026-05-23)

| Phase | Scope | Status |
|-------|-------|--------|
| Phase 0 | Design contract (this document) | ✅ |
| **Q1** | `ai_task_queue` schema + lease/finalize RPCs + embedded worker pool gated by `AI_QUEUE_ENABLED` | ✅ shipped |
| **Q2** | Migrate `ticker_analysis` to per-ticker queue tasks | ✅ shipped 2026-05-20; verified end-to-end across `ollama_primary`, `ollama_secondary`, and `glm` workers on 2026-05-21 |
| **Q3** | Retire global mutex for queue-managed jobs (other AI jobs no longer block them) | ✅ shipped 2026-05-23 — `is_queue_managed_job()` helper in `utils/job_tracking.py`; `get_running_ai_job()` short-circuits to None for queue-managed jobs; `run_scheduler_job_once.py` logs ignored `--wait-ai-lock` / `--ignore-ai-lock` flags for queue-managed jobs |
| **Q4** | Migrate more AI jobs to the queue: `ticker_meta_analysis`, `sector_meta_analysis`, `etf_group_analysis`, `market_daily_brief`, `ui_ai_summaries`, `action_queue_ai_review` | ⏳ open — each migration is its own observable rollout. **Now Q3 has shipped, each Q4 migration is a one-env-var change** (`AI_QUEUE_JOBS=ticker_analysis,<new_job>`) — no scheduler-side call-site changes needed; the queue-managed bypass auto-applies. |

Phases here used to be numbered "Phase 1–4". Renamed to **Q1–Q4** so cross-doc discussion is unambiguous (e.g. "queue Q3" vs `meta_analysis_roadmap.md`'s "Phase 3").

## Related docs

- [`docs/meta_analysis_roadmap.md`](meta_analysis_roadmap.md) — product layers (market → sector → ticker meta) that the queue powers. Q4 migrations directly reduce AI-lock contention seen by meta jobs.
- [`AGENTS.md`](../AGENTS.md) — "Meta Analysis (market → sector → ticker)" pointer block.

## Why

The current AI job execution model serializes too much work. It protects limited LLM capacity, but it does that with a global mutex that cannot represent the capacity we actually have: two Ollama hosts plus GLM.

Today there are three layers:

1. `utils/job_tracking.py` treats every name in `AI_JOB_NAMES` as mutually exclusive through `get_running_ai_job()`. One slow job can block all other AI jobs until its stale-lock window expires.
2. `web_dashboard/ollama_client.py` also has per-host semaphores using `OLLAMA_MAX_CONCURRENT_PER_HOST`. These are useful, but they are process-local protection, not a scheduler-wide queue.
3. `collect_with_summary_model_chain()` tries models sequentially in one caller thread. That is good fallback behavior for a single request, but it does not distribute independent ticker tasks across available backends.

The result is that a long `ticker_analysis` run can keep GLM, Ollama primary, and Ollama secondary effectively idle as a group, even if only one backend is truly busy.

## Goals And Non-Goals

Goals:

- Run multiple independent AI tasks concurrently, bounded by configured backend capacity.
- Bind workers to backends so GLM failures do not block Ollama work, and vice versa.
- Support manual and scheduled runs coexisting through the same queue.
- Use per-ticker tasks for `ticker_analysis` so retries are small and observable.
- Preserve AI audit logging for every LLM attempt.
- Replace silent skips with queue state: pending, leased, done, failed, cancelled.

Non-goals for the first implementation:

- Rewriting every AI job at once.
- Removing `job_executions`; it remains useful as a job audit/status surface.
- Replacing `AISkipListManager`; it remains the owner of permanent ticker skip policy.
- Supporting arbitrary multi-container scaling before the lease RPC is proven in one scheduler process.

## Architecture

```mermaid
flowchart LR
  cron[CronTickerAnalysis] --> enqueuer[EnqueuePerTickerTasks]
  manual[ManualRun] --> enqueuer
  enqueuer --> queue[(ai_task_queue)]
  queue -->|"lease"| workerA[WorkerOllamaPrimary]
  queue -->|"lease"| workerB[WorkerOllamaSecondary]
  queue -->|"lease"| workerC[WorkerGlm]
  workerA --> service[TickerAnalysisService]
  workerB --> service
  workerC --> service
  service --> audit[(AIAuditJSONL)]
  service -->|"success"| done[MarkDone]
  service -->|"transientFailure"| release[ReleaseForRetry]
  service -->|"permanentFailure"| failed[MarkFailed]
  release --> queue
  done --> queue
  failed --> skipList[AISkipListManager]
```

The scheduler becomes an enqueuer for queue-managed jobs. Workers become the only code path that performs LLM work for those jobs.

For `ticker_analysis`, the first migrated job, the scheduler should:

1. Select tickers using the existing `TickerAnalysisService.get_tickers_to_analyze()` policy.
2. Insert or update one `ai_task_queue` row per ticker.
3. Mark the top-level `job_executions` row as "enqueued N tasks" rather than "holding the AI lock".

The worker pool should:

1. Lease one eligible task atomically.
2. Heartbeat the lease while the task is running.
3. Execute the task on its configured backend.
4. Mark success, release for retry, or mark failed based on error classification.

## Queue Table Sketch

The new table should be separate from `ai_analysis_queue`. The existing table has a narrower shape and a uniqueness model for pending analysis requests, not leased worker tasks.

```sql
CREATE TABLE ai_task_queue (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  analysis_type VARCHAR(40) NOT NULL,
  target_key VARCHAR(100) NOT NULL,
  payload JSONB,
  priority INTEGER NOT NULL DEFAULT 0,
  status VARCHAR(20) NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  last_error TEXT,
  last_error_class VARCHAR(40),
  leased_by VARCHAR(120),
  leased_backend VARCHAR(40),
  leased_until TIMESTAMPTZ,
  available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  enqueued_by VARCHAR(40),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE INDEX ai_task_queue_pending_idx
  ON ai_task_queue (status, priority DESC, created_at)
  WHERE status = 'pending';

CREATE INDEX ai_task_queue_lease_recovery_idx
  ON ai_task_queue (status, leased_until)
  WHERE status = 'leased';

CREATE UNIQUE INDEX ai_task_queue_active_dedupe_idx
  ON ai_task_queue (analysis_type, target_key)
  WHERE status IN ('pending', 'leased');
```

Expected statuses:

- `pending`: available for lease.
- `leased`: assigned to a worker until `leased_until`.
- `done`: completed successfully.
- `failed`: terminal failure.
- `cancelled`: intentionally removed from work.

Q1 added a Postgres RPC for atomic leasing (`lease_ai_task`). The RPC uses `FOR UPDATE SKIP LOCKED` so multiple workers cannot lease the same row.

## Worker Lifecycle

Worker loop:

```text
while running:
    task = lease_one_task(backend, lease_ttl)
    if task is None:
        sleep(idle_poll_seconds)
        continue

    set_audit_context(task_id=task.id, backend=backend)
    start_heartbeat(task.id)

    try:
        run_task(task, backend)
        mark_done(task.id)
    except Exception as exc:
        error_class = classify_error(exc)
        handle_failure(task, error_class, exc)
    finally:
        stop_heartbeat(task.id)
        clear_audit_context()
```

Lease behavior:

- Default lease TTL: 90 seconds.
- Default heartbeat interval: 30 seconds.
- A worker crash naturally stops heartbeats; another worker can reclaim the row after `leased_until`.
- A worker should only finalize a task it still owns.
- A worker id should include process id, thread name, backend, and host where possible.

The worker should not hold or check the global AI lock. Capacity is controlled by worker counts and backend-specific limits.

## Backend Binding

Workers are backend-bound. A worker assigned to `ollama_primary` should call only the primary Ollama host. A worker assigned to `ollama_secondary` should call only the secondary Ollama host. A worker assigned to `glm` should call only GLM.

This avoids a worker starting on GLM and then consuming Ollama capacity inside a fallback chain. Cross-backend fallback happens by releasing the task back to the queue and letting another backend's worker pick it up.

Backend names:

- `ollama_primary`
- `ollama_secondary`
- `glm`

Initial worker counts:

- `AI_QUEUE_WORKERS_OLLAMA_PRIMARY=1`
- `AI_QUEUE_WORKERS_OLLAMA_SECONDARY=1`
- `AI_QUEUE_WORKERS_GLM=3`

The Ollama semaphore in `ollama_client.py` remains useful as defense in depth. If it raises `OllamaHostBusyError`, the worker should classify that as `host_busy` and release the task rather than wait inside the worker thread.

## Fallback Rules

Fallback is rules-based by error class. Workers do not call other backends mid-task.

| Error class | Typical source | Queue action | Backend preference |
| --- | --- | --- | --- |
| `host_busy` | `OllamaHostBusyError` | Release without incrementing attempts | Prefer another backend |
| `timeout_ollama` | Ollama stream/read timeout | Release and increment attempts | Any backend |
| `timeout_glm` | Z.AI request timeout | Release and increment attempts | Prefer non-GLM |
| `model_not_found` | Ollama 404 or missing model | Release and increment attempts | Any other backend |
| `rate_limited` | HTTP 429 from GLM/Z.AI | Release with delayed retry | Any backend after backoff |
| `bad_json` | Non-empty invalid LLM JSON | Retry until max attempts, then failed | Any backend |
| `schema_violation` | Normalized LLM output cannot fit contract | Failed immediately | None |
| `delisted_or_not_found` | Market/data source says ticker is invalid | Failed immediately plus skip-list handling | None |
| `unknown` | Unclassified exception | Retry until max attempts, then failed | Any backend |

The classifier should live in code, not config, so it can be unit tested and changed with the implementation. Only `AISkipListManager` should create permanent skip-list entries.

## Configuration

Feature flags:

- `AI_QUEUE_ENABLED=false` was the default during Q1 plumbing. CI now sets `AI_QUEUE_ENABLED=true` + `AI_QUEUE_JOBS=ticker_analysis` for the Flask deploy (see `web_dashboard/.woodpecker.yml`).
- `AI_QUEUE_JOBS=ticker_analysis,...` controls which jobs route through the queue. Add a job here only after its handler is registered in `build_task_handlers()` (otherwise workers refuse to start for that job).

Worker and lease settings:

- `AI_QUEUE_WORKERS_OLLAMA_PRIMARY=1`
- `AI_QUEUE_WORKERS_OLLAMA_SECONDARY=1`
- `AI_QUEUE_WORKERS_GLM=3`
- `AI_QUEUE_LEASE_TTL_SEC=90`
- `AI_QUEUE_HEARTBEAT_SEC=30`
- `AI_QUEUE_POLL_IDLE_SEC=2`
- `AI_QUEUE_BACKOFF_BASE_SEC=30`
- `AI_QUEUE_MAX_ATTEMPTS=3`

Existing model settings remain in the existing model configuration and settings modules. The queue should decide which backend runs a task, not invent a new model registry.

## Migration Plan

### Q1: Queue Plumbing — ✅ shipped

- `ai_task_queue` schema and lease/finalize RPCs in place (`database/schema/supabase/functions/lease_ai_task.sql` etc.).
- Worker module: `web_dashboard/scheduler/ai_task_workers.py`.
- Workers start only when `AI_QUEUE_ENABLED=true` AND a registered handler exists for at least one entry in `AI_QUEUE_JOBS`.
- Legacy inline path remains for jobs not listed in `AI_QUEUE_JOBS`.
- Unit tests cover config parsing, start gating, lease RPC payloads, and fallback error classification (`tests/test_ai_task_workers.py`).

### Q2: Migrate `ticker_analysis` — ✅ shipped 2026-05-20

- `web_dashboard/scheduler/jobs_ticker_analysis.py` enqueues per-ticker tasks when queue mode is on; legacy inline loop still runs when off.
- Manual `ticker_analysis` runs enqueue work rather than skipping due to a global AI lock.
- Each LLM attempt writes one audit row that joins back to the queue task.
- Verified 2026-05-21: 5 freshly-reset tasks were leased and completed by all three backends (`ollama_primary`, `ollama_secondary`, `glm`) within ~2 minutes; the 04:00 UTC cron the next night enqueued 101/101 with 99 done / 2 model-level failures.

### Q3: Retire Global Mutex For Queue-Managed Jobs — ✅ shipped 2026-05-23

- Added `is_queue_managed_job(job_id)` in `utils/job_tracking.py`. It reads the same `AI_QUEUE_ENABLED` / `AI_QUEUE_JOBS` env vars the worker pool reads (`AIQueueConfig.from_env`), with byte-for-byte equivalent parsing enforced by `tests/test_job_tracking_queue_managed.py::test_is_queue_managed_job_matches_ai_queue_config`. This makes a single env var the only switch needed to opt a job into queue mode.
- `get_running_ai_job(exclude_job_name=...)` now short-circuits to `None` whenever `exclude_job_name` is queue-managed (Q3 bypass). The function gained an `ignore_for_queue_managed=True` keyword for callers that need raw lock state (admin UI). Every scheduler call site that already passes `exclude_job_name=job_id` (`jobs_ticker_analysis`, `jobs_alpha`, `jobs_research`, `jobs_social`, `jobs_signals`, `jobs_opportunity`, `jobs_congress`, `jobs_etf_analysis`, `jobs_newsletter`, `jobs_ticker_meta_analysis`, `jobs_sector_meta_analysis`, `jobs_dashboard_research`, `jobs_ui_ai_summaries`) inherits the bypass automatically when the matching job name is added to `AI_QUEUE_JOBS`.
- `web_dashboard/scripts/run_scheduler_job_once.py` now uses `is_queue_managed_job` as the primary detection path and logs an explicit "Ignoring `--wait-ai-lock`/`--ignore-ai-lock` for queue-managed job X" line when those flags are dropped, instead of silently no-op'ing them.
- Watchdog (`scheduler/jobs_watchdog.py`) is unaffected: it still clears stale `status='running'` rows in `job_executions` for non-queue jobs. Queue-managed jobs now finish their scheduler-side row in seconds (just enqueueing), so the stale-clear window is effectively never hit for them.
- Keep `get_running_ai_job()` (and `AI_JOB_NAMES`, `mark_job_started`, `mark_job_completed`) for legacy jobs until they migrate; the bypass is opt-in via env config.
- **Why this matters now:** on 2026-05-22 `alpha_research` hung for ~1h, holding the global AI lock; the 06:45 UTC `ticker_meta_analysis` cron saw the stale lock and skipped without writing a `job_executions` row. Q3 ensures that as soon as `ticker_meta_analysis` is added to `AI_QUEUE_JOBS` in Q4, that failure mode disappears for it. With only `ticker_analysis` currently in `AI_QUEUE_JOBS`, no production behavior changes for other jobs — the bypass becomes live for each job the moment its name is added to the env list.

### Q4: Migrate More AI Jobs — ⏳ open

Candidates after `ticker_analysis`:

- `ticker_meta_analysis`
- `sector_meta_analysis`
- `etf_group_analysis`
- `market_daily_brief`
- `ui_ai_summaries`
- `action_queue_ai_review`

Each migration is a separate rollout so queue behavior can be observed in production. Coordinate with `meta_analysis_roadmap.md`: migrating `ticker_meta_analysis` and `sector_meta_analysis` is the queue side of the same work the meta roadmap calls "lock-aware scheduling" under Later phases.

## What We Keep

- `job_executions` as a high-level status/audit table.
- `job_steps` for append-only progress breadcrumbs.
- `AISkipListManager` for permanent ticker skip policy.
- `collect_with_summary_model_chain()` for non-queue jobs and for any job where one request should still own its own fallback chain.
- `OLLAMA_MAX_CONCURRENT_PER_HOST` as process-local protection.
- AI audit JSONL logging and provider detection.

## What We Retire

For queue-managed jobs only (live since Q3, 2026-05-23):

- The global AI mutex semantics from `get_running_ai_job()`. The function returns `None` immediately when `exclude_job_name` is in `AI_QUEUE_JOBS` and `AI_QUEUE_ENABLED=true`. Pass `ignore_for_queue_managed=False` only when you intentionally want raw lock state (admin UI).
- The top-of-job "already running, skip" guard in `ticker_analysis` (handled by the queue's `ai_task_queue_active_dedupe_idx`).
- Long-running job rows as the source of truth for active AI work. `job_executions` is still written by the scheduler-side wrapper as an audit trail; for queue-managed jobs that row reflects only "enqueued N tasks" and completes in seconds.

Instead, `ai_task_queue` rows become the source of truth for what is pending, leased, failed, or complete.

## Open Questions

1. Should manual `force=True` delete or supersede an existing active queue row, or should it update that row's priority and payload?
2. Should we add a backend-level circuit breaker so GLM workers pause for several minutes after repeated 429/timeout failures?
3. Should queue status be shown in the existing Jobs page or a dedicated AI Queue page?
4. Should finished queue rows be retained forever, archived after N days, or compacted into aggregate task history?
5. Once the lease RPC uses `FOR UPDATE SKIP LOCKED`, can we safely run more than one scheduler process, or do we still want an explicit singleton scheduler?

## Future Model Candidates

Models worth evaluating as we add more queue-managed jobs. Not committed to a phase yet — track here so we don't lose them.

| Model          | Pull name       | Size  | Good for                           | Installed on  |
| -------------- | --------------- | ----- | ---------------------------------- | ------------- |
| Magistral Small | `magistral:24b` | 14 GB | Financial reasoning, deep analysis | ts-desktop    |
| GPT-OSS         | `gpt-oss:20b`   | 13 GB | JSON output, fast tool/agent calls | ts-desktop    |

When evaluating each, decide whether it slots in as:

- A drop-in replacement for an existing backend's model (e.g. `AI_QUEUE_MODEL_OLLAMA_SECONDARY`), or
- A new backend binding with its own worker pool entry (e.g. a `magistral` or `gptoss` backend), which would also require updating `model_for_backend` / `ollama_base_url_for_backend` and the worker count flags.

Practical checks before promoting either to a real backend:

- VRAM headroom on the host that will run it (24 GB 3090 fits both, but not concurrently with qwen3.6:27b).
- JSON-mode reliability against our ticker / sector / ETF schemas (run the audit comparison harness).
- Latency under realistic prompt sizes — Magistral's reasoning traces can be long; GPT-OSS is usually fast but verify on agent-style prompts.

## Q1 Plumbing Acceptance Criteria (historical — all met)

Q1 plumbing was considered done when all of the following held; left here as a record so future migrations (Q4) can mirror the same bar:

- `ai_task_queue` schema and lease/finalize RPCs exist in the clean Supabase schema and an idempotent migration.
- Embedded worker pool code exists behind `AI_QUEUE_ENABLED`.
- Workers do not start unless both queue jobs and concrete handlers are registered.
- `ticker_analysis` and other AI jobs still use their legacy execution path until a later migration phase changes them (now changed for `ticker_analysis` in Q2).
- Focused tests cover config parsing, start gating, lease RPC payloads, and fallback error classification.
