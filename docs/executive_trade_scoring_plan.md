# Executive Trade Conflict Scoring (Follow-up Plan)

Status: Proposed. Follow-up to the executive-trades ingest feature (commit `cb1d4746`).

## Problem

Executive-branch trades (Trump, `chamber='Executive'`) now flow into `congress_trades`
and are picked up by the existing `analyze_congress_trades_job`. That scorer's entire
conflict signal is **committee jurisdiction overlap**:

- `analyze_congress_trades_batch.py` calls `get_committee_context()` and
  `prefetch_politician_committees()`, then prompts the LLM with
  `Committee Assignments: {committees}` (see lines ~52, ~193, ~202-217).
- The president has **no committee assignments**, so `prefetch_politician_committees`
  returns `Unknown (politician not found ...)` and every executive trade scores on a
  degenerate prompt. Scores will be noise, not signal.

The conflict model for an executive is fundamentally different from a legislator:
a president influences markets via executive orders, tariffs, agency appointments,
federal contracts, and sector-wide policy — not committee votes.

## Goal

Produce a meaningful `conflict_score` (0.0-1.0) for executive trades using an
executive-appropriate rubric, without regressing the congress path.

## Approach

### 1. Branch the scorer by chamber

In `analyze_congress_trades_batch.py`, detect `chamber == 'Executive'` when building
the trade context and route to a separate prompt builder
(`build_executive_conflict_prompt`) instead of the committee-based one. Everything
else (batching, `sync_supabase_conflict_score`, low-risk ETF/bond skip, Supabase
mirror) is reused unchanged.

### 2. Executive conflict rubric (replaces committee overlap)

Prompt the LLM to weigh executive-specific levers instead of committee jurisdiction:

- **Policy control**: Does the executive branch directly regulate/subsidize/tariff
  this company's sector? (energy, defense, pharma, semis, banks, crypto)
- **Federal contracting**: Is the issuer a major federal contractor?
- **Timing vs policy events**: Trade date near a known EO / tariff / appointment
  affecting the sector (v2 — needs an events source; v1 can rely on the model's
  general knowledge with lower confidence).
- **Direct mention/action**: Company or sector named in recent executive actions.

Store the same JSON shape (`conflict_score`, `confidence_score`, `reasoning`) so no
schema or downstream change is needed.

### 3. Sector enrichment (reuse)

Executive scoring leans heavily on sector. The batch script already enriches from
the `securities` table (`_sector_cache`). Ensure resolved executive tickers have
sector populated; if missing, fall back to a yfinance sector fetch during backfill
(the resolver already touches yfinance).

### 4. Optional v2 — executive actions context table

Add `executive_actions` (date, type, sector_tags, summary) populated from a public
EO/tariff feed, and inject matching actions into the prompt by trade date + sector.
Deferred until v1 rubric proves useful.

## Files to touch

- `web_dashboard/scripts/analyze_congress_trades_batch.py` — chamber branch +
  `build_executive_conflict_prompt`, skip committee prefetch for Executive.
- `web_dashboard/scheduler/jobs_congress.py` — no change (already reused).
- `tests/` — add `test_executive_conflict_scoring.py`: Executive trade routes to the
  executive prompt (no committee lookup), congress trade unchanged.

## Non-goals

- No change to ingest/resolver (already shipped).
- No new job — reuse `analyze_congress_trades` schedule.
- No auto-trading; scores are advisory only.

## Rollout

1. Land chamber-branch scorer + tests.
2. Re-run analysis over executive rows only (they'll have `conflict_score IS NULL`
   after backfill): `analyze_congress_trades_batch.py` picks them up automatically.
3. Spot-check a sample of scored executive trades for sane reasoning.
