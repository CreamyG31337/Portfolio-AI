# ETF → Sector Meta (ops cheat sheet)

Sector Insights on the ETF Holdings page is **not** reading raw holdings. It reads AI output built in two steps:

```text
etf_watchtower (nightly)  →  Research.etf_holdings_log
etf_group_analysis        →  Research.research_articles  (type: "ETF Analysis")
sector_meta_analysis      →  Research.sector_meta_analysis
```

If the site is down or deploys break the ETF group job, Sector Insights goes stale even when holdings look fine.

## When to run a catch-up

- Sector Insights dates or stances look months old.
- ETF Holdings shows recent dates but Sector Insights does not.
- After fixing the Research-backed ETF group job (post–Supabase holdings drop).

## One command (manual catch-up)

From repo root with venv activated:

```powershell
python web_dashboard\scripts\backfill_etf_sector_meta.py
```

That script:

1. Prints which days are missing ETF Analysis articles.
2. Runs `etf_group_analysis` repeatedly (6 ETFs per run) until gaps in the lookback window are filled or `--max-runs` is hit.
3. Runs `sector_meta_analysis` once to refresh Sector Insights.

Options:

```powershell
# After a long outage (up to 30 days of queue)
python web_dashboard\scripts\backfill_etf_sector_meta.py --lookback-days 30 --max-runs 35

# See gaps only
python web_dashboard\scripts\backfill_etf_sector_meta.py --report-only
```

## Automatic catch-up (nightly)

Each `etf_group_analysis` cron run:

- Queues missing (ETF, date) pairs for **14 days** by default.
- Expands to **30 days** automatically when gaps remain (env: `ETF_GROUP_QUEUE_MAX_LOOKBACK_DAYS`).

So a week offline usually heals within a few nights (~6 articles per night). A month offline may need **one** manual `backfill_etf_sector_meta.py` pass.

Env vars (optional):

| Variable | Default | Meaning |
|----------|---------|---------|
| `ETF_GROUP_QUEUE_LOOKBACK_DAYS` | `14` | Normal queue window |
| `ETF_GROUP_QUEUE_MAX_LOOKBACK_DAYS` | `30` | Max auto-expansion when behind |
| `META_ANALYSIS_PHASE3_SECTOR` | on | Kill-switch for sector meta job |

## Prerequisites (nothing else)

| Step | Required? | Notes |
|------|-----------|--------|
| Holdings in Research | Yes | Watchtower job; already running if ETF Holdings page has recent dates |
| Supabase `etf_holdings_log` | **No** | Removed; Research only |
| Ollama / LLM up | Yes | ETF group + sector meta use summarizing model |
| AI lock free | Usually | Backfill script waits; use `--ignore-ai-lock` only if you know another backend is free |

## Gap report only

```powershell
python web_dashboard\scripts\etf_meta_gap_report.py
```

## Related jobs (different feature)

- **`ticker_meta_analysis`** — per-ticker conviction cards; not required for Sector Insights.
