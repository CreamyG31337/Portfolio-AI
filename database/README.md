# Database Schema

This directory contains the authoritative and modular database schema for the project. 

> [!IMPORTANT]
> The **Source of Truth** for the database schema is now located in the `database/schema/` directory. Legacy incremental migrations and ad-hoc fixes have been consolidated into this modular structure.

## 🏗️ Schema Organization

The schema is divided into two main environments, each with its own modular subdirectories:

### 1. Supabase Production (`database/schema/supabase/`)
Contains the full schema for the core application database.
- **`tables/`**: Individual table definitions.
- **`functions/`**: PL/pgSQL functions and business logic.
- **`views/`**: Database views for reporting and dashboards.
- **`triggers/`**: Automation triggers.
- **`policies/`**: Row Level Security (RLS) policies.
- **`sequences/`**: Auto-incrementing sequences.
- **`types/`**: Custom database types (Enums, etc.).

### 2. Research Database (`database/schema/research/`)
Contains the schema for the AI research and data collection database.

## 🚀 Fresh Database Setup

To set up a fresh database environment:

1. Navigate to the desired database folder (e.g., `database/schema/supabase/`).
2. Run the **`_init_schema.sql`** script. 
   - This master script handles dependency ordering (creating types/functions before tables/views).
   - In Supabase, you can copy the contents into the SQL Editor.

## 🔄 Maintenance & Syncing

To keep these files in sync with a live database after making changes in production:

```powershell
.\web_dashboard\venv\Scripts\python.exe scripts\export_clean_schema.py
```

This script will connect to the databases defined in your `.env` file and regenerate the modular SQL files based on the actual live schema.

## 🧪 Test Environment Setup

For safe testing without touching production data:

### Quick Start

```powershell
# 1. Start test database
docker-compose -f docker-compose.test.yml up -d

# 2. Verify it's running
docker-compose -f docker-compose.test.yml ps

# 3. Connect to test database
psql postgresql://test_user:test_password@localhost:5433/portfolio_supabase_test
```

### What's Included

**Real Data:**
- TEST and TFSA fund positions, trades, and performance
- Real securities, benchmark data, exchange rates
- Congress trades, politicians, committees
- System settings and job execution logs

**Scrubbed PII:**
- All contributor names → "Test Contributor {N}"
- All real emails → "test-contributor-{N}@example.com"
- User names → "Test User {N}"
- User emails → "test-user-{N}@example.com"
- Phone numbers and addresses removed

**Synthetic Data:**
- 3374 fake social posts (matching production count)
- 10122 fake social metrics
- 2361 fake sentiment analysis records
- 817 fake research articles
- Fake market relationships and extracted tickers

**Mock Auth:**
- 3 test users (admin@test.com, contributor@test.com, viewer@test.com)
- Simulated Supabase auth.uid() function
- RLS testing enabled

### Test Database Features

- Runs on ports 5433 (Supabase) and 5434 (Research) - won't conflict with production
- RLS policies enabled by default (can be disabled with `\i database/utilities/disable_rls_test.sql`)
- Switch test users: `SELECT set_current_test_user('admin@test.com');`
- Full schema parity with production

### Regenerating Test Data

If production schema changes:

```powershell
# 1. Update schema from production
.\\web_dashboard\\venv\\Scripts\\python.exe scripts\\export_clean_schema.py

# 2. Regenerate test seed (scrubs PII, generates synthetic data)
.\\venv\\Scripts\\python.exe scripts\\generate_test_seed.py

# 3. Restart test databases
docker-compose -f docker-compose.test.yml down -v
docker-compose -f docker-compose.test.yml up -d
```

### Cleanup

```powershell
# Stop and remove test database
docker-compose -f docker-compose.test.yml down -v
```

## 🛠️ Additional Folders

- **`debug/`**: Diagnostic scripts for troubleshooting data issues.
- **`utilities/`**: Scripts for development (sample data, RLS toggles).
- **`archive/`**: Historical migrations kept for context only.
- **`analysis/`**: SQL queries used for data analysis and reporting.
