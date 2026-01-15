-- Table: job_retry_queue
DROP TABLE IF EXISTS job_retry_queue CASCADE;

CREATE TABLE job_retry_queue (
    id INTEGER NOT NULL DEFAULT nextval('job_retry_queue_id_seq'::regclass),
    job_name VARCHAR(100) NOT NULL,
    target_date DATE,
    entity_id VARCHAR(200),
    entity_type VARCHAR(50) DEFAULT 'fund'::character varying,
    failure_reason VARCHAR(50) NOT NULL,
    error_message TEXT,
    failed_at TIMESTAMP DEFAULT now(),
    retry_count INTEGER DEFAULT 0,
    last_retry_at TIMESTAMP,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'::character varying,
    context JSONB,
    created_at TIMESTAMP DEFAULT now(),
    resolved_at TIMESTAMP
,
    PRIMARY KEY (id)
);

-- Indexes
CREATE INDEX idx_retry_queue_created ON job_retry_queue (created_at);
CREATE INDEX idx_retry_queue_job_entity ON job_retry_queue (job_name, entity_type, status);
CREATE INDEX idx_retry_queue_pending ON job_retry_queue (target_date);
CREATE INDEX idx_retry_queue_status ON job_retry_queue (status, target_date);
CREATE UNIQUE INDEX unique_retry_entry ON job_retry_queue (job_name, target_date, entity_id, entity_type);