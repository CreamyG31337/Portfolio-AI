-- AQuA transfer Phase 1: point-in-time clock for research_articles.
--
-- available_at = when this system first knew about the article (immutable).
-- Analysis lookbacks must filter on available_at, not fetched_at / published_at.
-- published_at remains story-time / display-only.
--
-- Backfill uses fetched_at as the best recoverable first-seen timestamp.
-- Additive; safe to re-run.

ALTER TABLE research_articles
    ADD COLUMN IF NOT EXISTS available_at TIMESTAMPTZ;

COMMENT ON COLUMN research_articles.available_at IS
  'Point-in-time first-known timestamp for this system. Set once on insert; never updated on upsert. Analysis lookbacks must use available_at <= as_of, not fetched_at or published_at.';

UPDATE research_articles
SET available_at = COALESCE(fetched_at, NOW())
WHERE available_at IS NULL;

ALTER TABLE research_articles
    ALTER COLUMN available_at SET DEFAULT NOW();

-- Not NULL after backfill; keep nullable only if empty table edge cases remain.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM research_articles WHERE available_at IS NULL LIMIT 1
    ) THEN
        UPDATE research_articles SET available_at = NOW() WHERE available_at IS NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_research_available_at
    ON research_articles (available_at DESC);

CREATE INDEX IF NOT EXISTS idx_research_articles_available_unvalidated
    ON research_articles (available_at DESC)
    WHERE ticker_validated_at IS NULL AND tickers IS NOT NULL;
