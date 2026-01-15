CREATE POLICY "Users can update contributions for accessible contributors" ON "fund_contributions" FOR UPDATE TO public USING ((contributor_id IN ( SELECT contributor_access.contributor_id
   FROM contributor_access
  WHERE ((contributor_access.user_id = auth.uid()) AND ((contributor_access.access_level)::text = ANY ((ARRAY['manager'::character varying, 'owner'::character varying])::text[]))))));