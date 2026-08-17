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
-- 2. NO RISK FLAG ON ROWS WHOSE available_at IS AN OVERESTIMATE. Rows predating the
--    migration got available_at = fetched_at, but fetched_at was bumped on every
--    re-scrape by the old save_article ON CONFLICT clause. An article first seen in
--    2024 and re-scraped in 2026 carries available_at = 2026 and silently drops out
--    of every 2024-2025 lookback. 459 rows currently show a >30d publish-to-fetch
--    gap and are flagged.
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
  'TRUE when available_at is likely to OVERSTATE true first-known time, because fetched_at was recorded far later than the story was published and the old save_article bumped fetched_at on every re-scrape. Such rows may be absent from historical lookbacks that should contain them. This is a heuristic risk flag, not a record of provenance: backfilled and natively-recorded rows are indistinguishable in this schema (both DEFAULTs evaluate to the same transaction timestamp, so available_at = fetched_at holds for every row either way).';

-- Mark rows where the conservative backfill plausibly hid real history: the story was
-- published well before this system recorded fetching it. Those are the rows whose
-- available_at is most likely an overestimate.
--
-- NOT marked by "available_at = fetched_at": that equality holds for all 12,935 rows,
-- including ones inserted after the migration, because now() is stable within a
-- transaction and both column DEFAULTs evaluate to it. Backfilled and natively
-- recorded rows genuinely cannot be told apart from the data, so this flag reports
-- the risk that is measurable rather than a provenance it cannot know.
--
-- social_metrics gets no such flag: it has no published_at analogue, so there is
-- nothing to compare created_at against and no measurable risk signal.
UPDATE research_articles
SET available_at_is_estimated = TRUE
WHERE available_at_is_estimated = FALSE
  AND published_at IS NOT NULL
  AND fetched_at IS NOT NULL
  AND fetched_at - published_at > INTERVAL '30 days';

-- ---------------------------------------------------------------------------
-- 2. Expression indexes matching the actual lookback predicate
-- ---------------------------------------------------------------------------
-- CONCURRENTLY is intentionally NOT used: these run inside the migration
-- transaction alongside the DDL above. research_articles / social_metrics take a
-- brief write lock. If that is unacceptable on the live Research DB, run this file's
-- index statements separately with CREATE INDEX CONCURRENTLY outside a transaction.

-- NOTE: the two expressions differ, and must. research_articles.fetched_at is
-- TIMESTAMP WITHOUT TIME ZONE, so the naive value is pinned to UTC explicitly.
-- social_metrics.created_at is ALREADY timestamptz in this database (the checked-in
-- schema file describing it as TIMESTAMP is stale), and applying AT TIME ZONE 'UTC'
-- to a timestamptz performs the opposite conversion. An index expression that does
-- not match the predicate pit_time emits, character for character, will not be used.

CREATE INDEX IF NOT EXISTS idx_research_articles_as_of
    ON research_articles ((COALESCE(available_at, fetched_at AT TIME ZONE 'UTC')) DESC);

CREATE INDEX IF NOT EXISTS idx_social_metrics_ticker_as_of
    ON social_metrics (ticker, (COALESCE(available_at, created_at)) DESC);

-- ---------------------------------------------------------------------------
-- 3. Drop indexes that serve no query
-- ---------------------------------------------------------------------------
-- Superseded by the expression index above.
DROP INDEX IF EXISTS idx_research_available_at;
DROP INDEX IF EXISTS idx_social_metrics_available_at;

-- Never queried: the unvalidated-article consumers all order by fetched_at, which is
-- already covered by idx_research_articles_unvalidated.
DROP INDEX IF EXISTS idx_research_articles_available_unvalidated;
