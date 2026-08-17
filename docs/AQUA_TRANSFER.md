# AQuA transfer: governance, not their model

This project steals research **governance** from [AQuA](https://arxiv.org/abs/2608.12841) (arXiv 2608.12841), not the paper’s trading model or Sharpe numbers.

## What we skipped

- **Part II** hybrid conv/attention model, GPU training, 30-minute US large-cap labels, 2 bps cost assumptions. Wrong universe, frequency, and costs for a daily micro-cap book.
- **Operator sandbox / formulaic factor mining** (`alpha_lab/`) — deferred until Learn has honest after-cost track record with N logged. On ~50–90 daily names, 0.03 ICs appear by chance constantly.
- Treating `alpha_research_job` as a factor miner (it remains SearXNG article collection).
- Auto-trading off discovered factors.
- A six-agent Manager clone.

## What we built (v1)

### 1. Point-in-time (`available_at`)

**PIT** = when asking “what did we know on date T?”, only use facts first known by T.

| Table | Clock | Notes |
|-------|--------|--------|
| `research_articles.available_at` | Immutable first-known | Set once on insert; **never** updated on `ON CONFLICT`. Analysis lookbacks use `COALESCE(available_at, fetched_at AT TIME ZONE 'UTC')`, not `published_at`. The explicit UTC cast is required: `available_at` is TIMESTAMPTZ while `fetched_at` is a naive TIMESTAMP, and a bare `COALESCE` reinterprets the naive value in the session TimeZone — shifting every lookback boundary by the server's UTC offset. One implementation, in `web_dashboard/pit_time.py`; `research_repository` delegates to it rather than building its own predicate. |
| `social_metrics.available_at` / `social_posts.available_at` | Same idea | Lookbacks honor analysis windows; social sentiment no longer ignores `start_date`. |

Migrations:

- `database/migrations/2026-08_add_research_articles_available_at.sql`
- `database/migrations/2026-08_add_social_available_at.sql`

Apply:

```powershell
python web_dashboard/scripts/apply_research_articles_available_at_migration.py --apply
python web_dashboard/scripts/apply_social_available_at_migration.py --apply
```

**Still open (documented, not fixed in v1):** late ticker assignment via `backfill_missing_tickers` can attach tickers after the fact without an `article_tickers(assigned_at)` junction. That remains a leakage channel until a follow-up.

### 2. Falsifiable proposals

LLM outputs for `ticker_analysis`, `ticker_meta_analysis`, and `analyze_congress_trades` must include hypothesis / mechanism / expected_direction / horizon_days (7|30|90) / falsification_criteria / expected_failure_modes.

- Skill: `web_dashboard/skills/falsifiable_proposal.md` (prompt injection)
- Gate: `web_dashboard/falsifiable_proposal.py` (validation — author/reviewer LLMs are not trusted)
- Persisted on `stance_history.metadata.falsifiable_proposal` (including `mechanism_key`)

`mechanism_key` comes from a **closed vocabulary** (`MECHANISM_CATEGORIES`), not from the prose `mechanism` field. Slugifying free text gave every call its own bucket — two phrasings of one idea hash differently — so `by_mechanism` could only ever hold `n=1` rows with a hit rate of 0.0 or 1.0, making success criterion 3 unreachable by construction. The model picks one category; anything unrecognised collapses to `other` so cardinality stays bounded.

Insights thesis evaluation stays a **narrative** check vs saved research. Price scoring stays in `stance_outcomes`.

### 3. Honest scoring (costs + N)

- Cost model: `web_dashboard/microcap_cost_model.py` (ADV / market-cap buckets → 50 / 150 / 300 bps round-trip)
- `stance_outcomes` columns: `cost_bps`, `excess_after_cost` (directional after haircut), `belief_status` (`supported`|`refuted`|`inconclusive`)
- Track record: `by_mechanism`, `candidates_tested`, `expected_false_positives_alpha_05`; hit rates prefer after-cost belief
- Meta bundle prior stance injects **matured** mechanism win/loss only — never in-flight trophies

**Unknown liquidity is not a cost of 300 bps.** `round_trip_cost_bps` returns `None`
when neither ADV nor market cap is available (there is no ADV column on `securities`,
so a missing `market_cap` means no verdict). The row is stored with NULL cost columns
and `belief_status = 'inconclusive'`, and the scorer's upsert fills the verdict in on a
later run once the reference data lands — previously a missing `securities` row
manufactured a 3.0 pp haircut, and `ON CONFLICT DO NOTHING` froze the resulting false
refutation permanently. The job log reports `cost_unknown=N`.

**Baselines are haircut too.** `compute_baselines` takes each row's `cost_bps` and
scores every null model under the same rule as the actual rate: re-sign the raw excess
under the reassigned label, subtract that row's haircut, drop the row when the result
lands inside the ±0.25 pp inconclusive band. Without this the actual rate is after-cost
while the nulls are pre-cost, and `edge_vs_shuffled` goes structurally negative on any
book whose typical excess is smaller than its trading costs — reporting a units
mismatch as destroyed skill.

**`excess_metric` describes what was actually computed.** It reads
`directional_after_cost` only when at least one row carried a haircut, and
`directional` otherwise; `after_cost_coverage` reports how many scored rows predate
the cost columns. Pre-cost aggregates are never published under an after-cost label.

Migration: `database/migrations/2026-08_add_stance_outcomes_cost_belief.sql`

```powershell
python web_dashboard/scripts/apply_stance_outcomes_cost_belief_migration.py --apply
```

## Success criteria (v1)

1. A 2024 story first ingested in 2026 cannot appear in a mid-2025 dossier lookback.
2. New AI stances carry a horizon and refutation rule (or the JSON gate rejects them).
3. Learn can report which **mechanisms** have edge after cost vs shuffled, with **N** attached.

## Known limits (v1)

- **Backfilled `available_at` is an upper bound, not a measurement.** Pre-migration
  rows got `available_at = fetched_at`, and the old `save_article` bumped `fetched_at`
  on every re-scrape, so a story first seen in 2024 and re-scraped in 2026 carries a
  2026 first-known time and drops out of 2024–2025 lookbacks. This errs *late* on
  purpose: pulling the value back toward `published_at` would let a story appear in a
  window during which the system demonstrably did not have it, which is lookahead —
  strictly worse than losing history. `available_at_is_estimated` marks the affected
  rows so the two cases stay distinguishable.
- **`STRONG_BULLISH` / `STRONG_BEARISH` are never scored.** `ai_prompts` emits them,
  but they are absent from `stance_history.DIRECTIONAL_STANCES`, which gates the
  scoreable filter in `jobs_stance_outcomes` — so the model's highest-conviction calls
  never enter the ledger at all. Pre-existing, not introduced here; adding them changes
  what gets scored and is a product decision rather than a cleanup.
- **`by_mechanism` needs history before it means anything.** Every stance predating
  this work buckets as `unspecified` and is reported separately, deliberately excluded
  from the mechanism block injected into the meta prompt. Criterion 3 is reachable in
  principle but not answerable until enough proposals have matured.

## Later (Phase 4 — not started)

Optional `alpha_lab/` sealed operator registry (JSON AST only, no `eval()`, validation IC only, frozen test window, multiple-testing + this cost model). Do not couple to a Part II model loop.
