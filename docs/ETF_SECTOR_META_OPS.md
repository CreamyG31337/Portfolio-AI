# ETF → Sector Meta (ops cheat sheet)

**Program context:** This pipeline is one layer in the [meta analysis roadmap](meta_analysis_roadmap.md). The long-term goal is **actionable buy/sell guidance** (human-in-the-loop); sector meta is **rotation context**, not trade orders. The stack is built incrementally as we learn what the data supports.

## Pipeline (three steps)

Sector Insights on the ETF Holdings page is **not** reading raw holdings. It reads AI output built in order:

```text
etf_watchtower (nightly)  →  Research.etf_holdings_log
etf_group_analysis        →  Research.research_articles  (type: "ETF Analysis")
sector_meta_analysis      →  Research.sector_meta_analysis
```

Downstream (not ops on this page, see roadmap):

```text
ticker_meta_analysis      →  per-ticker conviction (sector prior = Phase 3c, not shipped)
action_queue              →  signal rules + meta context (not auto-trade)
```

## When to run a catch-up

- Sector Insights dates or stances look months old.
- ETF Holdings shows recent dates but Sector Insights does not.
- After deploy, outage, or any period when `etf_group_analysis` did not run.
- After the 2026-05 migration: holdings live on **Research only** (Supabase `etf_holdings_log` was dropped).

## One command (manual catch-up)

From repo root with venv activated:

```powershell
python web_dashboard\scripts\backfill_etf_sector_meta.py
```

That script:

1. Prints which days are missing ETF Analysis articles.
2. Purges stale `ai_analysis_queue` rows outside the lookback window (old pending rows used to starve May work).
3. Runs `etf_group_analysis` repeatedly (6 ETFs per run) until gaps are filled, `--max-runs` is hit, or **two consecutive runs fill zero pairs**.
4. Runs `sector_meta_analysis` once to refresh Sector Insights.

**Progress detection:** each run compares missing `(etf, date)` snapshots. Filling 6 pairs while watchtower adds 8 new same-day gaps is still progress; the script only stalls when **zero** pairs were filled for `--max-stall-runs` consecutive runs (default 2).

Options:

```powershell
# After a long outage (up to 30 days of queue)
python web_dashboard\scripts\backfill_etf_sector_meta.py --lookback-days 30 --max-runs 35

# See gaps only
python web_dashboard\scripts\backfill_etf_sector_meta.py --report-only

# Allow more empty runs before giving up (e.g. AI lock contention)
python web_dashboard\scripts\backfill_etf_sector_meta.py --max-stall-runs 4
```

## Automatic catch-up (nightly)

Each `etf_group_analysis` cron run:

- Queues missing (ETF, date) pairs for **14 days** by default.
- Expands to **30 days** automatically when gaps remain.

Implementation: `web_dashboard/etf_meta_pipeline.py` (`get_etf_queue_lookback_days`).

A week offline usually heals within several nights (~6 articles per night). A month offline typically needs **one** manual backfill pass.

Env vars (optional):

| Variable | Default | Meaning |
|----------|---------|---------|
| `ETF_GROUP_QUEUE_LOOKBACK_DAYS` | `14` | Normal queue window |
| `ETF_GROUP_QUEUE_MAX_LOOKBACK_DAYS` | `30` | Max auto-expansion when behind |
| `META_ANALYSIS_PHASE3_SECTOR` | on | Kill-switch for sector meta job |

## Prerequisites (minimal)

| Step | Required? | Notes |
|------|-----------|--------|
| Holdings in Research | Yes | Watchtower; ETF Holdings page shows recent dates |
| Supabase `etf_holdings_log` | **No** | Removed May 2026 |
| Ollama / LLM | Yes | Summarizing model chain |
| AI lock | Usually free | Backfill waits; `--ignore-ai-lock` only if intentional |

## Gap report only

```powershell
python web_dashboard\scripts\etf_meta_gap_report.py
```

## Related jobs (different features)

| Job | Role |
|-----|------|
| `ticker_meta_analysis` | Per-ticker second-order synthesis; needs sector prior (3c) for full ETF→ticker chain |
| `ticker_analysis` | First-order ticker JSON (can include BUY/SELL/HOLD in output) |
| `action_queue` | Technical signal alerts; meta is context only today |

## Files to know

| File | Purpose |
|------|---------|
| `web_dashboard/scripts/backfill_etf_sector_meta.py` | One-shot catch-up |
| `web_dashboard/scripts/etf_meta_gap_report.py` | Gap table |
| `web_dashboard/etf_meta_pipeline.py` | Shared lookback / gap counting |
| `web_dashboard/scheduler/jobs_etf_analysis.py` | Nightly ETF group job |
| `web_dashboard/scheduler/jobs_sector_meta_analysis.py` | Nightly sector meta job |
