CREATE OR REPLACE FUNCTION public.user_has_contributor_access(target_contributor_id uuid, required_access_level text DEFAULT 'viewer'::text)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
BEGIN
    -- Admin always has access
    IF EXISTS (
        SELECT 1 FROM user_profiles 
        WHERE user_id = auth.uid() AND role = 'admin'
    ) THEN
        RETURN TRUE;
    END IF;
    
    -- Check contributor_access table
    RETURN EXISTS (
        SELECT 1 FROM contributor_access 
        WHERE contributor_id = target_contributor_id
          AND user_id = auth.uid()
          AND (
              required_access_level = 'viewer'  -- Viewer can do anything
              OR access_level IN ('manager', 'owner')  -- Manager/owner for higher access
          )
    );
END;
$function$;