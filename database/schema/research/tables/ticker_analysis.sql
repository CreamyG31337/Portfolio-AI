-- Table: ticker_analysis
-- Stores AI analysis results for individual tickers with 3 months of multi-source data
-- Supports different analysis types (short_term, long_term, standard)
-- Includes embeddings for semantic search

DROP TABLE IF EXISTS ticker_analysis CASCADE;

CREATE TABLE ticker_analysis (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    ticker VARCHAR(10) NOT NULL,
    analysis_type VARCHAR(20) NOT NULL DEFAULT 'standard',
    
    -- Analysis period
    analysis_date DATE NOT NULL,        -- Date analysis was run
    data_start_date DATE NOT NULL,      -- Start of data window (e.g., 3 months ago)
    data_end_date DATE NOT NULL,        -- End of data window (usually today)
    
    -- AI Analysis Results
    sentiment VARCHAR(20) CHECK (sentiment IN ('BULLISH', 'BEARISH', 'NEUTRAL', 'MIXED')),
    sentiment_score NUMERIC(3, 2) CHECK (sentiment_score >= -1.0 AND sentiment_score <= 1.0),
    confidence_score NUMERIC(3, 2) CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0),
    themes TEXT[],                      -- ["semiconductors", "AI chips", "accumulation"]
    summary TEXT,                       -- 1-2 sentence actionable summary
    analysis_text TEXT,                 -- Full analysis (shown to user)
    reasoning TEXT,                     -- Internal reasoning (for debugging)
    
    -- Actionable Trading Fields (added 2025-01)
    stance VARCHAR(10) CHECK (stance IN ('BUY', 'SELL', 'HOLD', 'AVOID')),
    timeframe VARCHAR(20) CHECK (timeframe IN ('day_trade', 'swing', 'position')),
    entry_zone VARCHAR(50),             -- e.g., "$45-47"
    target_price VARCHAR(20),           -- e.g., "$52"
    stop_loss VARCHAR(20),              -- e.g., "$42"
    key_levels JSONB,                   -- {"support": ["$45", "$42"], "resistance": ["$50", "$55"]}
    catalysts TEXT[],                   -- ["earnings next week", "FDA approval pending"]
    risks TEXT[],                       -- ["high valuation", "sector rotation risk"]
    invalidation TEXT,                  -- What would invalidate this thesis
    
    -- Debug: What data was sent to AI
    input_context TEXT,                 -- The actual text sent to LLM (shown in debug panel)
    
    -- Data source counts (for staleness detection)
    etf_changes_count INTEGER DEFAULT 0,
    congress_trades_count INTEGER DEFAULT 0,
    research_articles_count INTEGER DEFAULT 0,
    
    -- Semantic search
    embedding vector(768),
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    model_used VARCHAR(50) DEFAULT 'granite3.3:8b',
    analysis_version INTEGER DEFAULT 1,
    
    -- For manual re-analysis requests
    requested_by VARCHAR(100),          -- User who requested re-analysis (NULL = scheduled)
    
    PRIMARY KEY (id),
    CONSTRAINT unique_ticker_analysis UNIQUE(ticker, analysis_type, analysis_date)
);

-- Indexes
CREATE INDEX idx_ticker_analysis_ticker ON ticker_analysis (ticker);
CREATE INDEX idx_ticker_analysis_date ON ticker_analysis (analysis_date DESC);
CREATE INDEX idx_ticker_analysis_updated ON ticker_analysis (updated_at DESC);
-- Note: Partial index for stale analyses removed - NOW() is not IMMUTABLE
-- Use regular index and filter in queries: WHERE updated_at < NOW() - INTERVAL '24 hours'
CREATE INDEX idx_ticker_analysis_embedding ON ticker_analysis 
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Comments
COMMENT ON TABLE ticker_analysis IS 'AI analysis results for individual tickers with 3 months of multi-source data (ETF changes, congress trades, signals, fundamentals, articles, sentiment)';
COMMENT ON COLUMN ticker_analysis.analysis_date IS 'Date the analysis was run (used for uniqueness constraint)';
COMMENT ON COLUMN ticker_analysis.data_start_date IS 'Start of data window analyzed (e.g., 3 months ago)';
COMMENT ON COLUMN ticker_analysis.data_end_date IS 'End of data window analyzed (usually today)';
COMMENT ON COLUMN ticker_analysis.input_context IS 'The exact text sent to LLM (shown in debug panel on ticker details page)';
COMMENT ON COLUMN ticker_analysis.requested_by IS 'User email who requested re-analysis (NULL = scheduled job)';
