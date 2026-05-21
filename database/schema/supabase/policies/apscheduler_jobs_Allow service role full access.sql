CREATE POLICY "Allow service role full access" ON "apscheduler_jobs" FOR ALL TO service_role USING (true) WITH CHECK (true);
