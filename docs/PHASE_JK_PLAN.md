# Phase J + K Plan — Event Catalysts & YouTube Captions

**Audience: implementation brief** for backlog phases in [`docs/ROADMAP.md`](ROADMAP.md).
Checklists and sequencing live in ROADMAP (**Phase J**, **Phase K**); this doc is the
codebase-aware integration map so an agent does not rediscover the wiring.

**Created 2026-07-22** while researching caption rippers and tracing the Collect →
Synthesize → Decide article path. Verified against the tree the same day (read-only).
Improve this plan where the codebase contradicts it; keep ROADMAP checklists in sync when
items land.

**Gates (do not ignore):**
- Phase H closed (**H7 done 2026-07-27:** `idea_triage` still 0 rows — Ideas unused for
  labels; do not train on triage or silently promote YT into Ideas without a product call).
- Prefer **I1 story dedup** before either phase at volume (K especially — same story on YT +
  news write-up will double-count without it). K1–K2 PoC OK with a tiny allowlist.
- No autonomous trading. Additive Research-DB schema only. Holdings jobs filter
  `funds.is_production = true`.

---

## Why these two phases together

| Phase | Layer | One-liner |
|-------|-------|-----------|
| **K** | Collect → Synthesize | Land YouTube captions as `research_articles` so **existing** summarize / relevance / meta / dossier paths see them. |
| **J** | Learn → Decide | Mine historical event windows + article evidence for repeatable ticker responses; surface when live news rhymes. |

K feeds J (and everything else that already reads articles). J does not need K to start
(J1–J4 can use today’s news corpus), but **K strengthens J2** once earnings/IR video lands
as dated, ticker-tagged evidence inside event windows.

```mermaid
flowchart TB
  subgraph Collect
    MR[market_research / RSS / ticker_research / symbol / alpha / opportunity / ETF / PDF]
    YT[K: youtube_caption_job]
  end
  subgraph ResearchDB
    RA[(research_articles)]
    EV[(event_catalog + links)]
    BT[(event_backtest_results)]
    PB[(event_playbooks)]
  end
  subgraph Enrich
    SUM[generate_summary + ticker extract]
    AR[article_relevance_job]
  end
  subgraph Synthesize
    TA[ticker_analysis — titles/summaries]
    TM[ticker_meta — conclusions only]
    SM[sector_meta — ETF Analysis only]
    MB[market_daily_brief — benchmarks only]
  end
  subgraph Decide
    IDEAS[/ideas — Alpha + Opportunity only]
    TODAY[/today]
    DOS[dossier + evidence-timeline]
    INS[Insights evidence_kind=research_article]
  end
  subgraph Learn
    ROI[track_record / source-ROI]
    JENG[J3–J4 backtest + playbooks]
  end
  MR --> RA
  YT --> RA
  RA --> SUM --> AR
  RA --> TA --> TM
  RA --> DOS
  RA --> INS
  RA --> ROI
  RA --> EV
  MB -.-> TM
  EV --> JENG --> PB
  PB --> TODAY
  PB --> IDEAS
  TM --> ROI
```

---

## Current article pipeline (facts to design against)

> Cross-checked 2026-07-22 with a full Collect→Decide trace
> ([pipeline map](a7658bcb-f2d6-4f91-908f-53893d83bea7)). Prefer this section over memory when
> wiring K/J.

### Storage contract

`database/schema/research/tables/research_articles.sql` — unique on `url`. Key fields:
`article_type`, `title`, `url`, `content`, `summary`, `conclusion`, `sentiment`,
`sentiment_score`, `tickers[]`, `ticker`, `sector`, `source`, `published_at`,
`fetched_at`, `relevance_score`, `ticker_validated_at`, `claims` / `fact_check` /
`logic_check`, optional `embedding vector(1024)`, `fund` (fund-scoped PDFs only),
`archive_*` (paywall → archive.org), `corroboration_count` / `corroboration_sources` (I1),
`source_metadata` jsonb (K2 collector provenance — summarizer never writes it).

Write path: `ResearchRepository.save_article` (`web_dashboard/research_repository.py`) —
`ON CONFLICT (url) DO UPDATE`. **Articles live in Research Postgres only** (`PostgresClient` /
`ResearchRepository`). DualWrite empty-read rules apply to fund CSVs, not this table — but
meta still **mixes** Supabase (`signal_analysis`, benchmarks, congress) with Postgres articles;
wrong client = silent empty.

