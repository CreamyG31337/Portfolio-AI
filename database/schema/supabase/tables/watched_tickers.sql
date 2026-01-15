-- Table: watched_tickers
DROP TABLE IF EXISTS watched_tickers CASCADE;

CREATE TABLE watched_tickers (
    ticker VARCHAR(20) NOT NULL,
    priority_tier VARCHAR(10) DEFAULT 'B'::character varying,
    is_active BOOLEAN DEFAULT true,
    source VARCHAR(50),
    created_at TIMESTAMP DEFAULT now()
,
    PRIMARY KEY (ticker)
);

-- Indexes
CREATE INDEX idx_watched_tickers_active ON watched_tickers (is_active);
CREATE INDEX idx_watched_tickers_priority ON watched_tickers (priority_tier);