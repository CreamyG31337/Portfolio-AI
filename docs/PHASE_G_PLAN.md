# Phase G Plan — Provenance, Filings, and Confluence

**Audience: historical.** Phase G of [`docs/ROADMAP.md`](ROADMAP.md) — G1–G5 + G7 **shipped**;
G6 optional and **gated by Phase H1** (source-ROI). **Active work is Phase H** in ROADMAP
(2026-07-15 design review): source-ROI report, meta-bundle injection of Phase G signals + prior
stance, trend memory, congress herd → ledger, executive ship-or-kill. Keep this doc for G specs
and acceptance criteria; update ROADMAP checklists when anything here still lands.

Created 2026-06-11 after Phases A–F shipped. Several items contain explicit **RESEARCH** tasks.
Improve this plan where the codebase contradicts it — and update this doc and ROADMAP.md as
items land.

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
- G3: **pivoted 2026-06-13.** SEDAR+/SEDI dropped — only free path is a CAPTCHA bypass (ToS
  red line), only clean path is a paid feed (owner declined). Replaced with **free
  shares-outstanding dilution detection** via yfinance `get_shares_full()`, which works for `.TO`
  tickers and flagged real movers (GLO.TO +48.9%, GANX +42.4%) in a live probe. New job owns
  `JOB_ID="dilution_watch"`; G2 becomes the broader US filing-risk watch under a new id. Canadian
  *insider* coverage is dropped with no free substitute (accept the gap).
- G4: social spike must be computed on the fly; signals come from Supabase `signal_analysis`
  JSON (not in-memory `web_dashboard/signals/` evaluators).
- G5: send via `mailgun_outbound.send_mailgun_message` (not `jobs_newsletter.py`, which is
  inbound AI processing); recipients from admin/env list (`RETRO_DIGEST_RECIPIENTS`).

## Why these items, in one paragraph

The Learn layer (stance ledger + outcome scoring) went live 2026-06-11. First 7-day outcome
scores land ~2026-06-18; track-record/calibration becomes meaningful ~2026-07-10. Phase G does
three things while that data matures: (1) fixes a provenance gap that gets worse every day it
exists — stances don't record which articles fed them, so the planned "which sources earn their
keep" analysis is impossible; (2) closes the dilution blind spot for the whole book — free
shares-outstanding tracking (G3) catches realized dilution on every ticker including the `.TO`
names EDGAR can't see, and EDGAR filing alerts (G2) add the forward/distress/delisting/activist
signal for US names; (3) adds one cheap synthesis job — cross-signal confluence — that consumes
everything already built without a single new LLM call.

## Hard rules (non-negotiable)

- **No autonomous trading.** Outputs are advisory artifacts a human reads. Ever.
- **Additive schema only.** New tables/columns with fallbacks; never repurpose existing
  UPSERT semantics. Match the migration style in `database/schema/supabase/migrations/`.
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

## G2 — EDGAR filing-risk watch (US: dilution intent, distress, delisting, activist)

**Why:** G3 (shares-outstanding) catches *realized* dilution everywhere for free, but it's
lagging and dilution-only. G2 adds the **forward** signal for US names — a shelf registration
(S-3) tells you dilution is *coming* before the share count moves — plus categories the share
count can't show at all: late filings, delisting notices, activist 13D stakes. So G2 is **not**
the dilution-placeholder replacement (G3 is); it's a new, broader SEC filing-risk watch. US-only
by nature (EDGAR has no Canadian filings).

**What to build:**
1. **Shared SEC HTTP helper:** extract/reuse the throttled client from
   `web_dashboard/scheduler/sec_form4_poc.py` — it already has `DEFAULT_USER_AGENT`,
   `SEC_EDGAR_USER_AGENT` env override, ~9 req/s global rate limiter, and retry/backoff on
   503/502/429. Generalize it for `company_tickers.json` and `data.sec.gov/submissions/...`
   endpoints; do not write a fresh per-call-site client.
2. **Ticker→CIK map:** SEC publishes `https://www.sec.gov/files/company_tickers.json`
   (**live-confirmed 2026-06-14**: 200, ~796 KB, 10,414 entries, shape
   `{"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"}` — trivial to build).
   Refresh weekly, cache locally. **US tickers only** — `.TO`/`.V` have no CIK; skip them
   (covered by G3). **Also skip-and-log unmapped US tickers**: some delisted/renamed micro-caps
   aren't in the map (MULN resolved to `None` in the probe) — must not error on a miss.
