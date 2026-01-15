CREATE OR REPLACE VIEW latest_positions AS  WITH ranked_positions AS (
         SELECT portfolio_positions.fund,
            portfolio_positions.ticker,
            portfolio_positions.shares,
            portfolio_positions.price AS current_price,
            portfolio_positions.cost_basis,
            portfolio_positions.currency,
            portfolio_positions.date,
            (portfolio_positions.shares * portfolio_positions.price) AS market_value,
            ((portfolio_positions.shares * portfolio_positions.price) - portfolio_positions.cost_basis) AS unrealized_pnl,
            row_number() OVER (PARTITION BY portfolio_positions.fund, portfolio_positions.ticker ORDER BY portfolio_positions.date DESC) AS rn
           FROM portfolio_positions
          WHERE (portfolio_positions.shares > (0)::numeric)
        ), latest_pos AS (
         SELECT ranked_positions.fund,
            ranked_positions.ticker,
            ranked_positions.shares,
            ranked_positions.current_price,
            ranked_positions.cost_basis,
            ranked_positions.currency,
            ranked_positions.date,
            ranked_positions.market_value,
            ranked_positions.unrealized_pnl,
            ranked_positions.rn
           FROM ranked_positions
          WHERE (ranked_positions.rn = 1)
        ), yesterday_positions AS (
         SELECT pp.fund,
            pp.ticker,
            pp.price AS yesterday_price,
            pp.date AS yesterday_date,
            row_number() OVER (PARTITION BY pp.fund, pp.ticker ORDER BY pp.date DESC) AS rn
           FROM (portfolio_positions pp
             JOIN latest_pos lp_1 ON ((((pp.fund)::text = (lp_1.fund)::text) AND ((pp.ticker)::text = (lp_1.ticker)::text))))
          WHERE ((pp.date < lp_1.date) AND (pp.shares > (0)::numeric) AND (pp.date >= (lp_1.date - '14 days'::interval)))
        ), five_day_positions AS (
         SELECT pp.fund,
            pp.ticker,
            pp.price AS five_day_price,
            pp.date AS five_day_date,
            row_number() OVER (PARTITION BY pp.fund, pp.ticker ORDER BY (abs(EXTRACT(epoch FROM (pp.date - (lp_1.date - '5 days'::interval)))))) AS rn
           FROM (portfolio_positions pp
             JOIN latest_pos lp_1 ON ((((pp.fund)::text = (lp_1.fund)::text) AND ((pp.ticker)::text = (lp_1.ticker)::text))))
          WHERE ((pp.date < lp_1.date) AND (pp.shares > (0)::numeric) AND (pp.date >= (lp_1.date - '10 days'::interval)) AND (pp.date <= (lp_1.date - '3 days'::interval)))
        )
 SELECT lp.fund,
    lp.ticker,
    s.company_name AS company,
    s.sector,
    s.industry,
    lp.shares,
    lp.current_price,
    lp.cost_basis,
    lp.market_value,
    lp.unrealized_pnl,
        CASE
            WHEN (lp.cost_basis > (0)::numeric) THEN ((lp.unrealized_pnl / lp.cost_basis) * (100)::numeric)
            ELSE (0)::numeric
        END AS return_pct,
    lp.currency,
    lp.date,
    yp.yesterday_price,
    yp.yesterday_date,
        CASE
            WHEN (yp.yesterday_price IS NOT NULL) THEN ((lp.current_price - yp.yesterday_price) * lp.shares)
            ELSE NULL::numeric
        END AS daily_pnl,
        CASE
            WHEN ((yp.yesterday_price IS NOT NULL) AND (yp.yesterday_price > (0)::numeric)) THEN (((lp.current_price - yp.yesterday_price) / yp.yesterday_price) * (100)::numeric)
            ELSE NULL::numeric
        END AS daily_pnl_pct,
    fp.five_day_price,
    fp.five_day_date,
        CASE
            WHEN (fp.five_day_price IS NOT NULL) THEN ((lp.current_price - fp.five_day_price) * lp.shares)
            ELSE NULL::numeric
        END AS five_day_pnl,
        CASE
            WHEN ((fp.five_day_price IS NOT NULL) AND (fp.five_day_price > (0)::numeric)) THEN (((lp.current_price - fp.five_day_price) / fp.five_day_price) * (100)::numeric)
            ELSE NULL::numeric
        END AS five_day_pnl_pct,
        CASE
            WHEN (fp.five_day_date IS NOT NULL) THEN EXTRACT(day FROM (lp.date - fp.five_day_date))
            ELSE NULL::numeric
        END AS five_day_period_days
   FROM (((latest_pos lp
     LEFT JOIN securities s ON (((lp.ticker)::text = (s.ticker)::text)))
     LEFT JOIN yesterday_positions yp ON ((((lp.fund)::text = (yp.fund)::text) AND ((lp.ticker)::text = (yp.ticker)::text) AND (yp.rn = 1))))
     LEFT JOIN five_day_positions fp ON ((((lp.fund)::text = (fp.fund)::text) AND ((lp.ticker)::text = (fp.ticker)::text) AND (fp.rn = 1))))
  ORDER BY lp.fund, lp.market_value DESC;