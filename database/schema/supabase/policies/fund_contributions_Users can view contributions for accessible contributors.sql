CREATE POLICY "Users can view contributions for accessible contributors" ON "fund_contributions" FOR SELECT TO public USING (((EXISTS ( SELECT 1
   FROM user_profiles
  WHERE ((user_profiles.user_id = auth.uid()) AND ((user_profiles.role)::text = 'admin'::text)))) OR (contributor_id IN ( SELECT contributor_access.contributor_id
   FROM contributor_access
  WHERE (contributor_access.user_id = auth.uid()))) OR (contributor_id IN ( SELECT c.id
   FROM (contributors c
     JOIN auth.users au ON ((normalize_email((c.email)::text) = normalize_email((au.email)::text))))
  WHERE ((au.id = auth.uid()) AND (c.email IS NOT NULL) AND ((c.email)::text <> ''::text))))));