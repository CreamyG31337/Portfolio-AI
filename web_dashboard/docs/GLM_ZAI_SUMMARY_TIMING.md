# GLM / Z.AI article summarization — response timing and timeout

## Purpose

Operational notes for tuning `GLM_TIMEOUT` (HTTP read timeout on `api.z.ai` / Zhipu `chat/completions` used by article summarization and other GLM paths in `ollama_client.py`).

## How the numbers were measured (2026-04-27)

On production host, from rotated Flask logs inside `trading-dashboard-flask`:

- Paths: `/app/web_dashboard/logs/app.log`, `app.log.1`, `app.log.2`
- **Successful** calls: lines matching `Z.AI summary request completed in <N>s`
- **Timed out** calls: lines matching `Z.AI summary request timed out after <N>s`

Counts and simple aggregates were computed from those line patterns (not from application metrics DB).

## Snapshot results (same log slice as above)

| Class | Count | Avg (s) | Median (s) | p95 (s) | Min (s) | Max (s) |
|-------|------:|--------:|-----------:|--------:|--------:|--------:|
| Completed | 324 | 48.24 | 43.52 | 90.77 | 16.89 | 117.12 |
| Timed out | 27 | 120.34 | 120.34 | 120.41 | 120.20 | 120.51 |

Interpretation:

- Most completions finish well under the previous 120s ceiling (p95 ~91s).
- Observed timeouts sit at ~120s because they hit the **client read timeout**, not a natural completion.
- Failures in the same period often logged `All summary attempts failed across model chain: ['glm-4.7']` when no fallback model succeeded.

## Current configuration (code)

- **`GLM_TIMEOUT`**: environment variable; default **180** seconds (3 minutes) if unset.
- Used for:
  - `_generate_summary_via_zhipu` (article summarization via Z.AI)
  - `OllamaClient._query_glm` (GLM chat/completions from the shared client)

Override in `.env` / Docker env, e.g. `GLM_TIMEOUT=180`.

## Follow-up

Re-sample the same log patterns after a week of production traffic to see whether timeout count drops and whether p95 completion times approach the new ceiling. If timeouts cluster at 180s, the provider is still stalling and further changes should be fallback models, concurrency, or provider status—not only raising the cap.
