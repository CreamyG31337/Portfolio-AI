CREATE OR REPLACE FUNCTION public.get_politician_leaderboard(
    p_cutoff_date DATE DEFAULT NULL,
    p_min_positions INT DEFAULT 3
)
RETURNS TABLE (
    politician_id INT,
    politician TEXT,
    party TEXT,
    chamber TEXT,
    positions BIGINT,
    wins BIGINT,
    losses BIGINT,
    win_pct NUMERIC,
    avg_return_pct NUMERIC,
    total_est_invested NUMERIC,
    total_est_pnl NUMERIC,
    best_position JSONB,
    worst_position JSONB
)
LANGUAGE sql
STABLE
AS $function$
WITH aggregated AS (
    SELECT
        cp.politician_id,
        p.name AS politician,
        p.party,
        p.chamber,
        COUNT(*) AS positions,
        SUM(CASE WHEN COALESCE(cp.pct_return, 0) > 0 THEN 1 ELSE 0 END) AS wins,
        SUM(CASE WHEN COALESCE(cp.pct_return, 0) <= 0 THEN 1 ELSE 0 END) AS losses,
        ROUND(
            CASE WHEN COUNT(*) > 0
                THEN SUM(CASE WHEN COALESCE(cp.pct_return, 0) > 0 THEN 1 ELSE 0 END)::NUMERIC
                     / COUNT(*) * 100
                ELSE 0
            END, 1
        ) AS win_pct,
        ROUND(AVG(COALESCE(cp.pct_return, 0)), 1) AS avg_return_pct,
        ROUND(SUM(COALESCE(cp.est_invested, 0)), 0) AS total_est_invested,
        ROUND(SUM(COALESCE(cp.est_pnl, 0)), 0) AS total_est_pnl
    FROM congress_positions cp
    JOIN politicians p ON cp.politician_id = p.id
    WHERE cp.status = 'closed'
      AND (p_cutoff_date IS NULL OR cp.first_buy_date >= p_cutoff_date)
    GROUP BY cp.politician_id, p.name, p.party, p.chamber
    HAVING COUNT(*) >= p_min_positions
),
best AS (
    SELECT DISTINCT ON (cp.politician_id)
        cp.politician_id,
        jsonb_build_object(
            'ticker', cp.ticker,
            'pct_return', COALESCE(cp.pct_return, 0),
            'est_pnl', COALESCE(cp.est_pnl, 0)
        ) AS best_position
    FROM congress_positions cp
    WHERE cp.status = 'closed'
      AND (p_cutoff_date IS NULL OR cp.first_buy_date >= p_cutoff_date)
    ORDER BY cp.politician_id, COALESCE(cp.est_pnl, 0) DESC
),
worst AS (
    SELECT DISTINCT ON (cp.politician_id)
        cp.politician_id,
        jsonb_build_object(
            'ticker', cp.ticker,
            'pct_return', COALESCE(cp.pct_return, 0),
            'est_pnl', COALESCE(cp.est_pnl, 0)
        ) AS worst_position
    FROM congress_positions cp
    WHERE cp.status = 'closed'
      AND (p_cutoff_date IS NULL OR cp.first_buy_date >= p_cutoff_date)
    ORDER BY cp.politician_id, COALESCE(cp.est_pnl, 0) ASC
)
SELECT
    a.politician_id,
    a.politician,
    a.party,
    a.chamber,
    a.positions,
    a.wins,
    a.losses,
    a.win_pct,
    a.avg_return_pct,
    a.total_est_invested,
    a.total_est_pnl,
    b.best_position,
    w.worst_position
FROM aggregated a
LEFT JOIN best b ON a.politician_id = b.politician_id
LEFT JOIN worst w ON a.politician_id = w.politician_id;
$function$;
