-- Create missing job_steps table used by utils.job_tracking.log_job_step().
-- Without this table, long-running scheduler jobs silently lose per-step diagnostics.

CREATE TABLE IF NOT EXISTS public.job_steps (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_name VARCHAR(100) NOT NULL,
    run_date DATE NOT NULL DEFAULT CURRENT_DATE,
    step_name VARCHAR(100) NOT NULL,
    message TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_job_steps_lookup
    ON public.job_steps (job_name, run_date, created_at DESC);

ALTER TABLE public.job_steps ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "job_steps_service_role_full_access" ON public.job_steps;
CREATE POLICY "job_steps_service_role_full_access"
    ON public.job_steps
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);
