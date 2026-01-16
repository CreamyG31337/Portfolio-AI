# Agent Guidelines for LLM Micro-Cap Trading Bot

## ⚠️ CRITICAL: Windows/PowerShell Environment

**THIS IS A WINDOWS ENVIRONMENT RUNNING POWERSHELL - NOT LINUX/BASH**

### Common Mistakes to Avoid:
- ❌ **DON'T use**: `ls`, `cat`, `grep`, `sed`, `awk`, `&&`, `||`, `$VAR`, `$(command)`
- ✅ **DO use**: `Get-ChildItem` or `dir`, `Get-Content` or `type`, `Select-String`, `-and`/`-or`, `$env:VAR`, `$(command)`
- ❌ **DON'T use**: `/path/to/file`, `~/.config`, `chmod +x`, `#!/bin/bash`
- ✅ **DO use**: `C:\path\to\file` or relative paths, `$env:USERPROFILE`, PowerShell syntax
- ❌ **DON'T use**: `cd dir1 && cd dir2` (bash chaining)
- ✅ **DO use**: `cd dir1; cd dir2` or separate commands (PowerShell uses `;` not `&&`)

### Path Separators:
- Use backslashes `\` or forward slashes `/` (PowerShell accepts both, but backslashes are Windows-native)
- Virtual environment: `.\venv\Scripts\activate` (NOT `source venv/bin/activate`)

### Command Examples:
```powershell
# ✅ CORRECT - PowerShell
.\venv\Scripts\activate
python script.py
Get-ChildItem *.py
$env:VAR = "value"