**Not** `research_articles`: inbound email newsletters stay in `newsletters`
(`newsletter_service.py` / `newsletter_ai_processing`) — do not assume email text is
queryable as articles for J2.

### Ingest jobs that already mint articles

| Job / path | `article_type` (examples) | Notes |
|------------|---------------------------|--------|
| `market_research_job` (×4 weekday ET) | `Market News` | SearXNG; domain health; `calculate_relevance_score` |
| `rss_feed_ingest_job` (~3h) | `Market News` | Enabled feeds from `rss_feeds` |
| `ticker_research_job` | `Ticker News` | Portfolio-ticker scrape path |
| `symbol_article_scraper_job` | `Symbol Article` (paywall stub may save `Ticker News`) | Holdings-scoped + `generate_summary` — **closest template for K** |
| `alpha_research` (~22:15 PT) | `Alpha Research` | **Ideas inbox consumer** |
| `opportunity_discovery_job` | `Opportunity Discovery` | **Ideas inbox consumer** |
| `process_research_reports_job` | `Research Report` | PDF folders / ticker hints |
| `etf_group_analysis` | `ETF Analysis` (`etf-analysis://…`) | **Sector meta only reads this type** |
| `etf_watchtower` | `ETF Change` | Auto-validated by `article_relevance_job` |
| `subreddit_scanner_job` | `Reddit Discovery` | Social discovery path |
| `archive_retry_job` | (reprocess) | Paywall → archive.org content refresh |

Shared helpers: `research_utils.extract_article_content`, `scheduler/jobs_common.py`
(`calculate_relevance_score`, `claim_recent_summary_input` 6h TTL, `has_strong_market_signal`),
`ollama_client.generate_summary` + `summary_common` prompts, `ticker_validator`,
`research_domain_health.DomainHealthTracker`, `article_pipeline.run_article_pipeline_parallel`.

### Enrichment that must run after insert

1. **Summarize + CoT fields** — most scrapers call `generate_summary` **inline** (global AI
   lock / contention with overnight queue jobs). **K should prefer the AI task queue** for
   transcript summarization (`docs/AI_TASK_QUEUE_DESIGN.md`) — do not add another long
   inline mutex hog next to `alpha_research`.
2. **`article_relevance_job`** (daily ~4:00 ET) — GLM cheap model cleans `tickers[]` for rows
   with `ticker_validated_at IS NULL` (auto-passes `ETF Change`). Lookback 90d, cap 200/run.
3. Optional reprocess: `reprocess_tickerless.py` for empty ticker arrays.
4. Optional embed: `OllamaClient.generate_embedding` → `embedding vector(1024)`.

### Who consumes articles today

| Consumer | File / function | What it uses | Implication for J/K |
|----------|-----------------|--------------|---------------------|
| **Ticker analysis** (1st pass) | `ticker_analysis_service._get_research_articles` / `_format_articles` | ~3mo window, up to ~10 titles/summaries/sentiment; count + `article_ids` into analysis evidence | YT rows with tickers + summary auto-enter standard analysis once present |
| **Ticker meta** (2nd pass) | `meta_analysis_service._fetch_article_snippets` | Last **6** rows in **90d**; **title + conclusion + sentiment only** | Long YT bodies useless unless summarize filled `conclusion`/`sentiment`. Cap 6 → noisy channels crowd out news |
| **Sector meta** | `sector_meta_analysis_service.fetch_etf_articles_for_sector` | **`article_type = 'ETF Analysis'` only** (≤14/sector, 730d lookback) | YouTube does **not** enter sector meta in v0 |
| **Market brief** | `market_brief_service.run_market_daily_brief` | Benchmarks / prior briefs — **no articles** | Feeds meta/Today as regime only; J5 may later *read* regime, not write articles into the brief |
| **Evidence timeline / dossier** | `intelligence_routes.ticker_evidence_timeline`; `ticker_utils` article list | `article_type` as label; ticker/`tickers` match | YT appears automatically once tickers set |
| **Insights** | `user_insights_service` (`evidence_kind='research_article'`) | Human can attach an article UUID to a thesis entry | Optional: surface IR YT rows as attachable evidence in UI later |
| **Ideas inbox** | `today_briefing_service.fetch_alpha_ideas` | **Only** `Alpha Research` + `Opportunity Discovery`, 14d | Raw `YouTube Transcript` will **not** show. J5/K promotions need Today block or deliberate type/API extension |
| **Source-ROI** | `track_record_service._fetch_article_domains` | G1 `evidence.article_ids` → `research_articles.source` | Set `source` to `youtube:{channel_id}`; articles never in a stance evidence chain stay invisible to ROI |
| **Stance provenance** | `build_artifact_bundle_with_evidence` | Article UUIDs into `stance_history.metadata.evidence` | After YT conclusions land in meta (or standard analysis), they become attributable |

