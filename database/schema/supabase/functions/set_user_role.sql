CREATE OR REPLACE FUNCTION public.set_user_role(user_email text, new_role text)
 RETURNS json
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE
    target_user_id UUID;
    current_role TEXT;
    admin_count INTEGER;
BEGIN
    -- Validate new_role
    IF new_role NOT IN ('user', 'readonly_admin', 'admin') THEN
        RETURN json_build_object(
            'success', false,
            'message', format('Invalid role: %s. Must be user, readonly_admin, or admin', new_role)
        );
    END IF;

    -- Note: Permission check is done at Flask level (can_modify_data_flask) before calling this RPC
    -- When called via service role key, auth.uid() is NULL so we can't check here
    -- The SECURITY DEFINER + service role pattern means Flask is responsible for authorization

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

    -- Note: Self-modification check is done at Flask level
    -- auth.uid() is NULL when called via service role key

    -- Check if role is already set
    IF current_role = new_role THEN
        RETURN json_build_object(
            'success', false,
            'message', format('%s already has role: %s', user_email, new_role)
        );
    END IF;

    -- If demoting from admin, check if this is the last admin
    IF current_role = 'admin' AND new_role != 'admin' THEN
        SELECT COUNT(*) INTO admin_count
        FROM user_profiles
        WHERE role = 'admin';

        IF admin_count <= 1 THEN
            RETURN json_build_object(
                'success', false,
                'message', 'Cannot demote the last admin. At least one admin must exist.'
            );
        END IF;
    END IF;

    -- Update role
    UPDATE user_profiles
    SET role = new_role, updated_at = NOW()
    WHERE user_id = target_user_id;

    RETURN json_build_object(
        'success', true,
        'message', format('Successfully set %s role to %s', user_email, new_role)
    );
END;
$function$;