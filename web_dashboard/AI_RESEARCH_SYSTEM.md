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
   - Creates vector embeddings (1024 dimensions via `bge-m3`, configurable) for semantic search
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
    embedding vector(1024)          -- For semantic search (bge-m3)
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

- **Model:** `bge-m3` (via Ollama) — configurable via `AI_EMBED_MODEL`
- **Dimensions:** 1024 — configurable via `AI_EMBED_DIM` (must match the column type)
- **Input cap:** ~24,000 characters — configurable via `AI_EMBED_MAX_CHARS` (truncation is centralized in `ollama_client.generate_embedding`)
- **Usage:** Semantic similarity search
- **Storage:** PostgreSQL pgvector extension (`vector(1024)`, HNSW cosine indexes)

> Historical note: this system originally used `nomic-embed-text` at 768 dimensions. It was migrated to `bge-m3` in May 2026 because the on-Ollama context for `nomic-embed-text` is hard-capped at 2048 tokens (~5500 chars), which caused long newsletters/articles to fail to embed. See `database/migrations/2026-05_migrate_embeddings_to_bge_m3_1024.sql` and `web_dashboard/scripts/reembed_research_vectors.py` for the schema change and backfill script.

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
# Second host for models that use OLLAMA_BASE_URL_2 (e.g. qwen3.6:27b-heretic) when that model runs on a different machine
# than OLLAMA_BASE_URL.
# OLLAMA_BASE_URL_2=http://second-ollama-host:11434
OLLAMA_MODEL=llama3
OLLAMA_TIMEOUT=120
OLLAMA_ENABLED=true
# How long Ollama keeps a model resident in VRAM after a request. Set on the
# *Ollama host* (not the Flask container) — the value above is just a reminder.
# Default Ollama is 5m; we use 7m so back-to-back jobs (summarize → embed →
# next article) reuse the loaded model and avoid 20–60s reload stalls.
# OLLAMA_KEEP_ALIVE=7m

Per-model Ollama routing (`base_url`, `fallback_base_url`, `think`, `streaming_timeout`) is configured in `web_dashboard/model_config.json` with optional `system_settings` overrides (`model_<name>_base_url`, etc.).

