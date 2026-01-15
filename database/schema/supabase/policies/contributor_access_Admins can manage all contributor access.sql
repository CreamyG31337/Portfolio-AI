CREATE POLICY "Admins can manage all contributor access" ON "contributor_access" FOR ALL TO public USING ((EXISTS ( SELECT 1
   FROM user_profiles
  WHERE ((user_profiles.user_id = auth.uid()) AND ((user_profiles.role)::text = 'admin'::text)))));