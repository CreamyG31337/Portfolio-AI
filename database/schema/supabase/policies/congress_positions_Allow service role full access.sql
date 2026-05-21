CREATE POLICY "Allow service role full access" ON "congress_positions" FOR ALL TO service_role USING (true) WITH CHECK (true);
