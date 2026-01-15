CREATE OR REPLACE FUNCTION public.normalize_email(email text)
 RETURNS text
 LANGUAGE plpgsql
 IMMUTABLE
 SET search_path TO 'public'
AS $function$
DECLARE
    normalized TEXT;
    local_part TEXT;
    domain_part TEXT;
BEGIN
    normalized := LOWER(TRIM(COALESCE(email, '')));
    
    IF normalized = '' OR POSITION('@' IN normalized) = 0 THEN
        RETURN normalized;
    END IF;
    
    local_part := SPLIT_PART(normalized, '@', 1);
    domain_part := SPLIT_PART(normalized, '@', 2);
    
    IF domain_part IN ('gmail.com', 'googlemail.com') THEN
        local_part := REPLACE(local_part, '.', '');
    END IF;
    
    RETURN local_part || '@' || domain_part;
END;
$function$;