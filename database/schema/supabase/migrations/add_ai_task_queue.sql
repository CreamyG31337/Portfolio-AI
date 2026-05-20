-- Add backend-bound AI task queue plumbing.
-- Phase 1 only: no scheduler job is migrated by this migration.

CREATE TABLE IF NOT EXISTS ai_task_queue (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    analysis_type VARCHAR(40) NOT NULL,
    target_key VARCHAR(100) NOT NULL,
    payload JSONB,
    priority INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'::character varying,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    last_error TEXT,
    last_error_class VARCHAR(40),
    leased_by VARCHAR(120),
    leased_backend VARCHAR(40),
    leased_until TIMESTAMP WITH TIME ZONE,
    available_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    enqueued_by VARCHAR(40),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    completed_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT ai_task_queue_attempts_nonnegative CHECK (attempts >= 0),
    CONSTRAINT ai_task_queue_max_attempts_positive CHECK (max_attempts > 0),
    CONSTRAINT ai_task_queue_status_check CHECK (
        status IN ('pending', 'leased', 'done', 'failed', 'cancelled')
    )
);

ALTER TABLE ai_task_queue ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS ai_task_queue_pending_idx
    ON ai_task_queue (status, priority DESC, created_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS ai_task_queue_lease_recovery_idx
    ON ai_task_queue (status, leased_until)
    WHERE status = 'leased';

CREATE INDEX IF NOT EXISTS ai_task_queue_type_status_idx
    ON ai_task_queue (analysis_type, status, target_key);

CREATE UNIQUE INDEX IF NOT EXISTS ai_task_queue_active_dedupe_idx
    ON ai_task_queue (analysis_type, target_key)
    WHERE status IN ('pending', 'leased');

DROP POLICY IF EXISTS "Allow service role full access" ON ai_task_queue;
CREATE POLICY "Allow service role full access" ON ai_task_queue
    FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow authenticated users to read ai task queue" ON ai_task_queue;
CREATE POLICY "Allow authenticated users to read ai task queue" ON ai_task_queue
    FOR SELECT TO authenticated USING (true);

CREATE OR REPLACE FUNCTION public.lease_ai_task(
    p_worker_id text,
    p_backend text,
    p_analysis_types text[] DEFAULT NULL,
    p_lease_seconds integer DEFAULT 90
)
 RETURNS SETOF public.ai_task_queue
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
BEGIN
    RETURN QUERY
    WITH candidate AS (
        SELECT id
        FROM ai_task_queue
        WHERE (
                status = 'pending'
                OR (status = 'leased' AND leased_until < now())
            )
          AND attempts < max_attempts
          AND available_at <= now()
          AND (
                p_analysis_types IS NULL
                OR cardinality(p_analysis_types) = 0
                OR analysis_type = ANY(p_analysis_types)
            )
        ORDER BY priority DESC, created_at ASC
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    UPDATE ai_task_queue AS q
    SET status = 'leased',
        leased_by = p_worker_id,
        leased_backend = p_backend,
        leased_until = now() + make_interval(secs => GREATEST(p_lease_seconds, 1)),
        updated_at = now(),
        last_error = NULL,
        last_error_class = NULL
    FROM candidate
    WHERE q.id = candidate.id
    RETURNING q.*;
END;
$function$;

CREATE OR REPLACE FUNCTION public.enqueue_ai_task(
    p_analysis_type text,
    p_target_key text,
    p_payload jsonb DEFAULT NULL::jsonb,
    p_priority integer DEFAULT 0,
    p_enqueued_by text DEFAULT NULL::text,
    p_max_attempts integer DEFAULT 3
)
 RETURNS public.ai_task_queue
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    queued public.ai_task_queue;
BEGIN
    INSERT INTO ai_task_queue (
        analysis_type,
        target_key,
        payload,
        priority,
        max_attempts,
        enqueued_by
    )
    VALUES (
        LEFT(p_analysis_type, 40),
        LEFT(UPPER(p_target_key), 100),
        COALESCE(p_payload, '{}'::jsonb),
        p_priority,
        GREATEST(p_max_attempts, 1),
        LEFT(COALESCE(p_enqueued_by, ''), 40)
    )
    ON CONFLICT (analysis_type, target_key)
        WHERE status IN ('pending', 'leased')
    DO UPDATE SET
        priority = GREATEST(ai_task_queue.priority, EXCLUDED.priority),
        payload = COALESCE(ai_task_queue.payload, '{}'::jsonb) || EXCLUDED.payload,
        max_attempts = GREATEST(ai_task_queue.max_attempts, EXCLUDED.max_attempts),
        enqueued_by = CASE
            WHEN EXCLUDED.enqueued_by IS NULL OR EXCLUDED.enqueued_by = ''
                THEN ai_task_queue.enqueued_by
            ELSE EXCLUDED.enqueued_by
        END,
        updated_at = now()
    RETURNING * INTO queued;

    RETURN queued;
END;
$function$;

CREATE OR REPLACE FUNCTION public.heartbeat_ai_task(
    p_task_id uuid,
    p_worker_id text,
    p_lease_seconds integer DEFAULT 90
)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    updated_count integer;
BEGIN
    UPDATE ai_task_queue
    SET leased_until = now() + make_interval(secs => GREATEST(p_lease_seconds, 1)),
        updated_at = now()
    WHERE id = p_task_id
      AND leased_by = p_worker_id
      AND status = 'leased';

    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RETURN updated_count = 1;
END;
$function$;

CREATE OR REPLACE FUNCTION public.complete_ai_task(
    p_task_id uuid,
    p_worker_id text
)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    updated_count integer;
BEGIN
    UPDATE ai_task_queue
    SET status = 'done',
        leased_by = NULL,
        leased_backend = NULL,
        leased_until = NULL,
        updated_at = now(),
        completed_at = now(),
        last_error = NULL,
        last_error_class = NULL
    WHERE id = p_task_id
      AND leased_by = p_worker_id
      AND status = 'leased';

    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RETURN updated_count = 1;
END;
$function$;

CREATE OR REPLACE FUNCTION public.release_ai_task(
    p_task_id uuid,
    p_worker_id text,
    p_error_class text,
    p_error_message text,
    p_increment_attempts boolean DEFAULT true,
    p_delay_seconds integer DEFAULT 0
)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    updated_count integer;
BEGIN
    UPDATE ai_task_queue
    SET attempts = attempts + CASE WHEN p_increment_attempts THEN 1 ELSE 0 END,
        status = CASE
            WHEN attempts + CASE WHEN p_increment_attempts THEN 1 ELSE 0 END >= max_attempts
                THEN 'failed'
            ELSE 'pending'
        END,
        leased_by = NULL,
        leased_backend = NULL,
        leased_until = NULL,
        available_at = now() + make_interval(secs => GREATEST(p_delay_seconds, 0)),
        updated_at = now(),
        completed_at = CASE
            WHEN attempts + CASE WHEN p_increment_attempts THEN 1 ELSE 0 END >= max_attempts
                THEN now()
            ELSE completed_at
        END,
        last_error = LEFT(COALESCE(p_error_message, ''), 2000),
        last_error_class = LEFT(COALESCE(p_error_class, 'unknown'), 40)
    WHERE id = p_task_id
      AND leased_by = p_worker_id
      AND status = 'leased';

    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RETURN updated_count = 1;
END;
$function$;

CREATE OR REPLACE FUNCTION public.fail_ai_task(
    p_task_id uuid,
    p_worker_id text,
    p_error_class text,
    p_error_message text
)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    updated_count integer;
BEGIN
    UPDATE ai_task_queue
    SET status = 'failed',
        leased_by = NULL,
        leased_backend = NULL,
        leased_until = NULL,
        updated_at = now(),
        completed_at = now(),
        last_error = LEFT(COALESCE(p_error_message, ''), 2000),
        last_error_class = LEFT(COALESCE(p_error_class, 'unknown'), 40)
    WHERE id = p_task_id
      AND leased_by = p_worker_id
      AND status = 'leased';

    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RETURN updated_count = 1;
END;
$function$;
