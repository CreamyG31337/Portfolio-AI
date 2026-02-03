-- Migration: Enforce contributor_id FK on fund_contributions
-- This migration:
-- 1. Backfills contributor_id by matching on email (unique) or exact name
-- 2. Creates missing contributors from orphaned contributions
-- 3. Adds the FK constraint

-- ============================================================================
-- STEP 1: Backfill contributor_id by matching on email (highest confidence)
-- ============================================================================
UPDATE fund_contributions fc
SET contributor_id = c.id
FROM contributors c
WHERE fc.contributor_id IS NULL
  AND fc.email IS NOT NULL
  AND fc.email != ''
  AND LOWER(fc.email) = LOWER(c.email);

-- ============================================================================
-- STEP 2: Backfill contributor_id by exact name match (only if unique)
-- This avoids matching "John Smith" to the wrong contributor
-- ============================================================================
UPDATE fund_contributions fc
SET contributor_id = (
    SELECT c.id 
    FROM contributors c 
    WHERE LOWER(c.name) = LOWER(fc.contributor)
    LIMIT 1
)
WHERE fc.contributor_id IS NULL
  AND (SELECT COUNT(*) FROM contributors c WHERE LOWER(c.name) = LOWER(fc.contributor)) = 1;

-- ============================================================================
-- STEP 3: Create contributors for orphaned contributions
-- Group by (contributor name, email) to avoid duplicates
-- ============================================================================
INSERT INTO contributors (name, email, kyc_status, created_at, updated_at)
SELECT DISTINCT ON (LOWER(fc.contributor), LOWER(fc.email))
    fc.contributor,
    fc.email,
    'pending',
    NOW(),
    NOW()
FROM fund_contributions fc
WHERE fc.contributor_id IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM contributors c 
    WHERE LOWER(c.name) = LOWER(fc.contributor)
      AND (
        (c.email IS NULL AND fc.email IS NULL) OR
        LOWER(c.email) = LOWER(fc.email)
      )
  )
ORDER BY LOWER(fc.contributor), LOWER(fc.email), fc.created_at DESC;

-- ============================================================================
-- STEP 4: Backfill contributor_id for newly created contributors
-- ============================================================================
UPDATE fund_contributions fc
SET contributor_id = c.id
FROM contributors c
WHERE fc.contributor_id IS NULL
  AND LOWER(c.name) = LOWER(fc.contributor)
  AND (
    (c.email IS NULL AND fc.email IS NULL) OR
    LOWER(c.email) = LOWER(fc.email)
  );

-- ============================================================================
-- STEP 5: Add FK constraint (NOT VALID first for safety, then validate)
-- ============================================================================
-- First drop the old FK if it exists (from previous partial migrations)
ALTER TABLE fund_contributions 
DROP CONSTRAINT IF EXISTS fund_contributions_contributor_id_fkey;

-- Add FK constraint as NOT VALID (allows constraint to be added without full table scan)
ALTER TABLE fund_contributions 
ADD CONSTRAINT fund_contributions_contributor_id_fkey 
FOREIGN KEY (contributor_id) 
REFERENCES contributors(id) 
ON DELETE SET NULL
NOT VALID;

-- Validate the constraint (this will fail if there are orphaned contributor_ids)
ALTER TABLE fund_contributions 
VALIDATE CONSTRAINT fund_contributions_contributor_id_fkey;

-- ============================================================================
-- VERIFICATION QUERIES (run these to check results)
-- ============================================================================
-- Check for any remaining NULL contributor_ids:
-- SELECT COUNT(*) as orphaned_count FROM fund_contributions WHERE contributor_id IS NULL;

-- Check for any invalid contributor_ids (should be 0 after validation):
-- SELECT COUNT(*) FROM fund_contributions fc 
-- WHERE fc.contributor_id IS NOT NULL 
--   AND NOT EXISTS (SELECT 1 FROM contributors c WHERE c.id = fc.contributor_id);

-- View the backfill results:
-- SELECT 
--     c.name as contributor_name,
--     c.email as contributor_email,
--     COUNT(fc.id) as contribution_count
-- FROM fund_contributions fc
-- LEFT JOIN contributors c ON fc.contributor_id = c.id
-- GROUP BY c.id, c.name, c.email
-- ORDER BY contribution_count DESC;
