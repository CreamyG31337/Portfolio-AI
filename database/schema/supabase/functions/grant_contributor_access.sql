CREATE OR REPLACE FUNCTION public.grant_contributor_access(contributor_email text, user_email text, access_level text DEFAULT 'viewer'::text)
 RETURNS json
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE
    target_contributor_id UUID;
    target_user_id UUID;
    result JSON;
BEGIN
    -- Get contributor ID
    SELECT id INTO target_contributor_id
    FROM contributors
    WHERE normalize_email(email) = normalize_email(contributor_email);
    
    IF target_contributor_id IS NULL THEN
        RETURN json_build_object(
            'success', false,
            'message', format('Contributor with email % not found', contributor_email)
        );
    END IF;
    
    -- Get user ID
    SELECT id INTO target_user_id
    FROM auth.users
    WHERE normalize_email(email) = normalize_email(user_email);
    
    IF target_user_id IS NULL THEN
        RETURN json_build_object(
            'success', false,
            'message', format('User with email % not found', user_email)
        );
    END IF;
    
    -- Grant access
    INSERT INTO contributor_access (contributor_id, user_id, access_level, granted_by)
    VALUES (target_contributor_id, target_user_id, access_level, auth.uid())
    ON CONFLICT (contributor_id, user_id) 
    DO UPDATE SET 
        access_level = EXCLUDED.access_level,
        granted_by = EXCLUDED.granted_by,
        granted_at = NOW();
    
    RETURN json_build_object(
        'success', true,
        'message', format('Access granted: % can view %', user_email, contributor_email)
    );
END;
$function$;