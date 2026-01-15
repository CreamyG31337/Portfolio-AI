CREATE OR REPLACE FUNCTION public.get_user_funds(user_uuid uuid)
 RETURNS TABLE(fund_name character varying)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
BEGIN
    RETURN QUERY
    SELECT uf.fund_name
    FROM user_funds uf
    WHERE uf.user_id = user_uuid;
END;
$function$;