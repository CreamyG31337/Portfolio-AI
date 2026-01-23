# ETF AI Analysis System - Technical Summary

## Overview

This system uses LLMs to analyze ETF holdings changes and individual tickers, generating structured insights that are stored in the database for retrieval and semantic search.

---

## System Architecture

### Two Analysis Types

#### 1. **ETF Group Analysis** (ETF-level)
- **What**: Analyzes all holdings changes for a single ETF on a specific date as a group
- **When**: Daily at 9:00 PM EST (after ETF Watchtower job)
- **Input**: All significant changes (>= 1000 shares OR >= 0.5% change) for one ETF on one date
- **Output**: Research article stored in `research_articles` table
- **Job**: `etf_group_analysis_job()` in `web_dashboard/scheduler/jobs_etf_analysis.py`

#### 2. **Ticker Analysis** (Ticker-level)
- **What**: Comprehensive analysis of a single ticker using 3 months of multi-source data
- **When**: Daily at 10:00 PM EST, runs for max 2 hours (resumable)
- **Input**: 3 months of data from multiple sources (see below)
- **Output**: Structured analysis stored in `ticker_analysis` table
- **Job**: `ticker_analysis_job()` in `web_dashboard/scheduler/jobs_ticker_analysis.py`

---

## Data Sources for Ticker Analysis

The ticker analysis gathers data from:

1. **Price Data** (via yfinance): OHLCV, 52-week range, volume metrics, recent price action
2. **ETF Changes** (max 50): All ETFs that bought/sold this ticker
3. **Congress Trades** (max 30): Politician transactions
4. **Technical Signals**: Buy/sell signals from signal analysis
5. **Fundamentals**: Company financials from `securities` table
6. **Research Articles** (max 10): Articles mentioning the ticker
7. **Social Sentiment**: StockTwits/Reddit sentiment metrics

**Time Window**: 90 days (3 months) lookback period

---

## LLM Prompt Style

### ETF Group Analysis Prompt

**Style**: Structured JSON output with specific fields

**Input Context**:
- ETF name and ticker
- Date being analyzed
- ETF fund description (if available in `securities.fund_description`)
- Table of holdings changes (sorted by magnitude, max 200 rows)

**Output Format** (JSON):
```json
{
    "pattern": "accumulation|distribution|rotation|mixed|rebalancing",
    "sentiment": "BULLISH|BEARISH|NEUTRAL|MIXED",
    "sentiment_score": 0.0 to 1.0,
    "themes": ["theme1", "theme2"],
    "summary": "1-2 sentence summary",
    "analysis": "Full analysis paragraph",
    "notable_changes": [
        {"ticker": "XYZ", "action": "BUY", "reason": "why notable"}
    ]
}
```

**Key Task**: Analyze changes as a GROUP to identify overall patterns, themes, and alignment with ETF's investment strategy.

### Ticker Analysis Prompt

**Style**: Structured JSON output with **actionable trading analysis**

**Input Context**:
- Pre-formatted tables of all data sources (ETF changes, congress trades, signals, fundamentals, articles, sentiment)
- **Price data** including OHLCV, 52-week range, and volume metrics (added 2025-01)
- Formatted similar to AI context builder (no LLM tools - all data pre-fetched)

**Output Format** (JSON):
```json
{
    "sentiment": "BULLISH|BEARISH|NEUTRAL|MIXED",
    "sentiment_score": -1.0 to 1.0,
    "confidence_score": 0.0 to 1.0,
    "stance": "BUY|SELL|HOLD|AVOID",
    "timeframe": "day_trade|swing|position",
    "entry_zone": "$45-47 or null",
    "target_price": "$52 or null",
    "stop_loss": "$42 or null",
    "key_levels": {
        "support": ["$45", "$42"],
        "resistance": ["$50", "$55"]
    },
    "catalysts": ["catalyst 1", "catalyst 2"],
    "risks": ["risk 1", "risk 2"],
    "invalidation": "What would invalidate this thesis",
    "themes": ["key theme 1", "key theme 2"],
    "summary": "1-2 sentence actionable summary",
    "analysis_text": "3-5 paragraph detailed analysis with evidence",
    "reasoning": "Internal reasoning for this assessment"
}
```

**Key Task**: Provide **actionable** analysis with trading stance, price levels, catalysts, and risks based on institutional activity, congressional trading, price action, and research mentions.

---

## Storage

### ETF Group Analysis → `research_articles` Table

**Location**: Research Database (PostgreSQL)

