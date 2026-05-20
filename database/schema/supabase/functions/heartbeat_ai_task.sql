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
