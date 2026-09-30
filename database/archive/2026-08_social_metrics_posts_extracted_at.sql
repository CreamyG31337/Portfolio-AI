-- social_metrics.posts_extracted_at: mark a metric's raw_data as walked.
--
-- Target: research Postgres (RESEARCH_DATABASE_URL), not Supabase.
--
-- extract_posts_from_raw_data() used to select work with
--   NOT EXISTS (SELECT 1 FROM social_posts sp WHERE sp.metric_id = sm.id)
-- which was fine only while every post always produced a row. Cross-poll
-- dedupe (INSERT ... ON CONFLICT (platform, post_id) DO NOTHING) broke that
-- assumption: a metric whose posts were all seen on an earlier poll creates
-- zero rows, so the presence test kept re-selecting it and extraction could
-- never advance past it.
--
-- Apply with web_dashboard/scripts/apply_social_sentiment_migrations.py --apply
-- (CREATE INDEX CONCURRENTLY cannot run inside a transaction block).

ALTER TABLE social_metrics
    ADD COLUMN IF NOT EXISTS posts_extracted_at TIMESTAMPTZ;

-- Metrics that already produced posts are, by definition, already walked.
-- Without this every historical metric would be re-scanned once.
UPDATE social_metrics sm
SET posts_extracted_at = NOW()
WHERE sm.posts_extracted_at IS NULL
  AND EXISTS (SELECT 1 FROM social_posts sp WHERE sp.metric_id = sm.id);

-- Rows that can never yield posts should not be rescanned either.
UPDATE social_metrics sm
SET posts_extracted_at = NOW()
WHERE sm.posts_extracted_at IS NULL
  AND (
        sm.raw_data IS NULL
     OR jsonb_typeof(sm.raw_data) <> 'array'
     OR jsonb_array_length(sm.raw_data) = 0
  );

-- The extraction hot path: pending work, newest first.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_social_metrics_pending_extract
    ON social_metrics (created_at DESC)
    WHERE posts_extracted_at IS NULL;
