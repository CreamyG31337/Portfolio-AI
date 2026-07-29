# Fund Contributors (Holders) Migration Guide

## The Issue

**Holders/contributors data was missing from the Chimera fund in Supabase** because the original database migration didn't include a table for fund contributors.

### What are Contributors?

Contributors (also called "holders") are the **investors who have put money into the fund**. This is different from dashboard users:

- **Contributors/Holders**: People who have invested money in the fund
  - Stored in `fund_contributions.csv` in each fund directory
  - Used to calculate ownership percentages
  - Example: Lance Colton, Owen Gothard, Christian Rosende

- **Dashboard Users**: People who can log in to view the web dashboard
  - Stored in `user_profiles` and `user_funds` tables in Supabase
  - Can view fund data based on permissions
  - May or may not be contributors

### Why Was It Missing?

The original Supabase migration scripts (`migrate_all_funds.py`, `migrate.py`) only migrated:
1. Portfolio positions
2. Trade log
3. Cash balances

But NOT fund contributions/contributors.

## The Solution

### Step 1: Create the Database Table

Run the SQL schema to create the `fund_contributions` table:

```bash
# In Supabase SQL Editor, run:
database/schema/supabase/tables/fund_contributions.sql
```

This creates:
- `fund_contributions` table to store individual contributions/withdrawals
- `contributor_ownership` view to calculate current ownership
- `fund_contributor_summary` view for fund-level statistics
- Row Level Security policies for access control

### Step 2: Migrate Contributor Data

Run the migration script to populate the table:

```bash
# Activate virtual environment first
.\venv\Scripts\activate

# Migrate all funds
python web_dashboard/migrate_contributors.py

# Or migrate just Project Chimera
python web_dashboard/migrate_contributors.py --fund "Project Chimera"

# Or do a dry run first
python web_dashboard/migrate_contributors.py --fund "Project Chimera" --dry-run
```

### Step 3: Verify the Migration

Check the data in Supabase SQL Editor:

```sql
-- View all contributors for Project Chimera
SELECT * FROM fund_contributions
WHERE fund = 'Project Chimera'
ORDER BY timestamp;

-- View contributor ownership summary
SELECT * FROM contributor_ownership
WHERE fund = 'Project Chimera';

-- View fund summary
SELECT * FROM fund_contributor_summary
WHERE fund = 'Project Chimera';
```

## Database Schema

### fund_contributions Table

```sql
CREATE TABLE fund_contributions (
    id UUID PRIMARY KEY,
    fund VARCHAR(50) NOT NULL,
    contributor VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    amount DECIMAL(10, 2) NOT NULL,
    contribution_type VARCHAR(20) NOT NULL, -- CONTRIBUTION or WITHDRAWAL
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### Sample Data

| fund | contributor | amount | contribution_type | timestamp |
|------|-------------|---------|-------------------|-----------|
| Project Chimera | Lance Colton | 35.48 | CONTRIBUTION | 2025-09-07 |
| Project Chimera | Owen Gothard | 500.00 | CONTRIBUTION | 2025-09-08 |
| Project Chimera | Christian Rosende | 200.00 | CONTRIBUTION | 2025-09-08 |

## Views

### contributor_ownership

Shows current ownership for each contributor:
- Total contributions
- Total withdrawals
- Net contribution
- Ownership percentage (calculated by application)

### fund_contributor_summary

Shows fund-level statistics:
- Total number of contributors
- Total contributions
- Total withdrawals
- Net capital
- Fund inception date

## Future Updates

To keep contributors in sync going forward, you can either:

1. **Continue using CSV files** (current approach)
   - Contributors are managed via `fund_contributions.csv`
   - Re-run migration script when contributors change
   
2. **Use Supabase directly** (future enhancement)
   - Update application to read/write contributors from Supabase
   - Modify `ContributorManager` to use SupabaseRepository
   - Keep CSV files as backup

## Troubleshooting

### Error: Table doesn't exist

Run the schema file first:
```sql
-- In Supabase SQL Editor
database/schema/supabase/tables/fund_contributions.sql
```

### Error: Connection failed

Check your `.env` file has Supabase credentials:
```env
SUPABASE_URL=your-project-url
SUPABASE_KEY=your-anon-key
```

### Data looks wrong

Verify the CSV file format:
```bash
# Check the CSV file
head "trading_data/funds/Project Chimera/fund_contributions.csv"
```

Expected columns: `Timestamp,Contributor,Amount,Type,Notes,Email`

## Additional Notes

- The migration script **deletes existing data** for each fund before inserting new data
- Run `--dry-run` first to preview changes
- Contributor emails are used for the "Get Contributor Emails" feature
- Ownership percentages are calculated in the application based on net contributions

