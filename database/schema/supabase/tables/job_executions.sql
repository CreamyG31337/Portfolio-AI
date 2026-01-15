-- Table: job_executions
DROP TABLE IF EXISTS job_executions CASCADE;

CREATE TABLE job_executions (
    id INTEGER NOT NULL DEFAULT nextval('job_executions_id_seq'::regclass),
    job_name VARCHAR(100) NOT NULL,
    target_date DATE NOT NULL,
    fund_name VARCHAR(200),
    status VARCHAR(20) NOT NULL,
    started_at TIMESTAMP DEFAULT now(),
    completed_at TIMESTAMP,
    funds_processed ARRAY,
    error_message TEXT,
    duration_ms INTEGER
,
    PRIMARY KEY (id)
);

-- Indexes
CREATE INDEX idx_job_executions_date ON job_executions (target_date);
CREATE INDEX idx_job_executions_running ON job_executions (status);
CREATE INDEX idx_job_executions_status ON job_executions (job_name, target_date, status);
CREATE UNIQUE INDEX unique_job_execution ON job_executions (job_name, target_date, fund_name);