-- Migration: harden_get_distinct_column_values
-- Date: 2026-05-20
-- Purpose: Close the SECURITY DEFINER bypass exposed by anon EXECUTE on
--          public.get_distinct_column_values. Sync the repo source with
--          the production whitelist + column-name validation (the repo
--          version is stale).
--
-- Audit reference: docs/RLS_AUDIT_PHASE0.md (out-of-scope-but-related).
--
-- Why no SECURITY INVOKER change here:
--   The whitelist includes portfolio_positions and trade_log, both of
--   which have per-fund RLS policies. Under INVOKER the function would
--   silently return only the caller's fund-visible distinct values
--   instead of the global set — a behavior change we can't validate
--   without a dev env. Defer INVOKER conversion to Phase 2.
--
-- Operator notes:
--   * 3a is a no-op against prod (CREATE OR REPLACE with the exact
--     existing body). Confirmed via pg_get_functiondef on 2026-05-20.
--     Apply anyway because the repo source-of-truth is stale.
--   * 3b is the actual hardening: REVOKE EXECUTE from anon. Legitimate
--     callers (flask_data_utils.py:1598, ticker_utils.py:184) use an
--     authenticated user token and are unaffected.
--   * Pre-stage rollback in your shell before applying.
--
-- Rollback:
--   GRANT EXECUTE ON FUNCTION public.get_distinct_column_values(text, text) TO anon;
--   (Body rollback is a no-op since 3a did not change behavior.)


-- =============================================================
-- 3a. Sync function body with prod (whitelist + column regex).
-- =============================================================
CREATE OR REPLACE FUNCTION public.get_distinct_column_values(
    p_table text,
    p_column text
)
RETURNS TABLE(value text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
BEGIN
    -- Whitelist of allowed tables
    IF p_table NOT IN (
        'securities',
        'watched_tickers',
        'congress_trades',
        'congress_trades_enriched',
        'insider_trades',
        'portfolio_positions',
        'trade_log'
    ) THEN
        RAISE EXCEPTION 'Table "%" is not in the allowed whitelist', p_table;
    END IF;

    -- Validate column name (alphanumeric + underscore only)
    IF p_column !~ '^[a-zA-Z_][a-zA-Z0-9_]*$' THEN
        RAISE EXCEPTION 'Invalid column name: %', p_column;
    END IF;

    RETURN QUERY EXECUTE format(
        'SELECT DISTINCT %I::TEXT AS value FROM %I WHERE %I IS NOT NULL ORDER BY 1',
        p_column, p_table, p_column
    );
END;
$function$;


-- =============================================================
-- 3b. Stop anon from calling this function.
-- NOTE: A simple `REVOKE EXECUTE ... FROM anon` is INSUFFICIENT here
-- because Postgres default-grants EXECUTE to PUBLIC, and anon inherits
-- from PUBLIC. We discovered this on first apply — anon could still
-- call the function after the FROM-anon revoke. Revoke from PUBLIC
-- instead; authenticated and service_role keep their explicit grants.
-- =============================================================
REVOKE EXECUTE ON FUNCTION public.get_distinct_column_values(text, text) FROM PUBLIC;

-- SMOKE TEST:
--   * As anon: SET LOCAL ROLE anon;
--     SELECT * FROM get_distinct_column_values('insider_trades','ticker') LIMIT 1;
--     -> permission denied for function get_distinct_column_values.
--   * As an authenticated user via the Flask app, hit any page that
--     refreshes ticker lists (uses ticker_utils.py:184). Expect success.
