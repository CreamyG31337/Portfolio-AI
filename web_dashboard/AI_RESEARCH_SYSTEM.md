# AI Research System Documentation

## Overview

The AI Research System is an automated intelligence gathering and analysis platform that continuously monitors financial markets, extracts relevant news articles, and provides AI-powered insights through semantic search. The system combines web scraping, AI summarization, and vector embeddings to create a searchable knowledge base of financial information.

## Architecture

### Core Components

1. **SearXNG Client** (`searxng_client.py`)
   - Privacy-respecting metasearch engine
   - Aggregates results from multiple search engines
   - Provides web search and news search capabilities
   - Handles rate limiting and retries

2. **Ollama Client** (`ollama_client.py`)
   - Local LLM integration (runs in Docker)
   - Generates article summaries with structured metadata
   - Creates vector embeddings (768 dimensions) for semantic search
   - Extracts tickers, sectors, and key themes from articles
   - Writes JSONL audit records for AI inference calls (summary, crowd sentiment, embeddings)

3. **AI Audit Trail** (`ai_audit.py`)
   - Lightweight, thread-safe JSONL logging for AI inference events
   - Daily log files in `web_dashboard/logs/ai_audit/YYYY-MM-DD.jsonl`
   - Captures model/provider, caller, duration, success/error, and compact input/output metadata
   - Includes automatic log retention cleanup (default 30 days)

4. **Research Repository** (`research_repository.py`)
   - PostgreSQL database for storing articles
   - Vector similarity search using pgvector
   - CRUD operations for research articles
   - Handles ETF ticker lookups (returns sector articles)

5. **Research Utils** (`research_utils.py`)
   - Content extraction using Trafilatura
   - Domain blacklist management
   - Article content cleaning and normalization

6. **Domain Health Tracker** (`research_domain_health.py`)
   - Monitors domain reliability
   - Auto-blacklists domains with repeated failures
   - Tracks success/failure rates per domain

## Automated Background Jobs

The system runs three scheduled jobs that continuously collect and process financial news:

### 1. Market Research Job
**Schedule:** Every 6 hours  
**Purpose:** Collect general market news and trends

**Process:**
1. Searches for general market news using SearXNG
2. Extracts article content using Trafilatura
3. Generates AI summaries with Ollama (extracts sectors/themes)
4. Creates vector embeddings for semantic search
5. Saves to database with `article_type="market_news"`

**Query Examples:**
- "stock market news today"
- "financial markets analysis"
- "economic indicators"

### 2. Ticker Research Job
**Schedule:** Every 6 hours  
**Purpose:** Monitor news for specific portfolio holdings

**Process:**
1. Identifies all tickers in production funds
2. **ETF Handling:** 
   - Detects ETFs (ticker/company name contains "ETF")
   - Queries securities table for ETF sectors
   - Researches sectors instead of individual ETF tickers
   - Saves sector articles with `ticker=NULL, sector=<sector>`
3. **Regular Tickers:**
   - Searches for news specific to each ticker
   - Uses company name for better search results
4. Generates summaries and embeddings
5. Saves to database with `article_type="ticker_news"`

**Query Examples:**
- "AAPL Apple stock news"
- "Technology sector news investment" (for ETFs)

### 3. Opportunity Discovery Job
**Schedule:** Every 12 hours  
**Purpose:** Hunt for new investment opportunities

**Process:**
1. Rotates through discovery queries (one per run)
2. Searches for relevant opportunities
3. Extracts tickers and sectors from articles
4. Saves with `article_type="opportunity_discovery"`

**Query Examples:**
- "undervalued microcaps"
- "emerging technology stocks"
- "small cap growth opportunities"

## Data Flow

```
┌─────────────┐
│  SearXNG    │  ← Web search for articles
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Trafilatura │  ← Extract article content
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Ollama   │  ← Generate summary + embedding
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  PostgreSQL │  ← Store article + vector
└─────────────┘
```

## Article Storage Schema

```sql
CREATE TABLE research_articles (
    id UUID PRIMARY KEY,
    ticker VARCHAR(20),              -- NULL for sector/market articles
    sector VARCHAR(100),            -- Sector name (e.g., "Technology")
    article_type VARCHAR(50),       -- 'ticker_news', 'market_news', 'opportunity_discovery'
    title TEXT NOT NULL,
    url TEXT UNIQUE,                -- Prevents duplicates
    summary TEXT,                   -- AI-generated summary
    content TEXT,                   -- Full article text
    source VARCHAR(100),            -- Source name
    published_at TIMESTAMP,
    fetched_at TIMESTAMP,
    relevance_score DECIMAL(3,2),   -- 0.00 to 1.00
    embedding vector(768)           -- For semantic search
);
```

## AI Assistant Integration

The AI Assistant page (`pages/ai_assistant.py`) provides two search modes:

### 1. Live Web Search
- Uses SearXNG to search the web in real-time
- Filters results for relevance to portfolio tickers
- Provides up-to-the-minute information

### 2. Repository Search
- Searches stored articles using vector similarity
- Finds semantically similar articles to user queries
- Uses cosine similarity on embeddings
- Configurable similarity threshold (default: 0.5)

**Search Flow:**
```
User Query
    │
    ├─→ Generate Embedding (Ollama)
    │
    └─→ Vector Similarity Search (PostgreSQL)
        │
        └─→ Return Top N Similar Articles
```

## ETF Handling

The system intelligently handles ETFs:

