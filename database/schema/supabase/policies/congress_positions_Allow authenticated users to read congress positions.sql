CREATE POLICY "Allow authenticated users to read congress positions" ON "congress_positions" FOR SELECT TO authenticated USING (true);