### Retention / dedup reality

- Consumers use **time windows** (14d Ideas / ~30d dossier / 90d meta / 730d sector ETF).
- `ResearchRepository.delete_old_articles(days_to_keep=30)` exists but **no scheduled caller
  found** — table can grow; K allowlist + caps matter more than assuming GC.
- Dedup today: exact `url` + in-process URL claim + 6h summary-input hash. **Near-dup stories
  (SearXNG + RSS + later YT)** still need Phase **I1**.

### Hard rules that bite these phases

- Meta prompt sees **conclusions**, not transcripts — **summarize is mandatory** for K.
- Ideas is a **closed article_type allowlist** — do not assume “saved article = idea.”
- Sector meta is **ETF Analysis–shaped** — do not dump YT into it casually.
- `claim_recent_summary_input` TTL (~6h) dedupes identical summary inputs in-process —
  chunked earnings calls need stable chunking or one stitched body hash.
- Article ingest LLM is mostly **inline** today; K summarization should be **queue-managed**.
- Supabase REST 1000-row cap; Research article queries use Postgres directly (good).
- AI task queue for any new LLM enrichment (see `docs/AI_TASK_QUEUE_DESIGN.md`).

---

## Phase K — YouTube captions → research articles

### Recommended stack (from ROADMAP research notes)

