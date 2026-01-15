CREATE POLICY "Users can view performance metrics for their funds" ON "performance_metrics" FOR SELECT TO public USING ((((fund)::text IN ( SELECT user_funds.fund_name
   FROM user_funds
  WHERE (user_funds.user_id = auth.uid()))) OR ((fund)::text IN ( SELECT fund_contributions.fund
   FROM fund_contributions
  WHERE (normalize_email((fund_contributions.email)::text) = normalize_email((( SELECT user_profiles.email
           FROM user_profiles
          WHERE (user_profiles.user_id = auth.uid())))::text))))));