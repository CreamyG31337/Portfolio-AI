CREATE OR REPLACE VIEW fund_contributor_summary AS  SELECT fc.fund,
    count(DISTINCT COALESCE((c.id)::text, (fc.contributor)::text)) AS total_contributors,
    sum(
        CASE
            WHEN ((fc.contribution_type)::text = 'CONTRIBUTION'::text) THEN fc.amount
            ELSE (0)::numeric
        END) AS total_contributions,
    sum(
        CASE
            WHEN ((fc.contribution_type)::text = 'WITHDRAWAL'::text) THEN fc.amount
            ELSE (0)::numeric
        END) AS total_withdrawals,
    sum(
        CASE
            WHEN ((fc.contribution_type)::text = 'CONTRIBUTION'::text) THEN fc.amount
            WHEN ((fc.contribution_type)::text = 'WITHDRAWAL'::text) THEN (- fc.amount)
            ELSE (0)::numeric
        END) AS net_capital,
    min(fc."timestamp") AS fund_inception,
    max(fc."timestamp") AS last_activity
   FROM (fund_contributions fc
     LEFT JOIN contributors c ON ((fc.contributor_id = c.id)))
  GROUP BY fc.fund;