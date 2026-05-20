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