# Database
RESEARCH_DATABASE_URL=postgresql://user:pass@host:5432/dbname
```

## Ollama Operational Notes

These are easy to forget and have bitten us before:

### Ollama wraps llama.cpp

The Ollama desktop/server install bundles the `llama.cpp` / `ggml` runtime
(`ggml-base.dll`, `ggml-cpu-*.dll`, `cuda_v13`, `rocm`, `vulkan` under
`<install>/lib/ollama/`). There is no separate `llama-server` process to find
or configure. All knobs (model lifecycle, KV cache, GPU offload, keep-alive)
go through Ollama, not through `llama.cpp` flags.

### Two-host routing is for placement, not load-balancing

We support two Ollama hosts via four env-var aliases that collapse to two slots:

| Env var | Alias of | Models that prefer it (primary) |
|---|---|---|
| `OLLAMA_BASE_URL_AMD` | `OLLAMA_BASE_URL` | `granite3.3:8b` |
| `OLLAMA_BASE_URL_NVIDIA` | `OLLAMA_BASE_URL_2` | `qwen3.6:27b-heretic` |

`fallback_base_url` in `model_config.json` is **host-down failover** (HTTP 404
or 5xx triggers a single retry on the other host inside `_post_ollama`). It is
**not** load-balancing — if both hosts are up but busy, requests still go to
the primary and queue there. See the `TODO(ollama-hosts)` block in
`ollama_client.py` for the planned cleanup to a generic N-host model.

### `num_ctx` is configured, not passed per-call

The `num_ctx` value Ollama sees is resolved in exactly one place:

```
model_config.json  →  system_settings override (model_<name>_num_ctx)  →  request
```

There is intentionally **no `num_ctx` / `num_ctx_override` parameter** on any
public summarization or query function. Earlier versions had one and it was
removed because changing `num_ctx` between requests forces Ollama to evict and
reload the model weights (typically 20–60s on a 24GB-class GPU), which:

- wrecks any latency benchmark that varies it per-request (you measure reload
  time, not inference);
- defeats `OLLAMA_KEEP_ALIVE` (the keep-alive timer resets but the model is
  gone anyway because the ctx changed);
- is almost never what callers actually want.

If you genuinely need a different `num_ctx`, edit the config and accept the
single reload. Per-call overrides are gone for good.

### Picking `num_ctx` on a shared GPU

`num_ctx` × model size mostly determines KV-cache VRAM. On the
single-3090 NVIDIA host this box also runs Plex transcoding, the IDE, browser,
etc., so we deliberately undersize `num_ctx`:

| Model | `num_ctx` | Why |
|---|---|---|
| `qwen3.6:27b-heretic` | `20000` | Leaves ~13k tokens slack over the ~6.5k-token worst-case summary input while keeping KV ≈ 2.5 GB so Plex/IDE can coexist. |

Powers-of-two are a llama.cpp lore thing; in practice round numbers like 20000
work fine — there is no measurable benefit to 16384 or 32768 specifically.
Operators with dedicated VRAM can raise the value via the
`model_qwen3.6:27b-heretic_num_ctx` row in `system_settings` without redeploying.

### Summarizer input pipeline

What gets sent to the summarizing LLM is built by
`web_dashboard/summary_common.py`:

1. **Character cap**, by article type:
   - `Newsletter` → 16,000 chars (~4k tokens), override with `AI_SUMMARY_MAX_CHARS_NEWSLETTER`.
   - Everything else → 6,000 chars (~1.5k tokens), override with `AI_SUMMARY_MAX_CHARS`.
2. **Head + tail truncation** when over budget: keep the first 60 % and the
   last 40 %, joined by an explicit marker
   (`[...content truncated; middle section omitted...]`). The tail is preserved
   on purpose — newsletter sign-offs, conclusions, and call-to-action lines
   carry disproportionate signal for ticker extraction.
3. **Fallback chain on failure**: if a model returns an empty body or hits
   `_looks_like_query_ollama_user_facing_error`, `collect_with_summary_model_chain`
   advances to the next entry in the chain (primary Ollama → secondary Ollama →
   GLM → …). Truncation itself does not trigger fallback; truncation happens
   *before* the call.

If you change either constant, update `tests/test_summary_common_truncation.py`
in the same change.

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
- Check Ollama model is loaded (`ollama list` should show `bge-m3` or whatever `AI_EMBED_MODEL` is set to)
- Inputs are truncated to `AI_EMBED_MAX_CHARS` (default 24,000) inside `ollama_client.generate_embedding`; if Ollama still complains about context length, the model itself (not just the column) has a smaller hard cap — try shrinking `AI_EMBED_MAX_CHARS` rather than passing longer text
- If the returned vector's dimension doesn't match `AI_EMBED_DIM` (default 1024) the call is rejected — check the model and column type agree
- Check Ollama logs for errors

**"Every Ollama call takes 30+ seconds, then fast for a while, then slow again"**
- You're hitting model reloads. Two causes:
  1. `keep_alive` is too short — the model is being evicted between jobs. Set
     `OLLAMA_KEEP_ALIVE=7m` (or longer) on the Ollama host and restart it.
  2. Something is varying `num_ctx` per request. This shouldn't be possible
     from app code anymore (the per-call override was removed), but if you've
     added a new caller, confirm it's not passing `num_ctx` to Ollama directly.
- `ollama ps` on the host shows whether a model is currently resident and when
  it will expire.

**"Changed `num_ctx` in `model_config.json` but the new value isn't being used"**
- The model has to be unloaded for the new ctx to take effect. Either wait for
  `keep_alive` to expire, or `ollama stop <model>` then issue any request.
- Also check `system_settings` — `model_<name>_num_ctx` there overrides
  `model_config.json`. The admin UI (AI Settings page) is the easiest place to
  see the effective value.

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

