CREATE POLICY "Owners can grant access to their contributors" ON "contributor_access" FOR INSERT TO public WITH CHECK ((contributor_id IN ( SELECT contributor_access_1.contributor_id
   FROM contributor_access contributor_access_1
  WHERE ((contributor_access_1.user_id = auth.uid()) AND ((contributor_access_1.access_level)::text = 'owner'::text)))));