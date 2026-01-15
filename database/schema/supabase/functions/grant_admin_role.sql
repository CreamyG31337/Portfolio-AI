CREATE OR REPLACE FUNCTION public.grant_admin_role(user_email text)
 RETURNS json
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE
    target_user_id UUID;
    current_role TEXT;
    admin_count INTEGER;
    result JSON;
BEGIN
    -- Verify caller is admin
    IF NOT is_admin(auth.uid()) THEN
        RETURN json_build_object(
            'success', false,
            'message', 'Permission denied: Only admins can grant admin roles'
        );
    END IF;
    
    -- Get user ID and current role by email
    SELECT up.user_id, up.role INTO target_user_id, current_role
    FROM user_profiles up
    INNER JOIN auth.users au ON up.user_id = au.id
    WHERE au.email = user_email;
    
    IF target_user_id IS NULL THEN
        RETURN json_build_object(
            'success', false,
            'message', format('User with email %s not found', user_email)
        );
    END IF;
    
    -- Check if already admin
    IF current_role = 'admin' THEN
        RETURN json_build_object(
            'success', false,
            'already_admin', true,
            'message', format('%s is already an admin', user_email)
        );
    END IF;
    
    -- Update role to admin
    UPDATE user_profiles
    SET role = 'admin', updated_at = NOW()
    WHERE user_id = target_user_id;
    
    RETURN json_build_object(
        'success', true,
        'message', format('Successfully granted admin role to %s', user_email)
    );
END;
$function$;