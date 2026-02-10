-- Table: ai_analysis_queue
DROP TABLE IF EXISTS ai_analysis_queue CASCADE;

CREATE TABLE ai_analysis_queue (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    analysis_type VARCHAR(30) NOT NULL,
    target_key VARCHAR(50) NOT NULL,
    priority INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'pending'::character varying,
    created_at TIMESTAMP DEFAULT now(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0
,
    PRIMARY KEY (id)
);

-- Indexes
CREATE INDEX idx_analysis_queue_pending ON ai_analysis_queue (status, priority, created_at);
CREATE INDEX idx_analysis_queue_recent ON ai_analysis_queue (completed_at);
CREATE INDEX idx_analysis_queue_type_key ON ai_analysis_queue (analysis_type, target_key);
CREATE UNIQUE INDEX unique_pending_analysis ON ai_analysis_queue (analysis_type, target_key, status);