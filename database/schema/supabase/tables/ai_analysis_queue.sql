-- Table: ai_analysis_queue
-- Resumable job queue for AI analysis tasks
-- Tracks progress so interrupted work resumes where it left off

DROP TABLE IF EXISTS ai_analysis_queue CASCADE;

CREATE TABLE ai_analysis_queue (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    analysis_type VARCHAR(30) NOT NULL,   -- 'etf_group' or 'ticker'
    target_key VARCHAR(50) NOT NULL,      -- ETF ticker + date (e.g., 'IWC_2026-01-15'), or ticker symbol
    priority INTEGER DEFAULT 0,           -- Higher = process first (holdings=100, watched=10, manual=1000)
    status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'in_progress', 'completed', 'failed'
    
    -- For resumability
    created_at TIMESTAMPTZ DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    
    PRIMARY KEY (id)
);

-- Indexes
CREATE INDEX idx_analysis_queue_pending ON ai_analysis_queue (status, priority DESC, created_at)
    WHERE status IN ('pending', 'failed');
CREATE INDEX idx_analysis_queue_recent ON ai_analysis_queue (completed_at DESC)
    WHERE status = 'completed';
CREATE INDEX idx_analysis_queue_type_key ON ai_analysis_queue (analysis_type, target_key);

-- Unique constraint: prevent duplicate pending work
CREATE UNIQUE INDEX unique_pending_analysis ON ai_analysis_queue (analysis_type, target_key, status)
    WHERE status IN ('pending', 'in_progress');

-- Comments
COMMENT ON TABLE ai_analysis_queue IS 'Resumable job queue for AI analysis tasks. Tracks progress so interrupted work resumes where it left off.';
COMMENT ON COLUMN ai_analysis_queue.target_key IS 'ETF ticker + date (e.g., "IWC_2026-01-15") for etf_group, or ticker symbol for ticker analysis';
COMMENT ON COLUMN ai_analysis_queue.priority IS 'Higher priority processed first: manual=1000, holdings=100, watched=10';
