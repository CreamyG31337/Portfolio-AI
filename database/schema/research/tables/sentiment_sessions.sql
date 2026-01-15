-- Table: sentiment_sessions
DROP TABLE IF EXISTS sentiment_sessions CASCADE;

CREATE TABLE sentiment_sessions (
    id INTEGER NOT NULL DEFAULT nextval('sentiment_sessions_id_seq'::regclass),
    ticker VARCHAR(20) NOT NULL,
    platform VARCHAR(20) NOT NULL,
    session_start TIMESTAMP NOT NULL,
    session_end TIMESTAMP NOT NULL,
    post_count INTEGER DEFAULT 0,
    total_engagement INTEGER DEFAULT 0,
    needs_ai_analysis BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT now()
,
    PRIMARY KEY (id)
);