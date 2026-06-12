# Phase G Plan — Provenance, Filings, and Confluence

**Audience: a coding agent (Cursor plan mode).** This is the detailed implementation brief for
Phase G of [`docs/ROADMAP.md`](ROADMAP.md) (the master plan — read it first, especially its
Guardrails). Created 2026-06-11 after Phases A–F shipped. Run this through plan mode: several
items contain explicit **RESEARCH** tasks where you must investigate and propose an approach
before writing code. Improve this plan where the codebase contradicts it — and update this doc
and ROADMAP.md as items land.

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
  back off on 429/403. One polite shared HTTP helper, not per-call-site headers.
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
1. In `web_dashboard/meta_analysis_service.py`, `build_artifact_bundle(ticker)` (~line 376)
   assembles the prompt text from snapshots + `_fetch_article_snippets(ticker)` (~line 498).
   Refactor it to also return a structured evidence manifest, e.g.
   `{"article_ids": [...], "artifact_types": ["social", "congress", "signals", ...]}` —
   whatever artifact families actually went into the bundle.
2. Thread the manifest through `save_ticker_meta(...)` into the existing
   `record_stance_safe(..., metadata={...})` call (~line 716): add an `"evidence"` key to the
   metadata jsonb. **No schema change needed** — `stance_history.metadata` exists.
