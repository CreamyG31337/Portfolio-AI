CREATE POLICY "Users can view assigned funds" ON "funds" FOR SELECT TO public USING ((((name)::text IN ( SELECT user_funds.fund_name
   FROM user_funds
  WHERE (user_funds.user_id = auth.uid()))) OR is_admin(auth.uid())));