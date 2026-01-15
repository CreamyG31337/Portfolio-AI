CREATE OR REPLACE FUNCTION public.calculate_daily_performance(target_date date, fund_name character varying DEFAULT NULL::character varying)
 RETURNS TABLE(fund character varying, total_value numeric, cost_basis numeric, unrealized_pnl numeric, performance_pct numeric)
 LANGUAGE plpgsql
 SET search_path TO 'public'
AS $function$
BEGIN
    RETURN QUERY
    SELECT
        p.fund,
        COALESCE(SUM(p.total_value), 0) as total_value,
        COALESCE(SUM(p.cost_basis), 0) as cost_basis,
        COALESCE(SUM(p.pnl), 0) as unrealized_pnl,
        CASE
            WHEN SUM(p.cost_basis) > 0 THEN (SUM(p.pnl) / SUM(p.cost_basis)) * 100
            ELSE 0
        END as performance_pct
    FROM portfolio_positions p
    WHERE p.date::date = target_date
      AND p.shares > 0
      AND (fund_name IS NULL OR p.fund = fund_name)
    GROUP BY p.fund;
END;
$function$;