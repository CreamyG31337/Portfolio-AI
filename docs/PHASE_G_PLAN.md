# Phase G Plan — Provenance, Filings, and Confluence

**Audience: a coding agent (Cursor plan mode).** This is the detailed implementation brief for
Phase G of [`docs/ROADMAP.md`](ROADMAP.md) (the master plan — read it first, especially its
Guardrails). Created 2026-06-11 after Phases A–F shipped. Run this through plan mode: several
items contain explicit **RESEARCH** tasks where you must investigate and propose an approach
before writing code. Improve this plan where the codebase contradicts it — and update this doc
and ROADMAP.md as items land.

**Verified against codebase 2026-06-11; re-reviewed 2026-06-13** (fixed a scheduling defect —
G2 and G4 were both pointed at "22:30 ET", which collides and ignores that G4 consumes G2's
output; the file also mixes ET/PT triggers). Key corrections baked in below:
- G1: `_fetch_article_snippets` is at line 178 (not ~498); `build_artifact_bundle` already
  returns `tuple[str, dict | None]`; save path is `_save_meta`, not `save_ticker_meta`; article
  `id` is not in the current SELECT.
- G2: extract/reuse the throttled SEC client from `sec_form4_poc.py`; `filing_events` lives in
  Research DB; evidence-timeline reads via `PostgresClient` (not Supabase). **Scheduling: the
  codebase mixes `America/New_York` and `America/Los_Angeles` triggers — convert to one TZ and
  check `jobs.py` `cron_triggers` before picking a slot. G2 and G4 must NOT share a slot (G4
  reads G2's `filing_events`); run G2 earlier than G4. 22:15 ET is already taken (line 474 =
  19:15 PT).**
- G3: `insider_trades` unique key confirmed; no `source` column yet; `docs/research/` does not
  exist — create it for G3a.
- G4: social spike must be computed on the fly; signals come from Supabase `signal_analysis`
  JSON (not in-memory `web_dashboard/signals/` evaluators).
- G5: send via `mailgun_outbound.send_mailgun_message` (not `jobs_newsletter.py`, which is
  inbound AI processing); recipients from admin/env list (`RETRO_DIGEST_RECIPIENTS`).

## Why these items, in one paragraph

The Learn layer (stance ledger + outcome scoring) went live 2026-06-11. First 7-day outcome
scores land ~2026-06-18; track-record/calibration becomes meaningful ~2026-07-10. Phase G does
three things while that data matures: (1) fixes a provenance gap that gets worse every day it
exists — stances don't record which articles fed them, so the planned "which sources earn their
keep" analysis is impossible; (2) fills the two biggest data blind spots for a micro-cap book —
real EDGAR filing alerts (dilution, late filings, delisting, activists) and Canadian (SEDI)
insider coverage for the many `.TO` holdings that the current US-only Form 4 pipeline cannot
see; (3) adds one cheap synthesis job — cross-signal confluence — that consumes everything
already built without a single new LLM call.

## Hard rules (non-negotiable)

- **No autonomous trading.** Outputs are advisory artifacts a human reads. Ever.
- **Additive schema only.** New tables/columns with fallbacks; never repurpose existing
  UPSERT semantics. Match the migration style in `database/migrations/`.
