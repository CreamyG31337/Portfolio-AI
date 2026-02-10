-- =====================================================
-- ADMIN ROLE MANAGEMENT FUNCTIONS
-- =====================================================
-- Migration 37: Add functions to grant/revoke admin roles
-- Allows admins to promote/demote users
-- =====================================================

-- Function to grant admin role to a user
CREATE OR REPLACE FUNCTION grant_admin_role(user_email TEXT)
RETURNS JSON AS $$
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
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to revoke admin role from a user
CREATE OR REPLACE FUNCTION revoke_admin_role(user_email TEXT)
RETURNS JSON AS $$
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
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Update list_users_with_funds to include role information
-- Drop existing function first if it has different return type
DROP FUNCTION IF EXISTS list_users_with_funds();

CREATE FUNCTION list_users_with_funds()
RETURNS TABLE(
    user_id UUID,
    email TEXT,
    full_name TEXT,
    role TEXT,
    last_sign_in_at TIMESTAMP WITH TIME ZONE,
    funds TEXT[]
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        up.user_id,
        up.email::TEXT,
        up.full_name::TEXT,
        up.role::TEXT,
        au.last_sign_in_at,
        ARRAY_AGG(uf.fund_name) FILTER (WHERE uf.fund_name IS NOT NULL)::TEXT[] as funds
    FROM user_profiles up
    LEFT JOIN auth.users au ON au.id = up.user_id
    LEFT JOIN user_funds uf ON up.user_id = uf.user_id
    GROUP BY up.user_id, up.email, up.full_name, up.role, au.last_sign_in_at
    ORDER BY up.email;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =====================================================
-- MIGRATION COMPLETE
-- =====================================================

DO $$
BEGIN
    RAISE NOTICE '✅ Migration 37 complete: Admin role management functions created';
    RAISE NOTICE '📋 Functions added:';
    RAISE NOTICE '   - grant_admin_role(user_email)';
    RAISE NOTICE '   - revoke_admin_role(user_email)';
    RAISE NOTICE '   - Updated list_users_with_funds() to include role and last sign-in';
END $$;
