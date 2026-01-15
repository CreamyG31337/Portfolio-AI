CREATE POLICY "Users can view accessible contributors" ON "contributors" FOR SELECT TO public USING (((EXISTS ( SELECT 1
   FROM user_profiles
  WHERE ((user_profiles.user_id = auth.uid()) AND ((user_profiles.role)::text = 'admin'::text)))) OR (id IN ( SELECT contributor_access.contributor_id
   FROM contributor_access
  WHERE (contributor_access.user_id = auth.uid()))) OR (normalize_email((email)::text) = normalize_email((( SELECT user_profiles.email
   FROM user_profiles
  WHERE (user_profiles.user_id = auth.uid())))::text))));