3. **Per-CIK filing poll:** `https://data.sec.gov/submissions/CIK{cik:010d}.json`
   (**live-confirmed 2026-06-14** for AAPL + GME). `filings.recent` is **parallel arrays**
   (`form`, `filingDate`, `accessionNumber`, `primaryDocument`, `items`, `reportDate`, …) holding
   the latest ~1000 filings — far more than a nightly "new since yesterday" scan needs, so **no
   pagination**. For each production-fund holding + active watchlist ticker, flag new filings:
   - **Dilution / structure:** S-1, S-3, 424B5, S-8 (large), EFFECT; reverse split via 8-K
   - **Distress:** NT 10-Q, NT 10-K (late filings); 8-K Item 3.01 (listing deficiency)
   - **Delisting:** Form 25 / 25-NSE
   - **Activist / accumulation (positive):** SC 13D, SC 13G and amendments
   - **Classifier gotchas (live):** 8-K **item numbers are inline** in the `items` array
     (GME showed `items='2.02,7.01,9.01'`), so **Item 3.01 detection needs no extra fetch** — a
     plain substring match on `items` suffices. And the feed labels Schedule 13D as
     **`"SCHEDULE 13D/A"`**, not `"SC 13D/A"` — match **both** spellings. All other target forms
     (10-K, 10-Q, 25, 25-NSE, 424B2, 424B5, 8-K) appeared live.
4. **Storage:** new **Research-DB** table `filing_events` (append-only; migration file +
   `database/schema/research/tables/filing_events.sql`; wire via `\i tables/...` in
   `_init_schema.sql`). Use `CREATE TABLE IF NOT EXISTS` style (match `stance_history.sql`,
   not the older `DROP ... CASCADE` pattern):
   `id, ticker, cik, form_type, category ('dilution'|'distress'|'delisting'|'activist'),
   direction ('risk'|'positive'|'neutral'), filed_at, accession_no UNIQUE, title, url,
   raw jsonb, created_at`.
5. **Job:** a **new** module/job — e.g. `web_dashboard/scheduler/jobs_sec_filings.py`,
   `JOB_ID = "sec_filings"` (do **not** reuse `dilution_watch`; G3 takes that). Follow the
   `mark_job_started/completed/failed` + `enabled_by_default` registration shape used by the
   existing jobs in `jobs.py`. Nightly; no LLM. Scope: `latest_positions.ticker` + active
   `watched_tickers_v2.ticker`, US tickers only (per step 2). **Scheduling:** independent and
   no-LLM, so Ollama contention is irrelevant; the only constraint is it must write `filing_events`
   **before** G4 confluence reads them the same day. A daytime ET slot works; verify against
   `jobs.py` `cron_triggers` (mixed ET/PT) and don't collide with G4.
6. **Surfacing:** Today-screen block (risk events for held/watched tickers) +
   `filing` events merged into `GET /api/ticker/<ticker>/evidence-timeline`
   (`web_dashboard/routes/intelligence_routes.py`, line 203). This endpoint reads the **Research
   Postgres DB** via `PostgresClient` (not Supabase); it currently merges `stance` + `article`
   event types (G3 added `dilution`) — add a third source `event_type='filing'` from `filing_events`.
   **Naming — keep G2 and G3 distinct.** Both touch "dilution" (G2 = forward filing *intent*,
   e.g. an S-3 category='dilution'; G3 = realized share-count growth), so do NOT reuse G3's
   names: use briefing key `filing_alerts` (not `dilution_alerts`), a separate Today block
   labeled e.g. "SEC filings (risk)" distinct from G3's "Dilution alerts", and timeline
   `event_type='filing'` distinct from G3's `'dilution'`. Complementary signals, clearly labeled.

**RESEARCH:** (a) ~~submissions-API shape + how 8-K items are exposed~~ — **RESOLVED live
2026-06-14** (both endpoints hit, fair-access UA + ~9 req/s throttle reused): items are inline,
no per-8-K fetch needed; no pagination; findings folded into steps 2–3 above. (b) going-concern
language detection in 10-K/Q via EDGAR full-text search
(`https://efts.sec.gov/LATEST/search-index?q=...`) — **DEFERRED for V1 (2026-06-14):** it needs a
full-text query/fetch per 10-K/Q (the inline-`items` shortcut that makes 8-K Item 3.01 free does
not apply to going-concern language), so it's left out to keep the nightly scan to one submissions
fetch per ticker. Revisit as a `category='distress'` add-on if the per-ticker FTS cost proves
acceptable.

**Acceptance:** job runs against prod scope without placeholder messaging; fixture-based unit
tests for classification + dedupe on `accession_no`; events visible on dossier timeline;
SEC fair-access rules observed (shared helper with User-Agent, throttle).
**Size:** M (2–4 days).

