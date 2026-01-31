# Congress Trades: Sessions vs Trade-Level Analysis

## Data sources (why we need both)

- **FMP API** (`fetch_congress_trades_job`) – returns only ~10–20 results per run, so we can miss a lot of trades.
- **Scraping job** (`scrape_congress_trades_job`) – runs `seed_congress_trades.py` to scrape a broader source (e.g. Capitol Trades) and backfill/update Supabase. Scheduled or run manually.

So we rely on **FMP for recent drip-feed** and **scraping for broader coverage**. The scrape job, on success, now runs **session backfill** so new scraped trades get linked to sessions for session-based AI analysis.

## Why sessions exist

- **~30k trades** in the DB; analyzing each one with the AI would mean ~30k Ollama calls.
- **Sessions** = groups of trades (same politician, within a 7-day gap). One AI call per session: we send a table of all trades in that window and get one `conflict_score` + `risk_pattern` for the whole batch, then store that score on the session and on each trade’s analysis row.
- So we get **~1.5k sessions → ~1.5k AI calls** instead of 30k, plus richer context (e.g. “small sell = divestment, large sell = dumping” in one prompt).

## How sessions are created today

| Mechanism | What it does | When it runs |
|-----------|--------------|--------------|
| **backfill_congress_sessions.py** | Reads all trades from Supabase, groups by politician + 7-day gap, inserts `congress_trade_sessions` and links trades in `congress_trades_analysis` (trade_id, session_id). | **After scrape job** (automatically on success), or **manual** when you want to (re)build sessions. |
| **Scrape job** | Runs `seed_congress_trades.py`, then on success runs **backfill_congress_sessions.py** so new scraped trades get session-linked. | Scheduled or manual (`scrape_congress_trades_job`). |
| **find_or_create_session()** | Would extend or create a session for one trade and update `congress_trade_sessions`. | **Not used** – no caller in the codebase. |

New trades from the **FMP fetch job** are analyzed one-by-one in `fetch_congress_trades_job` and written to `congress_trades_analysis` **without** a `session_id`; they are not grouped into sessions until you run backfill (e.g. after a scrape, or manually). New trades from the **scrape job** get session-linked automatically because the job runs backfill after a successful scrape.

## Two analysis modes in the batch script

1. **Session mode** (`--sessions`)  
   - Input: rows in `congress_trade_sessions` with `needs_reanalysis = TRUE` (or all if `--rescore`).  
   - For each session: resolve trades (from `congress_trades_analysis` by `session_id`, or fallback: Supabase by politician + date range).  
   - One AI call per session; save score to session and to each trade’s analysis row.

2. **Trade-level mode** (no `--sessions`, “legacy”)  
   - Input: trades from Supabase that don’t yet have analysis (or all if `--rescore`).  
   - One AI call per trade; save to `congress_trades_analysis` only (no session).

## Are we “properly” creating sessions?

- **Yes**, if you explicitly run backfill:  
  `python web_dashboard/scripts/backfill_congress_sessions.py`  
  That creates/updates `congress_trade_sessions` and links trades in `congress_trades_analysis`. After that, `--sessions` analysis can run and will find trades via those links (or via the politician+date fallback if a session has no links).
- **No** automatic pipeline: new trades from the fetch job are not assigned to sessions unless you run backfill again (or you add a step that does that).

## Do we need sessions going forward?

**Option A – Keep session-based analysis (fewer calls, richer context)**  
- Keep running backfill when you want to (re)group trades (e.g. after big imports or periodically).  
- Then run the batch script with `--sessions` as you do now.  
- Optional: run backfill after each fetch, or wire `find_or_create_session` + linking into the fetch job so new trades get session-linked without a full backfill.

**Option B – Simplify to trade-level only**  
- Ignore sessions for analysis: run the batch script **without** `--sessions` so it only does one AI call per (unscored) trade.  
- No need to create or maintain sessions for analysis; ~30k (or whatever unscored count) AI calls.  
- You can keep `congress_trade_sessions` for UI/display or deprecate it later.

**Recommendation**  
- If AI load and “session story” (intent per batch) matter: keep sessions and run backfill when you add new data, then analyze with `--sessions`.  
- If you prefer simplicity and are fine with more AI calls: use trade-level only (no `--sessions`) and treat sessions as optional or legacy.
