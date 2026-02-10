-- =====================================================
-- PORTFOLIO DASHBOARD - AUTHENTICATION SCHEMA
-- =====================================================
-- This adds user authentication and permissions
-- Run this SECOND after 01_main_schema.sql
-- =====================================================

-- =====================================================
-- USER MANAGEMENT TABLES
-- =====================================================

-- User fund assignments table
CREATE TABLE IF NOT EXISTS user_funds (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    fund_name VARCHAR(50) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, fund_name)
);

-- User profiles table for additional user info
CREATE TABLE IF NOT EXISTS user_profiles (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    role VARCHAR(50) DEFAULT 'user',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id)
);

-- =====================================================
-- INDEXES FOR PERFORMANCE
-- =====================================================

-- User funds indexes
CREATE INDEX IF NOT EXISTS idx_user_funds_user_id ON user_funds(user_id);
CREATE INDEX IF NOT EXISTS idx_user_funds_fund_name ON user_funds(fund_name);

-- User profiles indexes
CREATE INDEX IF NOT EXISTS idx_user_profiles_user_id ON user_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_profiles_email ON user_profiles(email);

-- =====================================================
-- ROW LEVEL SECURITY POLICIES
-- =====================================================

-- Enable RLS on user tables
ALTER TABLE user_funds ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;

-- User funds policies
CREATE POLICY "Users can view their own fund assignments" ON user_funds
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their own fund assignments" ON user_funds
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own fund assignments" ON user_funds
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Users can delete their own fund assignments" ON user_funds
    FOR DELETE USING (auth.uid() = user_id);

-- User profiles policies
CREATE POLICY "Users can view their own profile" ON user_profiles
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their own profile" ON user_profiles
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own profile" ON user_profiles
    FOR UPDATE USING (auth.uid() = user_id);

-- =====================================================
-- ENHANCED RLS FOR PORTFOLIO DATA
-- =====================================================

-- Drop existing basic policies
DROP POLICY IF EXISTS "Allow all operations on portfolio_positions" ON portfolio_positions;
DROP POLICY IF EXISTS "Allow all operations on trade_log" ON trade_log;
DROP POLICY IF EXISTS "Allow all operations on cash_balances" ON cash_balances;
DROP POLICY IF EXISTS "Allow all operations on performance_metrics" ON performance_metrics;

-- Create fund-based access policies
CREATE POLICY "Users can view portfolio positions for their funds" ON portfolio_positions
    FOR SELECT USING (
        fund IN (
            SELECT fund_name FROM user_funds WHERE user_id = auth.uid()
        )
    );

CREATE POLICY "Users can view trades for their funds" ON trade_log
    FOR SELECT USING (
        fund IN (
            SELECT fund_name FROM user_funds WHERE user_id = auth.uid()
        )
    );

CREATE POLICY "Users can view cash balances for their funds" ON cash_balances
    FOR SELECT USING (
        fund IN (
            SELECT fund_name FROM user_funds WHERE user_id = auth.uid()
        )
    );

CREATE POLICY "Users can view performance metrics for their funds" ON performance_metrics
    FOR SELECT USING (
        fund IN (
            SELECT fund_name FROM user_funds WHERE user_id = auth.uid()
        )
    );

-- =====================================================
-- ACCESS CONTROL FUNCTIONS
-- =====================================================

-- Function to get user's assigned funds
CREATE OR REPLACE FUNCTION get_user_funds(user_uuid UUID)
RETURNS TABLE(fund_name VARCHAR(50)) AS $$
BEGIN
    RETURN QUERY
    SELECT uf.fund_name
    FROM user_funds uf
    WHERE uf.user_id = user_uuid;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to check if user has access to fund
CREATE OR REPLACE FUNCTION user_has_fund_access(user_uuid UUID, fund_name VARCHAR(50))
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM user_funds 
        WHERE user_id = user_uuid AND fund_name = user_has_fund_access.fund_name
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to get user's accessible funds (for API)
CREATE OR REPLACE FUNCTION get_user_accessible_funds()
RETURNS TABLE(fund_name VARCHAR(50)) AS $$
BEGIN
    RETURN QUERY
    SELECT uf.fund_name
    FROM user_funds uf
    WHERE uf.user_id = auth.uid();
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =====================================================
-- TRIGGERS FOR USER PROFILES
-- =====================================================

-- Trigger for user_profiles updated_at
CREATE TRIGGER update_user_profiles_updated_at
    BEFORE UPDATE ON user_profiles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =====================================================
-- HELPER FUNCTIONS FOR API
-- =====================================================

-- Function to create user profile on signup
CREATE OR REPLACE FUNCTION create_user_profile()
RETURNS TRIGGER AS $$
DECLARE
    user_count INTEGER;
    user_role VARCHAR(50);
