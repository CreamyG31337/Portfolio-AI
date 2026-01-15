CREATE OR REPLACE FUNCTION public.get_user_preferences()
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE
    user_uuid UUID;
    user_prefs JSONB;
BEGIN
    user_uuid := auth.uid();
    
    IF user_uuid IS NULL THEN
        RETURN '{}'::jsonb;
    END IF;
    
    SELECT COALESCE(preferences, '{}'::jsonb) INTO user_prefs
    FROM user_profiles
    WHERE user_id = user_uuid;
    
    RETURN user_prefs;
END;
$function$;