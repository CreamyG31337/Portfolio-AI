# Database Schema Setup Guide

This directory contains all database schema files for the Portfolio Dashboard.

## 🚀 Quick Setup (One Command)

Run the main setup script to create everything:

```sql
-- Copy and paste the entire content of 01_main_schema.sql into Supabase SQL editor
```

## 📁 Schema Files (Run in Order)

### 1. `01_main_schema.sql` - **START HERE**
- **Purpose**: Core portfolio tables and basic setup
- **Contains**: 
  - Portfolio positions, trade log, cash balances, performance metrics
  - Basic indexes and triggers
  - Initial data setup
- **Run First**: This is the foundation

### 2. `02_auth_schema.sql` - **RUN SECOND**
- **Purpose**: User authentication and permissions
- **Contains**:
  - User profiles and fund assignments
  - Row Level Security (RLS) policies
  - Access control functions
- **Run After**: Main schema is created

### 3. `03_sample_data.sql` - **OPTIONAL**
- **Purpose**: Sample users and fund assignments for testing
- **Contains**:
  - Test user accounts
  - Sample fund assignments
- **Run Last**: Only if you want test data

## 🔧 Manual Setup (If Needed)

If you prefer to run files individually:

1. **First**: Run `01_main_schema.sql`
2. **Second**: Run `02_auth_schema.sql` 
3. **Optional**: Run `03_sample_data.sql`

## ⚠️ Important Notes

- **Order Matters**: Always run files in numerical order
- **Backup First**: Consider backing up your database before running
- **Test Environment**: Test on a development database first
- **RLS Policies**: The auth schema enables Row Level Security - users will only see their assigned funds

## 🐛 Troubleshooting

- **"Table already exists"**: You can safely ignore these errors
- **"Function already exists"**: You can safely ignore these errors  
- **Permission errors**: Make sure you're running as a database admin
- **RLS issues**: Check that user_funds table has proper assignments

## 📋 Post-Setup Checklist

After running all schemas:

1. ✅ Verify tables exist: `portfolio_positions`, `trade_log`, `cash_balances`, `performance_metrics`
2. ✅ Verify auth tables exist: `user_profiles`, `user_funds`
3. ✅ Test RLS: Create a test user and assign them a fund
4. ✅ Run migration: `python migrate.py` to populate with your data
5. ✅ Test dashboard: Visit the web dashboard and verify login works

## 🔐 Security

- All portfolio data is protected by Row Level Security
- Users can only access funds assigned to them
- No "All Funds" access - each user sees only their assigned funds
- JWT tokens expire after 24 hours

## 🗄️ Local Postgres Setup (Research Articles)

### Overview
Research articles are stored in a local Postgres Docker container to avoid hitting Supabase's 500MB free tier limit. This uses a hybrid approach: Supabase for portfolio data, local Postgres for research articles.

### Prerequisites
1. **Postgres Docker Container**: Running via Portainer
   - **Recommended Image**: `pgvector/pgvector:pg17` (includes pgvector extension)
   - **Container Name**: `postgres-17.5` (or your container name)
   - **Port**: 5432 (default Postgres port)
2. **Database Created**: `trading_db` database exists
3. **pgvector Extension**: Installed and enabled (included in `pgvector/pgvector:pg17` image)
4. **Password Authentication**: Optional for localhost (trust authentication may work)

### Setup Steps

#### 1. Use pgvector Image (Recommended)
If you haven't already, switch your Postgres container to use the pgvector image:
- **Image**: `pgvector/pgvector:pg17`
- This image includes Postgres 17 with pgvector extension pre-installed
- Update your container in Portainer to use this image

#### 2. Enable pgvector Extension
If using a standard Postgres image, enable the extension:
```sql
-- Connect to trading_db database
-- Via Portainer console or: docker exec -it postgres-17.5 psql -U postgres -d trading_db
CREATE EXTENSION IF NOT EXISTS vector;
```

#### 3. Configure Environment
Add to `web_dashboard/.env`:
```ini
# IMPORTANT: Hostname depends on WHERE the app runs:
# 
# From workstation (Tailscale/SSH):
RESEARCH_DATABASE_URL=postgresql://postgres:password@your-tailscale-hostname:5432/trading_db
# 
# From server host:
RESEARCH_DATABASE_URL=postgresql://postgres:password@localhost:5432/trading_db
# 
# From Docker container (Postgres also in Docker):
RESEARCH_DATABASE_URL=postgresql://postgres:password@postgres-17.5:5432/trading_db
# 
# From Docker container (Postgres on host):
RESEARCH_DATABASE_URL=postgresql://postgres:password@host.docker.internal:5432/trading_db
```

**Note**: 
- Password is REQUIRED for remote connections (Tailscale/SSH)
- Password may not be required for localhost (trust authentication)
- **Not sure which hostname to use?** Run the connection tester:
  ```bash
  python web_dashboard/debug/test_postgres_connection.py
  ```
  It will test multiple hostnames and recommend the best one for your environment.

