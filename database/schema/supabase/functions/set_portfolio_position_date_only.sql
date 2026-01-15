CREATE OR REPLACE FUNCTION public.set_portfolio_position_date_only()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    NEW.date_only := (NEW.date AT TIME ZONE 'UTC')::date;
    RETURN NEW;
END;
$function$;