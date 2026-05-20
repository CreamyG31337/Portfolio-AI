CREATE POLICY "Allow service role full access" ON "ai_task_queue" FOR ALL TO service_role USING (true) WITH CHECK (true);
