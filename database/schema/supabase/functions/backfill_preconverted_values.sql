CREATE OR REPLACE FUNCTION public.backfill_preconverted_values(fund_filter character varying DEFAULT NULL::character varying)
 RETURNS TABLE(records_updated bigint, records_skipped bigint, errors_count bigint)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    updated_count BIGINT := 0;
    skipped_count BIGINT := 0;
    error_count BIGINT := 0;
BEGIN
    -- Single UPDATE query that handles all currency conversions
    WITH updated_records AS (
        UPDATE portfolio_positions pp
        SET 
            base_currency = COALESCE(pp.base_currency, f.base_currency, 'CAD'),
            exchange_rate = CASE
                -- Same currency - no conversion
                WHEN UPPER(COALESCE(pp.currency, 'CAD')) = UPPER(COALESCE(f.base_currency, 'CAD')) 
                    THEN 1.0
                -- USD to base currency (e.g., CAD)
                WHEN UPPER(COALESCE(pp.currency, 'CAD')) = 'USD' 
                    AND UPPER(COALESCE(f.base_currency, 'CAD')) != 'USD'
                    THEN COALESCE(
                        get_exchange_rate_for_date(pp.date, 'USD', UPPER(COALESCE(f.base_currency, 'CAD'))),
                        1.35  -- Fallback for USD→CAD
                    )
                -- Base currency to USD
                WHEN UPPER(COALESCE(f.base_currency, 'CAD')) = 'USD'
                    AND UPPER(COALESCE(pp.currency, 'CAD')) != 'USD'
                    THEN COALESCE(
                        get_exchange_rate_for_date(pp.date, UPPER(COALESCE(pp.currency, 'CAD')), 'USD'),
                        -- Try inverse if direct rate not found
                        CASE 
                            WHEN UPPER(COALESCE(pp.currency, 'CAD')) = 'CAD'
                                THEN 1.0 / COALESCE(
                                    get_exchange_rate_for_date(pp.date, 'USD', 'CAD'),
                                    1.35
                                )
                            ELSE 1.0
                        END,
                        1.0  -- Final fallback
                    )
                -- Other combinations - store as-is
                ELSE 1.0
            END,
            total_value_base = CASE
                WHEN UPPER(COALESCE(pp.currency, 'CAD')) = UPPER(COALESCE(f.base_currency, 'CAD'))
                    THEN pp.total_value
                WHEN UPPER(COALESCE(pp.currency, 'CAD')) = 'USD' 
                    AND UPPER(COALESCE(f.base_currency, 'CAD')) != 'USD'
                    THEN pp.total_value * COALESCE(
                        get_exchange_rate_for_date(pp.date, 'USD', UPPER(COALESCE(f.base_currency, 'CAD'))),
                        1.35
                    )
                WHEN UPPER(COALESCE(f.base_currency, 'CAD')) = 'USD'
                    AND UPPER(COALESCE(pp.currency, 'CAD')) != 'USD'
                    THEN pp.total_value * COALESCE(
                        get_exchange_rate_for_date(pp.date, UPPER(COALESCE(pp.currency, 'CAD')), 'USD'),
                        CASE 
                            WHEN UPPER(COALESCE(pp.currency, 'CAD')) = 'CAD'
                                THEN 1.0 / COALESCE(
                                    get_exchange_rate_for_date(pp.date, 'USD', 'CAD'),
                                    1.35
                                )
                            ELSE 1.0
                        END,
                        1.0
                    )
                ELSE pp.total_value
            END,
            cost_basis_base = CASE
                WHEN UPPER(COALESCE(pp.currency, 'CAD')) = UPPER(COALESCE(f.base_currency, 'CAD'))
                    THEN pp.cost_basis
                WHEN UPPER(COALESCE(pp.currency, 'CAD')) = 'USD' 
                    AND UPPER(COALESCE(f.base_currency, 'CAD')) != 'USD'
                    THEN pp.cost_basis * COALESCE(
                        get_exchange_rate_for_date(pp.date, 'USD', UPPER(COALESCE(f.base_currency, 'CAD'))),
                        1.35
                    )
                WHEN UPPER(COALESCE(f.base_currency, 'CAD')) = 'USD'
                    AND UPPER(COALESCE(pp.currency, 'CAD')) != 'USD'
                    THEN pp.cost_basis * COALESCE(
                        get_exchange_rate_for_date(pp.date, UPPER(COALESCE(pp.currency, 'CAD')), 'USD'),
                        CASE 
                            WHEN UPPER(COALESCE(pp.currency, 'CAD')) = 'CAD'
                                THEN 1.0 / COALESCE(
                                    get_exchange_rate_for_date(pp.date, 'USD', 'CAD'),
                                    1.35
                                )
                            ELSE 1.0
                        END,
                        1.0
                    )
                ELSE pp.cost_basis
            END,
            pnl_base = CASE
                WHEN UPPER(COALESCE(pp.currency, 'CAD')) = UPPER(COALESCE(f.base_currency, 'CAD'))
                    THEN pp.pnl
                WHEN UPPER(COALESCE(pp.currency, 'CAD')) = 'USD' 
                    AND UPPER(COALESCE(f.base_currency, 'CAD')) != 'USD'
                    THEN pp.pnl * COALESCE(
                        get_exchange_rate_for_date(pp.date, 'USD', UPPER(COALESCE(f.base_currency, 'CAD'))),
                        1.35
                    )
                WHEN UPPER(COALESCE(f.base_currency, 'CAD')) = 'USD'
                    AND UPPER(COALESCE(pp.currency, 'CAD')) != 'USD'
                    THEN pp.pnl * COALESCE(
                        get_exchange_rate_for_date(pp.date, UPPER(COALESCE(pp.currency, 'CAD')), 'USD'),
                        CASE 
                            WHEN UPPER(COALESCE(pp.currency, 'CAD')) = 'CAD'
                                THEN 1.0 / COALESCE(
                                    get_exchange_rate_for_date(pp.date, 'USD', 'CAD'),
                                    1.35
                                )
                            ELSE 1.0
                        END,
                        1.0
                    )
                ELSE pp.pnl
            END
        FROM funds f
        WHERE pp.fund = f.name
            AND pp.total_value_base IS NULL
            AND (fund_filter IS NULL OR pp.fund = fund_filter)
        RETURNING pp.id
    )
    SELECT COUNT(*) INTO updated_count FROM updated_records;
    
    -- Return statistics
    RETURN QUERY SELECT updated_count, skipped_count, error_count;
END;
$function$;