-- =====================================================
-- DISABLE ALL RLS POLICIES (TEST MODE ONLY)
-- =====================================================
-- WARNING: This removes all row-level security!
-- ONLY use in local test environments, never in production!
-- =====================================================

DO $$
DECLARE
    r RECORD;
    disabled_count INTEGER := 0;
BEGIN
    FOR r IN (
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
          AND rowsecurity = true
    ) LOOP
        BEGIN
            EXECUTE 'ALTER TABLE ' || quote_ident(r.tablename) || ' DISABLE ROW LEVEL SECURITY';
            RAISE NOTICE 'RLS disabled on table: %', r.tablename;
            disabled_count := disabled_count + 1;
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'Failed to disable RLS on %: %', r.tablename, SQLERRM;
        END;
    END LOOP;

    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Summary: Disabled RLS on % tables', disabled_count;
    RAISE NOTICE '============================================================';
END $$;

-- =====================================================
-- VERIFY RLS STATUS
-- =====================================================
SELECT
    schemaname,
    tablename,
    rowsecurity as rls_enabled
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;
