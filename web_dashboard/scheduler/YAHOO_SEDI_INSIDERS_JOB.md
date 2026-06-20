# Yahoo SEDI Insiders Job (ROADMAP G7)

## Overview

- **Job:** `yahoo_sedi_insiders_job`
- **Module:** `web_dashboard/scheduler/jobs_yahoo_sedi_insiders.py`
- **Service:** `web_dashboard/yahoo_sedi_insider_service.py`
- **Schedule:** Weekly Monday 07:00 ET (after `dilution_watch` at 06:30 ET)

Ingests Canadian insider transactions for production-fund holdings and active watchlist tickers ending in `.TO` or `.V` via `yfinance.Ticker(t).insider_transactions` (Yahoo's SEDI mirror). Rows upsert into Supabase `insider_trades` with `source='yahoo_sedi'`.

## Prerequisites

Apply migration before first run:

```sql
-- database/schema/supabase/migrations/add_insider_trades_source.sql
ALTER TABLE insider_trades ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'sec_form4';
```

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `YAHOO_SEDI_INSIDER_DAYS` | `365` | Only ingest rows whose `Start Date` is within this many days |

## Manual run

```powershell
cd web_dashboard
python scripts/run_scheduler_job_once.py yahoo_sedi_insiders
```

## Verification

```sql
SELECT ticker, source, COUNT(*)
FROM insider_trades
WHERE source = 'yahoo_sedi'
GROUP BY 1, 2
ORDER BY 3 DESC;
```

Re-run the job — row counts should not grow for unchanged Yahoo data (upsert on unique key).

## Limitations

- Best-effort Yahoo/SEDI mirror, not official SEDI
- Some tickers return no rows (e.g. CCO.TO in the 2026-06-14 probe)
- Option exercises, gifts, and redemptions are filtered out (not open-market conviction)

## Consumers (unchanged)

- `insider_clusters_service.build_insider_cluster_buys` — Today briefing + `/api/insiders/cluster-buys`
- `confluence_service` — insider cluster family
