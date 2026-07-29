CREATE OR REPLACE VIEW latest_positions AS  WITH fund_snapshot_date AS (
         SELECT portfolio_positions.fund,
            max(portfolio_positions.date) AS snapshot_date
           FROM portfolio_positions
          GROUP BY portfolio_positions.fund
        ), snapshot_positions AS (
         SELECT pp.fund,
            pp.ticker,
            pp.shares,
            pp.price AS current_price,
            pp.cost_basis,
            pp.currency,
            pp.date,
            (pp.shares * pp.price) AS market_value,
            ((pp.shares * pp.price) - pp.cost_basis) AS unrealized_pnl
           FROM (portfolio_positions pp
             JOIN fund_snapshot_date fsd ON ((((pp.fund)::text = (fsd.fund)::text) AND (pp.date = fsd.snapshot_date))))
          WHERE (pp.shares > (0)::numeric)
        ), yesterday_positions AS (
         SELECT pp.fund,
            pp.ticker,
            pp.price AS yesterday_price,
            pp.date AS yesterday_date,
            row_number() OVER (PARTITION BY pp.fund, pp.ticker ORDER BY pp.date DESC) AS rn
           FROM (portfolio_positions pp
             JOIN snapshot_positions sp ON ((((pp.fund)::text = (sp.fund)::text) AND ((pp.ticker)::text = (sp.ticker)::text))))
          WHERE ((pp.date < sp.date) AND (pp.shares > (0)::numeric) AND (pp.date >= (sp.date - '14 days'::interval)))
        ), five_day_positions AS (
         SELECT pp.fund,
            pp.ticker,
            pp.price AS five_day_price,
            pp.date AS five_day_date,
            row_number() OVER (PARTITION BY pp.fund, pp.ticker ORDER BY (abs(EXTRACT(epoch FROM (pp.date - (sp.date - '5 days'::interval)))))) AS rn
           FROM (portfolio_positions pp
             JOIN snapshot_positions sp ON ((((pp.fund)::text = (sp.fund)::text) AND ((pp.ticker)::text = (sp.ticker)::text))))
          WHERE ((pp.date < sp.date) AND (pp.shares > (0)::numeric) AND (pp.date >= (sp.date - '10 days'::interval)) AND (pp.date <= (sp.date - '3 days'::interval)))
        )
 SELECT sp.fund,
    sp.ticker,
    s.company_name AS company,
    s.sector,
    s.industry,
    sp.shares,
    sp.current_price,
    sp.cost_basis,
    sp.market_value,
    sp.unrealized_pnl,
        CASE
            WHEN (sp.cost_basis > (0)::numeric) THEN ((sp.unrealized_pnl / sp.cost_basis) * (100)::numeric)
            ELSE (0)::numeric
        END AS return_pct,
    sp.currency,
    sp.date,
    yp.yesterday_price,
    yp.yesterday_date,
        CASE
            WHEN (yp.yesterday_price IS NOT NULL) THEN ((sp.current_price - yp.yesterday_price) * sp.shares)
            ELSE NULL::numeric
        END AS daily_pnl,
        CASE
            WHEN ((yp.yesterday_price IS NOT NULL) AND (yp.yesterday_price > (0)::numeric)) THEN (((sp.current_price - yp.yesterday_price) / yp.yesterday_price) * (100)::numeric)
            ELSE NULL::numeric
        END AS daily_pnl_pct,
    fp.five_day_price,
    fp.five_day_date,
        CASE
            WHEN (fp.five_day_price IS NOT NULL) THEN ((sp.current_price - fp.five_day_price) * sp.shares)
            ELSE NULL::numeric
        END AS five_day_pnl,
        CASE
            WHEN ((fp.five_day_price IS NOT NULL) AND (fp.five_day_price > (0)::numeric)) THEN (((sp.current_price - fp.five_day_price) / fp.five_day_price) * (100)::numeric)
            ELSE NULL::numeric
        END AS five_day_pnl_pct,
        CASE
            WHEN (fp.five_day_date IS NOT NULL) THEN EXTRACT(day FROM (sp.date - fp.five_day_date))
            ELSE NULL::numeric
        END AS five_day_period_days
   FROM (((snapshot_positions sp
     LEFT JOIN securities s ON (((sp.ticker)::text = (s.ticker)::text)))
     LEFT JOIN yesterday_positions yp ON ((((sp.fund)::text = (yp.fund)::text) AND ((sp.ticker)::text = (yp.ticker)::text) AND (yp.rn = 1))))
     LEFT JOIN five_day_positions fp ON ((((sp.fund)::text = (fp.fund)::text) AND ((sp.ticker)::text = (fp.ticker)::text) AND (fp.rn = 1))))
  ORDER BY sp.fund, sp.market_value DESC;
