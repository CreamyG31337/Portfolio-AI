# Agent Prompt: Backfill trade_log.reason for Webull-imported trades

## Task

Write and execute a Python script that backfills the `reason` field in the `trade_log` Supabase table for all trades whose reason currently reads `'Imported from Webull (Row N) BUY'`. Replace each with a meaningful 1–2 sentence investment rationale, sourced from research documents already in the database where possible.

**Run in dry-run mode first** (print proposed changes, no writes). Only perform actual writes after the dry-run output looks correct.

---

## Context

This is a Flask/Python trading dashboard app. The working directory is `c:\Users\cream\Documents\LLM Trading Bot\LLM-Micro-Cap-trading-bot`. All scripts should be run from the `web_dashboard/` subdirectory or with it on the Python path.

### Database clients

Two databases in use:

**Supabase** (for portfolio data including trade_log):
```python
import sys
sys.path.insert(0, 'web_dashboard')
from supabase_client import SupabaseClient
supabase = SupabaseClient(use_service_role=True)
# Query: supabase.supabase.table('trade_log').select(...).execute()
# Update: supabase.supabase.table('trade_log').update({...}).eq('id', row_id).execute()
```

**PostgreSQL research DB** (for research_articles and ticker_analysis):
```python
from postgres_client import PostgresClient
pg = PostgresClient()
# Query: pg.execute_query("SELECT ...", (params,))
```

### LLM client (GLM via Z.AI API)

Use GLM the same way `thesis_update_job.py` does. The API key is loaded from env/secrets via:
```python
from glm_config import get_zhipu_api_key
```

API endpoint: `https://api.z.ai/api/coding/paas/v4/chat/completions`
Model: `glm-4.7`
Format: OpenAI-compatible (messages array, temperature, max_tokens)
The API sometimes rate-limits (429) — use exponential backoff with base delay of 15s, up to 5 retries.

---

## Step 1: Find trades to backfill

Query `trade_log` for all rows where reason matches the Webull import pattern:

```sql
SELECT id, fund, ticker, date, reason
FROM trade_log
WHERE reason LIKE 'Imported from Webull%'
ORDER BY ticker, fund
```

Group by ticker (both RRSP and TFSA have the same tickers — generate the rationale once per unique ticker, then apply it to all matching rows for that ticker across all funds).

---

## Step 2: Load research reports

Query all 6 research reports from the research DB:

```sql
SELECT id, title, tickers, fund, conclusion, content
FROM research_articles
WHERE article_type = 'Research Report'
```

Build a lookup: `ticker → list of matching reports` using the `tickers` array column. Note: some tickers in trade_log use `.TO` suffix (e.g. `FTS.TO`) while research reports may store as `FTS` — normalize by stripping `.TO` for matching, but keep the original ticker in the output.

The two CHIMERA-fund reports (`fund = 'CHIMERA'`) have `tickers = NULL` but contain the full portfolio thesis in `content`. For any ticker that appears in the CHIMERA fund's trade_log, search those two docs' `content` for the ticker symbol as a substring fallback.

---

## Step 3: Load fallback ticker analysis

For tickers without a research report match, query the research DB:

```sql
SELECT ticker, summary, stance, sentiment, confidence_score, analysis_date
FROM ticker_analysis
WHERE ticker = ANY(%(tickers)s)
ORDER BY analysis_date DESC
```

Use the most recent record per ticker as fallback context.

---

## Step 4: Generate rationales (3 tiers)

### Tier 1 — Research report available
Use `conclusion` + up to 3000 characters of `content` from the matching research report.

LLM system prompt:
```
You are writing a one-sentence investment rationale for a trade log. Be specific and factual. Do not use filler phrases like "based on the analysis" or "according to the report". Just state the investment thesis directly.
```

LLM user prompt:
```
Research report conclusion: {conclusion}

Relevant excerpt: {content_excerpt}

Write exactly one sentence (max 25 words) explaining why {ticker} was a buy candidate in September 2025. Focus on the specific investment thesis: valuation, growth drivers, or competitive advantage.
```

### Tier 2 — Individual stock, ticker_analysis fallback
Use `summary` + `stance` from `ticker_analysis`.

LLM user prompt:
```
Current analysis summary: {summary}
Current stance: {stance}

Write exactly one sentence (max 25 words) capturing the likely investment thesis for buying {ticker}. Note this is based on current analysis, not historical. Prefix with "Initial position: ".
```

### Tier 3 — ETF / index fund (no LLM needed)
Detect ETFs by checking if ticker matches known patterns or the `securities` table `asset_class = 'ETF'`. Use deterministic templates:

| Pattern | Template |
|---------|----------|
| VOO, VTI, VFV.TO, XEQT.TO, XIC.TO | "Broad market index exposure for passive diversification." |
| XGD.TO, CGL.TO, GLCC.TO, AEM.TO | "Gold/precious metals exposure as inflation hedge and portfolio diversifier." |
| BUG, CIBR, XHAK.TO | "Thematic cybersecurity ETF for sector exposure." |
| ITA, LHX (defense stocks) | "Defense/aerospace sector exposure." |
| ROBO, NXTG.TO | "Thematic robotics/next-gen technology ETF." |
| ZEA.TO, XHC.TO, FXD, FXG, FXL, FTXL | "Sector ETF for diversified thematic exposure." |

If no template matches, use: `"ETF held for thematic or sector diversification."`

---

## Step 5: Output / dry run

For each ticker, print:
```
TICKER: {ticker}
TIER: {1|2|3}
SOURCE: {report title | ticker_analysis | ETF template}
PROPOSED REASON: {generated rationale}
AFFECTS: {N} trade_log rows (funds: {list of funds})
---
```

After printing all, prompt: "Apply these updates? (y/n)"

If confirmed (or if run with `--apply` flag), execute:
```python
supabase.supabase.table('trade_log') \
    .update({'reason': generated_reason}) \
    .eq('ticker', ticker) \
    .like('reason', 'Imported from Webull%') \
    .execute()
```

---

## Step 6: Summary report

After applying, print:
- Total tickers processed
- Tier 1 count (research report)
- Tier 2 count (ticker_analysis fallback)
- Tier 3 count (ETF template)
- Any tickers skipped (no source found, LLM failed, etc.)

---

## Important constraints

- **Do not overwrite** any `trade_log.reason` that does NOT match `'Imported from Webull%'` — preserve DRIP entries, manual entries, etc.
- **Rate limit GLM carefully** — sleep 3s between successful API calls, use exponential backoff on 429
- **Rationale length:** keep under 30 words. This is a trade log field, not an essay.
- **One rationale per unique ticker** — both RRSP and TFSA funds get the same reason for the same ticker
- The script should be runnable as a standalone Python file from the project root directory
