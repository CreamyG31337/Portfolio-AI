-- Migration: tighten_rls_group_b
-- Date: 2026-05-20
-- Purpose: Enable RLS + service-role-only policy on 5 operational tables
--          that have no user-facing reads, plus close the
--          congress_trades_enriched view bypass.
--
-- Audit reference: docs/RLS_AUDIT_PHASE0.md (Group B).
--
-- Operator notes:
--   * NO DEV ENVIRONMENT — apply against prod in a low-traffic window.
--   * Apply table-by-table, smoke-testing between each, NOT all at once.
--     Each table is wrapped in its own BEGIN/COMMIT for that reason.
--   * Order: lowest-risk first.
--       1. ai_analysis_skip_list   (0 rows, background only)
--       2. ai_analysis_queue        (background only)
--       3. job_retry_queue          (background only)
--       4. congress_trade_returns   (read only via view; view revoke below)
--       5. apscheduler_jobs         (highest scheduler-impact if wrong)
--   * After all 5 tables are locked, run the final REVOKE on the view.
--   * Pre-stage the rollback in your shell before applying.
--
-- Rollback (per table):
--   ALTER TABLE public.<table> DISABLE ROW LEVEL SECURITY;
--   DROP POLICY IF EXISTS "Allow service role full access" ON public.<table>;
-- Rollback (view step):
--   GRANT SELECT ON public.congress_trades_enriched TO anon;


-- =============================================================
-- 1/5: ai_analysis_skip_list
-- =============================================================
BEGIN;
DROP POLICY IF EXISTS "Allow service role full access" ON public.ai_analysis_skip_list;
CREATE POLICY "Allow service role full access" ON public.ai_analysis_skip_list
    FOR ALL TO service_role USING (true) WITH CHECK (true);
ALTER TABLE public.ai_analysis_skip_list ENABLE ROW LEVEL SECURITY;
COMMIT;

-- SMOKE TEST 1: as anon -> permission denied
--   SET LOCAL ROLE anon; SELECT count(*) FROM public.ai_analysis_skip_list;
-- Expect: permission denied for table ai_analysis_skip_list


-- =============================================================
-- 2/5: ai_analysis_queue
-- =============================================================
BEGIN;
DROP POLICY IF EXISTS "Allow service role full access" ON public.ai_analysis_queue;
CREATE POLICY "Allow service role full access" ON public.ai_analysis_queue
    FOR ALL TO service_role USING (true) WITH CHECK (true);
ALTER TABLE public.ai_analysis_queue ENABLE ROW LEVEL SECURITY;
COMMIT;

-- SMOKE TEST 2: confirm anon denied + watch one ticker_analysis cycle
-- transition pending -> in_progress -> completed.


-- =============================================================
-- 3/5: job_retry_queue
-- =============================================================
BEGIN;
DROP POLICY IF EXISTS "Allow service role full access" ON public.job_retry_queue;
CREATE POLICY "Allow service role full access" ON public.job_retry_queue
    FOR ALL TO service_role USING (true) WITH CHECK (true);
ALTER TABLE public.job_retry_queue ENABLE ROW LEVEL SECURITY;
COMMIT;

-- SMOKE TEST 3: confirm anon denied + run
--   python web_dashboard/scripts/check_job_backlog_health.py
-- Expect: non-empty output, no errors.


-- =============================================================
-- 4/5: congress_trade_returns
-- =============================================================
BEGIN;
DROP POLICY IF EXISTS "Allow service role full access" ON public.congress_trade_returns;
CREATE POLICY "Allow service role full access" ON public.congress_trade_returns
    FOR ALL TO service_role USING (true) WITH CHECK (true);
ALTER TABLE public.congress_trade_returns ENABLE ROW LEVEL SECURITY;
COMMIT;

-- SMOKE TEST 4: as authenticated, congress_trades_enriched view still
-- returns data (view is owned by postgres, base-table RLS bypassed for
-- the owner). Anon will be blocked by the REVOKE below.


-- =============================================================
-- 5/5: apscheduler_jobs
-- =============================================================
BEGIN;
DROP POLICY IF EXISTS "Allow service role full access" ON public.apscheduler_jobs;
CREATE POLICY "Allow service role full access" ON public.apscheduler_jobs
    FOR ALL TO service_role USING (true) WITH CHECK (true);
ALTER TABLE public.apscheduler_jobs ENABLE ROW LEVEL SECURITY;
COMMIT;

-- SMOKE TEST 5 (most important):
--   * Tail scheduler container logs for `permission denied` or
--     APScheduler errors during the next 2 minutes. Expect none — the
--     jobstore connects as `postgres` superuser via the pooler.
--   * /admin/jobs loads with "Next Run" column populated.
--   * Trigger one cheap idempotent job (e.g. securities_metadata_refresh);
--     confirm it completes and retry-queue side effects work.


-- =============================================================
-- Final step: close the congress_trades_enriched view bypass.
-- The view joins congress_trade_returns and is owned by postgres,
-- granted SELECT to anon. Locking the base table doesn't help anon
-- reading through the view, so revoke the anon grant.
-- =============================================================
REVOKE SELECT ON public.congress_trades_enriched FROM anon;

-- SMOKE TEST FINAL:
--   * As anon: GET /rest/v1/congress_trades_enriched?select=count
--     -> permission denied. Pre-revoke returned 29,100.
--   * As authenticated non-admin: pages using the view still render
--     (ai_routes.py:120, social_sentiment_routes.py:147).
