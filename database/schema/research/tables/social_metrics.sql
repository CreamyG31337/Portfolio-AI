-- Table: social_metrics
DROP TABLE IF EXISTS social_metrics CASCADE;

CREATE TABLE social_metrics (
    id INTEGER NOT NULL DEFAULT nextval('social_metrics_id_seq'::regclass),
    ticker VARCHAR(20) NOT NULL,
    platform VARCHAR(20) NOT NULL,
    volume INTEGER DEFAULT 0,
    bull_bear_ratio DOUBLE PRECISION DEFAULT 0.0,
    sentiment_label VARCHAR(20),
    sentiment_score DOUBLE PRECISION,
    raw_data JSONB,
    created_at TIMESTAMP DEFAULT now(),
    basic_sentiment_score NUMERIC(3, 2),
    has_ai_analysis BOOLEAN DEFAULT false,
    analysis_session_id INTEGER,
    raw_posts ARRAY,
    post_count INTEGER DEFAULT 0,
    engagement_score DOUBLE PRECISION DEFAULT 0.0,
    data_quality_score DOUBLE PRECISION DEFAULT 0.0,
    collection_metadata JSONB
,
    PRIMARY KEY (id)
);

-- Indexes
CREATE INDEX idx_social_created_at ON social_metrics (created_at);
CREATE INDEX idx_social_platform ON social_metrics (platform);
CREATE INDEX idx_social_ticker_platform ON social_metrics (ticker, platform);
CREATE INDEX idx_social_ticker_time ON social_metrics (ticker, created_at);