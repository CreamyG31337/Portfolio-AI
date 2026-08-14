-- Social sentiment AI pipeline: post identity, session link, and indexes.
--
-- Target: research Postgres (RESEARCH_DATABASE_URL), not Supabase.
--
-- Context: the pipeline (social_metrics.raw_data -> social_posts ->
-- sentiment_sessions -> social_sentiment_analysis) shipped with no indexes on
-- its own tables, no post-identity constraint, and no way to attach a post to
-- a session directly. Measured consequences over 14 days of live data:
--   * Reddit stored 17,763 post rows representing 251 distinct posts (70.8x),
--     because every ticker is re-polled ~20x/day and nothing deduplicated
--     across polls.
--   * Sessions grouped on social_metrics.analysis_session_id, which cannot
--     express per-day grouping: one poll routinely returns posts from several
--     days, and a metric row can only point at one session.
--
-- Apply with web_dashboard/scripts/apply_social_sentiment_indexes.py --apply.
-- That runner is required: the CREATE INDEX CONCURRENTLY statements below
-- cannot run inside a transaction block, and PostgresClient.get_connection()
-- commits as one.

-- --------------------------------------------------------------------------
-- Part 1: schema (transactional, safe to run normally)
-- --------------------------------------------------------------------------

-- Posts claim their own session. Authoritative link, replacing the hop
-- through social_metrics.analysis_session_id.
ALTER TABLE social_posts
    ADD COLUMN IF NOT EXISTS session_id INTEGER REFERENCES sentiment_sessions(id);

-- _stable_post_id() always returns a non-empty value, so the dedupe key below
-- can be trusted. NULLs would silently defeat it (NULL <> NULL in a unique
-- index, so every null-id post would be treated as distinct).
UPDATE social_posts SET post_id = 'legacy:' || id WHERE post_id IS NULL;
ALTER TABLE social_posts ALTER COLUMN post_id SET NOT NULL;

-- --------------------------------------------------------------------------
-- Part 2: indexes (each must run outside a transaction block)
-- --------------------------------------------------------------------------

-- Cross-poll dedupe target for INSERT ... ON CONFLICT (platform, post_id).
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_social_posts_platform_post_id
    ON social_posts (platform, post_id);

-- create_sentiment_sessions(): WHERE sp.session_id IS NULL
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_social_posts_unassigned
    ON social_posts (posted_at DESC)
    WHERE session_id IS NULL;

-- analyze_sentiment_session(): LEFT JOIN social_posts sp ON sp.session_id = ss.id
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_social_posts_session_id
    ON social_posts (session_id);

-- extract_posts_from_raw_data(): NOT EXISTS (... WHERE sp.metric_id = sm.id)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_social_posts_metric_id
    ON social_posts (metric_id);

-- create_sentiment_sessions() reuses an existing session for a ticker/day.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sentiment_sessions_ticker_day
    ON sentiment_sessions (ticker, platform, session_start);

-- Queue worker lease + cron enqueue: pending sessions, newest first.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sentiment_sessions_pending
    ON sentiment_sessions (session_start DESC)
    WHERE needs_ai_analysis = TRUE;

-- Dashboard: WHERE ssa.analyzed_at > NOW() - INTERVAL '7 days' ORDER BY analyzed_at DESC
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_social_sentiment_analysis_analyzed_at
    ON social_sentiment_analysis (analyzed_at DESC);

-- extracted_tickers rows are always fetched by their parent analysis.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_extracted_tickers_analysis_id
    ON extracted_tickers (analysis_id);

-- One analysis per session. A queue task that inserts and then dies before
-- clearing needs_ai_analysis gets re-leased; without this the retry inserts a
-- duplicate. analyze_sentiment_session() also checks first, but that check
-- races between concurrent workers and this does not.
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_social_sentiment_analysis_session
    ON social_sentiment_analysis (session_id);
