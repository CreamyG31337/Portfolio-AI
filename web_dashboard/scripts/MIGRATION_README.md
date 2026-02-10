# Congress Trades Pipeline

## Current Production Workflow

Congress trades are fetched directly from the FMP (Financial Modeling Prep) API and inserted into the `congress_trades` table. There is no staging step.

### Scheduled Jobs:
1. **`fetch_congress_trades_job`** - Fetches trades from FMP API, analyzes with AI, upserts to `congress_trades`
2. **`analyze_congress_trades_job`** - Scores unanalyzed trades via Ollama
3. **`scrape_congress_trades_job`** (manual) - Scrapes from external source via `seed_congress_trades.py`

### Manual Scripts:
- `seed_congress_trades.py` - Manual import from external source
- `analyze_congress_trades_batch.py` - Batch AI analysis

---

## AI Analysis Notes

AI analysis is stored in PostgreSQL `congress_trades_analysis` table with foreign key to `congress_trades.id`.

If migration breaks AI analysis:
```bash
python web_dashboard/scripts/fix_ai_analysis_references.py
```

This deletes orphaned analyses - they'll regenerate on next AI run.

---

## Historical Note

The `congress_trades_staging` table and staging-to-production workflow were removed in Feb 2026.
The old workflow (scrape -> staging -> validate -> promote) was replaced by the current direct-insert pipeline.
