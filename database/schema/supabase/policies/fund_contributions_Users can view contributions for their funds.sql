CREATE POLICY "Users can view contributions for their funds" ON "fund_contributions" FOR SELECT TO public USING ((((fund)::text IN ( SELECT user_funds.fund_name
   FROM user_funds
  WHERE (user_funds.user_id = auth.uid()))) OR (normalize_email((email)::text) = normalize_email((( SELECT user_profiles.email
   FROM user_profiles
  WHERE (user_profiles.user_id = auth.uid())))::text))));