BEGIN
    -- Check if this is the first user (admin)
    SELECT COUNT(*) INTO user_count FROM user_profiles;
    
    IF user_count = 0 THEN
        user_role := 'admin';
    ELSE
        user_role := 'user';
    END IF;
    
    INSERT INTO user_profiles (user_id, email, full_name, role)
    VALUES (
        NEW.id,
        NEW.email,
        NULLIF(BTRIM(COALESCE(NEW.raw_user_meta_data->>'full_name', '')), ''),
        user_role
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger to auto-create user profile
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION create_user_profile();

-- =====================================================
-- ADMIN FUNCTIONS AND POLICIES
-- =====================================================

-- Function to check if user is admin
CREATE OR REPLACE FUNCTION is_admin(user_uuid UUID)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM user_profiles 
        WHERE user_id = user_uuid AND role = 'admin'
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Admin policies for user management
CREATE POLICY "Admins can view all user profiles" ON user_profiles
    FOR SELECT USING (is_admin(auth.uid()));

CREATE POLICY "Admins can view all user funds" ON user_funds
    FOR SELECT USING (is_admin(auth.uid()));

CREATE POLICY "Admins can manage user funds" ON user_funds
    FOR ALL USING (is_admin(auth.uid()));

-- =====================================================
-- FUND ASSIGNMENT FUNCTIONS
-- =====================================================

-- Function to assign fund to user (admin only)
-- Returns JSON with status and message
CREATE OR REPLACE FUNCTION assign_fund_to_user(user_email TEXT, fund_name TEXT)
RETURNS JSON AS $$
#variable_conflict use_variable
DECLARE
    target_user_id UUID;
    assignment_exists BOOLEAN;
    rows_inserted INTEGER;
    result JSON;
BEGIN
    -- Get user ID by email
    SELECT id INTO target_user_id
    FROM auth.users
    WHERE email = user_email;
    
    IF target_user_id IS NULL THEN
        RAISE EXCEPTION 'User with email % not found', user_email;
    END IF;
    
    -- Check if assignment already exists
    SELECT EXISTS (
        SELECT 1 FROM user_funds uf 
        WHERE uf.user_id = target_user_id 
        AND uf.fund_name = assign_fund_to_user.fund_name
    ) INTO assignment_exists;
    
    IF assignment_exists THEN
        -- Assignment already exists
        result := json_build_object(
            'success', false,
            'already_assigned', true,
            'message', format('Fund "%s" is already assigned to %s', assign_fund_to_user.fund_name, user_email)
        );
    ELSE
        -- Insert fund assignment
        INSERT INTO user_funds (user_id, fund_name)
        VALUES (target_user_id, assign_fund_to_user.fund_name);
        
        GET DIAGNOSTICS rows_inserted = ROW_COUNT;
        
        IF rows_inserted > 0 THEN
            result := json_build_object(
                'success', true,
                'already_assigned', false,
                'message', format('Successfully assigned fund "%s" to %s', assign_fund_to_user.fund_name, user_email)
            );
        ELSE
            result := json_build_object(
                'success', false,
                'already_assigned', false,
                'message', 'Failed to assign fund'
            );
        END IF;
    END IF;
    
    RETURN result;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to remove fund from user (admin only)
-- Uses auth.users for user lookup to maintain consistency with assign_fund_to_user
CREATE OR REPLACE FUNCTION remove_fund_from_user(user_email TEXT, fund_name TEXT)
RETURNS BOOLEAN AS $$
DECLARE
    target_user_id UUID;
    rows_deleted INTEGER;
BEGIN
    -- Get user ID by email from auth.users (same as assign_fund_to_user)
    SELECT id INTO target_user_id
    FROM auth.users
    WHERE email = user_email;
    
    IF target_user_id IS NULL THEN
        RAISE EXCEPTION 'User with email % not found', user_email;
    END IF;
    
    -- Delete fund assignment
    DELETE FROM user_funds
    WHERE user_id = target_user_id AND user_funds.fund_name = remove_fund_from_user.fund_name;
    
    GET DIAGNOSTICS rows_deleted = ROW_COUNT;
    
    RETURN rows_deleted > 0;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to safely delete a user (admin only)
-- Blocks deletion if user email exists in fund_contributions (is a contributor)
CREATE OR REPLACE FUNCTION delete_user_safe(user_email TEXT)
RETURNS JSON AS $$
DECLARE
    target_user_id UUID;
    contributor_count INTEGER;
    result JSON;
BEGIN
    -- Get user ID from auth.users
    SELECT id INTO target_user_id
    FROM auth.users
    WHERE email = user_email;
    
    IF target_user_id IS NULL THEN
        RETURN json_build_object('success', false, 'message', 'User not found');
    END IF;
    
    -- Check if user email exists in fund_contributions (is a contributor)
    -- Use normalize_email for consistent matching (Gmail dots, case-insensitive)
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
    
    -- Safe to delete - cascade will handle user_funds and user_profiles
    DELETE FROM auth.users WHERE id = target_user_id;
    
    RETURN json_build_object('success', true, 'message', 'User deleted successfully');
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to list all users with their fund assignments
CREATE OR REPLACE FUNCTION list_users_with_funds()
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
        up.email,
        up.full_name,
        up.role,
        au.last_sign_in_at,
        ARRAY_AGG(uf.fund_name) as funds
    FROM user_profiles up
    LEFT JOIN auth.users au ON au.id = up.user_id
    LEFT JOIN user_funds uf ON up.user_id = uf.user_id
    GROUP BY up.user_id, up.email, up.full_name, up.role, au.last_sign_in_at
    ORDER BY up.email;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =====================================================
-- SCHEMA COMPLETE
-- =====================================================

-- Success message
DO $$
BEGIN
    RAISE NOTICE '✅ Authentication schema created successfully!';
    RAISE NOTICE '🔐 Row Level Security enabled - users can only see their assigned funds';
    RAISE NOTICE '👥 User management tables created';
    RAISE NOTICE '📋 Next step: Run 03_sample_data.sql (optional)';
    RAISE NOTICE '🚀 Or start using the dashboard with real users!';
END $$;
