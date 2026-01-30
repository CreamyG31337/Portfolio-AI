-- =====================================================
-- SET USER ROLE FUNCTION
-- =====================================================
-- Migration 40: Add set_user_role function for flexible role management
-- Allows admins to set any valid role (user, readonly_admin, admin)
-- =====================================================

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

    -- Verify caller can modify data (must be full admin, not readonly_admin)
    IF NOT can_modify_data(auth.uid()) THEN
        RETURN json_build_object(
            'success', false,
            'message', 'Permission denied: Only full admins can modify user roles'
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

    -- Prevent admin from modifying their own role
    IF target_user_id = auth.uid() THEN
        RETURN json_build_object(
            'success', false,
            'message', 'Cannot modify your own role'
        );
    END IF;

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

-- =====================================================
-- MIGRATION COMPLETE
-- =====================================================

DO $$
BEGIN
    RAISE NOTICE '✅ Migration 40 complete: set_user_role function added';
    RAISE NOTICE '📋 Function added:';
    RAISE NOTICE '   - set_user_role(user_email, new_role) for flexible role management';
    RAISE NOTICE '🔐 Valid roles: user, readonly_admin, admin';
END $$;
