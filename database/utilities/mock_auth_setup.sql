-- =====================================================
-- MOCK SUPABASE AUTH SYSTEM FOR LOCAL TESTING
-- =====================================================
-- Creates fake auth.users table and test users for RLS
-- This enables RLS testing without production Supabase auth dependency
-- =====================================================

-- Create auth schema (if not exists)
CREATE SCHEMA IF NOT EXISTS auth;

-- Create mock auth.users table
CREATE TABLE IF NOT EXISTS auth.users (
    id UUID PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    encrypted_password TEXT,
    email_confirmed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    raw_user_meta_data JSONB DEFAULT '{}'::jsonb
);

-- =====================================================
-- INSERT TEST USERS
-- =====================================================
-- Three test users with different roles for RLS testing

INSERT INTO auth.users (id, email, email_confirmed_at, raw_user_meta_data) VALUES
    ('00000000-0000-0000-0000-000000000001', 'admin@test.com', NOW(), '{"full_name": "Test Admin", "role": "admin"}'),
    ('00000000-0000-0000-0000-000000000002', 'contributor@test.com', NOW(), '{"full_name": "Test Contributor", "role": "contributor"}'),
    ('00000000-0000-0000-0000-000000000003', 'viewer@test.com', NOW(), '{"full_name": "Test Viewer", "role": "viewer"}')
ON CONFLICT (id) DO NOTHING;

-- =====================================================
-- MOCK AUTH.UID() FUNCTION
-- =====================================================
-- Simulates Supabase's auth.uid() function using session variable
-- Default returns admin user if not set

CREATE OR REPLACE FUNCTION auth.uid() RETURNS UUID AS $$
BEGIN
    -- Return current test user from session variable, default to admin
    RETURN COALESCE(
        NULLIF(current_setting('app.current_user_id', true), '')::UUID,
        '00000000-0000-0000-0000-000000000001'::UUID
    );
END;
$$ LANGUAGE plpgsql STABLE;

-- =====================================================
-- HELPER FUNCTION TO SET CURRENT TEST USER
-- =====================================================
-- Switch between test users for RLS testing
-- Usage: SELECT set_current_test_user('admin@test.com');

CREATE OR REPLACE FUNCTION set_current_test_user(user_email TEXT) RETURNS TEXT AS $$
DECLARE
    user_uuid UUID;
BEGIN
    SELECT id INTO user_uuid FROM auth.users WHERE email = user_email;

    IF user_uuid IS NULL THEN
        RAISE EXCEPTION 'Test user % not found', user_email;
    END IF;

    -- Set the current user in session configuration
    PERFORM set_config('app.current_user_id', user_uuid::TEXT, false);

    RETURN 'Current test user set to: ' || user_email || ' (' || user_uuid || ')';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION set_current_test_user IS
'Switch test user context for RLS testing. Usage: SELECT set_current_test_user(''admin@test.com'');';

-- =====================================================
-- HELPER FUNCTION TO CLEAR TEST USER
-- =====================================================
-- Reset to default admin user

CREATE OR REPLACE FUNCTION clear_test_user() RETURNS TEXT AS $$
BEGIN
    PERFORM set_config('app.current_user_id', '', false);
    RETURN 'Test user cleared. Current user: ' || auth.uid()::TEXT;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- HELPER FUNCTION TO SHOW CURRENT USER
-- =====================================================
-- Display which test user is currently active

CREATE OR REPLACE FUNCTION show_current_user() RETURNS TABLE (
    email TEXT,
    user_id UUID,
    full_name TEXT,
    role TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        u.email,
        u.id,
        u.raw_user_meta_data->>'full_name' as full_name,
        u.raw_user_meta_data->>'role' as role
    FROM auth.users u
    WHERE u.id = auth.uid();
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- SETUP COMPLETE
-- =====================================================

DO $$
BEGIN
    RAISE NOTICE '✅ Mock Supabase auth system setup complete!';
    RAISE NOTICE '👥 Test users created:';
    RAISE NOTICE '   - admin@test.com (UUID: 00000000-0000-0000-0000-000000000001)';
    RAISE NOTICE '   - contributor@test.com (UUID: 00000000-0000-0000-0000-000000000002)';
    RAISE NOTICE '   - viewer@test.com (UUID: 00000000-0000-0000-0000-000000000003)';
    RAISE NOTICE '🔧 Use: SELECT set_current_test_user(''admin@test.com'');';
    RAISE NOTICE '👀 Check: SELECT * FROM show_current_user();';
END $$;
