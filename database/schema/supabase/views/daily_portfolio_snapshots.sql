CREATE OR REPLACE VIEW daily_portfolio_snapshots AS  WITH daily_positions AS (
         SELECT portfolio_positions.fund,
            portfolio_positions.ticker,
            date(portfolio_positions.date) AS snapshot_date,
            portfolio_positions.shares,
            portfolio_positions.price,
            portfolio_positions.cost_basis,
            (portfolio_positions.shares * portfolio_positions.price) AS market_value,
            ((portfolio_positions.shares * portfolio_positions.price) - portfolio_positions.cost_basis) AS unrealized_pnl,
            portfolio_positions.date AS full_timestamp
           FROM portfolio_positions
          WHERE (portfolio_positions.shares > (0)::numeric)
        ), ranked_daily AS (
         SELECT daily_positions.fund,
            daily_positions.ticker,
            daily_positions.snapshot_date,
            daily_positions.shares,
            daily_positions.price,
            daily_positions.cost_basis,
            daily_positions.market_value,
            daily_positions.unrealized_pnl,
            daily_positions.full_timestamp,
            row_number() OVER (PARTITION BY daily_positions.fund, daily_positions.ticker, daily_positions.snapshot_date ORDER BY daily_positions.full_timestamp DESC) AS rn
           FROM daily_positions
        ), latest_daily AS (
         SELECT ranked_daily.fund,
            ranked_daily.ticker,
            ranked_daily.snapshot_date,
            ranked_daily.shares,
            ranked_daily.price,
            ranked_daily.cost_basis,
            ranked_daily.market_value,
            ranked_daily.unrealized_pnl,
            ranked_daily.full_timestamp,
            ranked_daily.rn
           FROM ranked_daily
          WHERE (ranked_daily.rn = 1)
        )
 SELECT fund,
    snapshot_date,
    count(DISTINCT ticker) AS position_count,
    sum(market_value) AS total_market_value,
    sum(cost_basis) AS total_cost_basis,
    sum(unrealized_pnl) AS total_unrealized_pnl,
        CASE
            WHEN (sum(cost_basis) > (0)::numeric) THEN ((sum(unrealized_pnl) / sum(cost_basis)) * (100)::numeric)
            ELSE (0)::numeric
        END AS total_return_pct
   FROM latest_daily
  GROUP BY fund, snapshot_date
  ORDER BY fund, snapshot_date DESC;