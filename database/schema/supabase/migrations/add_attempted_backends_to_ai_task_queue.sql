-- Cross-backend retry policy for ai_task_queue.
--
-- Problem: a task that fails on backend X (e.g. ollama_primary returning
-- "no result" for granite3.3:8b on a specific ticker) gets released back to
-- the queue. Any worker can pick it up. In practice the same backend often
-- grabs it again, burns 3 attempts, and the task is marked failed without
-- ever trying ollama_secondary or glm.
--
-- Two real cases on 2026-05-22 (XMA.TO, XGD.TO) failed this way: 3 attempts,
-- all on ollama_primary, with the same "ticker_analysis returned no result
-- for X on ollama_primary" error.
--
-- Fix: track which backends have attempted each task in attempted_backends
-- (text[]). The lease RPC HARD-FILTERS out tasks where the polling backend
-- is already in attempted_backends, so a failing backend cannot re-lease its
-- own task while any other backend has not yet tried. The escape hatch:
-- once cardinality(attempted_backends) >= 3 (every known backend has tried),
-- the filter relaxes so any backend can retry until max_attempts is hit.
-- The release RPC appends the just-failed backend to attempted_backends.
--
-- Why hard filter, not just ORDER BY: a soft ORDER BY still allowed primary
-- to win a LIMIT 1 race when only tried-by-primary rows were eligible. Live
-- test on 2026-05-23 with two reset rows confirmed: secondary correctly took
-- one, but primary still grabbed the other because LIMIT 1 fell back to a
-- tried row when nothing better was visible to that worker's poll.
--
-- Idempotent: safe to re-run; column add and RPC replacement both no-op if
-- already applied.

ALTER TABLE ai_task_queue
    ADD COLUMN IF NOT EXISTS attempted_backends VARCHAR(40)[] NOT NULL DEFAULT '{}';

COMMENT ON COLUMN ai_task_queue.attempted_backends IS
    'Backends that have leased and released-with-failure on this task. Used by lease_ai_task to prefer untried backends on retry. Cleared on enqueue.';

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
          -- Cross-backend retry: a backend that has already failed on this
          -- task cannot re-lease it while any other backend has not yet
          -- tried. Escape hatch when every known backend (3 in our setup)
          -- has tried, so the task can keep retrying within max_attempts.
          AND (
                NOT (p_backend = ANY(attempted_backends))
                OR cardinality(attempted_backends) >= 3
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
        -- Track backends that have failed on this task (deduped). Only
        -- record when we're actually counting this attempt against the cap;
        -- transient host_busy releases (p_increment_attempts=false) should
        -- not lock a backend out of retrying.
        attempted_backends = CASE
            WHEN p_increment_attempts AND leased_backend IS NOT NULL
                 AND NOT (leased_backend = ANY(attempted_backends))
                THEN array_append(attempted_backends, leased_backend)
            ELSE attempted_backends
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
        enqueued_by,
        attempted_backends
    )
    VALUES (
        LEFT(p_analysis_type, 40),
        LEFT(UPPER(p_target_key), 100),
        COALESCE(p_payload, '{}'::jsonb),
        p_priority,
        GREATEST(p_max_attempts, 1),
        LEFT(COALESCE(p_enqueued_by, ''), 40),
        '{}'::varchar(40)[]
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
