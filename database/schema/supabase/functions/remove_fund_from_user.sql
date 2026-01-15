CREATE OR REPLACE FUNCTION public.remove_fund_from_user(user_email text, fund_name text)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    target_user_id UUID;
    rows_deleted INTEGER;
BEGIN
    SELECT id INTO target_user_id
    FROM auth.users
    WHERE email = user_email;
    
    IF target_user_id IS NULL THEN
        RAISE EXCEPTION 'User with email % not found', user_email;
    END IF;
    
    DELETE FROM user_funds
    WHERE user_id = target_user_id AND user_funds.fund_name = remove_fund_from_user.fund_name;
    
    GET DIAGNOSTICS rows_deleted = ROW_COUNT;
    
    RETURN rows_deleted > 0;
END;
$function$;