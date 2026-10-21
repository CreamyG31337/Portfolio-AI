# Contributors (Holders) Missing from Chimera Fund - Resolution

## Issue Summary

**Problem**: Holders/contributors data was missing from the Project Chimera fund in Supabase.

**Root Cause**: The Supabase migration did not include a table for fund contributors. The migration scripts only migrated:
- Portfolio positions
- Trade log  
- Cash balances

But NOT fund contributions/contributors (holders).

## What Are Contributors?

Contributors (also called "holders") are **investors who have contributed money to the fund**. This is different from dashboard users:

- **Contributors/Holders**: Investors in the fund
  - Data source: `fund_contributions.csv` in each fund directory
  - Used to calculate ownership percentages
  - Example data: Lance Colton, Owen Gothard, Christian Rosende, etc.

- **Dashboard Users**: People who can log in to view the web dashboard
  - Data source: Supabase `user_profiles` and `user_funds` tables
  - Used for authentication and access control

## Files Created

### 1. SQL Schema
- **`database/schema/supabase/05_fund_contributions_schema.sql`**
  - Creates `fund_contributions` table
  - Creates `contributor_ownership` view
  - Creates `fund_contributor_summary` view
  - Sets up Row Level Security

### 2. Migration Script
- **`web_dashboard/migrate_contributors.py`**
  - Migrates data from `fund_contributions.csv` to Supabase
  - Supports single fund or all funds
  - Includes dry-run mode for testing

### 3. Documentation
- **`web_dashboard/CONTRIBUTORS_MIGRATION.md`**
  - Detailed migration instructions
  - Schema documentation
  - Troubleshooting guide

### 4. Updated Files
- **`database/schema/supabase/00_complete_setup.sql`**
  - Added fund_contributions table to complete setup
- **`docs/DATABASE_SCHEMA.md`**
  - Added documentation for fund_contributions table and views

## How to Fix

### Step 1: Run the SQL Schema

In your Supabase SQL Editor, run:
```sql
-- Copy and paste the contents of:
database/schema/supabase/05_fund_contributions_schema.sql
```

This creates:
- `fund_contributions` table
- `contributor_ownership` view (shows current ownership)
- `fund_contributor_summary` view (shows fund-level stats)
- Security policies

### Step 2: Migrate the Data

Open PowerShell and run:

```powershell
# Activate virtual environment
.\venv\Scripts\activate

# Migrate Project Chimera only
python web_dashboard/migrate_contributors.py --fund "Project Chimera"

# Or migrate all funds
python web_dashboard/migrate_contributors.py
```

### Step 3: Verify the Data

In Supabase SQL Editor:

```sql
-- Check contributor data
SELECT * FROM fund_contributions
WHERE fund = 'Project Chimera'
ORDER BY timestamp;

-- View ownership summary
SELECT * FROM contributor_ownership
WHERE fund = 'Project Chimera';

-- View fund summary
SELECT * FROM fund_contributor_summary
WHERE fund = 'Project Chimera';
```

## Expected Results

For Project Chimera, you should see:
- **10 contributors** (Lance Colton, Owen Gothard, Christian Rosende, Ryan Walker, Lightning, Ashe Colton, Venita Colton, Chad Rutherford, Alex Strilets, Hugh Glover)
- **17 total contributions** (as of the CSV data)
- **Total contributions**: $8,418.98 CAD

## Database Schema

### fund_contributions Table

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| fund | VARCHAR(50) | Fund name |
| contributor | VARCHAR(255) | Contributor name |
| email | VARCHAR(255) | Contributor email |
| amount | DECIMAL(10,2) | Contribution/withdrawal amount |
| contribution_type | VARCHAR(20) | "CONTRIBUTION" or "WITHDRAWAL" |
| timestamp | TIMESTAMP | When the transaction occurred |
| notes | TEXT | Additional notes |

### Views

**contributor_ownership**: Shows net contribution and ownership for each contributor
**fund_contributor_summary**: Shows aggregate statistics for the entire fund

## Future Considerations

The application currently reads contributor data from CSV files. In the future, you could:

1. **Keep using CSV files** (current approach)
   - Simple and works with existing code
   - Re-run migration when contributors change
   
2. **Use Supabase directly**
   - Modify `ContributorManager` to use `SupabaseRepository`
   - Update the web dashboard to manage contributors
   - Keep CSV files as backup only

## Questions?

See detailed documentation in:
- `web_dashboard/CONTRIBUTORS_MIGRATION.md` - Full migration guide
- `docs/DATABASE_SCHEMA.md` - Database schema documentation
- `database/schema/supabase/05_fund_contributions_schema.sql` - SQL schema

## Quick Reference

```bash
# Migration commands
python web_dashboard/migrate_contributors.py --fund "Project Chimera"
python web_dashboard/migrate_contributors.py --dry-run
python web_dashboard/migrate_contributors.py  # All funds

# SQL verification
SELECT * FROM fund_contributions WHERE fund = 'Project Chimera';
SELECT * FROM contributor_ownership WHERE fund = 'Project Chimera';
```

