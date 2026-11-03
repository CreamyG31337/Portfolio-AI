# Data-usage audit — does everything we collect feed a decision?

**Run 2026-11-03** against production (Supabase + Research DB, read-only). Re-run this
whenever a job "succeeds" but you haven't seen its output in a while — every bug below
was a job reporting success.

Legend: **Feeds** = reaches a stance (ticker / meta analysis bundle), Today/Ideas, or the
Action Queue. **UI only** = shown on a page, never used by analysis. **Void** = written,
read by nothing.

## Broken collection (job reports success, saves ~nothing)

| Source | Symptom | Cause | Status |
|---|---|---|---|
| **Insider trades** (`insider_trades`, 136k rows) | ~600/wk until mid-Aug, then ~0–20/wk. Log: `Found 1000 trades: 0 new, 0 duplicates, 185 old, 1 errors` (≈815 unaccounted) | Bolt batching (commit `681286c`) upserts the whole page in one statement; the page repeats a few conflict keys (4 of 1000 on 2026-11-03), so Postgres rejects the batch and every row is lost. Source only holds the latest 1000, so ~2 months are unrecoverable from it. | Fix: dedupe by conflict key, chunk, fall back per-row |
| **Opportunity Discovery** (article type, 264 rows) | Nothing saved since 2026-07-25; runs daily in ~4s | Query picked by `datetime.now().hour % len(queries)`; job now runs once a day at 04:15 UTC, so it runs query #4 ("biotech clinical trial results \<month\>") every day — returns nothing. 7 of 8 queries never run. Today/Ideas reads this type. | Fix: rotate by day |
| **RSS feeds** | Never collected | Job defined, never scheduled | ✅ fixed 2026-11-02 (#660). Investing.com feed still never fetches |
| **YouTube summaries** | ~25% of Sep–mid-Oct transcripts had leaked model reasoning as the summary | GLM truncation (fixed mid-Oct) | ✅ 147 re-summarized 2026-11-02 |
| **Per-ticker sentiment** | Column empty on 100% of articles | Generated, never saved | ✅ fixed 2026-11-02 (#661) |
| **ETF Change articles** | Newest `fetched_at` 2026-08-18 though the job runs daily | One fixed URL per ETF + upsert on URL → each day overwrites the same row, date never advances, so it falls out of every evidence window | Low priority: same data reaches analysis via `etf_holdings_changes` |

## Collected but not used by analysis

| Source | Volume | Read by | Opportunity |
|---|---|---|---|
| **Newsletters** (`newsletters`) | 737 total, 174 in 30d, 675 with tickers, all AI-summarized (claims, sentiment, conclusion) | UI only (`app.py`, research routes) | **Biggest gap.** Same shape as articles; add to the ticker/meta article evidence (or land them as an article type). Curated by you, so likely higher quality than SearXNG. |
| **Market relationships** (`market_relationships`) | 5,007 supplier/competitor links, written by 4 research jobs | Void (only `check_relationships.py`) | Peer context: "news on a supplier/competitor of a holding". Could feed the dossier or a meta "peers" block. |
| **Congress realized returns** (`congress_trade_returns` 50k, `congress_positions` 3k) | Daily jobs | UI only | Weight congress evidence by the politician's track record (the 5.1b leaderboard data already exists). |
| **Congress sessions** (`congress_trade_sessions`) | 1,548 rows, last write 2025-12-30 | Meta-analysis reads summaries by id | Stale: `rescore_congress_sessions` is unscheduled. Either reschedule or stop citing them. |
| `ticker_theses` | 123 rows, last write 2026-08-22 | settings / grok thesis / insights | Looks superseded by `thesis_entries`; confirm and retire. |
| `post_summaries` | 0 rows | `social_service.py` | Dead code path. |

## What actually feeds stances (last 30 days)

Evidence families in `stance_history.metadata.evidence.artifact_types`:

- **Ticker analysis** (999 stances): social 100%, fundamentals 100%, signals 99%, price 98%,
  articles 73%, ETF changes 40%, congress 27%, insider 11% (low because collection broke).
- **Meta analysis** (1,806): standard analysis / prior stance / regime / sector prior / signals
  ~100%, human thesis 74%, social 72%, articles 72%, congress 57%, confluence 11%, dilution 10%,
  filing 6%, insider cluster 1%.

**Does any family help?** 30d after-cost edge vs the shuffled baseline, stances with vs without
each family. Correlational only (families aren't randomly assigned), and stances are overlapping
daily calls.

| | All | Notable |
|---|---|---|
| Ticker analysis (n=1,065) | **−2.9pp**, −0.92 mean excess | with insider −6.0pp vs without −0.2pp; nothing clearly positive |
| Meta analysis (n=2,038) | **+0.7pp**, −0.91 | no family moves edge more than ~±1.5pp |

Stances *without* articles score +22–25pp, but they're a small (n≈130–200), unusual group
(likely ETFs / thin-coverage names with few directional calls). Worth one look before reading
anything into it.

Takeaway: the system is roughly at chance overall. Adding more feeds won't fix that by itself;
the leverage is in **quality of what's fed** (dead sources, stale summaries, per-ticker
sentiment, curated sources like newsletters and the YouTube allowlist).

## Ranked opportunities

1. **Fix insider ingest** — losing ~600 rows/week every day it waits. Small.
2. **Fix Opportunity Discovery rotation** — Ideas has been missing one of its two sources since July. Small.
3. **Feed newsletters into ticker/meta evidence** — curated, already summarized, unused. Medium.
4. **Sweep blocklist / promotion** (ROADMAP K12/K13). Small–medium.
5. **Weight congress evidence by politician track record** using `congress_trade_returns`. Medium.
6. **Peers block from `market_relationships`**. Medium.
7. Housekeeping: reschedule or drop congress sessions; ETF Change article URL per day (or drop
   the article and rely on the table); retire `ticker_theses` / `post_summaries`; Investing.com feed.

## How this was measured

- Freshness: row counts, newest row and last-7-day rows per table (both DBs).
- Consumers: `grep` for each table across `web_dashboard/` excluding tests/scripts/debug.
- Usage: `stance_history` evidence families joined to `stance_outcomes` (30d), scored with
  `track_record_service.compute_baselines` + the after-cost rule
  (helper: `web_dashboard/scripts/k5_youtube_source_roi.py::stats`).
- Job health: `job_executions` messages; "success" with suspicious counters was the main tell.
