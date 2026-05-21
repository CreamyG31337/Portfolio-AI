-- Migration: rename_orphan_ui_ai_tables
-- Date: 2026-05-20
-- Purpose: Soft-drop the orphan Supabase copies of ui_ai_summary and
--          ui_ai_rollup_fund by renaming them with a _deprecated_ prefix
--          and revoking all anon/authenticated grants. Live writes happen
--          on the research Postgres instance via RESEARCH_DATABASE_URL,
--          NOT this Supabase. The Supabase copies are 0 rows and have no
--          inbound FK / view / function dependencies.
--
-- Audit reference: docs/RLS_AUDIT_PHASE0.md (sections 1.8, 1.9).
--
-- Why rename instead of DROP:
--   No dev environment. RENAME preserves data and reverses with one
--   ALTER. A real DROP TABLE becomes a SEPARATE migration proposed for
--   30+ days from now, only after we confirm no app errors mention
--   either old name in logs.
--
-- Operator notes:
--   * Apply only AFTER Migrations 1-3 have baked clean.
--   * Built-in safety guard refuses to rename if either table is
--     non-empty at apply time.
--   * Research-DB copies (under RESEARCH_DATABASE_URL) are untouched.
--   * Pre-stage rollback in your shell before applying.
--
-- Rollback (instant, lossless):
--   ALTER TABLE public._deprecated_ui_ai_summary_20260520 RENAME TO ui_ai_summary;
--   ALTER TABLE public._deprecated_ui_ai_rollup_fund_20260520 RENAME TO ui_ai_rollup_fund;
--   GRANT ALL ON TABLE public.ui_ai_summary, public.ui_ai_rollup_fund
--       TO anon, authenticated, service_role;


BEGIN;

-- Safety guard: refuse to rename if either table has gained rows
-- since the audit.
DO $$
BEGIN
    IF (SELECT count(*) FROM public.ui_ai_summary) > 0 THEN
        RAISE EXCEPTION 'ui_ai_summary not empty — aborting rename';
    END IF;
    IF (SELECT count(*) FROM public.ui_ai_rollup_fund) > 0 THEN
        RAISE EXCEPTION 'ui_ai_rollup_fund not empty — aborting rename';
    END IF;
END $$;

-- Rename (preserves data, indexes, constraints; reverses with one ALTER).
ALTER TABLE public.ui_ai_summary RENAME TO _deprecated_ui_ai_summary_20260520;
ALTER TABLE public.ui_ai_rollup_fund RENAME TO _deprecated_ui_ai_rollup_fund_20260520;

-- Strip anon/authenticated grants so the deprecated tables can't be
-- reached via PostgREST. service_role keeps full access in case we
-- need to recover.
REVOKE ALL ON TABLE
    public._deprecated_ui_ai_summary_20260520,
    public._deprecated_ui_ai_rollup_fund_20260520
FROM anon, authenticated;

COMMIT;

-- SMOKE TEST:
--   * /dashboard and AI summary panes render unchanged (data flows
--     through PostgresClient against RESEARCH_DATABASE_URL).
--   * SELECT to_regclass('public.ui_ai_summary'); -> NULL.
--   * SELECT count(*) FROM public._deprecated_ui_ai_summary_20260520; -> 0.
--   * Connect with RESEARCH_DATABASE_URL and verify
--     SELECT count(*) FROM ui_ai_summary; is unchanged.
--   * App logs for 24 hours show no errors mentioning either old name.
