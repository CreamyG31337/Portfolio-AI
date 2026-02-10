CREATE OR REPLACE VIEW etf_holdings_changes AS  WITH daily_holdings AS (
         SELECT etf_holdings_log.date,
            etf_holdings_log.etf_ticker,
            etf_holdings_log.holding_ticker,
            etf_holdings_log.shares_held,
            lag(etf_holdings_log.shares_held) OVER (PARTITION BY etf_holdings_log.etf_ticker, etf_holdings_log.holding_ticker ORDER BY etf_holdings_log.date) AS prev_shares
           FROM etf_holdings_log
        ), changes AS (
         SELECT daily_holdings.date,
            daily_holdings.etf_ticker,
            daily_holdings.holding_ticker,
            daily_holdings.shares_held AS shares_after,
            daily_holdings.prev_shares AS shares_before,
            (daily_holdings.shares_held - COALESCE(daily_holdings.prev_shares, (0)::numeric)) AS share_change,
                CASE
                    WHEN ((daily_holdings.prev_shares IS NULL) OR (daily_holdings.prev_shares = (0)::numeric)) THEN 100.0
                    ELSE round((((daily_holdings.shares_held - daily_holdings.prev_shares) / daily_holdings.prev_shares) * (100)::numeric), 2)
                END AS percent_change,
                CASE
                    WHEN (daily_holdings.shares_held > COALESCE(daily_holdings.prev_shares, (0)::numeric)) THEN 'BUY'::text
                    WHEN (daily_holdings.shares_held < COALESCE(daily_holdings.prev_shares, (0)::numeric)) THEN 'SELL'::text
                    ELSE 'HOLD'::text
                END AS action
           FROM daily_holdings
          WHERE (daily_holdings.shares_held <> COALESCE(daily_holdings.prev_shares, (0)::numeric))
        )
 SELECT date,
    etf_ticker,
    holding_ticker,
    share_change,
    percent_change,
    action,
    shares_before,
    shares_after
   FROM changes
  WHERE ((abs(share_change) >= (1000)::numeric) OR (abs(percent_change) >= 0.5));