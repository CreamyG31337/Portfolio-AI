-- Aggregate portfolio_positions to one row per calendar day (base currency).
-- Used by the dashboard performance chart so TFSA-scale history does not
-- paginate ~90k per-position rows through PostgREST.

CREATE OR REPLACE FUNCTION public.get_portfolio_daily_totals(
    p_fund text DEFAULT NULL,
    p_start timestamptz DEFAULT NULL,
    p_end timestamptz DEFAULT NULL
)
RETURNS TABLE (
    date date,
    value numeric,
    cost_basis numeric,
    pnl numeric
)
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path TO 'public'
AS $function$
    SELECT
        (pp.date AT TIME ZONE 'UTC')::date AS date,
        SUM(COALESCE(pp.total_value_base, pp.total_value))::numeric AS value,
        SUM(COALESCE(pp.cost_basis_base, pp.cost_basis))::numeric AS cost_basis,
        SUM(COALESCE(pp.pnl_base, pp.pnl))::numeric AS pnl
    FROM portfolio_positions pp
    WHERE (p_fund IS NULL OR pp.fund = p_fund)
      AND (p_start IS NULL OR pp.date >= p_start)
      AND (p_end IS NULL OR pp.date < p_end)
    GROUP BY 1
    ORDER BY 1;
$function$;

REVOKE ALL ON FUNCTION public.get_portfolio_daily_totals(text, timestamptz, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_portfolio_daily_totals(text, timestamptz, timestamptz) TO authenticated;
GRANT EXECUTE ON FUNCTION public.get_portfolio_daily_totals(text, timestamptz, timestamptz) TO service_role;
