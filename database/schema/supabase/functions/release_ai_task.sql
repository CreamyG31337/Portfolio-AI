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
        -- Track which backends have failed on this task (deduped). Only
        -- record when the failure counts against max_attempts; transient
        -- host_busy releases (p_increment_attempts=false) should not lock a
        -- backend out of retrying.
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
