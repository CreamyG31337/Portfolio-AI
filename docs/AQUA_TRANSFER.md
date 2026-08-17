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
| `research_articles.available_at` | Immutable first-known | Set once on insert; **never** updated on `ON CONFLICT`. Analysis lookbacks use `COALESCE(available_at, fetched_at)`, not `published_at`. |
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

Insights thesis evaluation stays a **narrative** check vs saved research. Price scoring stays in `stance_outcomes`.

### 3. Honest scoring (costs + N)

- Cost model: `web_dashboard/microcap_cost_model.py` (ADV / market-cap buckets → 50 / 150 / 300 bps round-trip)
- `stance_outcomes` columns: `cost_bps`, `excess_after_cost` (directional after haircut), `belief_status` (`supported`|`refuted`|`inconclusive`)
- Track record: `by_mechanism`, `candidates_tested`, `expected_false_positives_alpha_05`; hit rates prefer after-cost belief
- Meta bundle prior stance injects **matured** mechanism win/loss only — never in-flight trophies

Migration: `database/migrations/2026-08_add_stance_outcomes_cost_belief.sql`

```powershell
python web_dashboard/scripts/apply_stance_outcomes_cost_belief_migration.py --apply
```

## Success criteria (v1)

1. A 2024 story first ingested in 2026 cannot appear in a mid-2025 dossier lookback.
2. New AI stances carry a horizon and refutation rule (or the JSON gate rejects them).
3. Learn can report which **mechanisms** have edge after cost vs shuffled, with **N** attached.

## Later (Phase 4 — not started)

Optional `alpha_lab/` sealed operator registry (JSON AST only, no `eval()`, validation IC only, frozen test window, multiple-testing + this cost model). Do not couple to a Part II model loop.
