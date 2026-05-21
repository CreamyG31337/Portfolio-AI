-- Migration: tighten_rls_group_a
-- Date: 2026-05-20
-- Purpose: Enable RLS + service-role full access + authenticated SELECT
--          policy on insider_trades and congress_positions.
--
-- Audit reference: docs/RLS_AUDIT_PHASE0.md (Group A).
--
-- Operator notes:
--   * Apply only AFTER tighten_rls_group_b.sql has baked clean.
--   * Apply table-by-table, smoke-test between.
--   * Order:
--       1. insider_trades       (read path fails gracefully on error)
--       2. congress_positions   (failure is more user-visible)
--   * Authenticated keeps SELECT via policy; writes remain service-role-only.
--   * Pre-stage rollback in your shell before applying.
--
-- Rollback (per table):
--   ALTER TABLE public.<table> DISABLE ROW LEVEL SECURITY;
--   DROP POLICY IF EXISTS "Allow service role full access" ON public.<table>;
--   DROP POLICY IF EXISTS "Allow authenticated users to read <noun>" ON public.<table>;


-- =============================================================
-- 1/2: insider_trades
-- =============================================================
BEGIN;
DROP POLICY IF EXISTS "Allow service role full access" ON public.insider_trades;
CREATE POLICY "Allow service role full access" ON public.insider_trades
    FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow authenticated users to read insider trades" ON public.insider_trades;
CREATE POLICY "Allow authenticated users to read insider trades" ON public.insider_trades
    FOR SELECT TO authenticated USING (true);

ALTER TABLE public.insider_trades ENABLE ROW LEVEL SECURITY;
COMMIT;

-- SMOKE TEST 1:
--   * As anon: GET /rest/v1/insider_trades?select=count
--     -> permission denied. Pre: 130,069.
--   * As authenticated non-admin: any portfolio's AI Insights / Audit
--     pane renders with insider-trades section populated
--     (ai_routes.py:61-96).
--   * fetch_insider_trades_job (next cron or manual trigger) inserts
--     new rows (jobs_insiders.py:178).


-- =============================================================
-- 2/2: congress_positions
-- =============================================================
BEGIN;
DROP POLICY IF EXISTS "Allow service role full access" ON public.congress_positions;
CREATE POLICY "Allow service role full access" ON public.congress_positions
    FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow authenticated users to read congress positions" ON public.congress_positions;
CREATE POLICY "Allow authenticated users to read congress positions" ON public.congress_positions
    FOR SELECT TO authenticated USING (true);

ALTER TABLE public.congress_positions ENABLE ROW LEVEL SECURITY;
COMMIT;

-- SMOKE TEST 2:
--   * As anon: GET /rest/v1/congress_positions?select=count
--     -> permission denied. Pre: 3,014.
--   * As authenticated non-admin: /congress_trades/positions data table
--     populates (app.py:5500).
--   * /congress_trades/positions leaderboard tab populates (app.py:5600).
--   * Next compute_congress_positions_job run completes
--     (jobs_congress_positions.py:174).