# ❌ WRONG - Linux/Bash
source venv/bin/activate
python script.py
ls *.py
export VAR="value"
```

## Environment Setup
- **This is a Windows environment** - use Windows-specific commands and paths
- **Always activate virtual environment** before running any commands:
  ```powershell
  .\venv\Scripts\activate
  ```
- **Use trading_data/funds/TEST directory** for development (not "trading_data/funds/Project Chimera" which is production)
- **Copy CSVs between funds** anytime: Copy files from `trading_data/funds/Project Chimera/` to `trading_data/funds/TEST/` for testing

## PowerShell Command Line Issues
- **Avoid multi-line Python strings** in `run_terminal_cmd` as they cause PowerShell `>>` continuation prompts
- **Use simple one-liners** or create separate `.py` files for complex testing
- **If stuck at `>>` prompt:** Press `Ctrl+C` to cancel and return to normal prompt
- **Example problematic command:**
  ```powershell
  python -c "
  text = '''multi-line string
  >> # PowerShell waits for completion
  ```
- **Better approach:**
  ```powershell
  # Create test_script.py and run it
  python test_script.py
  ```

## Build/Lint/Test Commands

### Type Checking
```bash
mypy trading_script.py
```

### Linting
```bash
ruff check trading_script.py
ruff check --fix trading_script.py  # Auto-fix issues
```

### Testing
```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_financial_calculations.py -v

# Run tests with coverage
python -m pytest tests/ --cov=.

# Interactive test runner
python run_tests.py
```

### Development Mode
```bash
python dev_run.py --data-dir "trading_data/funds/TEST"
```

## Committing Code
- **ALWAYS run unit tests before committing**:
  ```bash
  python -m pytest tests/ -v
  ```
- **Run linting and type checking** before committing:
  ```bash
  ruff check trading_script.py
  mypy trading_script.py
  ```
- **Ensure all tests pass** before pushing changes
- **Use descriptive commit messages** that explain the "why" rather than just the "what"

## Code Style Guidelines

### Python Version & Requirements
- Python 3.11+ required
- Use `decimal.Decimal` for all financial calculations
- Handle timezone-aware datetimes properly

### Type Hints
- Strict typing enabled with mypy
- Use complete type annotations for all functions
- Avoid `Any` types except when necessary
- Use `Optional[T]` for nullable types

### Imports
- Use absolute imports
- Group imports: standard library, third-party, local modules
- isort configuration: `known-first-party = ["trading_script"]`

### Formatting
- Line length: 100 characters
- Use double quotes for strings
- Follow PEP 8 conventions

### Naming Conventions
- Functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_CASE`
- Private methods: `_leading_underscore`

### Error Handling
- Use specific exception types, not generic `Exception`
- Log all errors with context
- Provide meaningful error messages
- Handle edge cases gracefully (None values, empty data)

### Documentation
- Use comprehensive docstrings for modules and functions
- Include type hints in docstrings when helpful
- Document complex business logic

### Financial Calculations
- Always use `Decimal` for money values
- Handle currency conversion properly
- Validate decimal precision
- Use `or 0` pattern for None handling in P&L calculations

### Testing
- Write unit tests for all financial calculations
- Test edge cases and error conditions
- Use descriptive test names
- Mock external dependencies

### TypeScript Frontend Development

**CRITICAL**: All JavaScript files in `web_dashboard/static/js/` are **auto-generated** from TypeScript source files.

#### ⚠️ IMPORTANT: Edit TypeScript, Not JavaScript

- **✅ DO**: Edit files in `web_dashboard/src/js/*.ts` (TypeScript source)
- **❌ DON'T**: Edit files in `web_dashboard/static/js/*.js` (compiled output - will be overwritten)
- **Build Process**: `npm run build:ts` compiles TypeScript → JavaScript
- **Served At**: `/assets/js/*.js` (via Flask's static file handler)

#### TypeScript Build Commands

```bash
# Compile TypeScript to JavaScript
npm run build:ts

# Build both CSS and TypeScript
npm run build

# Watch mode (if needed)
npm run watch:css
```

#### File Structure

```
web_dashboard/
├── src/js/          ← EDIT THESE (TypeScript source files)
│   ├── dashboard.ts
│   ├── jobs.ts
│   └── ...
└── static/js/       ← AUTO-GENERATED (Don't edit! Compiled from src/js/)
    ├── dashboard.js
    ├── jobs.js
    └── ...
```

**See `web_dashboard/src/js/README.md` for detailed TypeScript development guidelines.**

### Test-Driven Development (TDD) and Test Selection

**CRITICAL**: Always run the appropriate test suite based on what code you're modifying.

#### Identifying Code Type

**Flask Code** (run Flask tests):
- Files in `web_dashboard/` directory:
  - `web_dashboard/app.py` - Main Flask application
  - `web_dashboard/routes/*.py` - Flask route blueprints
  - `web_dashboard/flask_*.py` - Flask utilities
  - `web_dashboard/templates/*.html` - Flask templates
  - `web_dashboard/static/js/*.ts` - Frontend TypeScript (compiles to JS)
- Test files: `tests/test_flask_*.py`

**Console App Code** (run console app tests):
- Files in project root (not in `web_dashboard/`):
  - `trading_script.py` - Main console application
  - `portfolio/*.py` - Portfolio management
  - `financial/*.py` - Financial calculations
  - `utils/*.py` - Utility functions
  - Any other root-level Python files
- Test files: `tests/test_*.py` (excluding `test_flask_*.py`)

**Streamlit Code**:
- Files in `web_dashboard/pages/*.py` - Streamlit pages
- **No tests** - Streamlit is prototype, no test suite

#### Running Tests

**Before making ANY code changes:**
1. Identify which type of code you're modifying
2. Run the appropriate test suite
3. Ensure all tests pass before making changes

**Flask Tests:**
```bash
# Activate root venv (both test suites use the same venv)
.\venv\Scripts\activate

# Run all Flask tests
python -m pytest tests/test_flask_*.py -v

# Run specific Flask test file
python -m pytest tests/test_flask_routes.py -v
python -m pytest tests/test_flask_data_utils.py -v
```

**Console App Tests:**
```bash
# Activate root venv
.\venv\Scripts\activate

# Run all console app tests (excludes Flask tests)
python -m pytest tests/ -v -k "not flask"

# Or use the test runner
python run_tests.py all

# Run specific test category
python run_tests.py financial
python run_tests.py integration
```

**TDD Workflow:**
1. **Red**: Write failing test first
2. **Green**: Implement minimum code to pass
3. **Refactor**: Improve while keeping tests green
4. **Verify**: Run full test suite before committing

**After making changes:**
- **Flask changes**: Run `python -m pytest tests/test_flask_*.py -v` (with root venv activated)
- **Console app changes**: Run `python -m pytest tests/ -v -k "not flask"` (with root venv activated)
- **Both changed**: Run both test suites

### File Structure
- Keep modules focused on single responsibilities
- Use repository pattern for data access
- Separate business logic from presentation
- Follow existing modular architecture

### Security
- Never log or expose sensitive data
- Validate all user inputs
- Use secure practices for file operations
- Avoid exposing secrets in code

### Performance
- Cache expensive operations when appropriate
- Use efficient data structures
- Profile code before optimizing
- Consider memory usage for large datasets

## Test Accounts for Web Dashboard

### Location
Test account credentials are stored in: **`web_dashboard/test_credentials.json`**

⚠️ **Note**: This file is gitignored for security, but IDEs with dotfile permissions can read it.

### Available Accounts

1. **Admin Test Account**
   - Email: See `web_dashboard/test_credentials.json`
   - Role: Admin
   - Access: Full admin dashboard, all funds
   - Use for: Testing admin features, user management, scheduled tasks

2. **Guest Test Account**
   - Email: See `web_dashboard/test_credentials.json`
   - Role: User
   - Access: Regular dashboard, limited funds
   - Use for: Testing user experience, access restrictions

### Usage for Browser Testing

1. Read credentials from `web_dashboard/test_credentials.json`
2. Navigate to web dashboard using browser tools
3. Log in with test account credentials
4. Test features as needed

### Setup

To create/regenerate test accounts:
```bash
cd web_dashboard
python setup_test_accounts.py
```

See `web_dashboard/TEST_CREDENTIALS.md` for detailed documentation.

## Social Sentiment AI Analysis System

### Overview
The social sentiment system now includes comprehensive AI analysis similar to congress trades:

- **Data Collection**: Social posts from StockTwits and Reddit
- **AI Analysis**: Sentiment scoring, theme extraction, ticker validation
- **Storage**: Structured data in Supabase, AI results in Postgres research DB
- **UI**: Enhanced dashboard with expandable post details and AI insights

### Database Architecture
- **Supabase**: `social_metrics`, `social_posts`, `sentiment_sessions`
- **Postgres Research DB**: `social_sentiment_analysis`, `extracted_tickers`, `post_summaries`

### Key Components
- **social_service.py**: Core service with AI analysis methods
- **social_sentiment_ai_job.py**: Scheduled job for AI processing
- **pages/social_sentiment.py**: Enhanced UI with AI analysis display
- **Schema files**: 18_social_metrics.sql, 27_social_sentiment_ai_analysis.sql

### AI Analysis Pipeline
1. Extract posts from `raw_data` into `social_posts`
2. Group related posts into `sentiment_sessions` (4-hour windows)
3. Perform AI analysis using Ollama Granite model
4. Extract and validate tickers with context
5. Store results in research database

### Running AI Analysis
```bash
cd web_dashboard
python social_sentiment_ai_job.py
```

### Data Retention
- Raw posts: 14 days (then cleaned to save space)
- AI analysis results: 90 days
- Social metrics: 60 days (reduced from 90 for efficiency)

### Testing AI Features
1. Ensure Ollama is running with Granite model
2. Run social sentiment collection to generate data
3. Execute AI analysis job
4. Check web dashboard for AI analysis results
## Database Schema Documentation

### Schema Documentation Files

**Location:** docs/database/

The project maintains comprehensive, auto-generated database schema documentation in multiple formats:

1. **Markdown Documentation** (Human & LLM-readable):
   - docs/database/supabase_schema.md - Supabase Production DB (29 tables)
   - docs/database/research_schema.md - Research/AI DB (13 tables)
   - Includes: table list, columns, types, constraints, foreign keys, indexes
   - Well-organized with table of contents for easy navigation

2. **JSON Schema** (Machine/LLM-parseable):
   - docs/database/supabase_schema.json - Structured data for programmatic access
   - docs/database/research_schema.json - Structured research DB schema
   - Perfect for LLM analysis and automated tooling

3. **Clean SQL Schema** (Table-specific files):
   - `database/schema/supabase/*.sql` - Individual table definitions for Supabase
   - `database/schema/research/*.sql` - Individual table definitions for Research DB
   - `_init_schema.sql` in each folder pulls all tables together
   - Generated directly from production database, bypassing migration artifacts

### Generating/Updating Schema Documentation

**Generate Documentation (Markdown + JSON):**
```powershell
.\web_dashboard\venv\Scripts\python.exe scripts\generate_schema_docs.py
```

**Export Clean SQL Schema (Split by Table):**
```powershell
.\web_dashboard\venv\Scripts\python.exe scripts\export_clean_schema.py
```

### Migration Strategy

**Current State:**
- `database/schema/` - Clean, modular production schema (**SOURCE OF TRUTH**)
- `database/archive/` - Historical migrations kept for context only

**Recommended Approach:**
1. Use `database/schema/` SQL files as the absolute source of truth for all database objects (Tables, Views, Functions, Polices).
2. If you need to verify or recreate an object, look in the corresponding subdirectory of `database/schema/<db_folder>/`.
3. Use the `_init_schema.sql` script for fresh environment setups.
4. Always run `export_clean_schema.py` after making changes to the production database to keep the repository's modular schema synced.

## Test Database for Safe Development

### Cloud Agent Usage

Before modifying production code, test changes locally:

1. **Start Test Environment**:
   ```powershell
   docker-compose -f docker-compose.test.yml up -d
   ```

2. **Configure Application**:
   ```powershell
   cp .env.test.template .env
   ```

3. **Run Tests**:
   Application now uses test databases on localhost:5433 (Supabase) and localhost:5434 (Research)

4. **Clean Up**:
   ```powershell
   docker-compose -f docker-compose.test.yml down -v
   ```

### Test Data Characteristics

**Only TEST and TFSA funds included:**
- Real portfolio positions, trades, and performance metrics
- Real fund configurations and cash balances
- All other fund data excluded

**All PII scrubbed:**
- All real contributor names → "Test Contributor {N}"
- All real emails → "test-contributor-{N}@example.com"
- User names → "Test User {N}"
- User emails → "test-user-{N}@example.com"
- Phone numbers and addresses set to NULL

**Synthetic data for AI features:**
- Social posts, articles, and sentiment data are fake
- Benchmark and market data is real (public information)
- 3374 fake social posts, 817 fake research articles

### RLS Testing

The test database includes mock Supabase auth:

**Test Users:**
- `admin@test.com` - Full admin access
- `contributor@test.com` - Contributor access to TEST/TFSA
- `viewer@test.com` - Read-only access

**Switch users in psql:**
```sql
-- Switch to admin
SELECT set_current_test_user('admin@test.com');

-- Switch to contributor
SELECT set_current_test_user('contributor@test.com');

-- Check current user
SELECT * FROM show_current_user();
```

**Disable RLS (test mode only):**
```sql
\i database/utilities/disable_rls_test.sql
```

### Regenerating Test Data

If production schema changes:

```powershell
# 1. Export clean schema from production
.\web_dashboard\venv\Scripts\python.exe scripts\export_clean_schema.py

# 2. Generate test seed (scrubs PII, creates synthetic data)
.\venv\Scripts\python.exe scripts\generate_test_seed.py

# 3. Restart test databases
docker-compose -f docker-compose.test.yml down -v
docker-compose -f docker-compose.test.yml up -d
```

### Database Connection Details

**Supabase Test DB:**
- Port: 5433
- Database: portfolio_supabase_test
- User: test_user
- Password: test_password

**Research Test DB:**
- Port: 5434
- Database: portfolio_research_test
- User: test_user
- Password: test_password

Both databases run simultaneously, matching production structure exactly to prevent join/structure bugs.

