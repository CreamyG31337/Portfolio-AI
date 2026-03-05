CREATE OR REPLACE FUNCTION public.get_distinct_column_values(
    p_table text,
    p_column text
)
RETURNS TABLE(value text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
BEGIN
    -- Restrict to known public relations to avoid arbitrary SQL access.
    IF to_regclass(format('public.%I', p_table)) IS NULL THEN
        RAISE EXCEPTION 'Table % does not exist in public schema', p_table;
    END IF;

    RETURN QUERY EXECUTE format(
        'SELECT DISTINCT %1$I::text AS value
         FROM public.%2$I
         WHERE %1$I IS NOT NULL
         ORDER BY %1$I::text',
        p_column,
        p_table
    );
END;
$function$;
