-- Table: apscheduler_jobs
DROP TABLE IF EXISTS apscheduler_jobs CASCADE;

CREATE TABLE apscheduler_jobs (
    id VARCHAR(191) NOT NULL,
    next_run_time DOUBLE PRECISION,
    job_state BYTEA NOT NULL
,
    PRIMARY KEY (id)
);

-- Indexes
CREATE INDEX ix_apscheduler_jobs_next_run_time ON apscheduler_jobs (next_run_time);