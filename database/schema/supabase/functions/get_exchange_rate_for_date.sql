CREATE OR REPLACE FUNCTION public.get_exchange_rate_for_date(target_date timestamp with time zone, from_curr character varying DEFAULT 'USD'::character varying, to_curr character varying DEFAULT 'CAD'::character varying)
 RETURNS numeric
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    result_rate DECIMAL(10, 6);
BEGIN
    SELECT rate INTO result_rate
    FROM exchange_rates
    WHERE from_currency = from_curr
      AND to_currency = to_curr
      AND timestamp <= target_date
    ORDER BY timestamp DESC
    LIMIT 1;
    
    RETURN COALESCE(result_rate, 1.35);
END;
$function$;