- **Holdings-scoped jobs must filter funds by `funds.is_production = true`.** The test suite
  writes TEST_* funds with fixture positions into prod Supabase (see ROADMAP "Post-ship
  verification 2026-06-11"). Any job that enumerates positions without this filter will burn
  cycles on fake tickers. Follow the pattern in
  `web_dashboard/ticker_analysis_service.py::get_tickers_to_analyze()` (unfiltered fallback if
  the funds lookup fails).
- **Supabase REST caps at 1000 rows per request** regardless of `.limit()`. Paginate with
  `.range()` (pattern: `web_dashboard/insider_clusters_service.py::fetch_recent_insider_buys`).
- **SEC fair-access policy:** declared `User-Agent` header with contact email, ≤ 10 req/s,
  back off on 429/403. One polite shared HTTP helper, not per-call-site headers — extract from
  `web_dashboard/scheduler/sec_form4_poc.py` (see G2).
- **Scraping ToS:** if a source (SEDI, any third-party mirror) has unclear terms, write the
  feasibility memo and STOP for a human decision. Do not route around blocks.
- **No new LLM call sites** in this phase except where marked optional — and those go through
  `collect_with_summary_model_chain` + the AI task queue.
- Flask is production; Streamlit is prototype-only. Edit TypeScript in
  `web_dashboard/src/js/`, never `static/js/`. Don't touch `verification/`.
- Tests green before each item is declared done: `python -m pytest tests/test_flask_*.py -v`
  for Flask changes, `-k "not flask"` for core. Windows + PowerShell, venv at `.\venv`.

---

## G1 — Stance evidence provenance (P0 — do this first)

**Why:** `stance_history` rows record a `source_ref_id` (the meta-analysis row) and an
`artifact_bundle_digest` (a hash), but **not the IDs of the research articles inside the
bundle**. Every stance written without evidence IDs is permanently unattributable — the
Learn→Collect feedback loop (ROADMAP's dashed arrow, the source-ROI report) cannot be built on
them. This compounds daily; ship it before anything else.

**What to build:**
1. In `web_dashboard/meta_analysis_service.py`, `build_artifact_bundle(ticker)` (line 376)
   assembles the prompt text from snapshots + `_fetch_article_snippets(ticker)` (called at
   line 498; the function itself is at **line 178**). It **already returns**
   `tuple[str, dict[str, Any] | None]` (bundle text + primary standard-analysis row). Refactor
   to also return a structured evidence manifest — either as a **third tuple element** or as a
   key on a new return dict — e.g.
   `{"article_ids": [...], "artifact_types": ["social", "congress", "signals", ...]}` —
   whatever artifact families actually went into the bundle. **Do not break existing 2-tuple
   unpack sites** without updating all callers.
2. Thread the manifest through `_save_meta(...)` (line 630; there is no `save_ticker_meta`) into
   the existing `record_stance_safe(..., metadata={...})` call (line 716): add an `"evidence"`
   key to the metadata jsonb alongside the existing `contradictions_count` and
   `artifact_bundle_digest` keys. **No schema change needed** — `stance_history.metadata`
   exists; `record_stance_safe` in `web_dashboard/stance_history.py` serializes metadata via
   `json.dumps` into the jsonb column.
3. Do the same for the `ticker_analysis` hook in `web_dashboard/ticker_analysis_service.py`
   (`record_stance_safe` call at **line 1249**; currently passes `sentiment`/`sentiment_score`
   in metadata). Record which inputs were present: price data, signals, fundamentals — there may
   be no articles there; record what's true.
4. Extend `web_dashboard/scripts/verify_stance_pipeline.py` to report the % of last-24h
   stances carrying `metadata->'evidence'`.

**RESEARCH (before coding):** read `build_artifact_bundle` end to end and enumerate what is
actually in the bundle per artifact family; the manifest shape should mirror reality, not this
sketch. `_fetch_article_snippets` (line 178) currently selects
`title, conclusion, sentiment, sentiment_score, published_at, fetched_at` — **it does not
include `id`**. Add `id` to the SELECT before building `article_ids`.

**Acceptance:** new meta/analysis stances carry evidence in metadata; unit tests assert the
manifest passes through (extend `tests/test_stance_history.py` patterns — note that existing
tests call `record_stance` directly with `MagicMock` Postgres and **do not yet assert metadata
serialization**; add that); verify script shows coverage; no behavior change to the prompt text
itself (digest stability — compare digests before/after on an unchanged bundle).
**Size:** S (≈1 day).

## G2 — Real EDGAR filing watch (replaces the §4.1 placeholder)

**Why:** dilution is the #1 micro-cap killer; the current
`web_dashboard/scheduler/jobs_dilution_watch.py` is an honest placeholder (enumerates scope,
calls nothing). The same plumbing also catches late filings, delisting notices, and activist
stakes nearly for free.

**What to build:**
1. **Shared SEC HTTP helper:** extract/reuse the throttled client from
   `web_dashboard/scheduler/sec_form4_poc.py` — it already has `DEFAULT_USER_AGENT`,
   `SEC_EDGAR_USER_AGENT` env override, ~9 req/s global rate limiter, and retry/backoff on
   503/502/429. Generalize it for `company_tickers.json` and `data.sec.gov/submissions/...`
   endpoints; do not write a fresh per-call-site client.
2. **Ticker→CIK map:** SEC publishes `https://www.sec.gov/files/company_tickers.json`.
   Refresh weekly, cache locally (small table or file). US tickers only — route `.TO`/`.V`
   tickers to G3's scope instead of silently failing.
3. **Per-CIK filing poll:** `https://data.sec.gov/submissions/CIK{cik:010d}.json` lists recent
   filings with form types and dates. For each production-fund holding + active watchlist
   ticker, flag new filings in these classes:
   - **Dilution / structure:** S-1, S-3, 424B5, S-8 (large), EFFECT; reverse split via 8-K
   - **Distress:** NT 10-Q, NT 10-K (late filings); 8-K Item 3.01 (listing deficiency)
   - **Delisting:** Form 25 / 25-NSE
   - **Activist / accumulation (positive):** SC 13D, SC 13G and amendments
4. **Storage:** new **Research-DB** table `filing_events` (append-only; migration file +
   `database/schema/research/tables/filing_events.sql`; wire via `\i tables/...` in
   `_init_schema.sql`). Use `CREATE TABLE IF NOT EXISTS` style (match `stance_history.sql`,
   not the older `DROP ... CASCADE` pattern):
   `id, ticker, cik, form_type, category ('dilution'|'distress'|'delisting'|'activist'),
   direction ('risk'|'positive'|'neutral'), filed_at, accession_no UNIQUE, title, url,
   raw jsonb, created_at`.
5. **Job:** rewrite `dilution_watch_job` (keep `JOB_ID = "dilution_watch"` and the
   `mark_job_started/completed/failed` shape already there); nightly; no LLM. Current scope
   enumerates `latest_positions.ticker` + active `watched_tickers_v2.ticker`. `enabled_by_default`
   is **False** in `web_dashboard/scheduler/jobs.py` (config at line 216, currently a 6:30 AM ET
   trigger) — flip to True only once it reports real scans. **Scheduling:** this is independent
   and no-LLM, so Ollama contention is irrelevant; the only constraint is that it must produce
   `filing_events` **before** G4 confluence reads them the same day. The existing 6:30 AM ET slot
   works (filings from the morning poll are available to G4's evening run); keep it or pick
   another daytime ET slot — just don't collide with G4.
6. **Surfacing:** Today-screen block (risk events for held/watched tickers) +
   `filing` events merged into `GET /api/ticker/<ticker>/evidence-timeline`
   (`web_dashboard/routes/intelligence_routes.py`, line 203). This endpoint reads the **Research
   Postgres DB** via `PostgresClient` (not Supabase); it currently merges `stance` + `article`
   event types — add a third `event_type='filing'` from `filing_events`.

**RESEARCH:** (a) confirm the submissions-API JSON shape and how 8-K items are exposed
(item numbers live in the filing index, may need one extra fetch per 8-K — decide if V1 flags
all 8-Ks in scope or fetches items); (b) going-concern language detection in 10-K/Q via EDGAR
full-text search (`https://efts.sec.gov/LATEST/search-index?q=...`) — assess feasibility and,
if cheap, add as `category='distress'`; otherwise defer and say so in this doc.

**Acceptance:** job runs against prod scope without placeholder messaging; fixture-based unit
tests for classification + dedupe on `accession_no`; events visible on dossier timeline;
SEC fair-access rules observed (shared helper with User-Agent, throttle).
**Size:** M (2–4 days).

## G3 — Canadian insider coverage (SEDI) — research-first

**Why:** the book is heavily Canadian (`.TO`: DRX, GLO, GMIN, CCO, CNR, FTS, DOL, …) and the
insider pipeline is US Form 4 only — the insider-clusters feature (§4.2) is structurally blind
to half the portfolio. SEDI (sedi.ca) is the Canadian equivalent disclosure system.

**Deliverable 1 — feasibility memo (required):** create `docs/research/` (directory does not
exist yet) and write `docs/research/sedi_feasibility.md` covering: access options (SEDI's own
interface has no API and is notoriously hostile; third-party mirrors like canadianinsider.com
exist but check ToS), per-issuer query mechanics, transaction-code mapping to the existing
`Purchase`/`Sale` model, rate expectations, and a recommendation. **If every viable path
violates ToS or requires paid data, stop there** — the memo is the deliverable; a human decides.

**Deliverable 2 — prototype (only if memo finds a clean path):** weekly scan scoped to
`.TO`/`.V` production-fund holdings + watchlist. Store into the existing Supabase
`insider_trades` table.

**Schema (verified):** unique index `insider_trades_unique_key` on
`(ticker, insider_name, transaction_date, type, shares, price_per_share)` — **confirmed** in
`database/schema/supabase/tables/insider_trades.sql`. The upsert conflict target in
`web_dashboard/scheduler/jobs_insiders.py` matches this key. **No `source` column exists yet**
— add an additive `source` column (`'sec_form4'` default vs `'sedi'`) via migration so
provenance is queryable. Note: the pre-upsert duplicate check in `jobs_insiders.py` is
**narrower** than the unique key (only ticker/insider/date/type) — SEDI rows must not rely on
that check; trust the DB unique index + upsert instead.

`insider_clusters_service.py` is source-agnostic (queries all `Purchase` rows, no US-only filter)
and picks Canadian names up automatically — verify with a test using `.TO` fixture rows.

**Acceptance:** memo exists and is honest; if prototype ships: clusters include `.TO` tickers,
dedupe holds across re-scans, no ToS violations.
**Size:** memo S; pipeline M/L (genuinely uncertain — that's why memo first).

## G4 — Cross-signal confluence scorer (no LLM)

**Why:** many independent signal families now exist (stances/flips, insider clusters, congress
trades, social metrics, signals, liquidity, filing events once G2 lands) but nothing counts
coincidences. "Insider cluster + stance flip to BULLISH + volume breakout inside 10 days" is
the cheapest high-value synthesis left, and its outputs become scoreable predictions.

**What to build:**
1. New nightly job `web_dashboard/scheduler/jobs_confluence.py` (follow the
   `jobs_stance_outcomes.py` registration + `utils/job_tracking` pattern). Window: last 10
   days, per ticker, families queried straight from existing tables/services:
   - stance flip to a directional stance (`today_briefing_service.fetch_stance_flips` —
     signature: `fetch_stance_flips(postgres, *, days=2, limit=20)`; reuse, don't fork the SQL;
     it is the single owner of flip detection)
   - insider cluster (`insider_clusters_service.build_insider_cluster_buys`)
   - congress buys (Supabase **view** `congress_trades_enriched` — columns include ticker,
     type, amount, transaction_date)
   - social attention spike — `social_metrics` (Research DB) has `volume`/`post_count`/
     `created_at` indexed `(ticker, created_at)` but **no persisted z-score/baseline**. Define
     "spike" as an on-the-fly computation (e.g. latest volume vs trailing mean/STDDEV over N
     days) or drop the family and say so in this doc; no existing query computes z-scores
   - signals breakout/uptrend — queryable artifact is Supabase `signal_analysis` (JSON columns
     `structure_signal` with `trend`/`breakout`/`pullback`, plus `overall_signal` and
     `confidence_score`), written by `jobs_signals.py`. The `web_dashboard/signals/*.py` modules
     are in-memory evaluators, not the persisted query surface
   - filing events (G2): `direction='positive'` (13D) counts bullish; `'risk'` counts bearish
2. Score = number of **distinct families** firing, direction-aware (bullish families and risk
   families tallied separately; a ticker can have both).
3. **Storage:** Research-DB `confluence_events` (append-only):
   `id, ticker, as_of, direction ('bullish'|'risk'), score INT, families jsonb, details jsonb,
   created_at` + dedupe rule (skip insert if same ticker/direction/families within the window
   already recorded — mirror the stance-history dedupe philosophy).
4. **Make it scoreable:** when `score >= 3` and direction is bullish, also call
   `record_stance_safe(source="confluence", stance="BULLISH", confidence=None,
   metadata={"families": [...]})` — `jobs_stance_outcomes.py` then scores confluence events
   against ^RUT like every other stance, for free. **Risk-direction events stay events only:**
   `jobs_stance_outcomes` filters to directional stances (`BUY`/`SELL`/`BULLISH`/`BEARISH`/…);
   `RISK` is explicitly non-directional and won't be scored (see ROADMAP §1.2).
5. **Surfacing:** Today-screen block (top confluence events since yesterday) + events merged
   into the dossier evidence timeline (Research Postgres, same pattern as G2 filing events).

**Acceptance:** fixture-based unit tests (families counted distinctly; direction split; dedupe;
stance written only at threshold); job registered **late evening ET, after `stance_outcomes`
(21:30 ET) and after G2's daytime filing poll** so it sees fresh inputs — e.g. ~22:30 ET, but
verify against `jobs.py` `cron_triggers` first (the file mixes ET and PT; 22:15 ET is taken) and
do not share G2's slot; Today block renders.
**Size:** M (2–3 days).

## G5 — Weekly retro → Mailgun (finish the hookup)

**Why:** `web_dashboard/scheduler/jobs_weekly_stance_retro.py` already computes flips +
track-record summary but only logs a one-line message (Sunday 17:00 ET). It already calls
`fetch_stance_flips(pg, days=7, limit=500)` and
`build_track_record_summary(pg, horizon_days=30)` (returns `hit_rate_by_source`,
`hit_rate_by_verdict`, `best_calls`, `worst_calls`, counts).

**What to build:** render the retro as a small HTML digest (stance flips of the week, hit rates
by source once `stance_outcomes` has rows, best/worst calls from
`track_record_service.build_track_record_summary`, confluence events once G4 lands) and send via
Mailgun.

**Send path (corrected):** `jobs_newsletter.py` is **inbound** newsletter AI processing, not
outbound sending. Reuse:
- `web_dashboard/mailgun_outbound.py::send_mailgun_message(to_email, subject, html_body, ...)`
  (requires `MAILGUN_API_KEY` + send domain from env/system settings)
- Reference `web_dashboard/outbound_newsletter_pipeline.py` for Mailgun config patterns

**Recipients (decided):** this is a system-self-review digest, not a per-user portfolio digest.
Send to a small **admin/owner recipient list** from env/system_settings (e.g.
`RETRO_DIGEST_RECIPIENTS` — comma-separated emails). Call `send_mailgun_message` directly; do
**not** route through the per-user `user_newsletter_subscriptions` wave in
`outbound_newsletter_pipeline.py`. Gate send behind a feature flag (e.g.
`RETRO_DIGEST_ENABLED` or reuse Mailgun config presence check).

**Acceptance:** unit test for the digest builder (empty-data case must produce a sane email,
since outcomes are sparse until ~July); send path behind enable flag; recipients from admin/env
list only.
**Size:** S (≈1 day).

## G6 — FINRA daily short volume (optional stretch)

Free daily files (`https://cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt`,
pipe-delimited) give per-ticker short volume — better cadence than the bi-monthly short
interest in §4.5. Small daily job scoped to US holdings/watchlist; store
`short_volume_daily (ticker, trade_date, short_volume, total_volume, short_ratio)` in the
Research DB; show on the dossier; optionally feed a "short-ratio spike" family into G4.
**RESEARCH:** confirm current file URL/format and whether consolidated (CNMS) covers the
listings you hold. **Size:** S.

---

## Explicitly deferred (do NOT build in Phase G)

| Item | Unblocks when |
|------|---------------|
| Source-ROI report/screen (which collectors earn their keep) | G1 shipped **and** ~30d of `stance_outcomes` (~2026-07-10) |
| Shape A smart prioritizer | track record shows signal (~2026-07-10) |
| Shape B theme research, Shape C dedicated job | their cheap-learn gates (ROADMAP "Cheap-learn results") |
| 13F ownership deltas (§4.6) | after G2 proves the EDGAR plumbing |
| Earnings-call transcript summarization | after source-ROI proves synthesis hit rate |
| Bi-monthly short interest (§4.5) | superseded by G6 unless G6 research says otherwise |
| Embedding-based article dedup | anytime as a palate cleanser; not load-bearing |
| Holdings-table days-to-exit column | frontend polish; needs async grid enrichment, see §4.3 note |

## Sequencing

```
G1 provenance (P0, days)
  └─> G2 EDGAR filing watch ──> G4 confluence (filing family)
        G3 SEDI memo (parallel, anytime) ──> G3 pipeline (only if memo passes)
        G4 confluence (can start before G2; add filing family later)
        G5 retro Mailgun (parallel, anytime)
        G6 short volume (optional, last)
```

Work order recommendation: **G1 → G2 → G4 → G5 → G3 memo → (G3 pipeline | G6) as appetite
allows.** One PR-sized change set per item; check items off here and in ROADMAP.md as they
land; run the relevant test suite before declaring each done.

## Phase G checklist

- [x] **G1** stance evidence provenance (manifest in `stance_history.metadata`) — shipped
  2026-06-13: `build_artifact_bundle_with_evidence` + `evidence` key on both stance hooks;
  verify script reports 24h coverage
- [ ] **G2** EDGAR filing watch (`filing_events`, real `dilution_watch_job`, Today + dossier)
- [ ] **G3a** SEDI feasibility memo (`docs/research/sedi_feasibility.md`)
- [ ] **G3b** SEDI pipeline (only if G3a passes; `.TO` clusters live)
- [ ] **G4** confluence scorer (`confluence_events`, ledger hook at score ≥ 3, Today block)
- [ ] **G5** weekly retro Mailgun digest (admin/env recipient list via `RETRO_DIGEST_RECIPIENTS`)
- [ ] **G6** FINRA daily short volume (optional)
