CREATE POLICY "Allow authenticated users to read ai task queue" ON "ai_task_queue" FOR SELECT TO authenticated USING (true);
