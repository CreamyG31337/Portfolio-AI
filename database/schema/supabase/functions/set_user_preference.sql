CREATE OR REPLACE FUNCTION public.set_user_preference(pref_key text, pref_value text, user_uuid uuid DEFAULT NULL::uuid)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    target_user_uuid UUID;
    rows_updated INTEGER;
    pref_value_jsonb JSONB;
    profile_exists BOOLEAN;
BEGIN
    -- Use provided user_uuid or fall back to auth.uid()
    IF user_uuid IS NULL THEN
        target_user_uuid := auth.uid();
    ELSE
        target_user_uuid := user_uuid;
    END IF;
    
    IF target_user_uuid IS NULL THEN
        RAISE WARNING 'set_user_preference: target_user_uuid is NULL (user_uuid param was NULL and auth.uid() returned NULL)';
        RETURN FALSE;
    END IF;
    
    -- Check if profile exists (for debugging)
    SELECT EXISTS(
        SELECT 1 FROM user_profiles 
        WHERE user_id = target_user_uuid
    ) INTO profile_exists;
    
    IF NOT profile_exists THEN
        RAISE WARNING 'set_user_preference: Profile does not exist for user_id: %', target_user_uuid;
        RETURN FALSE;
    END IF;
    
    -- Convert TEXT to JSONB
    BEGIN
        pref_value_jsonb := pref_value::jsonb;
    EXCEPTION WHEN OTHERS THEN
        -- If conversion fails, wrap as a JSON string
        pref_value_jsonb := to_jsonb(pref_value);
    END;
    
    -- Update the preference using jsonb_set
    UPDATE user_profiles
    SET 
        preferences = jsonb_set(
            COALESCE(preferences, '{}'::jsonb),
            ARRAY[pref_key],
            pref_value_jsonb,
            true  -- create if missing
        ),
        updated_at = NOW()
    WHERE user_id = target_user_uuid;
    
    GET DIAGNOSTICS rows_updated = ROW_COUNT;
    
    IF rows_updated = 0 THEN
        RAISE WARNING 'set_user_preference: UPDATE returned 0 rows for user_id: %, pref_key: %, profile_exists: %', target_user_uuid, pref_key, profile_exists;
        RETURN FALSE;
    END IF;
    
    RETURN TRUE;
END;
$function$;