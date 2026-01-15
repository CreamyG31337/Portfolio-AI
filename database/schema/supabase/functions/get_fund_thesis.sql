CREATE OR REPLACE FUNCTION public.get_fund_thesis(fund_name character varying)
 RETURNS json
 LANGUAGE plpgsql
 SET search_path TO 'public'
AS $function$
DECLARE
    result JSON;
BEGIN
    SELECT json_build_object(
        'guiding_thesis', json_build_object(
            'title', ft.title,
            'overview', ft.overview,
            'pillars', COALESCE(
                (SELECT json_agg(
                    json_build_object(
                        'name', ftp.name,
                        'allocation', ftp.allocation,
                        'thesis', ftp.thesis
                    ) ORDER BY ftp.pillar_order
                )
                FROM fund_thesis_pillars ftp 
                WHERE ftp.thesis_id = ft.id), 
                '[]'::json
            )
        )
    ) INTO result
    FROM fund_thesis ft
    WHERE ft.fund = fund_name;
    
    RETURN result;
END;
$function$;