1. **Detection:** Checks if ticker or company name contains "ETF"
2. **Sector Lookup:** Queries `securities` table for ETF's sector
3. **Research Strategy:** Researches sector instead of individual ETF
4. **Storage:** Saves articles with `ticker=NULL, sector=<sector>`
5. **Retrieval:** When searching for ETF ticker, also returns sector articles

**Example:**
- ETF: `SPY` (S&P 500 ETF) → Sector: `"Technology"` (or other sectors)
- Research query: `"Technology sector news investment"`
- Articles saved: `ticker=NULL, sector="Technology"`
- When user searches `SPY`: Returns both ticker-specific (if any) and sector articles

## Domain Health & Blacklisting

### Automatic Blacklisting
- Tracks domain success/failure rates
- Auto-blacklists domains after N consecutive failures (default: 4)
- Prevents wasting time on unreliable sources

### Manual Blacklisting
- Configure in `settings.py`: `get_research_domain_blacklist()`
- Examples: `['msn.com', 'reuters.com']`

### Health Tracking
- Records success/failure per domain
- Stores in `domain_health_tracking` table
- Used to make intelligent decisions about which domains to trust

## Relevance Scoring

Articles are assigned relevance scores:

- **0.8** - Ticker-specific news (high relevance)
- **0.7** - Sector-level news (moderate-high relevance)
- **0.5** - General market news (default relevance)

Scores are used for:
- Filtering low-quality articles
- Ranking search results
- Prioritizing content in UI

## Vector Embeddings

- **Model:** nomic-embed-text (via Ollama)
- **Dimensions:** 768
- **Usage:** Semantic similarity search
- **Storage:** PostgreSQL pgvector extension

**Similarity Calculation:**
```sql
SELECT *, 1 - (embedding <=> query_embedding) as similarity
FROM research_articles
WHERE 1 - (embedding <=> query_embedding) >= min_similarity
ORDER BY similarity DESC
```

## Research Page

The Research page (`pages/research.py`) provides:

- **Statistics:** Total articles, by type, by sector
- **Filtering:** By ticker, sector, article type, date range
- **Search:** Text search across title, summary, content
- **Viewing:** Detailed article view with full content
- **Pagination:** Efficient browsing of large datasets

## Configuration

### Environment Variables

```bash
# SearXNG
SEARXNG_BASE_URL=http://host.docker.internal:8080
SEARXNG_ENABLED=true
SEARXNG_TIMEOUT=10

# Ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
# Second host for models that use OLLAMA_BASE_URL_2 (e.g. qwen3.6:27b) when that model runs on a different machine
# than OLLAMA_BASE_URL.
# OLLAMA_BASE_URL_2=http://second-ollama-host:11434
OLLAMA_MODEL=llama3
OLLAMA_TIMEOUT=120
OLLAMA_ENABLED=true

Per-model Ollama routing (`base_url`, `fallback_base_url`, `think`, `streaming_timeout`) is configured in `web_dashboard/model_config.json` with optional `system_settings` overrides (`model_<name>_base_url`, etc.).

# Database
RESEARCH_DATABASE_URL=postgresql://user:pass@host:5432/dbname
```

### Settings (`settings.py`)

- `get_research_domain_blacklist()` - Manual domain blacklist
- `get_discovery_search_queries()` - Opportunity discovery queries
- `get_system_setting("auto_blacklist_threshold", default=4)` - Auto-blacklist threshold

## Job Scheduling

Jobs are registered in `scheduler/scheduler_core.py`:

```python
# Market Research: Every 6 hours at :00
scheduler.add_job(
    market_research_job,
    trigger=CronTrigger(hour='*/6', minute=0),
    id='market_research_job'
)

# Ticker Research: Every 6 hours at :30
scheduler.add_job(
    ticker_research_job,
    trigger=CronTrigger(hour='*/6', minute=30),
    id='ticker_research_job'
)

# Opportunity Discovery: Every 12 hours at :30
scheduler.add_job(
    opportunity_discovery_job,
    trigger=CronTrigger(hour='*/12', minute=30),
    id='opportunity_discovery_job'
)
```

## Monitoring & Logging

### Job Execution Logs
- Stored in `job_executions` table
- Tracks success/failure, duration, messages
- Viewable in Admin UI (`scheduler_ui.py`)

### Logging Levels
- **INFO:** Job start/end, articles saved
- **DEBUG:** Detailed processing steps
- **WARNING:** Failed extractions, blacklisted domains
- **ERROR:** Critical failures

## Performance Considerations

### Rate Limiting
- Delays between articles (1 second)
- Delays between tickers (3 seconds)
- Delays between sectors (3 seconds)

### Batch Processing
- Processes articles sequentially
- Limits results per search (5-8 articles)
- Pagination for large result sets

### Caching
- Embeddings cached in database
- Summaries stored to avoid regeneration
- Domain health cached for quick lookups

## Troubleshooting

### Common Issues

**"SearXNG is not available"**
- Check SearXNG container is running
- Verify `SEARXNG_BASE_URL` is correct
- Check network connectivity

**"Ollama client not initialized"**
- Verify Ollama container is running
- Check `OLLAMA_BASE_URL` configuration
- Ensure model is downloaded

**"No articles found"**
- Check job execution logs
- Verify database connection
- Check domain blacklist isn't too restrictive

**"Embedding generation failed"**
- Check Ollama model is loaded
- Verify content isn't too long (>6000 chars truncated)
- Check Ollama logs for errors

## Future Enhancements

Potential improvements:
- Multi-language support
- Sentiment analysis
- Article categorization (earnings, mergers, etc.)
- Real-time alerts for important news
- Integration with trading signals
- Advanced filtering by market cap, industry
- Article deduplication improvements
- Export functionality

