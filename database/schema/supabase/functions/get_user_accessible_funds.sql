CREATE OR REPLACE FUNCTION public.get_user_accessible_funds()
 RETURNS TABLE(fund_name character varying)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
BEGIN
    RETURN QUERY
    SELECT uf.fund_name
    FROM user_funds uf
    WHERE uf.user_id = auth.uid();
END;
$function$;