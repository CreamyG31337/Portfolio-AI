-- Table: ai_analysis_skip_list
-- Tracks tickers that failed analysis and should be skipped
-- Admin can view and manage via admin UI

DROP TABLE IF EXISTS ai_analysis_skip_list CASCADE;

CREATE TABLE ai_analysis_skip_list (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    ticker VARCHAR(10) NOT NULL UNIQUE,
    reason TEXT,                          -- Why it failed (error message)
    first_failed_at TIMESTAMPTZ DEFAULT now(),
    last_failed_at TIMESTAMPTZ DEFAULT now(),
    failure_count INTEGER DEFAULT 1,
    skip_until TIMESTAMPTZ,               -- NULL = skip forever, or date to retry
    added_by VARCHAR(100),                -- 'system' or admin email
    notes TEXT,                           -- Admin notes
    
    PRIMARY KEY (id)
);

-- Indexes
CREATE INDEX idx_skip_list_ticker ON ai_analysis_skip_list (ticker);
CREATE INDEX idx_skip_list_last_failed ON ai_analysis_skip_list (last_failed_at DESC);

-- Comments
COMMENT ON TABLE ai_analysis_skip_list IS 'Tracks tickers that failed analysis and should be skipped. Shown in admin UI with clickable links to ticker details page.';
COMMENT ON COLUMN ai_analysis_skip_list.skip_until IS 'NULL = skip forever, or date to retry after';
COMMENT ON COLUMN ai_analysis_skip_list.added_by IS "'system' for auto-added after failures, or admin email for manual additions";
