-- Add atomic enqueue/dedupe RPC for AI task queue producers.

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
