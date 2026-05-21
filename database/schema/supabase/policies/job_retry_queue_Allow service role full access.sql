CREATE POLICY "Allow service role full access" ON "job_retry_queue" FOR ALL TO service_role USING (true) WITH CHECK (true);
