CREATE OR REPLACE FUNCTION public.revoke_admin_role(user_email text)
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
            'message', 'Permission denied: Only admins can revoke admin roles'
        );
    END IF;
    
    -- Prevent admin from removing their own admin role
    SELECT id INTO target_user_id FROM auth.users WHERE email = user_email;
    IF target_user_id = auth.uid() THEN
        RETURN json_build_object(
            'success', false,
            'message', 'Cannot revoke your own admin role'
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
    
    -- Check if user is already not an admin
    IF current_role != 'admin' THEN
        RETURN json_build_object(
            'success', false,
            'message', format('%s is not an admin', user_email)
        );
    END IF;
    
    -- Check if this is the last admin
    SELECT COUNT(*) INTO admin_count
    FROM user_profiles
    WHERE role = 'admin';
    
    IF admin_count <= 1 THEN
        RETURN json_build_object(
            'success', false,
            'message', 'Cannot revoke the last admin role. At least one admin must exist.'
        );
    END IF;
    
    -- Update role to user
    UPDATE user_profiles
    SET role = 'user', updated_at = NOW()
    WHERE user_id = target_user_id;
    
    RETURN json_build_object(
        'success', true,
        'message', format('Successfully revoked admin role from %s', user_email)
    );
END;
$function$;