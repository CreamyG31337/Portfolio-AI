# Migration 007: Enforce Contributor FK on Fund Contributions

## Overview

This migration enforces proper foreign key relationships between `fund_contributions` and `contributors` tables, fixing data integrity issues and enabling email auto-fill in the UI.

## Changes Made

### 1. Database Migration (`007_enforce_contributor_fk.sql`)

The migration:
1. **Backfills `contributor_id`** for existing contributions by:
   - Matching on email (highest confidence, since email is unique)
   - Matching on exact name (only if unique contributor with that name)
2. **Creates missing contributors** for orphaned contributions
3. **Adds FK constraint** with `ON DELETE SET NULL` (keeps contribution history if contributor is deleted)

### 2. API Changes (`admin_routes.py`)

The `POST /api/admin/contributions` endpoint now:
- Accepts `contributor_id` directly (preferred)
- Looks up contributors by email first, then by name
- Creates new contributors automatically if no match found
- Always populates both `contributor_id` and `contributor` (snapshot) fields
- Also populates `fund_id` for the fund FK

### 3. Frontend Changes (`contributions.ts`)

- **Datalist populated from `contributors` table** instead of contribution history
- **Email auto-fill** when selecting a contributor from the dropdown
- **Tracks `contributor_id`** for selected contributors and sends it with form submission
- **Clears selection** if user edits the name after selecting

## Running the Migration

```sql
-- Connect to your Supabase database and run:
\i migrations/007_enforce_contributor_fk.sql
```

Or run via Supabase SQL Editor.

## Verification Queries

After running the migration, verify with:

```sql
-- Check for any remaining NULL contributor_ids:
SELECT COUNT(*) as orphaned_count FROM fund_contributions WHERE contributor_id IS NULL;

-- Check FK constraint exists:
SELECT conname FROM pg_constraint WHERE conname = 'fund_contributions_contributor_id_fkey';

-- View backfill results:
SELECT 
    c.name as contributor_name,
    c.email as contributor_email,
    COUNT(fc.id) as contribution_count
FROM fund_contributions fc
LEFT JOIN contributors c ON fc.contributor_id = c.id
GROUP BY c.id, c.name, c.email
ORDER BY contribution_count DESC;
```

## Rollback

If needed, you can remove the FK constraint:

```sql
ALTER TABLE fund_contributions DROP CONSTRAINT fund_contributions_contributor_id_fkey;
```

Note: This only removes the constraint, not the backfilled data.

## Future Considerations

- **Phase 2**: Consider making `contributor_id` required for new contributions (app-level validation first)
- **Phase 3**: DB-level `NOT NULL` constraint once all historical data is clean
