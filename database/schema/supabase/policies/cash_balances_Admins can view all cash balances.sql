CREATE POLICY "Admins can view all cash balances" ON "cash_balances" FOR SELECT TO public USING ((EXISTS ( SELECT 1
   FROM user_profiles
  WHERE ((user_profiles.user_id = auth.uid()) AND ((user_profiles.role)::text = 'admin'::text)))));