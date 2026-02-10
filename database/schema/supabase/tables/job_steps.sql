-- Job Steps: Real-time step-by-step progress logging for long-running jobs
-- Append-only table for tracking where jobs are in their pipeline

CREATE TABLE IF NOT EXISTS job_steps (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_name VARCHAR(100) NOT NULL,
    run_date DATE NOT NULL DEFAULT CURRENT_DATE,
    step_name VARCHAR(100) NOT NULL,
    message TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'running',  -- running, success, failed, skipped
    metadata JSONB,                                   -- optional: article_url, ticker, error details
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_job_steps_lookup ON job_steps (job_name, run_date, created_at DESC);
