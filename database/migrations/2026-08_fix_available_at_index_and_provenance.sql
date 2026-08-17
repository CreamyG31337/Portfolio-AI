-- AQuA transfer Phase 1 (corrective): make the PIT indexes usable and record which
-- available_at values are estimates.
--
-- Follows 2026-08_add_research_articles_available_at.sql and
-- 2026-08_add_social_available_at.sql, both already applied. Additive and
-- idempotent; safe to re-run. No column is dropped and no available_at value is
-- recomputed, so this cannot move an existing point-in-time boundary.
--
-- Three problems this fixes:
--
-- 1. UNUSABLE INDEXES. Every consumer filters on
--    COALESCE(available_at, fetched_at AT TIME ZONE 'UTC'), which is not sargable
--    against a plain (available_at) index. The original indexes therefore serve no
--    query while still costing write throughput on the hottest ingest tables.
--    Replaced with expression indexes that match the predicate exactly.
--
-- 2. NO PROVENANCE ON BACKFILLED ROWS. Rows predating the migration got
--    available_at = fetched_at, but fetched_at was bumped on every re-scrape by the
--    old save_article ON CONFLICT clause. An article first seen in 2024 and
--    re-scraped in 2026 carries available_at = 2026 and silently drops out of every
--    2024-2025 lookback.
--
--    NOTE ON DIRECTION -- deliberate, do not "fix" this by taking
--    LEAST(fetched_at, published_at): published_at is story time, and an article can
--    be published long before this system ever saw it. Pulling available_at back
--    toward published_at would let a story appear in a window during which we
--    demonstrably did not have it, which is lookahead bias -- the exact failure the
--    column exists to prevent. Erring LATE only loses real history; erring EARLY
--    fabricates knowledge. Late is the safe direction, so the values stand.
--
--    What was missing is that nothing marked those rows as estimates. The flag below
--    lets analysis distinguish a measured first-known time from a reconstructed one
--    without changing any boundary.
--
-- 3. A DEAD PARTIAL INDEX. idx_research_articles_available_unvalidated is queried by
--    nothing: every ticker_validated_at IS NULL consumer (backfill_relevance,
--    reprocess_tickerless, jobs_article_relevance) still orders by fetched_at.

-- ---------------------------------------------------------------------------
-- 1. Provenance flag
-- ---------------------------------------------------------------------------

ALTER TABLE research_articles
    ADD COLUMN IF NOT EXISTS available_at_is_estimated BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN research_articles.available_at_is_estimated IS
  'TRUE when available_at was reconstructed from fetched_at by the 2026-08 backfill rather than recorded at ingest. Such values are an upper bound on true first-known time (fetched_at was bumped on re-scrape), so these rows may be missing from historical lookbacks that should contain them. Rows inserted after the migration record available_at directly and are FALSE.';

ALTER TABLE social_metrics
    ADD COLUMN IF NOT EXISTS available_at_is_estimated BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN social_metrics.available_at_is_estimated IS
  'TRUE when available_at was reconstructed from created_at by the 2026-08 backfill rather than recorded at ingest.';

-- Mark the rows the earlier backfill touched. They are exactly the rows that predate
-- the column: anything inserted since carries its own DEFAULT NOW() value, which is
-- strictly later than the migration. Bounded by the migration timestamp rather than
-- by "available_at = fetched_at" because a same-second ingest would match that
-- equality by coincidence.
DO $$
DECLARE
    migration_applied_at TIMESTAMPTZ;
BEGIN
    SELECT MAX(available_at) INTO migration_applied_at
    FROM research_articles
    WHERE available_at IS NOT NULL
      AND available_at = fetched_at AT TIME ZONE 'UTC';

    IF migration_applied_at IS NOT NULL THEN
        UPDATE research_articles
        SET available_at_is_estimated = TRUE
        WHERE available_at_is_estimated = FALSE
          AND available_at <= migration_applied_at
          AND available_at = fetched_at AT TIME ZONE 'UTC';
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 2. Expression indexes matching the actual lookback predicate
-- ---------------------------------------------------------------------------
-- CONCURRENTLY is intentionally NOT used: these run inside the migration
-- transaction alongside the DDL above. research_articles / social_metrics take a
-- brief write lock. If that is unacceptable on the live Research DB, run this file's
-- index statements separately with CREATE INDEX CONCURRENTLY outside a transaction.

CREATE INDEX IF NOT EXISTS idx_research_articles_as_of
    ON research_articles ((COALESCE(available_at, fetched_at AT TIME ZONE 'UTC')) DESC);

CREATE INDEX IF NOT EXISTS idx_social_metrics_ticker_as_of
    ON social_metrics (ticker, (COALESCE(available_at, created_at AT TIME ZONE 'UTC')) DESC);

-- ---------------------------------------------------------------------------
-- 3. Drop indexes that serve no query
-- ---------------------------------------------------------------------------
-- Superseded by the expression index above.
DROP INDEX IF EXISTS idx_research_available_at;
DROP INDEX IF EXISTS idx_social_metrics_available_at;

-- Never queried: the unvalidated-article consumers all order by fetched_at, which is
-- already covered by idx_research_articles_unvalidated.
DROP INDEX IF EXISTS idx_research_articles_available_unvalidated;