**Key Fields**:
- `title`: "{ETF_TICKER} Holdings Analysis - {DATE}"
- `content`: Full analysis paragraph
- `summary`: 1-2 sentence summary
- `article_type`: "ETF Analysis"
- `tickers`: Array of top 10 holding tickers that changed
- `sentiment`: BULLISH/BEARISH/NEUTRAL/MIXED
- `sentiment_score`: 0.0 to 1.0
- `published_at`: Date of analysis

**Unique Identifier**: `url` field uses format: `etf-analysis://{ETF_TICKER}/{DATE}`

### Ticker Analysis → `ticker_analysis` Table

**Location**: Research Database (PostgreSQL)

**Key Fields**:
- `ticker`: Ticker symbol
- `analysis_date`: Date analysis was run
- `data_start_date` / `data_end_date`: Time window analyzed (e.g., 3 months)
- `sentiment`: BULLISH/BEARISH/NEUTRAL/MIXED
- `sentiment_score`: -1.0 to 1.0
- `confidence_score`: 0.0 to 1.0
- `themes`: Array of themes (TEXT[])
- `summary`: 1-2 sentence summary
- `analysis_text`: Full detailed analysis
- `reasoning`: Internal reasoning
- `input_context`: **Exact text sent to LLM** (for debugging)
- `embedding`: Vector(768) - **generated from summary field**
- `etf_changes_count` / `congress_trades_count` / `research_articles_count`: Data source counts
- `requested_by`: User email (NULL = scheduled job)

**Unique Constraint**: `(ticker, analysis_type, analysis_date)` - one analysis per ticker per day

**Vector Index**: `embedding` column has IVFFlat index for semantic similarity search

---

## Embedding Generation

**What Gets Embedded**: The `summary` field (1-2 sentence summary), or `analysis_text` if summary is empty

**Why Summary**: 
- Concise representation of key themes
- Better for semantic search (less noise)
- Faster embedding generation
- More consistent similarity matching

