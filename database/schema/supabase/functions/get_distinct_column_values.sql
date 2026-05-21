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
    -- Whitelist of allowed tables
    IF p_table NOT IN (
        'securities',
        'watched_tickers',
        'congress_trades',
        'congress_trades_enriched',
        'insider_trades',
        'portfolio_positions',
        'trade_log'
    ) THEN
        RAISE EXCEPTION 'Table "%" is not in the allowed whitelist', p_table;
    END IF;

    -- Validate column name (alphanumeric + underscore only)
    IF p_column !~ '^[a-zA-Z_][a-zA-Z0-9_]*$' THEN
        RAISE EXCEPTION 'Invalid column name: %', p_column;
    END IF;

    RETURN QUERY EXECUTE format(
        'SELECT DISTINCT %I::TEXT AS value FROM %I WHERE %I IS NOT NULL ORDER BY 1',
        p_column, p_table, p_column
    );
END;
$function$;
