CREATE OR REPLACE FUNCTION public.delete_user_safe(user_email text)
 RETURNS json
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    target_user_id UUID;
    contributor_count INTEGER;
    result JSON;
BEGIN
    SELECT id INTO target_user_id
    FROM auth.users
    WHERE email = user_email;
    
    IF target_user_id IS NULL THEN
        RETURN json_build_object('success', false, 'message', 'User not found');
    END IF;
    
    SELECT COUNT(*) INTO contributor_count
    FROM fund_contributions
    WHERE normalize_email(fund_contributions.email) = normalize_email(user_email);
    
    IF contributor_count > 0 THEN
        RETURN json_build_object(
            'success', false, 
            'message', 'Cannot delete: User is a fund contributor with ' || contributor_count || ' contribution record(s). Remove their contributions first.',
            'is_contributor', true
        );
    END IF;
    
    DELETE FROM auth.users WHERE id = target_user_id;
    
    RETURN json_build_object('success', true, 'message', 'User deleted successfully');
END;
$function$;