## G3 — Dilution detection via shares-outstanding (free, all tickers incl. Canada)

**Decision (2026-06-13):** the SEDAR+/SEDI route is **dropped**. The only free path defeats a
CAPTCHA (ToS violation — barred by Hard Rules) and the only clean path is a **paid vendor feed**
(QuoteMedia / Avantis / Thomson Reuters), which the owner has declined. So official Canadian
*filing* data is off the table. (If the budget ever opens up, a paid CSA feed remains the
higher-fidelity option — but don't plan around it.)

**The free insight that replaces it:** dilution has a directly measurable *effect* — shares
outstanding rising — and yfinance exposes it for **US and Canadian tickers alike**, for free, with
no filing access at all. You don't need the S-3 or the SEDAR+ prospectus to know a company
diluted; the share count is the dilution. **Verified 2026-06-13** with
`yfinance.Ticker(t).get_shares_full(start=...)` on real holdings — it returned share-count time
series for every `.TO` ticker tried and immediately surfaced real signal: **GLO.TO +48.9%** and
**GANX +42.4%** shares outstanding over ~12 months (both heavy serial diluters), vs DRX.TO +0.1%
and CCO.TO −1.1%. This covers the exact Canadian names EDGAR (G2) cannot see.

**SHIPPED 2026-06-14.** `web_dashboard/dilution_service.py` (yfinance fetch + pure compute),
rewritten `web_dashboard/scheduler/jobs_dilution_watch.py`, `dilution_observations` table,
Today block + dossier surfacing, 9 unit tests. Live run against the real book flagged 5 movers:
**GLO.TO +59%**, **GANX +37%**, **OKLO +25%**, **PANW +21%** (365d), **LTRX +12%** (90d). What
was built (and where it diverged from the original sketch):
1. Job `jobs_dilution_watch.py`, `JOB_ID = "dilution_watch"`, **weekly Mon 06:30 ET**,
   `enabled_by_default: True`, no LLM. Replaces the §4.1 placeholder (G2 is the separate US
   *filing* watch under `JOB_ID="sec_filings"`; G3 is the universal *effect* watch).
2. Production-fund holdings + active watchlist (the `is_production` filter with unfiltered
   fallback — avoids wasting yfinance calls on TEST_* fixtures). `get_shares_full()` cached 6h.
3. **Windows changed to (90, 365), thresholds {90: 10%, 365: 20%}** — not the 30/90 originally
   sketched. **Why (learned from the live scan):** dilution is usually *gradual* and yfinance's
   share-count tail runs **~50 days stale**, so a 30d window from today often has zero fresh
   points, and even 90d is truncated. Year-over-year is the reliable signal (GLO's +59% lives
   there; sliced to 30/90d it falls under any bar). 90d still catches an acute raise (LTRX).
   Lookback is **400d** (must exceed the 365d window or the baseline has no data — a bug caught
   in the live run). `min_points=2` per window guards against a single stale reading.
4. **Storage:** `dilution_observations` (`database/schema/research/tables/dilution_observations.sql`,
   wired into `_init_schema.sql`, **applied to prod Research DB**):
   `id, ticker, as_of DATE, window_days, shares_start, shares_end, pct_change, flagged, created_at`,
   UNIQUE `(ticker, as_of, window_days)`. Only **flagged** rows are persisted (clean readings are
   noise). Job upserts `ON CONFLICT DO NOTHING`.
5. **Surfacing:** `dilution_alerts` in the Today briefing payload (`today_briefing_service` →
   `fetch_recent_dilution_flags`, SQL-cast to JSON-safe types), a `today-dilution` block in
   `today.ts`, and a `dilution` event merged into `/api/ticker/<ticker>/evidence-timeline`.

**Honest limitations (in the code comments too):**
- **Lagging, not an alert** — detects realized issuance after it hits the share count, not the
  filing moment, and the data tail is ~50d stale. Forward intent (a shelf before it's drawn) is
  exactly what G2's EDGAR watch adds for US names — G2 and G3 are complementary.
- **Canadian insider coverage is a separate, still-open gap.** G3 closes the *dilution* blind
  spot on `.TO`, but **not** the *insider-cluster* blind spot — §4.2 clusters remain US-only
  (Form 4). That gap is NOT accepted as permanent: a 2026-06-14 probe found yfinance
  `Ticker(t).insider_transactions` **does carry SEDI data for `.TO` names** (GLO.TO, GMIN.TO,
  CNR.TO, DRX.TO all returned real insider rows), so it's closeable for free — see **G7**.

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
   - dilution flag (G3): a flagged `dilution_observations` row counts as a **risk** family
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
`RETRO_DIGEST_RECIPIENT_ACCOUNTS` — comma-separated `user_profiles.full_name` values resolved
to current account emails; direct `RETRO_DIGEST_RECIPIENTS` remains supported). Call
`send_mailgun_message` directly; do
**not** route through the per-user `user_newsletter_subscriptions` wave in
`outbound_newsletter_pipeline.py`. Gate send behind a feature flag (e.g.
`RETRO_DIGEST_ENABLED` or reuse Mailgun config presence check).

**Acceptance:** unit test for the digest builder (empty-data case must produce a sane email,
since outcomes are sparse until ~July); send path behind enable flag; recipients from admin/env
list only.
**Size:** S (≈1 day).

**Ops status (updated 2026-07-16):** Account-based recipient resolution shipped under Phase H3.
The production deploy defaults `RETRO_DIGEST_RECIPIENT_ACCOUNTS` to `Lance Colton`; its current
`user_profiles.email` is resolved at send time. Mailgun outbound keys are still required.

## G6 — FINRA daily short volume (optional stretch)

Free daily files (`https://cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt`,
pipe-delimited) give per-ticker short volume — better cadence than the bi-monthly short
interest in §4.5. Small daily job scoped to US holdings/watchlist; store
`short_volume_daily (ticker, trade_date, short_volume, total_volume, short_ratio)` in the
Research DB; show on the dossier; optionally feed a "short-ratio spike" family into G4.
**RESEARCH:** confirm current file URL/format and whether consolidated (CNMS) covers the
listings you hold. **Size:** S.

## G7 — Canadian insider coverage via yfinance (revives the dropped SEDI goal, for free)

**Why:** the §4.2 insider-cluster feature is Form 4 only, so it's blind to the `.TO` half of the
book — the gap the original (SEDI) G3 was meant to fix before SEDAR+ was dropped as paid/ToS-
blocked. **A 2026-06-14 probe reopened it:** `yfinance.Ticker(t).insider_transactions` carries
Yahoo-sourced **SEDI data for `.TO` tickers** — free, and yfinance is already core infrastructure
here (no new dependency, no new ToS exposure). Live sample: GLO.TO returned officer/director
"Acquisition in the public market" buys; GMIN.TO 92 rows, CNR.TO 150, DRX.TO 7 (CCO.TO 0 — not
every name has data). This is lower-fidelity than an official feed but non-zero and free.

**What to build:**
1. A small job (weekly; e.g. fold into `jobs_insiders.py` or a sibling) that, for production-fund
   `.TO`/`.V` holdings + watchlist, reads `yf.Ticker(t).insider_transactions` and upserts into the
   existing Supabase `insider_trades` table. The **source-agnostic** `insider_clusters_service.py`
   then picks Canadian names up automatically (verify with a `.TO` fixture test).
2. **Add the `source` column** to `insider_trades` first (additive migration: `'sec_form4'`
   default vs `'yahoo_sedi'`) so provenance is queryable and the two ingesters don't fight.
3. **Parsing (from the probe — the `Transaction` column is blank for these rows; classify off the
   `Text` field):**
   - `"Acquisition in the public market…"` → `type='Purchase'` (the conviction signal clusters need)
   - `"Sale at price…"` → `type='Sale'`
   - **Exclude** `"Exercise of options…"`, `"Stock Gift…"`, `"Redemption, retraction…"` — not
     open-market conviction trades; counting them would fabricate clusters.
   - Fields: `Insider` (format `"Surname (First)"` — normalize), `Start Date` → `transaction_date`,
     `Shares`, price parsed from `Text` (`Value` is sometimes NaN). Map onto the existing
     `insider_trades` unique key; trust the DB unique index + upsert (the pre-upsert dup check in
     `jobs_insiders.py` is narrower — see notes carried over from the old SEDI plan).

**Honest limitations:** best-effort completeness (Yahoo's SEDI mirror, not the source); some names
return nothing; option-exercise/gift noise must be filtered. Good enough to surface `.TO` insider
clusters that are invisible today; not a system of record.

**Acceptance:** `source` column added; `.TO` insider rows ingested and deduped across re-runs;
`insider_clusters_service` surfaces a `.TO` cluster in a fixture test; no option-exercise/gift
rows leak in as Purchases.
**Size:** M (2–3 days). **Coordinate with whoever is editing the insider code** (Cursor is in
that area now) to avoid collisions.

---

## Explicitly deferred (do NOT build in Phase G)

| Item | Unblocks when |
|------|---------------|
| Source-ROI report/screen (which collectors earn their keep) | G1 shipped **and** ~30d of `stance_outcomes` (~2026-07-10) |
| Shape A smart prioritizer | track record shows signal (~2026-07-10) |
| Shape B theme research, Shape C dedicated job | their cheap-learn gates (ROADMAP "Cheap-learn results") |
| 13F ownership deltas (§4.6) | after G2 proves the EDGAR plumbing |
| Earnings-call transcript summarization | **→ Phase K** in [`ROADMAP.md`](ROADMAP.md#phase-k--youtube-captions--research-articles) (YouTube captions → `research_articles`; H1 source-ROI already shipped) |
| Bi-monthly short interest (§4.5) | superseded by G6 unless G6 research says otherwise |
| Embedding-based article dedup | anytime as a palate cleanser; not load-bearing |
| Holdings-table days-to-exit column | frontend polish; needs async grid enrichment, see §4.3 note |

## Sequencing

```
G1 provenance (P0, days) ✓ shipped
  ├─> G3 shares-outstanding dilution watch (free, all tickers incl .TO) ✓ ─┐
  ├─> G2 EDGAR filing-risk watch (US: shelf/distress/delisting/13D)    ───┤
  │                                                                       └─> G4 confluence (dilution + filing families)
  ├─> G7 Canadian insider coverage via yfinance (closes the .TO cluster gap, free)
  ├─> G5 retro Mailgun (parallel, anytime)
  └─> G6 short volume (optional, last)
```

Work order recommendation: **G1 ✓ → G3 ✓ → G2 → G4 → G7 → G5 → G6 as appetite allows.** G3 led
the dilution work because it's free, country-agnostic, and already validated; G2 adds the US
forward/distress/activist signal; G7 closes the remaining `.TO` *insider* gap for free. One
PR-sized change set per item; check items off here and in ROADMAP.md as they land; run the
relevant test suite before declaring each done.

## Phase G checklist

- [x] **G1** stance evidence provenance (manifest in `stance_history.metadata`) — shipped
  2026-06-13: `build_artifact_bundle_with_evidence` + `evidence` key on both stance hooks;
  verify script reports 24h coverage
- [x] **G3** dilution watch via shares-outstanding (free; yfinance `get_shares_full`;
  `dilution_observations`; replaces the §4.1 placeholder; covers `.TO`) — **shipped 2026-06-14**,
  live run flagged GLO.TO +59%, GANX +37%, OKLO +25%, PANW +21%, LTRX +12%. *(SEDAR+ dilution
  dropped — paid/ToS; the `.TO` insider gap it left is now G7, not accepted as permanent.)*
- [x] **G2** EDGAR filing-risk watch — US (`filing_events`, new `sec_filings` job: shelf/distress/
  delisting/13D; Today + dossier). EDGAR endpoints research-confirmed live 2026-06-14.
  **Shipped 2026-06-14:** shared throttled SEC client `scheduler/sec_http.py` (extracted from
  `sec_form4_poc.py` — one global ~9 req/s limiter); `sec_filings_service.py` (ticker→CIK via
  `company_tickers.json`, weekly disk cache; `classify_filing`; parallel-array extraction; dedupe;
  graceful-degrade reader); `scheduler/jobs_sec_filings.py` (`JOB_ID="sec_filings"`, mon–fri
  18:30 ET, `enabled_by_default=False` until the table is applied); `filing_events.sql` wired into
  `_init_schema.sql` (NOT applied to prod — human applies the DDL); Today block `filing_alerts`
  ("SEC filings (risk)") + `event_type='filing'` on the evidence timeline; 21 unit tests.
  **Deferred for V1:** going-concern full-text detection (EDGAR FTS — not wired) and 8-K
  reverse-split detection (needs filing-title/full-text parsing); both need a per-filing fetch
  the inline-`items` approach avoids, so left out to keep the nightly scan cheap.
- [x] **G4** confluence scorer (`confluence_events`, ledger hook at score ≥ 3, Today block) — shipped 2026-06-17
- [x] **G5** weekly retro → Mailgun digest — code shipped 2026-06-20; **prod email not configured** (deferred)
- [x] **G7** Canadian insider coverage via yfinance `insider_transactions` — shipped 2026-06-20:
  `yahoo_sedi_insider_service.py`, `jobs_yahoo_sedi_insiders.py`, `source` column migration,
  weekly Mon 07:00 ET. See [`web_dashboard/scheduler/YAHOO_SEDI_INSIDERS_JOB.md`](../web_dashboard/scheduler/YAHOO_SEDI_INSIDERS_JOB.md).
- [ ] **G6** FINRA daily short volume (optional)
