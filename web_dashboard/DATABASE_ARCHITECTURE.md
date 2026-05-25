# Database Architecture

This project uses **two separate databases** for different purposes:

## 1. Supabase (Primary - Cloud PostgreSQL)
**Connection**: Via `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`

**Purpose**: Main application data, transactional data, user-facing features

**Tables**:
- `portfolio_positions` - Current holdings
- `trade_log` - Trade history
- `cash_balances` - Cash positions
- `performance_metrics` - Performance tracking
- `securities` - Security metadata (ticker, company name, sector)
- `congress_trades` - Congressional trading activity (scraped data)
- `politicians` - Politician information
- `committees` - Congressional committees
- `committee_assignments` - Politician-committee relationships
- `research_articles` - (NOTE: This might be in wrong DB - see below)
- And more...

**Schema Location**: `web_dashboard/schema/*.sql`

**Why Supabase?**:
- Managed PostgreSQL with automatic backups
- Built-in authentication
- Real-time subscriptions
- Row Level Security (RLS)
- Good for production application data

---

## 2. PostgreSQL (Local/Docker - Research Database)
**Connection**: Via `RESEARCH_DATABASE_URL` environment variable

**Purpose**: Large text storage, research data, AI analysis results (to save Supabase costs)

**Tables**:
- `research_articles` - Article content, embeddings, AI analysis
  - Full article text (can be lengthy)
  - Vector embeddings (1024 dimensions via pgvector, model `bge-m3` — configurable via `AI_EMBED_MODEL` / `AI_EMBED_DIM`)
  - AI summaries and metadata
- `market_relationships` - Company relationship graph
- `congress_trades_analysis` - **NEW** AI conflict-of-interest analysis results
  - `trade_id` → References `congress_trades.id` in Supabase
  - `session_id` → References `congress_trade_sessions.id` (groups related trades)
  - `reasoning` - Long-form AI reasoning text
  - `conflict_score` - AI-generated score (0.0 to 1.0)
  - `confidence_score` - Confidence level (0.0 to 1.0)
- `congress_trade_sessions` - **NEW** "Living Sessions" of related trades
  - Tracks groups of trades (7-day gap rule) that tell an evolving story
  - `start_date`, `end_date`, `trade_count`
  - `conflict_score` & `ai_summary` for the ENTIRE session
  - `needs_reanalysis` flag triggers updates when new trades arrive

**Schema Location**: 
- Research articles: `web_dashboard/scripts/setup_postgres.py`
- Congress analysis: `web_dashboard/schema/22_congress_trades_analysis.sql`

**Why Separate Database?**:
- **Cost savings**: Supabase charges for storage; lengthy AI reasoning text is cheaper on self-hosted Postgres
- **Vector search**: Uses pgvector extension for semantic article search
- **Performance**: Offload heavy vector operations from Supabase
- **Data ownership**: Research data stored on own infrastructure

---

## Environment Variables

### Development (.env file)
```bash
# Supabase (Cloud)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key

# PostgreSQL Research DB (Docker/Local)
RESEARCH_DATABASE_URL=postgresql://user:password@host:5432/trading_db
```

### Production (Woodpecker Secrets)
Both `SUPABASE_SERVICE_ROLE_KEY` and `RESEARCH_DATABASE_URL` are configured as Woodpecker secrets.

---

## Migration Strategy

### Supabase Migrations
Run SQL files in order: `01_*.sql`, `02_*.sql`, etc.
```bash
# Via Supabase CLI or web interface
```

### PostgreSQL Migrations
```bash
# Using Python helper script
python web_dashboard/schema/apply_postgres_schema.py

# Or directly via psql
psql $RESEARCH_DATABASE_URL -f web_dashboard/schema/22_congress_trades_analysis.sql
```

---

## Cross-Database Relationships

**Congress Trades Analysis** (`congress_trades_analysis` in Postgres):
- `trade_id` field references `congress_trades.id` in Supabase
- **NOT** a true foreign key (different databases)
- Application code is responsible for maintaining referential integrity
- When querying, JOIN manually by ID:
  ```python
  # 1. Get trade from Supabase
  trade = supabase.table('congress_trades').select('*').eq('id', 123).execute()
  
  # 2. Get analysis from Postgres
  analysis = postgres.execute_query(
      "SELECT * FROM congress_trades_analysis WHERE trade_id = %s",
      (123,)
  )
  ```

**Important**: Both the manual `analyze_congress_trades_batch.py` script AND the scheduler job `analyze_congress_trades_job()` now write to PostgreSQL, not Supabase's `notes` field.

---

---
## Living Session Architecture

We now group related trades into "Living Sessions" to provide better context for AI analysis:

1. **Session Grouping**: Trades by the same politician within a **7-day window** are grouped together.
2. **Living Updates**: When a new trade arrives:
   - If within 7 days of an existing session → Extends the session & sets `needs_reanalysis = TRUE`.
   - If gap > 7 days → Creates a new session & sets `needs_reanalysis = TRUE`.
3. **Session Analysis**: The AI analyzes the *entire session* at once, looking for patterns (e.g., selling bonds to buy defense stocks).
   - If ONE trade is suspicious, the WHOLE session is flagged.
   - Low-risk sessions (only ETFs/Funds) are auto-filtered (Score: 0.0) but still tracked.

This reduces API costs (fewer calls) and improves detection quality (better context).

---

## Future Considerations

### Should `research_articles` move to Supabase?
Currently in Postgres for vector search, but could benefit from Supabase's:
- Better access control (RLS)
- Realtime subscriptions
- Easier web dashboard integration

**Tradeoff**: Would increase Supabase storage costs due to large article content and embeddings.

### Schema Organization
Consider creating sub-folders:
- `schema/supabase/` - Supabase migrations
- `schema/postgres/` - PostgreSQL migrations
