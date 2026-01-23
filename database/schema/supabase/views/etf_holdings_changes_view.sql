-- View: etf_holdings_changes
-- Computes daily changes in ETF holdings from etf_holdings_log
-- Single source of truth: no duplicate data storage
-- Filters to significant changes only (>= 1000 shares OR >= 0.5% change)

CREATE OR REPLACE VIEW etf_holdings_changes AS
WITH daily_holdings AS (
    SELECT 
        date,
        etf_ticker,
        holding_ticker,
        shares_held,
        LAG(shares_held) OVER (
            PARTITION BY etf_ticker, holding_ticker 
            ORDER BY date
        ) AS prev_shares
    FROM etf_holdings_log
),
changes AS (
    SELECT
        date,
        etf_ticker,
        holding_ticker,
        shares_held AS shares_after,
        prev_shares AS shares_before,
        shares_held - COALESCE(prev_shares, 0) AS share_change,
        CASE 
            WHEN prev_shares IS NULL OR prev_shares = 0 THEN 100.0
            ELSE ROUND(((shares_held - prev_shares)::numeric / prev_shares * 100), 2)
        END AS percent_change,
        CASE 
            WHEN shares_held > COALESCE(prev_shares, 0) THEN 'BUY' 
            WHEN shares_held < COALESCE(prev_shares, 0) THEN 'SELL'
            ELSE 'HOLD'
        END AS action
    FROM daily_holdings
    WHERE shares_held != COALESCE(prev_shares, 0)
)
SELECT 
    date,
    etf_ticker,
    holding_ticker,
    share_change,
    percent_change,
    action,
    shares_before,
    shares_after
FROM changes
WHERE ABS(share_change) >= 1000 OR ABS(percent_change) >= 0.5;

-- Comments
COMMENT ON VIEW etf_holdings_changes IS 'Daily changes in ETF holdings computed from etf_holdings_log. Shows significant changes only (>= 1000 shares OR >= 0.5% change).';
