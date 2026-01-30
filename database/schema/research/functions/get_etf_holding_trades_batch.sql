-- Function: get_etf_holding_trades_batch
-- Batch version of get_etf_holding_trades that accepts an array of holding tickers
-- Returns ETF buy/sell trades for multiple holding tickers by comparing consecutive dates
-- Performance optimization: single SQL call instead of N calls for N tickers

DROP FUNCTION IF EXISTS get_etf_holding_trades_batch(text[], date, date, int);

CREATE OR REPLACE FUNCTION get_etf_holding_trades_batch(
  p_holding_tickers text[],
  p_start_date date,
  p_end_date date,
  p_limit int default 100
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
  -- Get distinct ETF/holding pairs that appear in the date range
  SELECT DISTINCT e.etf_ticker, e.holding_ticker
  FROM etf_holdings_log e
  WHERE e.holding_ticker = ANY(p_holding_tickers)
    AND e.date BETWEEN p_start_date AND p_end_date
),
seed_prev AS (
  -- Bring in the last row before the start date per ETF/holding pair (if it exists)
  -- This ensures the first row in range has a valid previous value for comparison
  SELECT prev.*
  FROM in_range_etfs t
  JOIN LATERAL (
    SELECT e.*
    FROM etf_holdings_log e
    WHERE e.holding_ticker = t.holding_ticker
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
  WHERE e.holding_ticker = ANY(p_holding_tickers)
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
ORDER BY c.date DESC, c.etf_ticker ASC
LIMIT p_limit;
$$;

COMMENT ON FUNCTION get_etf_holding_trades_batch IS 'Batch version: Returns ETF buy/sell trades for multiple holding tickers. Used for AI context to avoid N+1 query pattern.';
