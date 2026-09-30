-- AQuA transfer Phase 1 (social): immutable first-known clock.
-- available_at set once on insert; analysis lookbacks should prefer it over
-- created_at when present. Backfill from created_at.
-- Additive; safe to re-run.

ALTER TABLE social_metrics
    ADD COLUMN IF NOT EXISTS available_at TIMESTAMPTZ;

ALTER TABLE social_posts
    ADD COLUMN IF NOT EXISTS available_at TIMESTAMPTZ;

COMMENT ON COLUMN social_metrics.available_at IS
  'Point-in-time first-known timestamp. Set once on insert; never rewritten.';

COMMENT ON COLUMN social_posts.available_at IS
  'Point-in-time first-known timestamp. Set once on insert; never rewritten.';

UPDATE social_metrics
SET available_at = COALESCE(created_at, NOW())
WHERE available_at IS NULL;

UPDATE social_posts
SET available_at = COALESCE(created_at, NOW())
WHERE available_at IS NULL;

ALTER TABLE social_metrics
    ALTER COLUMN available_at SET DEFAULT NOW();

ALTER TABLE social_posts
    ALTER COLUMN available_at SET DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_social_metrics_available_at
    ON social_metrics (ticker, available_at DESC);

CREATE INDEX IF NOT EXISTS idx_social_posts_available_at
    ON social_posts (available_at DESC);
