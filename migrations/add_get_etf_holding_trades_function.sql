-- Migration: Add get_etf_holding_trades function
-- Date: 2026-01-22
-- Purpose: Returns ETF buy/sell trades for a given holding ticker by comparing consecutive dates
-- Used by: Ticker details price chart to show ETF activity markers

-- Add composite index for efficient queries
CREATE INDEX IF NOT EXISTS idx_ehl_holding_date 
ON etf_holdings_log (holding_ticker, date) 
INCLUDE (etf_ticker, shares_held);

-- Create the function
CREATE OR REPLACE FUNCTION public.get_etf_holding_trades(
  p_holding_ticker text,
  p_start_date date,
  p_end_date date,
  p_etf_ticker text default null
)
RETURNS TABLE (
  trade_date date,
  etf_ticker text,
  holding_ticker text,
  trade_type text,
  shares_change numeric,
  shares_after numeric
)
LANGUAGE sql
STABLE
AS $$
WITH in_range_etfs AS (
  -- Get distinct ETFs that hold this ticker in the date range
  SELECT DISTINCT e.etf_ticker
  FROM etf_holdings_log e
  WHERE e.holding_ticker = p_holding_ticker
    AND (p_etf_ticker IS NULL OR e.etf_ticker = p_etf_ticker)
    AND e.date BETWEEN p_start_date AND p_end_date
),
seed_prev AS (
  -- Bring in the last row before the start date per ETF (if it exists)
  -- This ensures the first row in range has a valid previous value for comparison
  SELECT prev.*
  FROM in_range_etfs t
  JOIN LATERAL (
    SELECT e.*
    FROM etf_holdings_log e
    WHERE e.holding_ticker = p_holding_ticker
      AND e.etf_ticker = t.etf_ticker
      AND e.date < p_start_date
    ORDER BY e.date DESC
    LIMIT 1
  ) prev ON true
),
data AS (
  -- Combine in-range data with seed previous rows
  SELECT e.date, e.etf_ticker, e.holding_ticker, COALESCE(e.shares_held, 0) AS shares_after
  FROM etf_holdings_log e
  WHERE e.holding_ticker = p_holding_ticker
    AND (p_etf_ticker IS NULL OR e.etf_ticker = p_etf_ticker)
    AND e.date BETWEEN p_start_date AND p_end_date

  UNION ALL

  SELECT s.date, s.etf_ticker, s.holding_ticker, COALESCE(s.shares_held, 0) AS shares_after
  FROM seed_prev s
),
calc AS (
  -- Calculate share changes using window function
  SELECT
    d.*,
    d.shares_after - LAG(d.shares_after) OVER (
      PARTITION BY d.etf_ticker, d.holding_ticker 
      ORDER BY d.date
    ) AS shares_change
  FROM data d
)
SELECT
  c.date AS trade_date,
  c.etf_ticker,
  c.holding_ticker,
  CASE
    WHEN c.shares_change > 0 THEN 'Purchase'
    WHEN c.shares_change < 0 THEN 'Sale'
    ELSE NULL
  END AS trade_type,
  c.shares_change,
  c.shares_after
FROM calc c
WHERE c.date BETWEEN p_start_date AND p_end_date
  AND c.shares_change IS NOT NULL
  AND c.shares_change <> 0
ORDER BY c.date ASC, c.etf_ticker ASC;
$$;

-- Grant execute permission to authenticated users
GRANT EXECUTE ON FUNCTION public.get_etf_holding_trades(text, date, date, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.get_etf_holding_trades(text, date, date, text) TO service_role;

COMMENT ON FUNCTION public.get_etf_holding_trades IS 'Returns ETF buy/sell trades for a holding ticker by comparing consecutive dates. Used for ticker detail chart markers.';
