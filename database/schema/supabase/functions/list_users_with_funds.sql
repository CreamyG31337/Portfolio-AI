CREATE OR REPLACE FUNCTION public.list_users_with_funds()
 RETURNS TABLE(user_id uuid, email text, full_name text, role text, last_sign_in_at timestamp with time zone, funds text[])
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
BEGIN
    RETURN QUERY
    SELECT
        up.user_id,
        up.email::TEXT,
        up.full_name::TEXT,
        up.role::TEXT,
        au.last_sign_in_at,
        ARRAY_AGG(uf.fund_name) FILTER (WHERE uf.fund_name IS NOT NULL)::TEXT[] as funds
    FROM user_profiles up
    LEFT JOIN auth.users au ON au.id = up.user_id
    LEFT JOIN user_funds uf ON up.user_id = uf.user_id
    GROUP BY up.user_id, up.email, up.full_name, up.role, au.last_sign_in_at
    ORDER BY up.email;
END;
$function$;