#### 4. Run Setup Script
```bash
python web_dashboard/scripts/setup_postgres.py
```

This will:
- Test the database connection
- Verify pgvector extension
- Create the `research_articles` table
- Create indexes for fast queries

### Schema: `10_research_articles.sql`

**Table**: `research_articles`

**Fields**:
- `id` (UUID): Primary key
- `ticker` (VARCHAR): Stock ticker symbol
- `sector` (VARCHAR): Sector name
- `article_type` (VARCHAR): 'ticker_news', 'market_news', 'earnings'
- `title` (TEXT): Article title
- `url` (TEXT, UNIQUE): Article URL (prevents duplicates)
- `summary` (TEXT): AI-generated summary
- `content` (TEXT): Full article content
- `source` (VARCHAR): Source name (e.g., "Yahoo Finance")
- `published_at` (TIMESTAMP): When article was published
- `fetched_at` (TIMESTAMP): When we scraped it
- `relevance_score` (DECIMAL): 0.00 to 1.00
- `embedding` (vector(1024)): Vector embedding for semantic search (bge-m3; configurable via `AI_EMBED_MODEL` / `AI_EMBED_DIM`)

**Indexes**:
- `idx_research_ticker`: Fast lookups by ticker
- `idx_research_fetched`: Fast queries by fetch date (DESC for recent first)
- `idx_research_type`: Filter by article type

### Usage Example

```python
from web_dashboard.research_repository import ResearchRepository

# Initialize repository
repo = ResearchRepository()

# Save an article
article_id = repo.save_article(
    ticker="NVDA",
    sector="Technology",
    article_type="ticker_news",
    title="NVIDIA Announces New GPU",
    url="https://example.com/article",
    summary="NVIDIA released a new GPU...",
    content="Full article text...",
    source="Yahoo Finance",
    relevance_score=0.85
)

# Get articles by ticker
articles = repo.get_articles_by_ticker("NVDA", limit=10)

# Get recent articles
recent = repo.get_recent_articles(limit=20, days=7)

# Search articles
results = repo.search_articles("earnings report", ticker="NVDA")

# Clean up old articles (keep last 30 days)
deleted = repo.delete_old_articles(days_to_keep=30)
```

### Troubleshooting

**Connection Errors**:
- Verify Postgres container is running
- Check RESEARCH_DATABASE_URL format (no spaces, correct password)
- Ensure database `trading_db` exists
- Test connection: `psql -h localhost -U postgres -d trading_db`

**pgvector Errors**:
- Verify extension: `SELECT * FROM pg_extension WHERE extname = 'vector';`
- **Recommended**: Switch to `pgvector/pgvector:pg17` image in Portainer (includes extension)
- If using standard Postgres image: `CREATE EXTENSION IF NOT EXISTS vector;`

**Permission Errors**:
- Ensure user has CREATE TABLE permissions
- Check that password authentication is working
- Verify user can connect to `trading_db` database

### Debugging Utilities

Helper utilities are available in `web_dashboard/debug/` for debugging and exploring the database:

#### 1. `postgres_utils.py` - Command-line utilities
```bash
# Test connection
python web_dashboard/debug/postgres_utils.py --test

# Get database info (version, user, pgvector status)
python web_dashboard/debug/postgres_utils.py --info

# List all tables
python web_dashboard/debug/postgres_utils.py --list-tables

# Describe a table structure
python web_dashboard/debug/postgres_utils.py --describe research_articles

# Execute a SQL query
python web_dashboard/debug/postgres_utils.py --sql "SELECT COUNT(*) FROM research_articles"

# Get research articles statistics
python web_dashboard/debug/postgres_utils.py --stats
```

#### 2. `postgres_shell.py` - Interactive SQL shell
```bash
# Start interactive shell
python web_dashboard/debug/postgres_shell.py

# In the shell:
postgres> SELECT * FROM research_articles LIMIT 5;
postgres> \dt          # List tables
postgres> \help        # Show help
postgres> \quit         # Exit
```

#### 3. `test_postgres_connection.py` - Connection tester
```bash
# Test which hostname works from your environment
python web_dashboard/debug/test_postgres_connection.py
```
This script tests multiple hostname patterns (localhost, host.docker.internal, container name, etc.) and recommends the best one for your setup. Useful when using Tailscale or unsure which hostname to use.

**Note**: These utilities use `RESEARCH_DATABASE_URL` from your `.env` file. For Tailscale/remote connections, make sure it includes the password and correct hostname.

#### 4. `verify_postgres_production.py` - Production verification
```bash
# Verify Postgres is working in production (run on server)
python web_dashboard/debug/verify_postgres_production.py
```
This script performs a comprehensive check:
- Tests database connection
- Verifies research_articles table exists
- Shows table statistics (total articles, recent articles)
- Checks read/write permissions
- Displays latest article info

**Quick verification** (using postgres_utils):
```bash
python web_dashboard/debug/postgres_utils.py --verify
```