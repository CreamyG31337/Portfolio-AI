CREATE OR REPLACE VIEW contributor_ownership AS  SELECT fc.fund,
    COALESCE(c.name, fc.contributor) AS contributor,
    COALESCE(c.email, fc.email) AS email,
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
        END) AS net_contribution,
    count(*) AS transaction_count,
    min(fc."timestamp") AS first_contribution,
    max(fc."timestamp") AS last_transaction
   FROM (fund_contributions fc
     LEFT JOIN contributors c ON ((fc.contributor_id = c.id)))
  GROUP BY fc.fund, COALESCE(c.name, fc.contributor), COALESCE(c.email, fc.email)
 HAVING (sum(
        CASE
            WHEN ((fc.contribution_type)::text = 'CONTRIBUTION'::text) THEN fc.amount
            WHEN ((fc.contribution_type)::text = 'WITHDRAWAL'::text) THEN (- fc.amount)
            ELSE (0)::numeric
        END) > (0)::numeric)
  ORDER BY fc.fund, (sum(
        CASE
            WHEN ((fc.contribution_type)::text = 'CONTRIBUTION'::text) THEN fc.amount
            WHEN ((fc.contribution_type)::text = 'WITHDRAWAL'::text) THEN (- fc.amount)
            ELSE (0)::numeric
        END)) DESC;