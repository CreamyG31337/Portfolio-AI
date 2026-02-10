-- Align account-related foreign keys with auth.users and expose last sign-in in user listing RPC.

-- contributor_access
ALTER TABLE IF EXISTS public.contributor_access
DROP CONSTRAINT IF EXISTS contributor_access_contributor_id_fkey;
ALTER TABLE IF EXISTS public.contributor_access
ADD CONSTRAINT contributor_access_contributor_id_fkey
FOREIGN KEY (contributor_id) REFERENCES public.contributors(id) ON DELETE CASCADE;

ALTER TABLE IF EXISTS public.contributor_access
DROP CONSTRAINT IF EXISTS contributor_access_granted_by_fkey;
ALTER TABLE IF EXISTS public.contributor_access
ADD CONSTRAINT contributor_access_granted_by_fkey
FOREIGN KEY (granted_by) REFERENCES auth.users(id);

ALTER TABLE IF EXISTS public.contributor_access
DROP CONSTRAINT IF EXISTS contributor_access_user_id_fkey;
ALTER TABLE IF EXISTS public.contributor_access
ADD CONSTRAINT contributor_access_user_id_fkey
FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

-- user_funds
ALTER TABLE IF EXISTS public.user_funds
DROP CONSTRAINT IF EXISTS user_funds_fund_id_fkey;
ALTER TABLE IF EXISTS public.user_funds
ADD CONSTRAINT user_funds_fund_id_fkey
FOREIGN KEY (fund_id) REFERENCES public.funds(id) ON DELETE CASCADE;

ALTER TABLE IF EXISTS public.user_funds
DROP CONSTRAINT IF EXISTS user_funds_user_id_fkey;
ALTER TABLE IF EXISTS public.user_funds
ADD CONSTRAINT user_funds_user_id_fkey
FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

-- user_profiles
ALTER TABLE IF EXISTS public.user_profiles
DROP CONSTRAINT IF EXISTS user_profiles_user_id_fkey;
ALTER TABLE IF EXISTS public.user_profiles
ADD CONSTRAINT user_profiles_user_id_fkey
FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

-- system_settings
ALTER TABLE IF EXISTS public.system_settings
DROP CONSTRAINT IF EXISTS system_settings_updated_by_fkey;
ALTER TABLE IF EXISTS public.system_settings
ADD CONSTRAINT system_settings_updated_by_fkey
FOREIGN KEY (updated_by) REFERENCES auth.users(id);

-- list_users_with_funds RPC now includes auth.users.last_sign_in_at
DROP FUNCTION IF EXISTS public.list_users_with_funds();

CREATE OR REPLACE FUNCTION public.list_users_with_funds()
RETURNS TABLE(
    user_id uuid,
    email text,
    full_name text,
    role text,
    last_sign_in_at timestamp with time zone,
    funds text[]
)
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
