CREATE POLICY "Allow service role full access" ON "ai_analysis_skip_list" FOR ALL TO service_role USING (true) WITH CHECK (true);