3. Do the same for the `ticker_analysis` hook in `web_dashboard/ticker_analysis_service.py`
   (record which inputs were present: price data, signals, fundamentals — there may be no
   articles there; record what's true).
4. Extend `web_dashboard/scripts/verify_stance_pipeline.py` to report the % of last-24h
   stances carrying `metadata->'evidence'`.

**RESEARCH (before coding):** read `build_artifact_bundle` end to end and enumerate what is
actually in the bundle per artifact family; the manifest shape should mirror reality, not this
sketch. Check whether `_fetch_article_snippets` already selects article `id` (if not, add it
to the SELECT).

**Acceptance:** new meta/analysis stances carry evidence in metadata; unit tests assert the
manifest passes through (extend `tests/test_stance_history.py` patterns); verify script shows
coverage; no behavior change to the prompt text itself (digest stability — compare digests
before/after on an unchanged bundle).
**Size:** S (≈1 day).

## G2 — Real EDGAR filing watch (replaces the §4.1 placeholder)

**Why:** dilution is the #1 micro-cap killer; the current
`web_dashboard/scheduler/jobs_dilution_watch.py` is an honest placeholder (enumerates scope,
calls nothing). The same plumbing also catches late filings, delisting notices, and activist
stakes nearly for free.

**What to build:**
1. **Ticker→CIK map:** SEC publishes `https://www.sec.gov/files/company_tickers.json`.
   Refresh weekly, cache locally (small table or file). US tickers only — route `.TO`/`.V`
   tickers to G3's scope instead of silently failing.
2. **Per-CIK filing poll:** `https://data.sec.gov/submissions/CIK{cik:010d}.json` lists recent
   filings with form types and dates. For each production-fund holding + active watchlist
   ticker, flag new filings in these classes:
   - **Dilution / structure:** S-1, S-3, 424B5, S-8 (large), EFFECT; reverse split via 8-K
   - **Distress:** NT 10-Q, NT 10-K (late filings); 8-K Item 3.01 (listing deficiency)
   - **Delisting:** Form 25 / 25-NSE
   - **Activist / accumulation (positive):** SC 13D, SC 13G and amendments
3. **Storage:** new Research-DB table `filing_events` (append-only; migration file +
   `database/schema/research/tables/filing_events.sql`):
   `id, ticker, cik, form_type, category ('dilution'|'distress'|'delisting'|'activist'),
   direction ('risk'|'positive'|'neutral'), filed_at, accession_no UNIQUE, title, url,
   raw jsonb, created_at`.
4. **Job:** rewrite `dilution_watch_job` (keep `JOB_ID = "dilution_watch"` and the
   `mark_job_started/completed/failed` shape already there); nightly; no LLM. Flip
   `enabled_by_default` to True in `web_dashboard/scheduler/jobs.py` only once it reports real
   scans.
5. **Surfacing:** Today-screen block (risk events for held/watched tickers) +
   `filing` events merged into `GET /api/ticker/<ticker>/evidence-timeline`
   (`web_dashboard/routes/intelligence_routes.py`).

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

**Deliverable 1 — feasibility memo (required):** `docs/research/sedi_feasibility.md` covering:
access options (SEDI's own interface has no API and is notoriously hostile; third-party mirrors
like canadianinsider.com exist but check ToS), per-issuer query mechanics, transaction-code
mapping to the existing `Purchase`/`Sale` model, rate expectations, and a recommendation.
**If every viable path violates ToS or requires paid data, stop there** — the memo is the
deliverable; a human decides.

**Deliverable 2 — prototype (only if memo finds a clean path):** weekly scan scoped to
`.TO`/`.V` production-fund holdings + watchlist. Store into the existing Supabase
`insider_trades` table — **RESEARCH:** confirm the unique key
`(ticker, insider_name, transaction_date, type, shares, price_per_share)` accommodates SEDI
data and add an additive `source` column (`'sec_form4'` default vs `'sedi'`) so provenance is
queryable. `insider_clusters_service.py` is source-agnostic and picks Canadian names up
automatically — verify with a test using `.TO` fixture rows.

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
   - stance flip to a directional stance (`today_briefing_service.fetch_stance_flips` — reuse,
     don't fork the SQL; it is the single owner of flip detection)
   - insider cluster (`insider_clusters_service.build_insider_cluster_buys`)
   - congress buys (Supabase `congress_trades_enriched`)
   - social attention spike — **RESEARCH:** check what Research-DB `social_metrics` actually
     supports (per-ticker volume over time? z-score vs trailing baseline?) and define "spike"
     defensibly; if the data can't support it, drop the family and say so
   - signals breakout/uptrend (check `web_dashboard/signals/` for the queryable artifact)
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
   against ^RUT like every other stance, for free. (Risk-direction events stay events; RISK
   isn't directionally scoreable — see ROADMAP §1.2.)
5. **Surfacing:** Today-screen block (top confluence events since yesterday) + events merged
   into the dossier evidence timeline.

**Acceptance:** fixture-based unit tests (families counted distinctly; direction split; dedupe;
stance written only at threshold); job registered (pick a slot after the nightly collectors,
e.g. ~22:30 ET — check `jobs.py` for collisions); Today block renders.
**Size:** M (2–3 days).

## G5 — Weekly retro → Mailgun (finish the hookup)

**Why:** `web_dashboard/scheduler/jobs_weekly_stance_retro.py` already computes flips +
track-record summary but only logs a one-line message. The infra to send exists in
`web_dashboard/scheduler/jobs_outbound_newsletter.py`.

**What to build:** render the retro as a small HTML digest (stance flips of the week, hit rates
by source once `stance_outcomes` has rows, best/worst calls from
`track_record_service.build_track_record_summary`, confluence events once G4 lands) and send it
through the existing newsletter/Mailgun path. **RESEARCH:** read `jobs_outbound_newsletter.py`
+ `jobs_newsletter.py` first and reuse their recipient handling and send helper — do not
hand-roll SMTP/Mailgun calls or a second recipient list.

**Acceptance:** unit test for the digest builder (empty-data case must produce a sane email,
since outcomes are sparse until ~July); send path behind the existing newsletter enable flags.
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

- [ ] **G1** stance evidence provenance (manifest in `stance_history.metadata`)
- [ ] **G2** EDGAR filing watch (`filing_events`, real `dilution_watch_job`, Today + dossier)
- [ ] **G3a** SEDI feasibility memo (`docs/research/sedi_feasibility.md`)
- [ ] **G3b** SEDI pipeline (only if G3a passes; `.TO` clusters live)
- [ ] **G4** confluence scorer (`confluence_events`, ledger hook at score ≥ 3, Today block)
- [ ] **G5** weekly retro Mailgun digest
- [ ] **G6** FINRA daily short volume (optional)
