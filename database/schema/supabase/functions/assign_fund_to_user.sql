CREATE OR REPLACE FUNCTION public.assign_fund_to_user(user_email text, fund_name text)
 RETURNS json
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
#variable_conflict use_variable
DECLARE
    target_user_id UUID;
    assignment_exists BOOLEAN;
    rows_inserted INTEGER;
    result JSON;
BEGIN
    -- Get user ID by email
    SELECT id INTO target_user_id
    FROM auth.users
    WHERE email = user_email;
    
    IF target_user_id IS NULL THEN
        RAISE EXCEPTION 'User with email % not found', user_email;
    END IF;
    
    -- Check if assignment already exists
    SELECT EXISTS (
        SELECT 1 FROM user_funds uf 
        WHERE uf.user_id = target_user_id 
        AND uf.fund_name = assign_fund_to_user.fund_name
    ) INTO assignment_exists;
    
    IF assignment_exists THEN
        -- Assignment already exists
        result := json_build_object(
            'success', false,
            'already_assigned', true,
            'message', format('Fund "%s" is already assigned to %s', assign_fund_to_user.fund_name, user_email)
        );
    ELSE
        -- Insert fund assignment
        INSERT INTO user_funds (user_id, fund_name)
        VALUES (target_user_id, assign_fund_to_user.fund_name);
        
        GET DIAGNOSTICS rows_inserted = ROW_COUNT;
        
        IF rows_inserted > 0 THEN
            result := json_build_object(
                'success', true,
                'already_assigned', false,
                'message', format('Successfully assigned fund "%s" to %s', assign_fund_to_user.fund_name, user_email)
            );
        ELSE
            result := json_build_object(
                'success', false,
                'already_assigned', false,
                'message', 'Failed to assign fund'
            );
        END IF;
    END IF;
    
    RETURN result;
END;
$function$;