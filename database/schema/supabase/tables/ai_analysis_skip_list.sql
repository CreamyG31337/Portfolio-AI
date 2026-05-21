-- Table: ai_analysis_skip_list
DROP TABLE IF EXISTS ai_analysis_skip_list CASCADE;

CREATE TABLE ai_analysis_skip_list (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    ticker VARCHAR(10) NOT NULL,
    reason TEXT,
    first_failed_at TIMESTAMP DEFAULT now(),
    last_failed_at TIMESTAMP DEFAULT now(),
    failure_count INTEGER DEFAULT 1,
    skip_until TIMESTAMP,
    added_by VARCHAR(100),
    notes TEXT
,
    PRIMARY KEY (id)
);

ALTER TABLE ai_analysis_skip_list ENABLE ROW LEVEL SECURITY;

-- Indexes
CREATE UNIQUE INDEX ai_analysis_skip_list_ticker_key ON ai_analysis_skip_list (ticker);
CREATE INDEX idx_skip_list_last_failed ON ai_analysis_skip_list (last_failed_at);
CREATE INDEX idx_skip_list_ticker ON ai_analysis_skip_list (ticker);