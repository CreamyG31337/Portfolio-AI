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