1. **[`jdepoix/youtube-transcript-api`](https://github.com/jdepoix/youtube-transcript-api)** (MIT) — caption body.
2. **[`yt-dlp/yt-dlp`](https://github.com/yt-dlp/yt-dlp)** (Unlicense) — channel/playlist listing + metadata + VTT fallback.
3. Thin local wrapper — do not vendor random &lt;20★ CLI wrappers.

> **Source config + admin UI** (the `youtube_sources` table below, plus an
> `/admin/sources` page that also finally gives `rss_feeds` a UI) is specced separately in
> [`PHASE_K_SOURCES_UI_PLAN.md`](PHASE_K_SOURCES_UI_PLAN.md).

### Proposed modules / tables

| Piece | Suggestion | Mirrors |
|-------|------------|---------|
| Config table | `youtube_sources` (Research): `channel_id`, `label`, `kind` (`ir`/`macro`/`earnings_search`), `enabled`, `last_seen_at` | `rss_feeds` |
| Job | `youtube_caption_ingest_job` in `scheduler/jobs_youtube.py` | `jobs_symbol_articles.py` / `rss_feed_ingest_job` |
| Fetch helper | `web_dashboard/youtube_captions.py` — `fetch_caption_text(video_id) -> CaptionResult` | `research_utils.extract_article_content` |
| Article type | **`YouTube Transcript`** (stable string; document in save_article callers) | existing type strings |
| URL | Canonical `https://www.youtube.com/watch?v={id}` (unique key) | `research_articles_url_key` |
| `source` | **Shipped K2:** `youtube:{channel_id}` → `youtube:@handle` → `youtube:{channel-name-slug}` → `youtube:unknown`. Never bare `youtube.com` | track_record domain slice |
| Metadata | **Shipped K2:** additive `research_articles.source_metadata` JSONB (`video_id`, `channel_id`, `channel`, `duration_s`, `caption_lang`, `caption_kind`, `caption_kind_raw`, `fetch_source`, `char_count`, `truncated`, `youtube_source_id`, `alpha_mechanism`). `claims` was rejected — the summarizer owns and overwrites it, so every re-enrich would drop provenance | One generic column, not a youtube-specific one; reusable by future collectors |

### End-to-end flow (K)

```
allowlist poll (yt-dlp flat-playlist)
  → for each new video_id since cursor
  → youtube-transcript-api.fetch (manual EN > auto EN > any)
  → clean text (drop [Music], collapse dup lines)
  → cap content at YOUTUBE_TRANSCRIPT_MAX_CHARS (flag source_metadata.truncated)
  → generate_summary(article_type='YouTube Transcript')  # same CoT fields as symbol scraper
  → extract_and_validate_tickers (expected_tickers from youtube_sources lead)
  → save_article(article_type='YouTube Transcript', url=watch_url, content=cleaned,
                 summary/conclusion/sentiment=..., tickers=..., source=youtube:{channel_id},
                 source_metadata={video_id, channel_id, duration_s, caption_lang, caption_kind})
  → (queue mode: save body first, then enqueue youtube_transcript_summary for a worker)
  → nightly ticker_meta includes snippet if ticker matches and row is in top-6/90d
  → dossier timeline shows event_type=article, source=YouTube Transcript
```

### Pipeline integration matrix (K)

| Pipeline | Integration | Work required |
|----------|-------------|---------------|
| Summarize / CoT | **Shipped K2:** AI-queue job `youtube_transcript_summary` (target_key = video id) with inline fallback; CoT fields mirror `symbol_article_scraper_job` | Done. Body persists first, so a retry never re-hits YouTube (its rate-limit block lasts hours) |
| `article_relevance_job` | **Not reachable** — `save_article` always stamps `ticker_validated_at = NOW()`, and the job selects `IS NULL`. K2 validates tickers at ingest instead | None for K. Fixing the stamping is a cross-cutting change (see K2 notes) |
| Ticker analysis | Automatic via `_get_research_articles` once tickers + summary exist | Spot-check `research_articles_count` / evidence ids after first IR video |
| Ticker meta | Automatic via `_fetch_article_snippets` | Optional K4+: prefer higher `relevance_score` for IR earnings; or reserve 1 of 6 slots for `YouTube Transcript` (feature flag) |
| Sector meta | None in v0 | Do not force |
| Insights | Attachable as `evidence_kind=research_article` | Optional UI affordance later |
| Ideas | None in v0 | Optional later: promote high-relevance IR transcripts as `Opportunity Discovery`-shaped cards **or** extend `fetch_alpha_ideas` IN list behind a flag |
| Today | None in v0 | Optional “new IR video” block if holdings ticker matched |
| Evidence timeline | Automatic | Maybe include `url` in timeline metadata for deep link |
| Source-ROI (K5) | Automatic once G1 evidence includes those article ids | Ensure `source` is channel-grain |
| Phase J event link | Automatic once `published_at` + tickers set | Earnings-call videos become high-value J2 evidence |
| Domain health | Treat `youtube.com` as a special domain — do not auto-blacklist the whole host on one bad channel | Custom health keyed by `youtube:{channel_id}` |
| Dedup (I1) | Story identity should hash caption text + consider “same earnings call” across YT + PR wire | After I1; until then keep allowlist tiny |

### Length / cost gotchas (K)

**Resolved in K2 — option 1 (stitch + single summarize).** Stored `content` is capped at
`YOUTUBE_TRANSCRIPT_MAX_CHARS` (default 64k chars ≈ a 75-minute call) and
`source_metadata.truncated` flags rows that lost their tail. The summarizer budget for
`article_type = 'YouTube Transcript'` is 16k chars (`AI_SUMMARY_MAX_CHARS_TRANSCRIPT`, same as
Newsletter) instead of the 6k default, and `truncate_for_summary` keeps head **and** tail — at
6k the entire Q&A of an earnings call would have been discarded, which is the part that moves a
thesis. Revisit option 2 (map-reduce) before K3 volume if 16k proves too lossy.

- Hour-long auto-captions can be **tens of thousands of tokens**. v0 options (pick one, document):
  1. **Stitch + single summarize** with hard `content` cap (e.g. 32–64k chars) and note truncation in summary prompt. ← **chosen**
  2. **Chunked summarize** (map → reduce) via AI task queue — better quality, more queue load.
  3. **Earnings-only** first (shorter, higher signal) before macro channels.
- Prefer **manual** captions over auto when both exist (`youtube-transcript-api` default preference).
- Rate limits / `RequestBlocked` — backoff + proxy hook already in transcript-api; job must skip soft-fail.

### Acceptance criteria (K)

- [x] PoC: given a known earnings video with captions, produce cleaned text without downloading media.
  (**K1 done 2026-07-27** — see probe notes below; `web_dashboard/youtube_captions.py` +
  `scripts/youtube_caption_poc.py`.)
- [x] Upsert lands one `research_articles` row; re-run is idempotent on URL. (**K2 done
  2026-07-29** — `youtube_articles.ingest_video`; `article_exists` short-circuits a re-run,
  `--force` re-summarizes through the same `ON CONFLICT (url)` upsert.)
- [x] Row has non-empty `conclusion` + `sentiment` after summarize. (Covered by
  `tests/test_youtube_articles.py`; live spot-check is **K4**.)
- [ ] Holding ticker appears in `tickers[]`; within 90d it can appear in a meta bundle spot-check.
  (Ticker merge is implemented — `youtube_sources.expected_tickers` leads, then
  `extract_and_validate_tickers` — but the live meta spot-check is **K4**.)
- [ ] Dossier evidence-timeline lists it with type `YouTube Transcript`. (Automatic once a
  real row exists; verify in **K4**.)
- [ ] Job registered in `scheduler/jobs.py` with cron that does **not** collide with
  `alpha_research` / `sector_meta` / `ticker_meta` heavy window (check ET vs PT mix in
  `AVAILABLE_JOBS` — same footgun as Phase G).
- [x] Tests: caption clean + URL parse + mocked fetch/fallback; no network in unit tests
  (`tests/test_youtube_captions.py`). save_article mock landed with K2
  (`tests/test_youtube_articles.py`, 43 tests: fixture VTT → clean → normalize →
  `save_article` mock, source grain, metadata contract, idempotency, queue vs inline,
  soft-fails, duration gates).

### K1 probe notes (2026-07-27)

| Question | Result |
|----------|--------|
| Works at all from this Windows/residential IP? | **Yes** — `youtube-transcript-api` 1.2.4 `list`/`fetch`, no cookies, no API key |
| Auth / Google account needed? | **No** for public videos with captions |
| Earnings-length auto-captions? | **Yes** — NVDA Q4'25 call `LPEXkI_4qI4` (~61 min): auto EN, 1312 snippets, ~47k cleaned chars |
| yt-dlp VTT fallback? | **Yes** on short public video (`jNQXAC9IVRw`); used when timedtext path fails |
| Cloud / datacenter risk? | **Likely `RequestBlocked`/`IpBlocked`** on AWS/GCP/Azure per upstream README — expect proxies before deploying the job to the Ubuntu host; keep soft-fail |
| Age-restricted / login-gated? | Mapped as `age_restricted`; **out of scope for K1** (no browser cookies) |
| No EN captions? | Soft-fail `no_captions` (e.g. Gangnam-style KO-only auto) |

Run: `python scripts/youtube_caption_poc.py <url-or-id> [--json] [--out file.txt]`

### K2 implementation notes (2026-07-29)

Shipped: `web_dashboard/youtube_articles.py`, `scripts/youtube_article_ingest.py`,
`youtube_transcript_summary` AI-queue job, `research_articles.source_metadata` migration,
`tests/test_youtube_articles.py`.

Run one video end to end (allowlist only — this does **not** discover videos):

```powershell
python scripts/youtube_article_ingest.py "https://www.youtube.com/watch?v=LPEXkI_4qI4" --source-id 3
python scripts/youtube_article_ingest.py LPEXkI_4qI4 --dry-run   # normalize + print, no DB, no LLM
python web_dashboard/scripts/apply_article_source_metadata_migration.py --apply
```

Enable queue-managed transcript summarize by adding `youtube_transcript_summary` to
`AI_QUEUE_JOBS` (with `AI_QUEUE_ENABLED=true`); without it, ingest summarizes inline like
`symbol_article_scraper_job`. `ingest_video` returns a status
(`saved` / `queued` / `skipped_exists` / `skipped_duration` / `soft_fail` / `error`) rather than
raising, so a K3 poller can walk an allowlist without dying on one blocked video.

**Where this plan was wrong about the codebase (corrected here, not in code):**

1. **`article_relevance_job` will never see these rows.**
   `ResearchRepository.save_article` stamps `ticker_validated_at = NOW()` unconditionally (both
   the embedding and non-embedding branches), and `update_article_analysis` does the same. The
   relevance job selects `WHERE ticker_validated_at IS NULL`, so **no** row created through
   `save_article` is ever re-validated — this is true for every ingest path today, not just K.
   The plan's "no code change if tickers set + `ticker_validated_at` null" is therefore
   unreachable. K2 does its own ticker validation via `extract_and_validate_tickers` at ingest
   (plus `youtube_sources.expected_tickers` as the lead). Changing the stamping behaviour is a
   cross-cutting decision for a separate PR, not a YouTube change.
2. **`claims` is not a safe metadata home.** The summarizer writes `claims` on every
   summarize/re-enrich, so provenance stored there is lost on the first re-run. Hence the
   additive `source_metadata` JSONB.
3. **`claim_recent_summary_input` is deliberately not used** for transcripts. Exact-URL dedup
   plus `article_exists` already prevent duplicate work per video, and two different videos
   cannot produce the same stitched caption hash. It would matter for chunked summarize (K3+).
4. **6k summarizer budget was the real bottleneck**, not the `content` cap — see the length
   section above.

---

## Phase J — Event / news catalyst backtesting

### Proposed schema (Research DB)

Sketch only — match local migration style when implementing:

```text
event_catalog
  id uuid PK
  slug text UNIQUE          -- e.g. covid_wave_1, ukraine_invasion_2022
  event_class text          -- pandemic, conflict_escalation, energy_shock, rate_panic, ...
  title text
  start_date date
  end_date date             -- inclusive window or peak window
  peak_date date NULL
  geo text NULL
  severity text NULL        -- ordinal later
  notes text
  created_at timestamptz

event_article_links
  event_id uuid FK
  article_id uuid FK        -- research_articles.id
  link_method text          -- date_overlap | theme_tag | manual | llm
  PRIMARY KEY (event_id, article_id)

event_backtest_results
  id uuid PK
  event_id uuid FK
  ticker text
  window_pre_days int
  window_post_days int
  excess_return numeric     -- vs chosen baseline
  baseline text             -- SPY | sector ETF | equal-weight peers
  realized_vol numeric NULL
  avg_dollar_volume numeric NULL  -- liquidity honesty
  metadata jsonb
  UNIQUE (event_id, ticker, window_pre_days, window_post_days, baseline)

event_playbooks
  event_class text
  ticker text
  sample_n int
  direction_hit_rate numeric
  median_excess_return numeric
  consistency_score numeric
  updated_at timestamptz
  PRIMARY KEY (event_class, ticker)
```

### Engines / jobs

| ID | Component | LLM? | Notes |
|----|-----------|------|-------|
| J1 | Seed script / admin SQL for `event_catalog` | No | Hand-label 8–15 windows first |
| J2 | `event_article_link_job` or offline script | Optional later | Date overlap + ticker/`theme` heuristics; LLM labeling = J6 |
| J3 | `event_backtest_engine` (library) + `event_backtest_job` | No | yfinance history; mirror liquidity math spirit from `liquidity_service` |
| J4 | `event_playbook_rollup_job` | No | Min-N gate (e.g. ≥2 events in class) |
| J5 | Surfacing | Light rules or cheap classifier | Today block + optional Ideas rows |

### Pipeline integration matrix (J)

| Pipeline | Integration | Work required |
|----------|-------------|---------------|
| `research_articles` | J2 reads existing rows; no change to ingest | Theme tags / geopolitics coverage already audited in cheap learns |
| Ticker meta | Optional later: if live `event_class` match, inject “### Event playbook prior” family (mirror H2 feature-flag pattern) | **After** J4 proves consistency — do not pollute bundles with weak priors |
| Sector meta / market brief | Optional: conflict/energy classes nudge `news_pressure` / regime narrative | Defer; I2 FRED stress is a better quantitative gate |
| Ideas | J5: insert synthetic idea cards **or** `article_type` promotion rows that `fetch_alpha_ideas` understands | Prefer explicit API section `event_rhymes` on Ideas/Today rather than overloading Alpha types |
| Today | New block in `build_today_briefing` | Same pattern as insider clusters / confluence |
| Evidence timeline | Optional `event_backtest` event_type for dossier when viewing a playbook ticker | Nice-to-have |
| Track-record / ROI | Separate from stance ROI — playbook hit rates live on `event_playbooks` | Do not conflate with `stance_outcomes` |
| YouTube (K) | J2 links YT articles inside windows like any article | Strengthens earnings/conflict video evidence packs |
| Liquidity (§4.3) | Persist `avg_dollar_volume` / days-to-exit proxy on backtest rows; hide illiquid names from J5 | **Required** for micro-cap honesty |

### Live rhyme detection (J5) — keep dumb at first

v0 rules (no LLM):

1. Recent articles (7d) whose titles/summaries match keyword lists per `event_class`, **or**
2. Manual “activate event_class” admin flag, **or**
3. (After I2) FRED stress / regime spike crosses threshold mapped to a class.

Then join `event_playbooks` for that class, filter holdings ∪ watchlist ∪ high-liquidity peers,
push top N to Today.

### Acceptance criteria (J)

- [ ] J1: ≥8 seeded events across ≥3 classes in Research DB.
- [ ] J3: deterministic fixture test — known window + mocked prices → expected excess return.
- [ ] J4: one-off spike ticker fails min-N; multi-event responder ranks.
- [ ] J5: feature-flagged Today block; disabled by default until spot-check.
- [ ] No writes to `ticker_meta_analysis` UPSERT path from J jobs.
- [ ] Docs: runbook for adding a new hand-labeled event.

---

## Sequencing relative to the rest of the roadmap

```text
H7 (Ideas usage) ──► I1 (story dedup) ──┬──► K1–K4 (allowlisted YT)
                                        ├──► J1–J4 (catalog + backtest + playbooks)
                                        └──► I2/I4 (macro/RSS) in parallel as appetite allows
                 K5 ROI slice ◄────────── after ~30d YT outcomes in stance evidence
                 J5 live surface ◄─────── after J4 min-N looks non-random
                 J6 / K6 optional ◄────── only if K5/J4 pay off
```

**Parallelism:** J1–J3 (math + seed) can proceed without K. K1–K2 PoC can proceed without J.
**Do not** start K3 volume ingest or J5 surfacing before I1 if news ROI already looks inflated
(H1 concern).

---

## Explicit non-goals

- Forking WorldMonitor AGPL news/conflict stacks for event detection.
- Building a separate “video insights” product surface or DB silo.
- Auto-trading or portfolio orders from playbooks / transcripts.
- Ingesting trending finance YouTube at large.
- Feeding `YouTube Transcript` into sector meta as fake ETF Analysis.
- Silently adding `YouTube Transcript` to Ideas’ Alpha/Opportunity filter without a product
  decision (H7 may show Ideas is unused — don’t train on empty triage).

---

## Agent kickoff snippets

### Phase K PoC

> Read `docs/ROADMAP.md` Phase K + this file’s Phase K sections. Implement **K1 only**:
> `web_dashboard/youtube_captions.py` + a `scripts/` PoC that prints cleaned caption text for
> a CLI video URL. Prefer `youtube-transcript-api`, VTT via yt-dlp as fallback. No DB writes,
> no scheduler registration. Tests with fixtures (sample timedtext JSON / VTT). Windows
> PowerShell; use repo venv.

### Phase J seed + engine

> Read `docs/ROADMAP.md` Phase J + this file’s Phase J sections. Implement **J1 schema + seed
> SQL** and a pure-Python **J3** excess-return helper with mocked OHLC fixtures. No Today UI,
> no LLM. Additive Research migrations only.

---

## Open questions (resolve during implementation, update this doc)

1. **Ideas product:** After H7, is Ideas worth extending for J5/K promotions, or should
   event rhymes be Today-only?
2. **Meta slot policy:** Should IR `YouTube Transcript` get a reserved bundle slot so six
   news blurbs cannot erase an earnings call?
3. ~~**`source` grain:**~~ **Resolved K2 (2026-07-29): channel-level.**
   `youtube:{channel_id}` → `youtube:@handle` → `youtube:{channel-slug}` → `youtube:unknown`.
   Bare `youtube.com` was rejected: a single host label would average a trusted IR channel with
   every macro pundit, which defeats the point of K5. Small-sample fragmentation is accepted —
   the allowlist is tiny by design, and `confidence_weight` on `youtube_sources` is the intended
   lever if per-channel N stays too low to rank.
4. ~~**Chunking policy**~~ **Resolved K2 (2026-07-29): stitch + single summarize**, 64k-char
   `content` cap + 16k-char summarizer budget, `source_metadata.truncated` flag. Revisit
   map-reduce before K3 volume if 16k is too lossy for hour-long calls.
5. **Event baseline:** SPY vs sector ETF vs peer basket — start SPY + one sector ETF map;
   document in playbook metadata.
