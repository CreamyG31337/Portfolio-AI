-- Table: social_sentiment_analysis
DROP TABLE IF EXISTS social_sentiment_analysis CASCADE;

CREATE TABLE social_sentiment_analysis (
    id INTEGER NOT NULL DEFAULT nextval('social_sentiment_analysis_id_seq'::regclass),
    session_id INTEGER NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    platform VARCHAR(20) NOT NULL,
    sentiment_score NUMERIC(3, 2),
    confidence_score NUMERIC(3, 2),
    sentiment_label VARCHAR(20),
    summary TEXT,
    key_themes ARRAY,
    reasoning TEXT,
    model_used VARCHAR(100) DEFAULT 'granite3.1:8b'::character varying,
    analysis_version INTEGER DEFAULT 1,
    analyzed_at TIMESTAMP DEFAULT now()
,
    PRIMARY KEY (id)
);