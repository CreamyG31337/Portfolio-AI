-- =====================================================
-- QUICK COMMANDS TO SWITCH TEST USERS
-- =====================================================
-- Usage: \i database/utilities/set_test_user.sql
--
-- Run the appropriate command to switch user context for RLS testing
-- =====================================================

-- Admin user (full access)
SELECT set_current_test_user('admin@test.com');

-- Contributor user (limited access)
-- SELECT set_current_test_user('contributor@test.com');

-- Viewer user (read-only access)
-- SELECT set_current_test_user('viewer@test.com');

-- =====================================================
-- CHECK CURRENT USER
-- =====================================================
SELECT * FROM show_current_user();

-- =====================================================
-- CLEAR USER (reset to admin)
-- =====================================================
-- SELECT clear_test_user();
