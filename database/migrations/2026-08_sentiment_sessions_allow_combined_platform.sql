-- Allow the 'combined' platform on merged sentiment sessions.
--
-- Target: research Postgres (RESEARCH_DATABASE_URL), not Supabase.
--
-- Sessions are now one per ticker per UTC day spanning both sources, so their
-- platform is 'combined' rather than a single feed. social_sentiment_analysis
-- copies the session's platform onto the analysis row, so both constraints
-- have to accept it.
--
-- social_posts and social_metrics deliberately keep the two-value constraint:
-- an individual post always comes from exactly one platform.

ALTER TABLE sentiment_sessions
    DROP CONSTRAINT IF EXISTS sentiment_sessions_platform_check;
ALTER TABLE sentiment_sessions
    ADD CONSTRAINT sentiment_sessions_platform_check
    CHECK (platform IN ('stocktwits', 'reddit', 'combined'));

ALTER TABLE social_sentiment_analysis
    DROP CONSTRAINT IF EXISTS social_sentiment_analysis_platform_check;
ALTER TABLE social_sentiment_analysis
    ADD CONSTRAINT social_sentiment_analysis_platform_check
    CHECK (platform IN ('stocktwits', 'reddit', 'combined'));
