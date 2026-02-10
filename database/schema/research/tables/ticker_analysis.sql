-- Table: ticker_analysis
DROP TABLE IF EXISTS ticker_analysis CASCADE;

CREATE TABLE ticker_analysis (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    ticker VARCHAR(10) NOT NULL,
    analysis_type VARCHAR(20) NOT NULL DEFAULT 'standard'::character varying,
    analysis_date DATE NOT NULL,
    data_start_date DATE NOT NULL,
    data_end_date DATE NOT NULL,
    sentiment VARCHAR(20),
    sentiment_score NUMERIC(3, 2),
    confidence_score NUMERIC(3, 2),
    themes ARRAY,
    summary TEXT,
    analysis_text TEXT,
    reasoning TEXT,
    input_context TEXT,
    etf_changes_count INTEGER DEFAULT 0,
    congress_trades_count INTEGER DEFAULT 0,
    research_articles_count INTEGER DEFAULT 0,
    embedding NULL,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    model_used VARCHAR(50) DEFAULT 'granite3.3:8b'::character varying,
    analysis_version INTEGER DEFAULT 1,
    requested_by VARCHAR(100),
    stance VARCHAR(10),
    timeframe VARCHAR(20),
    entry_zone VARCHAR(50),
    target_price VARCHAR(20),
    stop_loss VARCHAR(20),
    key_levels JSONB,
    catalysts ARRAY,
    risks ARRAY,
    invalidation TEXT
,
    PRIMARY KEY (id)
);

-- Indexes
CREATE INDEX idx_ticker_analysis_date ON ticker_analysis (analysis_date);
CREATE INDEX idx_ticker_analysis_embedding ON ticker_analysis (embedding);
CREATE INDEX idx_ticker_analysis_stance ON ticker_analysis (stance);
CREATE INDEX idx_ticker_analysis_ticker ON ticker_analysis (ticker);
CREATE INDEX idx_ticker_analysis_updated ON ticker_analysis (updated_at);
CREATE UNIQUE INDEX unique_ticker_analysis ON ticker_analysis (ticker, analysis_type, analysis_date);