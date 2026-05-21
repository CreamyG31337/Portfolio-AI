-- Migration: revoke_anon_authenticated_grants
-- Date: deferred — apply >= 1 week after Migrations 1-4 have baked clean.
-- Purpose: Drop the now-inert default Supabase grants on the 7 locked
--          tables so \dp output and future audits don't show stale
--          ALL-privilege grants. RLS already denies anon and authenticated
--          access; this just removes the noise.
--
-- Audit reference: docs/RLS_AUDIT_PHASE0.md.
--
-- CRITICAL CORRECTNESS NOTE:
--   Postgres checks GRANTs BEFORE RLS policies. For Group A tables
--   (insider_trades, congress_positions), authenticated MUST keep
--   SELECT or the RLS read policy is useless and user-facing pages
--   break. This migration revokes only the WRITE privileges from
--   authenticated on Group A.
--
-- Operator notes:
--   * Apply statement-by-statement, with `\dp <table>` between each
--     statement to verify each REVOKE landed correctly.
--   * Pre-stage per-table rollback in your shell before applying.
--
-- Rollback (per table; re-grant only what we revoked):
--   GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
--       ON TABLE public.<table>
--       TO anon, authenticated;


BEGIN;

-- =============================================================
-- Group B: no user-facing reads — revoke everything from anon and
-- authenticated. RLS already denies them; grants are cosmetic.
-- =============================================================
REVOKE ALL ON TABLE
    public.job_retry_queue,
    public.apscheduler_jobs,
    public.ai_analysis_queue,
    public.ai_analysis_skip_list,
    public.congress_trade_returns
FROM anon, authenticated;


-- =============================================================
-- Group A: authenticated MUST keep SELECT. Revoke only writes from
-- authenticated; revoke everything from anon.
-- =============================================================
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON TABLE public.insider_trades, public.congress_positions
    FROM authenticated;

REVOKE ALL ON TABLE public.insider_trades, public.congress_positions
    FROM anon;

-- service_role grants stay intact in both groups.

COMMIT;

-- SMOKE TEST:
--   * \dp public.insider_trades shows only postgres, service_role, and
--     authenticated=r (SELECT only) — no anon= row.
--   * \dp public.apscheduler_jobs shows only postgres and service_role.
--   * All earlier verification steps (Migrations 1-4) still pass.
