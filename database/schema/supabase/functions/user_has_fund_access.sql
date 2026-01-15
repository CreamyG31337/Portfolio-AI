CREATE OR REPLACE FUNCTION public.user_has_fund_access(user_uuid uuid, fund_name character varying)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM user_funds 
        WHERE user_id = user_uuid AND user_funds.fund_name = user_has_fund_access.fund_name
    );
END;
$function$;