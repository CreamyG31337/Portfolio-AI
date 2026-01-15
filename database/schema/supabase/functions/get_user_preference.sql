CREATE OR REPLACE FUNCTION public.get_user_preference(pref_key text, user_uuid uuid DEFAULT NULL::uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    target_user_uuid UUID;
    pref_value JSONB;
BEGIN
    -- Use provided user_uuid or fall back to auth.uid()
    IF user_uuid IS NULL THEN
        target_user_uuid := auth.uid();
    ELSE
        target_user_uuid := user_uuid;
    END IF;
    
    IF target_user_uuid IS NULL THEN
        RETURN NULL;
    END IF;
    
    SELECT preferences->pref_key INTO pref_value
    FROM user_profiles
    WHERE user_id = target_user_uuid;
    
    RETURN pref_value;
END;
$function$;