**Vector Dimensions**: 768 (using Ollama's embedding model)

**Storage Format**: PostgreSQL `vector(768)` type with pgvector extension

**Usage**: Currently generated but **not actively used** - available for:
- Finding similar tickers by theme/sentiment
- Semantic search queries
- Portfolio recommendations
- Theme-based discovery

---

## Job Scheduling

### ETF Group Analysis Job

**Schedule**: Daily at 9:00 PM EST
**Trigger**: After ETF Watchtower job completes
**Resumability**: Uses `ai_analysis_queue` table
**Concurrency Protection**: Checks `job_executions` table before starting

**Process**:
1. Check queue for pending ETF analyses
2. If empty, queue today's ETFs with changes
3. For each ETF/date:
   - Fetch changes from `etf_holdings_changes` view
   - Get ETF metadata (fund description) from `securities` table
   - Format changes as table (max 200)
   - Send to LLM with ETF context
   - Save as research article

### Ticker Analysis Job

**Schedule**: Daily at 10:00 PM EST
**Duration Limit**: 2 hours max, then resumes next day
**Resumability**: Automatically resumes where it left off (freshness check skips recently analyzed)
**Concurrency Protection**: Checks `job_executions` table before starting

**Priority Queue**:
1. **Manual requests** (priority=1000): User-requested re-analysis
2. **Holdings** (priority=100): Tickers in current portfolio positions
3. **Watched tickers** (priority=10): Tickers on watchlist

**Process**:
1. Get prioritized list of tickers to analyze
2. For each ticker:
   - Skip if analyzed within last 24 hours
   - Skip if in `ai_analysis_skip_list`
   - Gather 3 months of multi-source data
   - Format as context string
   - Send to LLM
   - Generate embedding from summary
   - Save to `ticker_analysis` table
3. Stop after 2 hours, remaining tickers processed next day

---

## Skip List Management

**Table**: `ai_analysis_skip_list` (Supabase)

**Purpose**: Track tickers that failed analysis and should be skipped

**Auto-Skip Logic**: After 3 consecutive failures, ticker is automatically added to skip list

**Admin UI**: Available at `/admin/ai-settings` - shows failed tickers with clickable links

**Manual Override**: Users can request re-analysis via button on ticker details page, which removes ticker from skip list

---

## API Endpoints

### Ticker Analysis

- `GET /api/v2/ticker/<ticker>/analysis` - Get latest analysis for a ticker
- `POST /api/v2/ticker/<ticker>/reanalyze` - Queue manual re-analysis (priority=1000)

### ETF Metadata (Admin)

- `GET /api/admin/etf-metadata` - Get all ETFs with metadata
- `PUT /api/admin/etf-metadata/<ticker>` - Update ETF fund description

---

## UI Integration

### Ticker Details Page

**Location**: `/ticker?ticker={SYMBOL}`

**Features**:
- Displays latest AI analysis (sentiment, themes, summary, full analysis)
- "Re-Analyze" button (queues manual re-analysis)
- Debug panel (collapsible) showing `input_context` - exact text sent to LLM
- Shows data source counts and analysis date

### Admin Pages

- **ETF Metadata** (`/admin/etf-metadata`): Edit fund descriptions for ETFs
- **AI Settings** (`/admin/ai-settings`): View skip list, manage AI settings

---

## Key Design Decisions

1. **No LLM Tools**: All data is pre-fetched and formatted as text tables (like AI context builder)
2. **Single Source of Truth**: ETF changes computed from view, not duplicate table
3. **Resumable Jobs**: Queue-based system allows jobs to resume after interruption
4. **Freshness Check**: 24-hour skip prevents redundant analysis
5. **Priority Queue**: Manual requests > Holdings > Watched tickers
6. **Time Limits**: Ticker analysis stops after 2 hours to prevent long-running jobs
7. **Debug Visibility**: `input_context` stored for transparency
8. **Vector Search Ready**: Embeddings generated but not yet actively used

---

## LLM Configuration

**Model**: Uses `get_summarizing_model()` (typically `granite3.3:8b`)

**Settings**:
- `json_mode=True`: Forces structured JSON output
- `temperature=0.1`: Low temperature for consistent, factual analysis
- `system_prompt`: "You are a financial analyst. Return ONLY valid JSON with the exact fields specified."

**Embedding Model**: Uses Ollama's embedding endpoint (generates 768-dim vectors)

---

## Data Flow Summary

```
ETF Watchtower (8 PM)
  ↓
Store holdings → etf_holdings_log
  ↓
ETF Group Analysis (9 PM)
  ↓
Query etf_holdings_changes view
  ↓
For each (ETF, date):
  - Get fund description from securities
  - Format changes table (max 200)
  - LLM analysis → research_articles

Ticker Analysis (10 PM)
  ↓
Get priority list: manual > holdings > watched
  ↓
For each ticker (2 hour limit):
  - Skip if < 24 hours old
  - Skip if in skip_list
  - Gather 3 months: ETF changes, congress, signals, fundamentals, articles, sentiment
  - Format as context string
  - LLM analysis → ticker_analysis
  - Generate embedding from summary → ticker_analysis.embedding
```

---

## Future Opportunities

1. **Vector Search**: Use embeddings to find similar tickers by theme/sentiment
2. **AI Assistant Integration**: Include similar tickers in context when user asks about a ticker
3. **Portfolio Recommendations**: Suggest tickers similar to current holdings
4. **Theme Discovery**: Search for tickers by investment theme (e.g., "AI", "semiconductors")
5. **Comparative Analysis**: Show similar tickers on ticker details page

---

## Files Reference

**Services**:
- `web_dashboard/etf_group_analysis.py` - ETF group analysis service
- `web_dashboard/ticker_analysis_service.py` - Ticker analysis service
- `web_dashboard/ai_skip_list_manager.py` - Skip list management

**Jobs**:
- `web_dashboard/scheduler/jobs_etf_analysis.py` - ETF group analysis job
- `web_dashboard/scheduler/jobs_ticker_analysis.py` - Ticker analysis job

**Prompts**:
- `web_dashboard/ai_prompts.py` - Contains `ETF_GROUP_ANALYSIS_PROMPT` and `TICKER_ANALYSIS_PROMPT`

**Database**:
- `database/schema/research/tables/ticker_analysis.sql` - Ticker analysis table
- `database/schema/supabase/tables/ai_analysis_queue.sql` - Job queue
- `database/schema/supabase/tables/ai_analysis_skip_list.sql` - Skip list
- `database/schema/supabase/views/etf_holdings_changes_view.sql` - ETF changes view
- `database/schema/supabase/migrations/add_etf_metadata_to_securities.sql` - ETF metadata column

**UI**:
- `web_dashboard/templates/ticker_details.html` - Ticker details page
- `web_dashboard/src/js/ticker_details.ts` - Ticker details TypeScript
- `web_dashboard/templates/etf_metadata.html` - ETF metadata admin page
- `web_dashboard/src/js/etf_metadata.ts` - ETF metadata TypeScript
