CREATE OR REPLACE FUNCTION public.revoke_contributor_access(contributor_email text, user_email text)
 RETURNS json
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE
    target_contributor_id UUID;
    target_user_id UUID;
    rows_deleted INTEGER;
BEGIN
    -- Get IDs
    SELECT id INTO target_contributor_id FROM contributors
    WHERE normalize_email(email) = normalize_email(contributor_email);
    
    SELECT id INTO target_user_id FROM auth.users
    WHERE normalize_email(email) = normalize_email(user_email);
    
    IF target_contributor_id IS NULL OR target_user_id IS NULL THEN
        RETURN json_build_object('success', false, 'message', 'Contributor or user not found');
    END IF;
    
    -- Revoke access
    DELETE FROM contributor_access
    WHERE contributor_id = target_contributor_id
      AND user_id = target_user_id;
    
    GET DIAGNOSTICS rows_deleted = ROW_COUNT;
    
    RETURN json_build_object(
        'success', rows_deleted > 0,
        'message', format('Access revoked: % can no longer view %', user_email, contributor_email)
    );
END;
$function$;