CREATE OR REPLACE FUNCTION public.create_user_profile()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    user_count INTEGER;
    user_role VARCHAR(50);
BEGIN
    SELECT COUNT(*) INTO user_count FROM user_profiles;
    
    IF user_count = 0 THEN
        user_role := 'admin';
    ELSE
        user_role := 'user';
    END IF;
    
    INSERT INTO user_profiles (user_id, email, full_name, role)
    VALUES (
        NEW.id,
        NEW.email,
        COALESCE(NEW.raw_user_meta_data->>'full_name', ''),
        user_role
    );
    
    INSERT INTO user_funds (user_id, fund_name)
    SELECT DISTINCT NEW.id, fc.fund
    FROM fund_contributions fc
    WHERE normalize_email(fc.email) = normalize_email(NEW.email)
    ON CONFLICT (user_id, fund_name) DO NOTHING;
    
    RETURN NEW;
END;
$function$;