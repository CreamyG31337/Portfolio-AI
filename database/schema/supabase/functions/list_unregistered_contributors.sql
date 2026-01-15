CREATE OR REPLACE FUNCTION public.list_unregistered_contributors()
 RETURNS TABLE(contributor text, email text, funds text[], total_contribution numeric)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
BEGIN
    RETURN QUERY
    SELECT 
        fc.contributor::TEXT,
        COALESCE(fc.email, '')::TEXT as email,
        ARRAY_AGG(DISTINCT fc.fund)::TEXT[] as funds,
        SUM(CASE 
            WHEN fc.contribution_type = 'CONTRIBUTION' THEN fc.amount 
            WHEN fc.contribution_type = 'WITHDRAWAL' THEN -fc.amount 
            ELSE 0 
        END) as total_contribution
    FROM fund_contributions fc
    WHERE 
      -- Include if email is null/empty
      (fc.email IS NULL OR fc.email = '')
      OR 
      -- OR if email exists but doesn't match a user
      (
          fc.email IS NOT NULL 
          AND fc.email != '' 
          AND NOT EXISTS (
              SELECT 1 FROM auth.users au 
              WHERE normalize_email(au.email) = normalize_email(fc.email)
          )
      )
    GROUP BY fc.contributor, COALESCE(fc.email, '')
    HAVING SUM(CASE 
        WHEN fc.contribution_type = 'CONTRIBUTION' THEN fc.amount 
        WHEN fc.contribution_type = 'WITHDRAWAL' THEN -fc.amount 
        ELSE 0 
    END) > 0
    ORDER BY fc.contributor;
END;
$function$;